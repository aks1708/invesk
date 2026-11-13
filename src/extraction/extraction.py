"""FR2: instrumented fund data extraction via yfinance."""

from __future__ import annotations

import time
from collections.abc import Callable
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
    symbol = str(quote["symbol"])

    def fetch() -> tuple[
        Mapping[str, Any],
        list[dict[str, Any]],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
    ]:
        ticker = yf.Ticker(symbol)
        fund_data = ticker.funds_data
        return (
            ticker.info,
            holdings_from_frame(fund_data.top_holdings),
            dict(fund_data.sector_weightings or {}),
            operations_from_frame(fund_data.fund_operations, symbol),
            dict(fund_data.fund_overview or {}),
        )

    (
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
