from datetime import UTC, datetime
from io import StringIO
from types import SimpleNamespace

from src.core.events import EventEmitter
from src.core import pipeline


def test_news_research_remains_active_until_search_finishes(tmp_path, monkeypatch):
    started = []
    profile = SimpleNamespace(
        ticker="TEST",
        holdings=[],
        sector_weights={},
        gaps=[],
    )

    monkeypatch.setattr(pipeline, "extract_fund", lambda *args, **kwargs: profile)

    def search_news(*args, **kwargs):
        assert started[-1] == "news_search"
        return []

    monkeypatch.setattr(pipeline, "search_news", search_news)
    monkeypatch.setattr(
        pipeline,
        "synthesize",
        lambda *args, **kwargs: SimpleNamespace(
            company_insights="", sector_insights=""
        ),
    )
    events = EventEmitter(
        run_id="test-run",
        clock=lambda: datetime(2026, 11, 24, tzinfo=UTC),
        sink=StringIO(),
    )
    status, report = pipeline._run_stages(
        SimpleNamespace(fund="Sample Fund"),
        events,
        object(),
        run_dir=tmp_path,
        config=object(),
        api_key="test-key",
        exa_factory=lambda _key: object(),
        ollama_client_factory=object,
        report_writer=lambda *args, **kwargs: ("report", tmp_path / "report.md"),
        clock=lambda: datetime(2026, 11, 24, tzinfo=UTC),
        on_stage_started=started.append,
    )

    assert status == pipeline.EXIT_OK
    assert report == "report"
    assert started == ["fund_extraction", "news_search", "synthesis", "report"]
