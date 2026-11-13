"""Core FR4 malformed-response retry behavior."""

import io
from datetime import UTC, datetime
from types import SimpleNamespace

from _synthesis_support import make_profile, raw_sections
from src.core.events import EventEmitter
from src.core.models import ReportSections
from src.synthesis.synthesis import synthesize

FIXED_NOW = datetime(2026, 11, 12, 12, 0, 0, tzinfo=UTC)


class FakeOllama:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def chat(self, *, model, messages, options):
        self.calls.append({"model": model, "messages": messages, "options": options})
        return SimpleNamespace(message=SimpleNamespace(content=next(self.replies)))


def test_synthesize_retries_one_malformed_reply_then_returns_valid_sections():
    malformed = '{"company_insights": "only one section"}'
    client = FakeOllama([malformed, raw_sections()])
    events = EventEmitter(
        run_id="run-test", clock=lambda: FIXED_NOW, sink=io.StringIO()
    )

    sections = synthesize(make_profile(), (), ollama=client, events=events)

    assert sections == ReportSections(
        company_insights="Balfour Beatty won a contract and its order book is full.",
        sector_insights="Construction demand is expected to keep rising.",
    )
    assert len(client.calls) == 2
    first_prompt = client.calls[0]["messages"][0]["content"]
    retry_prompt = client.calls[1]["messages"][0]["content"]
    assert retry_prompt.startswith(first_prompt)
    assert malformed in retry_prompt
    assert "previous reply was invalid" in retry_prompt
