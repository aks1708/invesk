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

    assert report.startswith("# Vanguard FTSE 250 UCITS ETF (Currency: GBp)\n")
    assert "\nGenerated: 12-11-2026 12:00\n" in report
    assert "- Fund:" not in report
    assert "## Snapshot" not in report
    assert "Balfour Beatty PLC (1.38%)" not in report
    assert "industrials (20.55%)" not in report
    assert (
        "## Financial health\n\n| Metric | Value | What it means |\n"
        "| --- | --- | --- |\n| Total Assets | 2.15 billion | The total market "
        "value of everything the fund owns."
    ) in report
    assert "## Company insights\n\nCompany text. [1]" in report
    assert "## Sector insights\n\nSector text. [1]" in report


def test_render_report_financial_health_table_has_context_and_disclaimer():
    from dataclasses import replace

    profile = replace(
        make_profile(),
        overview={"totalAssets": 2148292608, "unlistedMetric": "42"},
    )
    report = render_report(profile, [make_news()], make_sections(), generated_at=FIXED_NOW)

    table = report.split("## Financial health\n\n", 1)[1].split("\n\n", 1)[0]
    rows = [line for line in table.splitlines() if line.startswith("| ") and "---" not in line]
    labels = [row.split(" | ")[0].lstrip("| ") for row in rows]
    assert labels == ["Metric", "Total Assets", "Unlisted Metric"]
    assert rows[1].endswith(
        "A large, stable asset base usually signals an established fund, "
        "though very large funds can find it harder to trade in and out of "
        "positions. |"
    )
    assert rows[2].endswith(
        "Yahoo reports this figure for the fund; check the fund's factsheet "
        "for its exact definition. |"
    )
    assert (
        "These figures describe the fund, not the financial health of "
        "each company it holds." in report
    )
def test_render_report_lists_only_cited_sources_as_numbered_links():
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

    assert "1. [Balfour wins contract](https://news.example/balfour)" in report
    assert "WPP cuts guidance" not in report


def test_render_report_sources_combine_citations_from_both_insight_sections():
    news = [
        make_news(),
        make_news(
            title="WPP cuts guidance",
            url="https://news.example/wpp",
            source="market.wire",
            related=("WPP",),
        ),
        make_news(
            title="Unrelated item",
            url="https://news.example/other",
            source="other.wire",
            related=("Other",),
        ),
    ]
    sections = ReportSections(
        company_insights="Company text. [1]",
        sector_insights="Sector text. [3]",
    )

    report = render_report(make_profile(), news, sections, generated_at=FIXED_NOW)

    assert "1. [Balfour wins contract](https://news.example/balfour)" in report
    assert "3. [Unrelated item](https://news.example/other)" in report
    assert "WPP cuts guidance" not in report


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
