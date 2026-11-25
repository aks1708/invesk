"""Normalize Yahoo fund data into the application's FundProfile model."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from src.core.models import FundProfile, Holding

#: Quote types Yahoo returns for funds; anything else (EQUITY, INDEX, …) is
#: rejected so a company share can never masquerade as the named fund.
FUND_QUOTE_TYPES = ("ETF", "MUTUALFUND")

#: Curated fund-level metrics presented in the report overview (PRD §10).
#: Extended 2026-11-13 with the fund-performance metrics an investor reads
#: first: returns (`trailingThreeMonthReturns` joins `ytdReturn` and the
#: three-/five-year averages), cost (`dividendRate` aside, see below),
#: income (`dividendRate`, `dividendYield`), risk (`beta3Year`, Morningstar
#: ratings), all straight from `info`. `category` comes from
#: `funds_data.fund_overview`, not `info`.
OVERVIEW_FIELDS = (
    "totalAssets",
    "expenseRatio",
    "yield",
    "navPrice",
    "currency",
    "ytdReturn",
    "threeYearAverageReturn",
    "fiveYearAverageReturn",
    "trailingThreeMonthReturns",
    "dividendRate",
    "dividendYield",
    "beta3Year",
    "morningStarOverallRating",
    "morningStarRiskRating",
)

#: Overview ratios Yahoo sends as fractions (0.2146 = 21.46%) — verified
#: against 1.8.0 payloads for ETFs and mutual funds (2026-11-12, re-verified
#: 2026-11-13). FR2 multiplies them by 100 so every ratio in a FundProfile is
#: a percent value: 10 means 10%, never 0.1. `ytdReturn` arrives already in
#: percent (11.73 = 11.73%) and passes through unchanged. `expenseRatio`
#: often falls back from `funds_data.fund_operations`, also a fraction.
FRACTION_RATIO_FIELDS = (
    "expenseRatio",
    "yield",
    "threeYearAverageReturn",
    "fiveYearAverageReturn",
    "annualHoldingsTurnover",
)

#: All overview ratio fields, percent values after normalization — the unit
#: contract downstream consumers (FR4 prompt, FR5 artifacts) format against.
#: `trailingThreeMonthReturns` and `dividendYield` arrive already in percent
#: (1.07 = 1.07%, verified 2026-11-13 across ETFs and mutual funds) and pass
#: through, like `ytdReturn`.
RATIO_FIELDS = FRACTION_RATIO_FIELDS + (
    "ytdReturn",
    "trailingThreeMonthReturns",
    "dividendYield",
)

#: Overview fields denominated in the fund's currency; rendered with
#: magnitude words (2.15 billion) by the FR4/FR5 presentation surfaces.
AMOUNT_FIELDS = ("totalAssets", "navPrice", "dividendRate")

#: Overview fields that are neither percents nor amounts — `beta3Year` is a
#: market-relative ratio (0.97) and the Morningstar ratings are 1–5
#: integers. They must never be multiplied by 100; the FR4/FR5 presentation
#: surfaces pass them through as-is.
UNITLESS_FIELDS = (
    "beta3Year",
    "morningStarOverallRating",
    "morningStarRiskRating",
)

STAGE = "fund_extraction"


class ExtractionError(RuntimeError):
    """Yahoo provider failure: network, HTTP, timeout, or unparseable data."""


class FundNotFoundError(ExtractionError):
    """No fund quote matched the requested name on Yahoo."""


def normalize_percent(raw: object) -> float | None:
    """Percent string or number → percent value in [0, 100]; unusable → None.

    Yahoo sends weights as a fraction (0.013818) or a percent string
    ("1.38%"). A bare number at or below 1 is read as a fraction and
    multiplied by 100; an explicit `%` suffix or a bare number above 1 is
    already a percent. Every percent-denominated value in a FundProfile is
    stored this way — 10 means 10%.
    """
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip()
    explicit_percent = text.endswith("%")
    try:
        value = float(text.removesuffix("%").strip())
    except ValueError:
        return None
    if not explicit_percent and value <= 1.0:
        value *= 100.0  # a bare fraction; "1.38%" is already a percent
    return value if 0.0 <= value <= 100.0 else None


def sector_label(key: str) -> str:
    """Yahoo sector key `consumer_cyclical` → readable `Consumer Cyclical`."""
    aliases = {"realestate": "Real Estate"}
    return aliases.get(key.lower()) or key.replace("_", " ").title()


def find_fund_quote(quotes: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """First Yahoo quote that is a fund (ETF/MUTUALFUND) with a symbol."""
    for quote in quotes or ():
        if (
            str(quote.get("quoteType") or "").upper() in FUND_QUOTE_TYPES
            and quote.get("symbol")
        ):
            return quote
    return None


def holdings_from_frame(frame: Any) -> list[dict[str, Any]]:
    """Boundary adapter: yfinance top-holdings DataFrame → plain dicts.

    Verified against yfinance 1.8.0 for ETFs and mutual funds: the weight
    column is `Holding Percent` (a fraction). Older layouts keep fallbacks.
    """
    if frame is None or len(frame) == 0:
        return []
    records = []
    for symbol, row in frame.iterrows():
        row = dict(row)
        name = row.get("Name")
        # NaN arrives as float nan; drop it at the boundary
        if name is None or (isinstance(name, float) and math.isnan(name)):
            name = ""
        percent = row.get("Holding Percent", row.get("Percent", row.get("Holding")))
        records.append(
            {
                "symbol": str(symbol).strip(),
                "name": str(name).strip() or str(symbol).strip(),
                "percent": percent,
            }
        )
    return records


def _finite_number(value: object) -> float | None:
    """Number-ish value → float; pandas NA/NaN, bools, text → None.

    `fund_operations` arrives from a DataFrame column whose missing entries
    are `pd.NA` or `float("nan")` — both unusable, neither a default.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def overview_metrics(
    info: Mapping[str, Any],
    *,
    fund_operations: Mapping[str, Any] | None = None,
    fund_overview: Mapping[str, Any] | None = None,
) -> dict[str, float | int | str]:
    """Curated overview metrics with Yahoo's mixed ratio units normalized.

    `expenseRatio`, `yield`, and the three-/five-year average returns
    arrive as fractions and are stored as percent values (0.2146 → 21.46);
    `ytdReturn`, `trailingThreeMonthReturns`, and `dividendYield` arrive as
    percents and pass through. Amounts (`totalAssets`, `navPrice`,
    `dividendRate`) stay in the fund's currency; formatting them (2.15
    billion) is the FR4/FR5 presentation concern. `beta3Year` and the
    Morningstar ratings are unitless and pass through untouched.

    Yahoo omits `expenseRatio` from `info` for most funds but reliably
    sends it (and `annualHoldingsTurnover`) in the funds-operations
    DataFrame; those become fallbacks, never overrides. `inception`
    converts `info.fundInceptionDate` (epoch seconds) to an ISO date, and
    `category` comes from `funds_data.fund_overview.categoryName`.
    """
    overview: dict[str, float | int | str] = {
        field: info[field] for field in OVERVIEW_FIELDS if info.get(field) is not None
    }
    for field in FRACTION_RATIO_FIELDS:
        value = overview.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            # round to 6 decimals: kills the ×100 float noise (0.0342*100
            # → 3.4200000000000004) without losing Yahoo's precision
            overview[field] = round(value * 100.0, 6)
    inception = info.get("fundInceptionDate")
    if inception is not None:
        overview["inception"] = datetime.fromtimestamp(
            float(inception), tz=UTC
        ).date().isoformat()
    for label, field in (
        ("Annual Report Expense Ratio", "expenseRatio"),
        ("Annual Holdings Turnover", "annualHoldingsTurnover"),
    ):
        if overview.get(field) is None and fund_operations:
            value = _finite_number(fund_operations.get(label))
            if value is not None:  # fractions here too (0.0003 → 0.03)
                overview[field] = round(value * 100.0, 6)
    category = (fund_overview or {}).get("categoryName")
    if category:
        overview["category"] = str(category)
    return overview


def operations_from_frame(frame: Any, symbol: str) -> dict[str, Any]:
    """Boundary adapter: yfinance fund-operations DataFrame → plain dicts.

    The frame is indexed by attribute label (`Annual Report Expense Ratio`,
    `Annual Holdings Turnover`, `Total Net Assets`) with one column per
    symbol plus a category average; only the fund's own column is kept.
    Missing entries stay `pd.NA`/NaN and are dropped later by
    `_finite_number` (P7: re-verify if the boundary changes — the raw
    `Total Net Assets` figure has unverifiable units and is never read).
    """
    if frame is None or symbol not in getattr(frame, "columns", ()):
        return {}
    return {str(label): value for label, value in frame[symbol].items()}


def build_profile(
    fund: str,
    quote: Mapping[str, Any],
    info: Mapping[str, Any],
    top_holdings: Sequence[Mapping[str, Any]],
    sector_weightings: Mapping[str, Any],
    *,
    fund_operations: Mapping[str, Any] | None = None,
    fund_overview: Mapping[str, Any] | None = None,
) -> FundProfile:
    """Pure adapter: raw Yahoo payloads → FundProfile; gaps over defaults."""
    gaps: list[str] = []

    holdings: list[Holding] = []
    for record in top_holdings:
        weight = normalize_percent(record.get("percent"))
        if weight is None:
            gaps.append(f"holding weight unusable for {record.get('name')}")
            continue
        holdings.append(
            Holding(
                name=str(record.get("name") or ""),
                symbol=str(record.get("symbol") or ""),
                weight=weight,
            )
        )
    if not holdings:
        gaps.append("top holdings not available")

    sector_weights: dict[str, float] = {}
    for key, raw in (sector_weightings or {}).items():
        weight = normalize_percent(raw)
        if weight is not None:
            sector_weights[sector_label(str(key))] = weight
    if not sector_weights:
        gaps.append("sector weights not available")

    overview = overview_metrics(
        info,
        fund_operations=fund_operations,
        fund_overview=fund_overview,
    )
    if not overview:
        gaps.append("overview metrics not available")

    # Yahoo omits info.fundFamily for most funds; funds_data.fund_overview
    # (the fundProfile module) reliably carries the family name.
    family = info.get("fundFamily") or (fund_overview or {}).get("family") or None

    return FundProfile(
        fund=fund,
        ticker=str(quote.get("symbol") or ""),
        name=str(info.get("longName") or quote.get("longname") or fund),
        provider="yahoo",
        family=family,
        currency=info.get("currency"),
        holdings=tuple(holdings),
        sector_weights=sector_weights,
        overview=overview,
        gaps=tuple(gaps),
    )

