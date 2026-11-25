"""Render fund data and validated insights as Markdown."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Final

from src.extraction.extraction import AMOUNT_FIELDS, RATIO_FIELDS
from src.core.formatting import format_amount, format_percent
from src.core.models import FundProfile, NewsItem, ReportSections

PROFILE_SCHEMA_VERSION: Final[int] = 3
NEWS_SCHEMA_VERSION: Final[int] = 2

_CITATION_RE: Final[re.Pattern[str]] = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")

def _format_report_timestamp(moment: datetime) -> str:
    """Render the report time as UTC in day-month-year, minute precision."""
    return moment.astimezone(timezone.utc).strftime("%d-%m-%Y %H:%M")


def _cited_source_numbers(sections: ReportSections) -> set[int]:
    """Citation markers in the insight sections → the cited source numbers.

    Markers are the validated `[n]` / `[n, m]` forms produced by synthesis;
    the numbers refer to positions in the full news list.
    """
    cited: set[int] = set()
    for text in (sections.company_insights, sections.sector_insights):
        for match in _CITATION_RE.finditer(text):
            cited.update(int(number) for number in match.group(1).split(","))
    return cited


def render_report(
    profile: FundProfile,
    news: Sequence[NewsItem],
    sections: ReportSections,
    *,
    generated_at: datetime,
) -> str:
    """FundProfile + NewsItem[] + ReportSections → the markdown report."""
    lines = [
        f"# {profile.name} (Currency: {profile.currency or 'Unknown'})",
        "",
        f"Generated: {_format_report_timestamp(generated_at)}",
        "",
        "## Financial health\n",
        _financial_health_text(profile),
        "",
        "## Company insights\n",
        sections.company_insights,
        "",
        "## Sector insights\n",
        sections.sector_insights,
    ]
    if profile.gaps:
        lines += ["", "## Data gaps"]
        lines += [f"- {gap}" for gap in profile.gaps]
    lines += ["", "## Sources\n"]
    if news:
        cited = _cited_source_numbers(sections)
        lines += [
            f"{index}. [{item.title}]({item.url})"
            for index, item in enumerate(news, start=1)
            if index in cited
        ]
    else:
        lines.append("None found in this run.")
    return "\n".join(lines) + "\n"


#: Investor-facing explanation per overview metric, shown in the Financial
#: health table. Keys are provider field names; unknown fields fall back to
#: `_METRIC_GUIDE_FALLBACK`. Keep the text pipe-free (Markdown table cells).
_METRIC_GUIDES: Final[dict[str, str]] = {
    "totalAssets": (
        "The total market value of everything the fund owns. A large, stable "
        "asset base usually signals an established fund, though very large "
        "funds can find it harder to trade in and out of positions."
    ),
    "expenseRatio": (
        "The fund's annual running cost as a percentage of its assets, taken "
        "from returns before you see them. Lower is better: at 1% a 10,000 "
        "holding costs 100 a year, at 0.2% it costs 20."
    ),
    "yield": (
        "Income the fund paid out over the past year as a percentage of its "
        "net asset value (NAV). It shows the cash return you might expect if "
        "you hold the fund for income rather than growth."
    ),
    "navPrice": (
        "The price of one fund unit, calculated from the value of the "
        "underlying holdings less liabilities. It is the reference price for "
        "fund transactions; an ETF's market price can still deviate from it "
        "during the trading day."
    ),
    "currency": (
        "The currency the fund's figures are reported in. If it differs from "
        "your own currency, exchange-rate moves can boost or erode your "
        "returns independently of the fund's performance."
    ),
    "ytdReturn": (
        "How much the fund's value has changed since the start of this year, "
        "with distributions reinvested, through the most recent trading day. "
        "A useful current snapshot, but a short window says little about how "
        "the fund performs over a full market cycle."
    ),
    "threeYearAverageReturn": (
        "The average yearly return over the last three years, with "
        "distributions reinvested. A three-year window smooths out one-off "
        "events and shows how the fund behaved across several market "
        "conditions."
    ),
    "fiveYearAverageReturn": (
        "The average yearly return over the last five years, with "
        "distributions reinvested. Five years usually spans both rising and "
        "falling markets, making it one of the better gauges of consistent "
        "management."
    ),
    "trailingThreeMonthReturns": (
        "The fund's total return over the most recent three months. Handy for "
        "spotting recent momentum, but far too short a window to judge a "
        "fund's quality on."
    ),
    "dividendRate": (
        "Income paid per fund unit over the past year. Multiply it by the "
        "number of units you hold to estimate the annual cash income from "
        "your investment."
    ),
    "dividendYield": (
        "The income the fund paid over the past year as a percentage of its "
        "price. For funds Yahoo typically reports the same trailing figure "
        "as the Yield row; an unusually high yield can also signal a falling "
        "price or elevated risk."
    ),
    "beta3Year": (
        "How strongly the fund has moved with its benchmark index (whose "
        "beta is 1.0), based on monthly returns over three years: 1.24 means "
        "it historically rose or fell about 24% more than the index. Above 1 "
        "suggests a bumpier ride; below 1 a calmer one."
    ),
    "morningStarOverallRating": (
        "Morningstar's 1-to-5 star rating comparing the fund's risk-adjusted "
        "performance with funds in the same category: 5 stars means the top "
        "10% of the category, 4 stars the next 22.5%, 3 stars the middle 35%, "
        "2 stars the next 22.5%, and 1 star the bottom 10%. It is "
        "backward-looking and not a prediction."
    ),
    "morningStarRiskRating": (
        "Morningstar's 1-to-5 score of the downside risk the fund has shown "
        "in the past — how far its returns fell below a risk-free return — "
        "compared with funds in its category: 1 is Low risk (the calmest "
        "10%), 2 Below Average, 3 Average, 4 Above Average, and 5 High (the "
        "riskiest 10%). Higher numbers mean a rockier ride."
    ),
    "inception": (
        "The date the fund launched. A longer track record gives more "
        "history to judge it by; a young fund has little evidence of how it "
        "weathers a downturn."
    ),
}
_METRIC_GUIDE_FALLBACK: Final[str] = (
    "Yahoo reports this figure for the fund; check the fund's factsheet for "
    "its exact definition."
)


def _financial_health_text(profile: FundProfile) -> str:
    """Present overview metrics as a table with investor-facing context."""
    metrics = _overview_display(profile.overview)
    if not metrics:
        return (
            "Fund overview metrics are not available. This section reports "
            "fund-level data only; it does not assess the individual "
            "companies held by the fund."
        )
    lines = [
        "| Metric | Value | What it means |",
        "| --- | --- | --- |",
    ]
    lines += [
        f"| {_metric_label(key)} | {value} | "
        f"{_METRIC_GUIDES.get(key, _METRIC_GUIDE_FALLBACK)} |"
        for key, value in metrics.items()
    ]
    lines += [
        "",
        "These figures describe the fund, not the financial health of "
        "each company it holds.",
    ]
    return "\n".join(lines)


def _metric_label(key: str) -> str:
    """Turn provider field names such as ``expenseRatio`` into readable labels."""
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key).replace("_", " ")
    return words[:1].upper() + words[1:]


def _overview_display(
    overview: Mapping[str, float | int | str],
) -> dict[str, str]:
    """Overview metrics → the artifact's formatted strings (schema 2).

    Ratios read as percents (FR2 stores them as percent values), amounts as
    magnitude words (2.15 billion); anything else passes through as text.
    """
    formatted: dict[str, str] = {}
    for key, value in overview.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if key in RATIO_FIELDS:
                formatted[key] = format_percent(float(value))
            elif key in AMOUNT_FIELDS:
                formatted[key] = format_amount(float(value))
            else:
                formatted[key] = str(value)
        else:
            formatted[key] = str(value)
    return formatted
