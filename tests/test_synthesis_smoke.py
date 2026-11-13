"""Optional live Ollama boundary smoke test; run with ``pytest -m smoke``."""

import io
import os
import socket
from datetime import UTC, datetime
from urllib.parse import urlsplit

import pytest

from src.core.events import EventEmitter
from src.core.models import FundProfile, ReportSections
from src.synthesis.synthesis import ollama_client, synthesize


def _ollama_endpoint_available() -> bool:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    parsed = urlsplit(host)
    if not parsed.hostname:
        return False
    default_port = 443 if parsed.scheme == "https" else 11434
    try:
        with socket.create_connection(
            (parsed.hostname, parsed.port or default_port), timeout=1.0
        ):
            return True
    except OSError:
        return False


@pytest.mark.smoke
def test_live_ollama_synthesizes_validated_sections():
    if not _ollama_endpoint_available():
        pytest.skip("start Ollama or set OLLAMA_HOST to run the live smoke test")

    profile = FundProfile(
        fund="Ollama smoke test",
        ticker="SMOKE",
        name="Smoke test fund",
        provider="test",
        family=None,
        currency=None,
        holdings=(),
        sector_weights={},
        overview={},
        gaps=(),
    )
    sink = io.StringIO()
    sections = synthesize(
        profile,
        (),
        ollama=ollama_client(),
        events=EventEmitter(
            run_id="smoke-ollama",
            clock=lambda: datetime.now(UTC),
            sink=sink,
        ),
    )

    assert isinstance(sections, ReportSections)
    assert sections.company_insights.strip()
    assert sections.sector_insights.strip()
