"""Best-effort Exa web fallback for questions not covered by saved news."""

from __future__ import annotations

import time
from typing import Any, Protocol

from src.core.events import EventEmitter
from src.qa.corpus import QANewsItem
from src.qa.retrieve import Passage, retrieve
from src.search.queries import exa_error_details, news_from_result

PROVIDER = "exa.qa_search"
MAX_RESULTS = 5
MAX_TEXT_CHARS = 6000
MAX_PASSAGES = 8
MAX_EVIDENCE_CHARS = 12000


class ExaClient(Protocol):
    def search(self, query: str, **options: Any) -> Any: ...


def web_passages_from_results(
    results: object,
    query: str,
    *,
    excluded_urls: set[str] | None = None,
) -> list[Passage]:
    """Convert Exa results into bounded, exact-text passages with W citations."""
    if not isinstance(results, list):
        return []

    excluded = excluded_urls or set()
    items: list[QANewsItem] = []
    seen = set(excluded)
    for rank, result in enumerate(results, start=1):
        item = news_from_result(result, entity="web", rank=rank)
        if item is None or item.url in seen:
            continue
        seen.add(item.url)
        items.append(
            QANewsItem(
                title=item.title,
                url=item.url,
                source=item.source,
                published=item.published,
                summary=item.summary,
                content=(item.content or "")[:MAX_TEXT_CHARS] or None,
            )
        )
    if not items:
        return []

    passages = retrieve(
        query,
        items,
        max_passages=MAX_PASSAGES,
        max_chars=MAX_EVIDENCE_CHARS,
    )
    return [
        Passage(
            **{
                **passage.__dict__,
                "source_id": f"W{passage.source_number}",
                "source_number": None,
            }
        )
        for passage in passages
    ]


def search_web(
    query: str,
    *,
    exa: ExaClient,
    events: EventEmitter,
    excluded_urls: set[str] | None = None,
) -> list[Passage]:
    """Make one instrumented, general-web search; failures degrade to no results."""
    started = time.monotonic()
    try:
        response = exa.search(
            query,
            num_results=MAX_RESULTS,
            type="auto",
            contents={
                "summary": {"query": query},
                "text": {"max_characters": MAX_TEXT_CHARS},
            },
        )
    except Exception as exc:
        http_status, request_id = exa_error_details(exc)
        fields: dict[str, object] = {
            "stage": "qa",
            "provider": PROVIDER,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "status": "error",
        }
        if http_status is not None:
            fields["http_status"] = http_status
        if request_id is not None:
            fields["request_id"] = request_id
        events.emit("external_call", **fields)
        return []

    events.emit(
        "external_call",
        stage="qa",
        provider=PROVIDER,
        latency_ms=int((time.monotonic() - started) * 1000),
        status="ok",
    )
    return web_passages_from_results(
        getattr(response, "results", None),
        query,
        excluded_urls=excluded_urls,
    )
