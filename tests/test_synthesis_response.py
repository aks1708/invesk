"""Focused tests split from test_synthesis.py."""

import json

import pytest

from _synthesis_support import (
    ReportSections,
    SynthesisError,
    parse_sections,
    raw_sections,
)

# --- parse_sections (boundary validation) --------------------------------------


def test_parse_sections_accepts_a_bare_object_and_trims_values():
    text = raw_sections(company_insights="  Balfour Beatty won a contract.  ")
    assert parse_sections(text) == ReportSections(
        company_insights="Balfour Beatty won a contract.",
        sector_insights="Construction demand is expected to keep rising.",
    )


def test_parse_sections_validates_source_tokens_and_maps_them_to_report_numbers():
    source_numbers = {"https://www.reuters.com/article/x": 4}
    text = raw_sections(
        company_insights="Balfour Beatty won a contract. [S4]",
        sector_insights="Construction demand is rising. [S4]",
    )

    sections = parse_sections(
        text, source_numbers=source_numbers
    )

    assert sections.company_insights.endswith("[4]")
    assert sections.sector_insights.endswith("[4]")


def test_parse_sections_accepts_grouped_source_tokens_and_maps_each_number():
    source_numbers = {
        "https://www.reuters.com/article/x": 28,
        "https://www.bb.com/sector": 41,
    }
    text = raw_sections(
        company_insights="Construction work is growing. [S28, S41]",
        sector_insights="Sector activity is rising. [S41]",
    )

    sections = parse_sections(text, source_numbers=source_numbers)

    assert sections.company_insights.endswith("[28, 41]")
    assert sections.sector_insights.endswith("[41]")


@pytest.mark.parametrize(
    ("company_insights", "reason"),
    [
        ("Balfour Beatty won a contract.", "missing source citations"),
        ("Balfour Beatty won a contract. [S99]", "unknown or malformed"),
        ("Balfour Beatty won a contract. [S01]", "unknown or malformed"),
        ("Balfour Beatty won a contract. [Sx]", "unknown or malformed"),
    ],
)
def test_parse_sections_rejects_missing_or_untrusted_source_tokens(
    company_insights, reason
):
    with pytest.raises(SynthesisError, match=reason):
        parse_sections(
            raw_sections(company_insights=company_insights),
                source_numbers={"https://www.reuters.com/article/x": 1},
        )


@pytest.mark.parametrize(
    "text",
    [
        "",  # no text at all
        "no json here",  # prose only
        "{not json",  # braces but not JSON
        '[{"level": "beginner"}]',  # a JSON list is not the object
        raw_sections(company_insights=None),  # section not a string
        raw_sections(sector_insights="   "),  # section empty
        raw_sections(company_insights="   "),  # section empty
        json.dumps({"company_insights": "s"}),  # sections missing
        json.dumps({"level": "beginner", **json.loads(raw_sections())}),  # removed option
            ],
)
def test_parse_sections_rejects_malformed_replies(text):
    with pytest.raises(SynthesisError) as excinfo:
        parse_sections(text)
    assert excinfo.value.error_code == "synthesis_failed"
