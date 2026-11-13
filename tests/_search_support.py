"""Shared fixtures and doubles for focused transformation tests."""

from types import SimpleNamespace

from src.core.models import FundProfile, Holding, NewsItem
from src.search.search import (
    SearchQuery,
    build_queries,
    dedupe_news,
    news_from_result,
)

def make_profile(holdings=(), sectors=None) -> FundProfile:
    return FundProfile(
        fund="Vanguard FTSE 250",
        ticker="VMID.L",
        name="Vanguard FTSE 250 UCITS ETF",
        provider="yahoo",
        family=None,
        currency=None,
        holdings=tuple(holdings),
        sector_weights=sectors or {},
        overview={},
        gaps=(),
    )


def raw_result(
    title="Balfour Beatty wins contract",
    url="https://www.reuters.com/article/x",
    **extra,
):
    fields = {
        "title": title,
        "url": url,
        "published_date": "2026-11-01T00:00:00.000Z",
        "summary": "It won a contract.",
        "text": "It won a 200 million pound contract on Tuesday.",
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


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


