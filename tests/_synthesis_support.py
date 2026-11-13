"""Shared fixtures and doubles for focused transformation tests."""

import json

from src.core.models import (
    FundProfile,
    Holding,
    NewsItem,
    ReportSections,
)
from src.synthesis.synthesis import (
    MAX_ITEMS_PER_ENTITY,
    SynthesisError,
    build_prompt,
    news_for_prompt,
    parse_sections,
)
def make_profile(holdings=(), sectors=None) -> FundProfile:
    return FundProfile(
        fund="Vanguard FTSE 250",
        ticker="VMID.L",
        name="Vanguard FTSE 250 UCITS ETF",
        provider="yahoo",
        family="Vanguard",
        currency="GBX",
        holdings=tuple(holdings),
        sector_weights=sectors or {},
        overview={},
        gaps=(),
    )


def news(
    title="Balfour Beatty wins contract",
    url="https://www.reuters.com/article/x",
    **overrides,
):
    fields = {
        "title": title,
        "url": url,
        "source": "www.reuters.com",
        "published": "2026-11-01T00:00:00.000Z",
        "summary": "It won a contract.",
        "content": "It won a 200 million pound contract on Tuesday.",
        "relevance": 1,
        "related": ("Balfour Beatty PLC",),
    }
    fields.update(overrides)
    return NewsItem(**fields)


def raw_sections(**overrides) -> str:
    """A syntactically valid reply body; `overrides` break it on purpose."""
    data = {
        "company_insights": "Balfour Beatty won a contract and its order book is full.",
        "sector_insights": "Construction demand is expected to keep rising.",
    }
    data.update(overrides)
    return json.dumps(data)

