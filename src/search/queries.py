"""Build Exa queries and normalize, deduplicate, and classify results."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Final
from urllib.parse import urlsplit

from src.core.models import FundProfile, NewsItem

_STATUS_RE: Final[re.Pattern[str]] = re.compile(r"status(?: code)? (\d+)")
_REQUEST_ID_RE: Final[re.Pattern[str]] = re.compile(r'"requestId"\s*:\s*"([^"]+)"')

SUMMARY_QUERY: Final[str] = "Key facts, figures, and dates"
#: FR3 focus: the top 5 companies and the top 5 sectors, each one query
#: (max 10 searches per fund at the default cap).
MAX_HOLDING_QUERIES: Final[int] = 5
MAX_SECTOR_QUERIES: Final[int] = 5


@dataclass(frozen=True)
class SearchConfig:
    """FR3 caps and degrade flag — configuration, not code (P7).

    Defaults follow PRD FR3; the composition root overrides them from the
    EXA_* environment variables (contracts/exa.v1.md).
    """

    max_searches: int = 10
    results_per_search: int = 5
    window_days: int = 90
    max_parallel: int = 4
    degrade_on_total_failure: bool = True


@dataclass(frozen=True)
class SearchQuery:
    """One Exa query: its text, the entity it targets, and the entity kind."""

    text: str
    entity: str
    kind: str  # "holding" | "sector"


def build_queries(profile: FundProfile, *, max_searches: int) -> tuple[SearchQuery, ...]:
    """FundProfile → capped, ordered queries (FR3, contracts/exa.v1.md).

    One per top-5 holding by weight (descending), then one per top-5 sector
    by weight until the cap — the search budget goes to the companies and
    sectors that move the fund, and sector queries ask where the sector is
    heading (the FR4 sector-insights input).
    """
    budget = max(0, max_searches)
    queries: list[SearchQuery] = []
    query_texts: set[str] = set()
    for holding in sorted(
        profile.holdings, key=lambda h: h.weight, reverse=True
    )[:MAX_HOLDING_QUERIES]:
        if len(queries) >= budget:
            break
        if not holding.name.strip():
            continue
        text = f"{holding.name} company news"
        if text in query_texts:
            continue
        query_texts.add(text)
        queries.append(
            SearchQuery(
                text=text,
                entity=holding.name,
                kind="holding",
            )
        )
    for sector, _weight in sorted(
        profile.sector_weights.items(), key=lambda kv: kv[1], reverse=True
    )[:MAX_SECTOR_QUERIES]:
        if len(queries) >= budget:
            break
        text = f"{sector} sector outlook"
        if text in query_texts:
            continue
        query_texts.add(text)
        queries.append(
            SearchQuery(text=text, entity=sector, kind="sector")
        )
    return tuple(queries)


def search_options(*, num_results: int, start: str, end: str) -> dict[str, Any]:
    """Keyword options for one SDK search call (contracts/exa.v1.md).

    exa-py maps these to the same wire fields as v1 — numResults,
    startPublishedDate, endPublishedDate — keeping the news category and the
    window, and requesting both the per-result summary (query-biased) and
    the full page text in compact, markdown-style form without HTML tags.
    The query text itself is the SDK call's first argument, not an option.
    """
    return {
        "num_results": num_results,
        "type": "auto",
        "category": "news",
        "start_published_date": start,
        "end_published_date": end,
        "contents": {
            "summary": {"query": SUMMARY_QUERY},
            "text": {
                "max_characters": None,
                "verbosity": "compact",
                "include_html_tags": False,
            },
        },
    }


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def news_from_result(result: Any, *, entity: str, rank: int) -> NewsItem | None:
    """Boundary adapter: one exa_py Result → NewsItem, or None if unusable.

    A result without a title or an http(s) URL cannot be cited or deduped, so
    it is dropped (counted, not an error). `rank` is the result's 1-based
    position in Exa's list — kept from the original position even when
    earlier entries are dropped.
    """
    title = str(getattr(result, "title", None) or "").strip()
    url = str(getattr(result, "url", None) or "").strip()
    try:
        parsed_url = urlsplit(url)
        hostname = parsed_url.hostname
    except ValueError:
        return None
    if (
        not title
        or parsed_url.scheme.lower() not in ("http", "https")
        or not parsed_url.netloc
        or not hostname
    ):
        return None
    return NewsItem(
        title=title,
        url=url,
        source=hostname,
        published=_string_or_none(getattr(result, "published_date", None)),
        summary=_string_or_none(getattr(result, "summary", None)),
        content=_string_or_none(getattr(result, "text", None)),
        relevance=rank,
        related=(entity,),
    )


def dedupe_news(items: Sequence[NewsItem]) -> list[NewsItem]:
    """Drop later URLs while retaining every targeted entity on the first item."""
    positions: dict[str, int] = {}
    unique: list[NewsItem] = []
    for item in items:
        position = positions.get(item.url)
        if position is not None:
            first = unique[position]
            unique[position] = replace(
                first, related=tuple(dict.fromkeys((*first.related, *item.related)))
            )
            continue
        positions[item.url] = len(unique)
        unique.append(item)
    return unique


def exa_error_details(exc: BaseException) -> tuple[int | None, str | None]:
    """A raised SDK error → (http_status, request_id), best effort.

    exa-py does not structure its errors: the provider status and error body
    arrive embedded in the exception message. Parse them from that text for
    the `external_call` event; timeouts and network failures carry neither.
    Messages contain provider text only — never the API key or query.
    """
    message = str(exc)
    status: int | None = None
    match = _STATUS_RE.search(message)
    if match:
        status = int(match.group(1))
    request_id: str | None = None
    match = _REQUEST_ID_RE.search(message)
    if match:
        request_id = match.group(1)
    return status, request_id
