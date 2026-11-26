"""FR3: news search via the Exa API (PRD FR3, contracts/exa.v1.md).

The FundProfile is fanned out into capped queries — one per top-5 holding by
weight plus one per top-5 sector by weight, both focused on where each
company and sector is heading — run in parallel through the `exa-py` SDK
within a published-date window, deduplicated by URL, and returned as
NewsItem[]. Individual search failures are logged and skipped; a total failure
degrades to no news (fund-data-only report later) via the config flag, or
raises SearchError when the flag is off. Dependencies (the Exa client, the
event emitter, the clock, the config) arrive by parameter, never at import
time (constitution P3). Events are emitted from the orchestrator thread only;
workers just return their outcomes.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Final, Protocol

from src.core.events import Clock, EventEmitter
from src.core.models import FundProfile, NewsItem
from src.search.queries import (
    MAX_HOLDING_QUERIES,
    MAX_SECTOR_QUERIES,
    SearchConfig,
    SearchQuery,
    build_queries,
    dedupe_news,
    exa_error_details,
    news_from_result,
    search_options,
)

EXA_TIMEOUT_SECONDS: Final[float] = 30.0
EXA_DATE_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S.000Z"
PROVIDER: Final[str] = "exa.search"
STAGE: Final[str] = "news_search"

class SearchError(RuntimeError):
    """Every Exa search failed and degrade mode is off (PRD FR3)."""


class ExaClient(Protocol):
    """What invesk needs from an `exa_py.Exa` client (or a test double).

    The SDK maps the snake_case options to the POST /search body
    (contracts/exa.v1.md); this module never touches HTTP itself.
    """

    def search(self, query: str, **options: Any) -> Any: ...


def exa_client(api_key: str) -> ExaClient:
    """The real client constructor, bound at the composition root (P3)."""
    from exa_py import Exa  # deferred third-party import (P3)

    return Exa(api_key, timeout=EXA_TIMEOUT_SECONDS)


@dataclass(frozen=True)
class _QueryOutcome:
    """Result of one search, measured in its worker thread."""

    query: SearchQuery
    succeeded: bool
    latency_ms: int
    raw_results: tuple[Any, ...] = ()
    request_id: str | None = None
    http_status: int | None = None


def _run_query(
    query: SearchQuery, *, exa: ExaClient, options: Mapping[str, Any]
) -> _QueryOutcome:
    """One instrumented candidate: call Exa, never raise, report the outcome."""
    started = time.monotonic()
    try:
        response = exa.search(query.text, **options)
    except Exception as exc:  # any failure is this search's failure (FR3)
        http_status, request_id = exa_error_details(exc)
        return _QueryOutcome(
            query=query,
            succeeded=False,
            latency_ms=int((time.monotonic() - started) * 1000),
            request_id=request_id,
            http_status=http_status,
        )
    results = getattr(response, "results", None)
    return _QueryOutcome(
        query=query,
        succeeded=True,
        latency_ms=int((time.monotonic() - started) * 1000),
        raw_results=tuple(results) if isinstance(results, list) else (),
    )


def search_news(
    profile: FundProfile,
    *,
    config: SearchConfig,
    exa: ExaClient,
    events: EventEmitter,
    clock: Clock,
) -> tuple[NewsItem, ...]:
    """FR3 stage: fan out capped Exa queries → deduplicated NewsItem[].

    Individual failures are logged (external_call status=error) and skipped.
    If every search fails, the degrade flag returns no news (a later
    fund-data-only report) or raises SearchError to abort. Emits one
    external_call per search and one stage_completed news_search; events are
    emitted from this thread in submission order, never from workers.
    """
    queries = build_queries(profile, max_searches=config.max_searches)
    now = clock().astimezone(timezone.utc)
    start = (now - timedelta(days=config.window_days)).strftime(EXA_DATE_FORMAT)
    end = now.strftime(EXA_DATE_FORMAT)

    outcomes: list[_QueryOutcome] = []
    if queries:
        options = search_options(
            num_results=config.results_per_search, start=start, end=end
        )
        with ThreadPoolExecutor(
            max_workers=min(config.max_parallel, len(queries))
        ) as pool:
            futures = [
                pool.submit(_run_query, query, exa=exa, options=options)
                for query in queries
            ]
            outcomes = [future.result() for future in futures]

    for outcome in outcomes:
        fields: dict[str, object] = {
            "stage": STAGE,
            "provider": PROVIDER,
            "entity": outcome.query.entity,
            "latency_ms": outcome.latency_ms,
            "status": "ok" if outcome.succeeded else "error",
        }
        if outcome.request_id is not None:
            fields["request_id"] = outcome.request_id
        if outcome.http_status is not None:
            fields["http_status"] = outcome.http_status
        events.emit("external_call", **fields)

    items: list[NewsItem] = []
    for outcome in outcomes:
        if not outcome.succeeded:
            continue
        for rank, raw in enumerate(outcome.raw_results, start=1):
            item = news_from_result(raw, entity=outcome.query.entity, rank=rank)
            if item is not None:
                items.append(item)
    news = dedupe_news(items)

    successful_searches = sum(outcome.succeeded for outcome in outcomes)
    failed_searches = len(outcomes) - successful_searches
    degraded = False
    if queries and failed_searches == len(outcomes):
        if not config.degrade_on_total_failure:
            raise SearchError(f"all {len(queries)} Exa searches failed")
        degraded = True
    events.emit(
        "stage_completed",
        stage=STAGE,
        searches=len(queries),
        ok=successful_searches,
        failed=failed_searches,
        results=sum(
            len(outcome.raw_results)
            for outcome in outcomes
            if outcome.succeeded
        ),
        news=len(news),
        degraded=degraded,
    )
    return tuple(news)
