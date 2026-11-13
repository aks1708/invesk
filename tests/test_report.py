"""FR5 rendering and artifact-document transformations (constitution P5).

Markdown and versioned artifact documents are tested as pure transformations.
"""

from datetime import UTC, datetime

from src.core.models import FundProfile, Holding, NewsItem, ReportSections
from src.reporting.report import (
    fund_profile_document,
    news_document,
    render_report,
)

FIXED_NOW = datetime(2026, 11, 12, 12, 0, 0, tzinfo=UTC)


def make_profile(gaps=()) -> FundProfile:
    return FundProfile(
        fund="Vanguard FTSE 250",
        ticker="VMID.L",
        name="Vanguard FTSE 250 UCITS ETF",
        provider="yahoo",
        family="Vanguard",
        currency="GBp",
        holdings=(Holding(name="Balfour Beatty PLC", symbol="BBY.L", weight=1.38),),
        sector_weights={"industrials": 20.55},
        overview={"totalAssets": 2148292608},
        gaps=gaps,
    )


def make_news(**overrides) -> NewsItem:
    values = {
        "title": "Balfour wins contract",
        "url": "https://news.example/balfour",
        "source": "example.news",
        "published": "2026-11-01",
        "summary": None,
        "content": "Full page text of the article.",
        "relevance": 1,
        "related": ("Balfour Beatty PLC",),
    }
    values.update(overrides)
    return NewsItem(**values)


def make_sections() -> ReportSections:
    return ReportSections(
        company_insights="Company text. [1]",
        sector_insights="Sector text. [1]",
    )


# --- render_report (the markdown transformation) -------------------------------


def test_render_report_has_metadata_data_sections_and_llm_insights():
    report = render_report(
        make_profile(), [make_news()], make_sections(), generated_at=FIXED_NOW
    )

    assert report.startswith("# Invesk report — Vanguard FTSE 250\n")
    assert "- Fund: Vanguard FTSE 250 UCITS ETF (Currency: GBp)" in report
    assert "- Generated: 12-11-2026 12:00" in report
    assert "## Snapshot\n\nVanguard FTSE 250 UCITS ETF is a Vanguard fund." in report
    assert "Balfour Beatty PLC (1.38%)" in report
    assert "industrials (20.55%)" in report
    assert "## Financial health\n\nAvailable fund-level metrics: Total Assets: 2.15 billion." in report
    assert "## Company insights\n\nCompany text. [1]" in report
    assert "## Sector insights\n\nSector text. [1]" in report
def test_render_report_lists_sources_with_url_source_and_date():
    news = [
        make_news(),
        make_news(
            title="WPP cuts guidance",
            url="https://news.example/wpp",
            source="market.wire",
            published=None,
        ),
    ]
    report = render_report(
        make_profile(), news, make_sections(), generated_at=FIXED_NOW
    )

    assert (
        "1. [Balfour wins contract](https://news.example/balfour) — example.news, 2026-11-01"
        in report
    )
    assert (
        "2. [WPP cuts guidance](https://news.example/wpp) — market.wire, date unknown"
        in report
    )


def test_render_report_preserves_citation_markers_and_source_numbering():
    news = [
        make_news(),
        make_news(
            title="WPP cuts guidance",
            url="https://news.example/wpp",
            source="market.wire",
            related=("WPP",),
        ),
    ]
    sections = ReportSections(
        company_insights="WPP cut its guidance. [2]",
        sector_insights="The reported development is relevant. [1]",
    )

    report = render_report(make_profile(), news, sections, generated_at=FIXED_NOW)

    assert "## Company insights\n\nWPP cut its guidance. [2]" in report
    assert "## Sector insights\n\nThe reported development is relevant. [1]" in report
    assert "1. [Balfour wins contract](https://news.example/balfour)" in report
    assert "2. [WPP cuts guidance](https://news.example/wpp)" in report


def test_render_report_without_news_says_so():
    uncited_sections = ReportSections(
        company_insights="No company news was found.",
        sector_insights="No sector news was found.",
    )
    report = render_report(make_profile(), [], uncited_sections, generated_at=FIXED_NOW)

    assert "## Sources\n\nNone found in this run.\n" in report


def test_render_report_flags_gaps_and_omits_the_section_when_clear():
    with_gaps = render_report(
        make_profile(
            gaps=("sector weights unavailable", "holding statements unavailable")
        ),
        [make_news()],
        make_sections(),
        generated_at=FIXED_NOW,
    )
    without = render_report(
        make_profile(), [make_news()], make_sections(), generated_at=FIXED_NOW
    )

    assert "## Data gaps" in with_gaps
    assert "- sector weights unavailable" in with_gaps
    assert "## Data gaps" not in without


# --- artifact documents ---------------------------------------------------------


def test_fund_profile_document_carries_the_schema_version_and_profile():
    document = fund_profile_document(make_profile(gaps=("sector weights",)))

    assert document["schema_version"] == 3  # schema 3: performance metrics
    assert document["fund"] == "Vanguard FTSE 250"
    assert document["ticker"] == "VMID.L"
    assert document["name"] == "Vanguard FTSE 250 UCITS ETF"
    assert document["provider"] == "yahoo"
    assert document["family"] == "Vanguard"
    assert document["currency"] == "GBp"
    assert document["holdings"] == [
        {"name": "Balfour Beatty PLC", "symbol": "BBY.L", "weight": "1.38%"}
    ]
    assert document["sector_weights"] == {"industrials": "20.55%"}
    assert document["overview"] == {"totalAssets": "2.15 billion"}
    assert document["gaps"] == ["sector weights"]


def test_news_document_carries_the_schema_version_and_items():
    document = news_document([make_news()])

    assert document["schema_version"] == 2
    assert document["news"] == [
        {
            "title": "Balfour wins contract",
            "url": "https://news.example/balfour",
            "source": "example.news",
            "published": "2026-11-01",
            "summary": None,
            "content": "Full page text of the article.",
            "relevance": 1,
            "related": ["Balfour Beatty PLC"],
        }
    ]
    assert news_document([]) == {"schema_version": 2, "news": []}
