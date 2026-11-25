"""Yahoo-backed fund-name suggestions shared by the browser interface."""

from __future__ import annotations

import re
from collections.abc import Callable

from src.extraction.profile import FUND_QUOTE_TYPES

MIN_QUERY_LEN = 2
MAX_SUGGESTIONS = 6

Suggester = Callable[[str], list[str]]

# Ticker charset: no whitespace, no lowercase (e.g. `0P00017EQ6.L`).
_SYMBOL_LIKE_RE = re.compile(r"[A-Z0-9][A-Z0-9.+\-^=]{0,11}\Z")


def _symbol_like(name: str, symbol: str) -> bool:
    """True when the candidate name is a ticker rather than a fund name."""
    if name == symbol:
        return True
    return bool(_SYMBOL_LIKE_RE.fullmatch(name)) and (
        any(char.isdigit() for char in name) or "." in name
    )


def _fund_name(quote: dict) -> str | None:
    """One Yahoo quote → its fund name, or None when it is not a fund.

    Candidates are tried in `longname`, `shortname` order; a candidate equal
    to the quote symbol or shaped like a ticker is skipped, so the returned
    suggestion is always a fund name (or None, which drops the quote).
    """
    if str(quote.get("quoteType") or "").upper() not in FUND_QUOTE_TYPES:
        return None
    symbol = str(quote.get("symbol") or "").strip()
    for field in ("longname", "shortname"):
        name = re.sub(r"\s+", " ", str(quote.get(field) or "")).strip()
        if name and not _symbol_like(name, symbol):
            return name
    return None


def yf_suggester(yf: object) -> Suggester:
    """Yahoo search → fund names only, in Yahoo's relevance order."""

    def suggest(query: str) -> list[str]:
        quotes = yf.Search(query, max_results=8).quotes or []  # type: ignore[attr-defined]
        names: list[str] = []
        for quote in quotes:
            name = _fund_name(quote)
            if name and name not in names:
                names.append(name)
        return names

    return suggest


def cached_suggester(upstream: Suggester) -> Suggester:
    """Memoize exact queries so editing text does not refetch prefixes."""
    cache: dict[str, list[str]] = {}

    def suggest(query: str) -> list[str]:
        if query not in cache:
            try:
                cache[query] = list(upstream(query))
            except Exception:
                cache[query] = []  # suggestions are best-effort, never fatal
        return cache[query]

    return suggest
