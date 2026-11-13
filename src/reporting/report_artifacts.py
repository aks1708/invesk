"""Serialize and write the versioned run artifacts."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from src.core.formatting import format_percent
from src.core.models import FundProfile, NewsItem, ReportSections
from src.reporting.report_rendering import (
    NEWS_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    _overview_display,
    render_report,
)

Clock = Callable[[], datetime]

def fund_profile_document(profile: FundProfile) -> dict[str, object]:
    """FundProfile → the fund_profile.json object (contracts/artifacts.v1.md)."""
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "fund": profile.fund,
        "ticker": profile.ticker,
        "name": profile.name,
        "provider": profile.provider,
        "family": profile.family,
        "currency": profile.currency,
        "holdings": [
            {
                "name": holding.name,
                "symbol": holding.symbol,
                "weight": format_percent(holding.weight),
            }
            for holding in profile.holdings
        ],
        "sector_weights": {
            sector: format_percent(weight)
            for sector, weight in profile.sector_weights.items()
        },
        "overview": _overview_display(profile.overview),
        "gaps": list(profile.gaps),
    }


def news_document(news: Sequence[NewsItem]) -> dict[str, object]:
    """NewsItem[] → the news.json object (contracts/artifacts.v1.md)."""
    return {
        "schema_version": NEWS_SCHEMA_VERSION,
        "news": [
            {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "published": item.published,
                "summary": item.summary,
                "content": item.content,
                "relevance": item.relevance,
                "related": list(item.related),
            }
            for item in news
        ],
    }


def _write_json(path: Path, document: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8") as sink:
        json.dump(document, sink, indent=2, ensure_ascii=False)
        sink.write("\n")


def write_report(
    run_dir: Path,
    profile: FundProfile,
    news: Sequence[NewsItem],
    sections: ReportSections,
    *,
    clock: Clock,
) -> tuple[str, Path]:
    """Write the §10 artifact set into run_dir → (report markdown, its path).

    fund_profile.json and news.json first, report.md last — so a report that
    exists implies its inputs were written too. Any failure raises OSError;
    the composition root maps that to exit 1 (PRD FR5).
    """
    _write_json(run_dir / "fund_profile.json", fund_profile_document(profile))
    _write_json(run_dir / "news.json", news_document(news))
    report = render_report(profile, news, sections, generated_at=clock())
    report_path = run_dir / "report.md"
    with report_path.open("w", encoding="utf-8") as sink:
        sink.write(report)
    return report, report_path
