"""Yahoo-backed fund-name suggestions shared by the browser interface."""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache

from src.extraction.profile import FUND_QUOTE_TYPES

MIN_QUERY_LEN = 1
MAX_SEARCH_QUOTES = 100
SCREENER_PAGE_SIZE = 250
MAX_INDEX_EXPANSIONS = 3

Suggester = Callable[[str], list[str]]

# Ticker charset: no whitespace, no lowercase (e.g. `0P00017EQ6.L`).
_SYMBOL_LIKE_RE = re.compile(r"[A-Z0-9][A-Z0-9.+\-^=]{0,11}\Z")


def _tokens(value: str) -> tuple[str, ...]:
    """Case-folded alphanumeric words for order-independent name matching."""
    return tuple(re.findall(r"[a-z0-9]+", value.casefold()))


def _name_matches(name: str, query: str) -> bool:
    """True when every query word occurs in the name, in any order."""
    query_tokens = _tokens(query)
    name_tokens = _tokens(name)
    return bool(query_tokens) and all(
        any(query_token in name_token for name_token in name_tokens)
        for query_token in query_tokens
    )


def _symbol_like(name: str, symbol: str) -> bool:
    """True when the candidate name is a ticker rather than a fund name."""
    if name == symbol:
        return True
    return bool(_SYMBOL_LIKE_RE.fullmatch(name)) and (
        any(char.isdigit() for char in name) or "." in name
    )


def _fund_name(quote: dict, query: str) -> str | None:
    """One Yahoo quote → a matching fund name, or None when it is not one.

    Only names containing the query (case-insensitively) are returned.
    Candidates equal to the quote symbol or shaped like a ticker are skipped.
    """
    if str(quote.get("quoteType") or "").upper() not in FUND_QUOTE_TYPES:
        return None
    symbol = str(quote.get("symbol") or "").strip()
    for field in ("longname", "longName", "shortname", "shortName"):
        name = re.sub(r"\s+", " ", str(quote.get(field) or "")).strip()
        if name and _name_matches(name, query) and not _symbol_like(name, symbol):
            return name
    return None


def _family_names(yf: object) -> tuple[str, ...]:
    """Yahoo's ETF screener exposes fund families shared by ETFs and funds."""
    try:
        query = yf.ETFQuery("eq", ["region", "us"])  # type: ignore[attr-defined]
        values = query.valid_values.get("fundfamilyname", ())
    except Exception:
        return ()
    return tuple(sorted((str(value) for value in values), key=str.casefold))


def _screen_family(yf: object, family: str) -> list[str]:
    """Page through all ETFs and mutual funds for one Yahoo fund family."""
    names: list[str] = []
    for quote_type in ("ETF", "MUTUALFUND"):
        if quote_type == "ETF":
            query = yf.ETFQuery(  # type: ignore[attr-defined]
                "eq", ["fundfamilyname", family]
            )
        else:
            # Yahoo's screener accepts fundfamilyname for mutual funds too,
            # although yfinance's FundQuery validator does not expose it.
            query = yf.FundQuery(  # type: ignore[attr-defined]
                "eq", ["exchange", "NAS"]
            )
            query.operands[:] = ["fundfamilyname", family]

        offset = 0
        while True:
            page = yf.screen(  # type: ignore[attr-defined]
                query, offset=offset, size=SCREENER_PAGE_SIZE
            )
            quotes = page.get("quotes") or []
            for quote in quotes:
                name = _fund_name(quote, family)
                if name and name not in names:
                    names.append(name)

            total = page.get("total")
            offset += len(quotes)
            if (
                not quotes
                or len(quotes) < SCREENER_PAGE_SIZE
                or (total is not None and offset >= int(total))
            ):
                break
    return names


def yf_suggester(yf: object) -> Suggester:
    """Yahoo fund-family screener, falling back to its relevance search."""
    families = _family_names(yf)

    @lru_cache(maxsize=128)
    def screen_family(family: str) -> tuple[str, ...]:
        return tuple(_screen_family(yf, family))

    def suggest(query: str) -> list[str]:
        query_tokens = tuple(token for token in _tokens(query) if len(token) >= 3)
        matching_families = (
            [
                family
                for family in families
                if any(
                    query_token in "".join(_tokens(family))
                    for query_token in query_tokens
                )
            ]
            if query_tokens
            else []
        )
        if matching_families:
            try:
                names: list[str] = []
                for family in matching_families:
                    for name in screen_family(family):
                        if _name_matches(name, query) and name not in names:
                            names.append(name)
                return names
            except Exception:
                # A screener outage should not take down ordinary suggestions.
                pass

        quotes = (
            yf.Search(query, max_results=MAX_SEARCH_QUOTES).quotes  # type: ignore[attr-defined]
            or []
        )
        names: list[str] = []
        for quote in quotes:
            name = _fund_name(quote, query)
            if name and name not in names:
                names.append(name)

        # A broad query such as "FTSE" can return the index but omit funds
        # tracking it. Use matching index names as bounded, more specific
        # searches; index quotes themselves remain excluded from suggestions.
        query_words = set(_tokens(query))
        index_names: list[str] = []
        for quote in quotes:
            if str(quote.get("quoteType") or "").upper() != "INDEX":
                continue
            index_name = next(
                (
                    re.sub(r"\s+", " ", str(quote.get(field) or "")).strip()
                    for field in ("longname", "longName", "shortname", "shortName")
                    if _name_matches(str(quote.get(field) or ""), query)
                ),
                "",
            )
            if (
                not index_name
                or set(_tokens(index_name)) <= query_words
                or index_name.casefold() in {name.casefold() for name in index_names}
            ):
                continue
            index_names.append(index_name)
            if len(index_names) >= MAX_INDEX_EXPANSIONS:
                break

        for index_name in index_names:
            related_quotes = (
                yf.Search(index_name, max_results=MAX_SEARCH_QUOTES).quotes  # type: ignore[attr-defined]
                or []
            )
            for quote in related_quotes:
                name = _fund_name(quote, query)
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
