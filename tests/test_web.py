"""Browser API lifecycle tests; provider calls are replaced with local fakes."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

import src.web.app as web_app
import src.web.__main__ as web_main
from src.core.config import EXIT_OK
from src.qa.retrieve import Passage


def test_web_entrypoint_defaults_to_port_8001_and_allows_override(monkeypatch):
    calls = []
    monkeypatch.setattr(web_main.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.delenv("INVESK_WEB_HOST", raising=False)
    monkeypatch.delenv("INVESK_WEB_PORT", raising=False)

    web_main.main()

    assert calls[-1][1] == {
        "host": "127.0.0.1",
        "port": 8001,
        "reload": False,
    }
    monkeypatch.setenv("INVESK_WEB_PORT", "8123")

    web_main.main()

    assert calls[-1][1]["port"] == 8123


class InlineExecutor:
    def submit(self, function, *args, **kwargs):
        function(*args, **kwargs)


def write_run_artifacts(run_dir: Path) -> str:
    report = (
        "# Sample Fund (Currency: USD)\n"
        "Generated: 24-11-2026 00:00\n\n"
        "## Financial health\n\nA diversified fund.\n\n"
        "## Sources\n\n[Article](https://example.test/story)\n"
    )
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    (run_dir / "fund_profile.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "fund": "Sample Fund",
                "ticker": "SAMP",
                "name": "Sample Fund",
                "provider": "yahoo",
                "family": "Sample",
                "currency": "USD",
                "holdings": [{"name": "Acme", "symbol": "ACM", "weight": "5%"}],
                "sector_weights": {"Technology": "25%"},
                "overview": {},
                "gaps": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "news.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "news": [
                    {
                        "title": "Acme announces a factory expansion",
                        "url": "https://example.test/story",
                        "source": "Daily Wire",
                        "published": "2026-11-20",
                        "summary": "Acme is expanding.",
                        "content": (
                            "Acme announced a factory expansion after demand "
                            "increased in its technology business. " * 9
                        ),
                        "relevance": 1,
                        "related": ["Acme"],
                    },
                    {
                        "title": "Uncited industry outlook",
                        "url": "https://example.test/uncited",
                        "source": "Market Journal",
                        "published": None,
                        "summary": "An additional collected article.",
                        "content": None,
                        "relevance": 1,
                        "related": ["Technology"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return report


def test_browser_run_opens_report_news_and_chat_without_a_run_path(
    tmp_path, monkeypatch
):
    manager = web_app.RunManager(tmp_path)
    manager._workers = InlineExecutor()
    monkeypatch.setattr(web_app, "manager", manager)
    monkeypatch.setattr(web_app, "_load_yf", lambda: object())
    monkeypatch.setattr(web_app, "compose_env", lambda _env: {})

    def fake_pipeline(run_input, events, _yf, *, run_dir, on_stage_started, **_kwargs):
        for stage in ("fund_extraction", "news_search", "synthesis", "report"):
            on_stage_started(stage)
            events.emit("stage_completed", stage=stage)
        report = write_run_artifacts(run_dir)
        events.emit("report_written", stage="report", path=str(run_dir / "report.md"))
        assert run_input.fund == "Sample Fund"
        return EXIT_OK, report

    monkeypatch.setattr(web_app, "_run_stages", fake_pipeline)
    monkeypatch.setattr(web_app, "ollama_client", lambda: object())
    observed = {}

    def fake_ask(run, question, history, _client, _events, **_kwargs):
        observed["run"] = run
        observed["question"] = question
        observed["history"] = list(history)
        status_callback = _kwargs["status_callback"]
        assert callable(status_callback)
        status_callback("searching_web")
        observed["status"] = "searching_web"
        passage = Passage(
            source_id="1",
            source_number=1,
            url="https://example.test/story",
            title="Acme announces a factory expansion",
            source="Daily Wire",
            published="2026-11-20",
            field="content",
            text="Acme announced a factory expansion.",
            start=0,
            end=37,
        )
        return "Acme is expanding capacity [1].", (1,), False, [passage], 1, 12, False

    monkeypatch.setattr(web_app, "_ask_turn", fake_ask)
    client = TestClient(web_app.app)

    created = client.post("/api/runs", json={"fund": "Sample Fund"})
    assert created.status_code == 202
    run_id = created.json()["id"]
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "succeeded"
    assert run["report"].startswith("# Sample Fund (Currency: USD)")
    assert "\x1b[" not in run["report"]
    assert [article["source_number"] for article in run["articles"]] == [1, 2]
    assert run["articles"][1]["title"] == "Uncited industry outlook"

    answer = client.post(
        f"/api/runs/{run_id}/questions",
        json={"question": "What is Acme doing?"},
    )
    assert answer.status_code == 200
    assert answer.json()["citations"] == [1]
    assert answer.json()["evidence"][0]["passages"] == [
        "Acme announced a factory expansion."
    ]
    assert observed["run"].report == run["report"]
    assert len(observed["run"].news) == 2
    assert observed["question"] == "What is Acme doing?"
    assert observed["status"] == "searching_web"
    assert manager.get(run_id).qa_status is None
    assert client.get(f"/api/runs/{run_id}/qa-status").json() == {"status": None}
    assert manager.get(run_id).qa_history == [
        ("What is Acme doing?", "Acme is expanding capacity [1].")
    ]

    reset = client.post(f"/api/runs/{run_id}/chat/reset")
    assert reset.status_code == 200
    assert reset.json() == {"reset": True}
    assert manager.get(run_id).qa_history == []

    next_answer = client.post(
        f"/api/runs/{run_id}/questions",
        json={"question": "And what does that mean?"},
    )
    assert next_answer.status_code == 200
    assert observed["history"] == []

    # Reset affects only chat continuity, not completed run artifacts.
    run_after_reset = client.get(f"/api/runs/{run_id}").json()
    assert run_after_reset["report"] == run["report"]
    assert [article["source_number"] for article in run_after_reset["articles"]] == [1, 2]


def test_browser_rejects_blank_fund_names():
    response = TestClient(web_app.app).post("/api/runs", json={"fund": "   "})
    assert response.status_code == 422


def test_fund_suggestions_return_all_suggester_results(monkeypatch):
    queries = []
    monkeypatch.setattr(
        web_app,
        "_get_fund_suggester",
        lambda: lambda query: queries.append(query)
        or [f"Fund {index}" for index in range(125)],
    )
    client = TestClient(web_app.app)

    one_character = client.get("/api/suggestions?query=%20a%20")
    assert one_character.json()["suggestions"] == [
        f"Fund {index}" for index in range(125)
    ]
    result = client.get("/api/suggestions?query=%20acme%20")

    assert result.status_code == 200
    assert queries == ["a", "acme"]
    assert result.json()["suggestions"] == [f"Fund {index}" for index in range(125)]


def test_fund_suggestions_are_best_effort(monkeypatch):
    monkeypatch.setattr(
        web_app,
        "_get_fund_suggester",
        lambda: lambda _query: (_ for _ in ()).throw(RuntimeError("Yahoo unavailable")),
    )

    response = TestClient(web_app.app).get("/api/suggestions?query=acme")

    assert response.status_code == 200
    assert response.json() == {"suggestions": []}


def test_chat_is_unavailable_until_report_succeeds(tmp_path, monkeypatch):
    manager = web_app.RunManager(tmp_path)
    job = web_app.RunJob(
        run_id="run-id",
        fund="Sample Fund",
        run_dir=tmp_path / "sample-fund" / "run-id",
        status="running",
    )
    manager._jobs[job.run_id] = job
    monkeypatch.setattr(web_app, "manager", manager)

    response = TestClient(web_app.app).post(
        "/api/runs/run-id/questions", json={"question": "What changed?"}
    )
    assert response.status_code == 409

    reset = TestClient(web_app.app).post("/api/runs/run-id/chat/reset")
    assert reset.status_code == 409
