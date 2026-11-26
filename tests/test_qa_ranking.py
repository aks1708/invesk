import io
from datetime import UTC, datetime

from src.core.events import EventEmitter
from src.qa.corpus import QANewsItem
from src.qa.ranking import retrieve_ranked


def _news(title: str, content: str) -> QANewsItem:
    return QANewsItem(
        title=title,
        url=f"https://example.test/{title.lower().replace(' ', '-')}",
        source="Daily",
        published="2026-11-20",
        summary=None,
        content=content,
    )


def _events():
    sink = io.StringIO()
    return EventEmitter(
        "run-current", lambda: datetime(2026, 11, 25, tzinfo=UTC), sink
    ), sink


def test_retrieval_uses_exact_passages_from_saved_markdown():
    article = (
        "Chip shipments to China were delayed after a change in customs "
        "processing, according to several suppliers. " * 8
    )
    news = [_news("Quarterly supply update", article)]
    events, sink = _events()

    passages = retrieve_ranked(
        "How did semiconductor export restrictions affect shipments?",
        news,
        events=events,
    )

    assert passages
    assert passages[0].source_number == 1
    assert article[passages[0].start : passages[0].end] == passages[0].text
    assert '"method": "lexical"' in sink.getvalue()
    assert '"lexical_candidates": 1' in sink.getvalue()
    assert "ollama.embed" not in sink.getvalue()


def test_lexical_retrieval_needs_no_vector_service():
    article = (
        "Acme expanded its factory after customer demand increased across "
        "its technology business. " * 8
    )
    news = [_news("Acme factory expansion", article)]
    events, sink = _events()

    passages = retrieve_ranked(
        "What happened to the Acme factory?",
        news,
        events=events,
    )

    assert passages
    assert passages[0].source_number == 1
    assert '"method": "lexical"' in sink.getvalue()
    assert '"lexical_candidates": 1' in sink.getvalue()
    assert "external_call" not in sink.getvalue()
