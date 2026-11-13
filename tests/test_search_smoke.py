"""Optional live Exa boundary smoke test; run with ``pytest -m smoke``."""

import io
import json
import os
from datetime import UTC, datetime

import pytest

from src.core.events import EventEmitter
from src.core.models import FundProfile, Holding, NewsItem
from src.search.search import SearchConfig, exa_client, search_news


@pytest.mark.smoke
def test_live_exa_search_returns_mappable_results_or_no_results():
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        pytest.skip("set EXA_API_KEY to run the live Exa smoke test")

    now = datetime.now(UTC)
    sink = io.StringIO()
    events = EventEmitter(run_id="smoke-exa", clock=lambda: now, sink=sink)
    profile = FundProfile(
        fund="Exa smoke test",
        ticker="SMOKE",
        name="Smoke test fund",
        provider="test",
        family=None,
        currency=None,
        holdings=(Holding(name="Apple Inc.", symbol="AAPL", weight=100.0),),
        sector_weights={},
        overview={},
        gaps=(),
    )

    items = search_news(
        profile,
        config=SearchConfig(
            max_searches=1,
            results_per_search=1,
            window_days=90,
            max_parallel=1,
        ),
        exa=exa_client(api_key),
        events=events,
        clock=lambda: now,
    )

    records = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert records[0]["event"] == "external_call"
    assert records[0]["status"] == "ok"
    assert records[-1]["event"] == "stage_completed"
    assert all(isinstance(item, NewsItem) for item in items)
    assert all(item.related == ("Apple Inc.",) for item in items)
