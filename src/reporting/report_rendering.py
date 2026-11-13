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

def _format_report_timestamp(moment: datetime) -> str:
    """Render the report time as UTC in day-month-year, minute precision."""
    return moment.astimezone(timezone.utc).strftime("%d-%m-%Y %H:%M")


def render_report(
    profile: FundProfile,
    news: Sequence[NewsItem],
    sections: ReportSections,
    *,
    generated_at: datetime,
) -> str:
    """FundProfile + NewsItem[] + ReportSections → the markdown report."""
    lines = [
        f"# Invesk report — {profile.fund}",
        "",
        f"- Fund: {profile.name} (Currency: {profile.currency or 'Unknown'})",
        f"- Generated: {_format_report_timestamp(generated_at)}",
        "",
        "## Snapshot\n",
        _snapshot_text(profile),
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
        lines += [
            f"{index}. [{item.title}]({item.url}) — {item.source}, "
            f"{item.published or 'date unknown'}"
            for index, item in enumerate(news, start=1)
        ]
    else:
        lines.append("None found in this run.")
    return "\n".join(lines) + "\n"


def _snapshot_text(profile: FundProfile) -> str:
    """Describe available fund composition without model-generated claims."""
    parts = (
        [f"{profile.name} is a {profile.family} fund."]
        if profile.family
        else [f"{profile.name} is an investment fund."]
    )
    if profile.holdings:
        top = sorted(profile.holdings, key=lambda holding: holding.weight, reverse=True)[:5]
        parts.append(
            "Its largest reported holdings are "
            + ", ".join(
                f"{holding.name} ({format_percent(holding.weight)})" for holding in top
            )
            + "."
        )
    else:
        parts.append("Top holdings information is not available.")
    if profile.sector_weights:
        sectors = sorted(
            profile.sector_weights.items(), key=lambda item: item[1], reverse=True
        )[:5]
        parts.append(
            "Its largest reported sector allocations are "
            + ", ".join(f"{name} ({format_percent(weight)})" for name, weight in sectors)
            + "."
        )
    else:
        parts.append("Sector allocation information is not available.")
    return " ".join(parts)


def _financial_health_text(profile: FundProfile) -> str:
    """Present overview metrics as data, without interpreting them."""
    metrics = _overview_display(profile.overview)
    if not metrics:
        return (
            "Fund overview metrics are not available. This section reports "
            "fund-level data only; it does not assess the individual "
            "companies held by the fund."
        )
    rendered = ", ".join(
        f"{_metric_label(key)}: {value}" for key, value in metrics.items()
    )
    return (
        "Available fund-level metrics: "
        + rendered
        + ". These figures describe the fund, not the financial health of "
        "each company it holds."
    )


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


