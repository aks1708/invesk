"""FR2: instrumented fund data extraction via yfinance."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from typing import Any

from src.core.events import EventEmitter
from src.core.models import FundProfile
from src.extraction.profile import (
    AMOUNT_FIELDS,
    FRACTION_RATIO_FIELDS,
    FUND_QUOTE_TYPES,
    OVERVIEW_FIELDS,
    RATIO_FIELDS,
    UNITLESS_FIELDS,
    ExtractionError,
    FundNotFoundError,
    STAGE,
    build_profile,
    find_fund_quote,
    holdings_from_frame,
    normalize_percent,
    operations_from_frame,
    overview_metrics,
    sector_label,
)


def _instrumented(events: EventEmitter, provider: str, call: Callable[[], Any]) -> Any:
    """Run one third-party call, emitting its `external_call` event (P6)."""
    started = time.monotonic()
    try:
        result = call()
    except Exception as exc:
        events.emit(
            "external_call",
            stage=STAGE,
            provider=provider,
            latency_ms=int((time.monotonic() - started) * 1000),
            status="error",
        )
        raise ExtractionError(f"{provider} failed: {exc}") from exc
    events.emit(
        "external_call",
        stage=STAGE,
        provider=provider,
        latency_ms=int((time.monotonic() - started) * 1000),
        status="ok",
    )
    return result


def _matching_etf_equity_quote(
    quotes: list[dict[str, Any]], fund: str
) -> dict[str, Any] | None:
    """Find Yahoo's ETF result when search incorrectly labels it EQUITY.

    Yahoo can return the current ETF as EQUITY alongside stale MUTUALFUND
    share-class quotes for the same fund. Only consider this fallback when
    the requested name is explicitly an ETF, and require its meaningful name
    tokens to match; the candidate is then verified via `Ticker.info`.
    """
    if "etf" not in re.findall(r"[a-z0-9]+", fund.casefold()):
        return None
    query_tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", fund.casefold())
        if len(token) > 2 and token != "etf"
    ]
    if not query_tokens:
        return None
    for quote in quotes or ():
        if str(quote.get("quoteType") or "").upper() != "EQUITY":
            continue
        name = " ".join(
            str(quote.get(field) or "")
            for field in ("longname", "longName", "shortname", "shortName")
        )
        name_tokens = re.findall(r"[a-z0-9]+", name.casefold())
        joined_name = "".join(name_tokens)
        if all(
            token in name_tokens or token in joined_name for token in query_tokens
        ) and quote.get("symbol"):
            return quote
    return None


def extract_fund(fund: str, *, yf: Any, events: EventEmitter) -> FundProfile:
    """FR2 stage: fund name → Yahoo lookup and fetch → FundProfile."""
    quotes = _instrumented(
        events, "yahoo.search", lambda: yf.Search(fund, max_results=5).quotes
    )
    quote = find_fund_quote(quotes)
    if quote is None:
        raise FundNotFoundError(
            f"no fund matched {fund!r} on Yahoo (quoteType {' or '.join(FUND_QUOTE_TYPES)})"
        )
    alternate_etf_quote = _matching_etf_equity_quote(quotes, fund)
    symbol = str(quote["symbol"])

    def fetch() -> tuple[
        Mapping[str, Any],
        Mapping[str, Any],
        list[dict[str, Any]],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
    ]:
        ticker = yf.Ticker(symbol)
        selected_quote = quote
        info = ticker.info
        try:
            fund_data = ticker.funds_data
            return (
                selected_quote,
                info,
                holdings_from_frame(fund_data.top_holdings),
                dict(fund_data.sector_weightings or {}),
                operations_from_frame(fund_data.fund_operations, symbol),
                dict(fund_data.fund_overview or {}),
            )
        except Exception as exc:
            if (
                alternate_etf_quote is None
                or "no fund data found" not in str(exc).casefold()
            ):
                raise

            # A validated ETF result is safer than a stale mutual-fund class
            # whose Yahoo quoteSummary has no fundProfile data.
            etf_symbol = str(alternate_etf_quote["symbol"])
            etf_ticker = yf.Ticker(etf_symbol)
            etf_info = etf_ticker.info
            if str(etf_info.get("quoteType") or "").upper() != "ETF":
                raise
            etf_data = etf_ticker.funds_data
            return (
                alternate_etf_quote,
                etf_info,
                holdings_from_frame(etf_data.top_holdings),
                dict(etf_data.sector_weightings or {}),
                operations_from_frame(etf_data.fund_operations, etf_symbol),
                dict(etf_data.fund_overview or {}),
            )

    (
        quote,
        info,
        top_holdings,
        sector_weightings,
        fund_operations,
        fund_overview,
    ) = _instrumented(events, "yahoo.quote_summary", fetch)
    return build_profile(
        fund,
        quote,
        info or {},
        top_holdings,
        sector_weightings,
        fund_operations=fund_operations,
        fund_overview=fund_overview,
    )
