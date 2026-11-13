"""Core FR3 partial-failure and degrade-policy tests."""

import io
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from _search_support import make_profile, raw_result
from src.core.events import EventEmitter
from src.core.models import Holding
from src.search.search import SearchConfig, SearchError, search_news

FIXED_NOW = datetime(2026, 11, 12, 12, 0, 0, tzinfo=UTC)


class FakeExa:
    def __init__(self, *, failed_queries=(), results=None):
        self.failed_queries = set(failed_queries)
        self.results = results or {}

    def search(self, query, **options):
        if query in self.failed_queries:
            raise RuntimeError("simulated Exa failure")
        return SimpleNamespace(results=self.results.get(query, []))


def run_search(exa, *, config):
    sink = io.StringIO()
    events = EventEmitter(
        run_id="run-test", clock=lambda: FIXED_NOW, sink=sink
    )
    profile = make_profile(
        holdings=(Holding(name="Apple Inc.", symbol="AAPL", weight=50.0),),
        sectors={"Industrials": 50.0},
    )
    items = search_news(
        profile,
        config=config,
        exa=exa,
        events=events,
        clock=lambda: FIXED_NOW,
    )
    return items


def test_search_news_keeps_successful_results_when_one_query_fails():
    exa = FakeExa(
        failed_queries={"Apple Inc. company news"},
        results={"Industrials sector outlook": [raw_result()]},
    )

    items = run_search(exa, config=SearchConfig())

    assert len(items) == 1
    assert items[0].related == ("Industrials",)


def test_search_news_degrades_to_no_news_when_every_query_fails():
    exa = FakeExa(
        failed_queries={"Apple Inc. company news", "Industrials sector outlook"}
    )

    items = run_search(
        exa, config=SearchConfig(degrade_on_total_failure=True)
    )

    assert items == ()


def test_search_news_raises_when_degrade_is_disabled():
    exa = FakeExa(
        failed_queries={"Apple Inc. company news", "Industrials sector outlook"}
    )

    with pytest.raises(SearchError, match="all 2 Exa searches failed"):
        run_search(exa, config=SearchConfig(degrade_on_total_failure=False))
