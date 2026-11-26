"""FR3b semantic news-deduplication tests."""

import io
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from _search_support import news
from src.core.config import UsageError, parse_dedupe_config
from src.core.events import EventEmitter
from src.dedupe import DedupeConfig, deduplicate_news, embedding_text


def event_sink():
    sink = io.StringIO()
    events = EventEmitter(
        run_id="dedupe-test",
        clock=lambda: datetime(2026, 11, 25, tzinfo=UTC),
        sink=sink,
    )
    return sink, events


class FakeEmbed:
    def __init__(self, vectors=None, error=None):
        self.vectors = vectors
        self.error = error
        self.calls = []

    def embed(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(embeddings=self.vectors)


def records(sink):
    return [json.loads(line) for line in sink.getvalue().splitlines()]


def test_config_defaults_and_overrides():
    assert parse_dedupe_config({}) == DedupeConfig()
    assert parse_dedupe_config({}).similarity_threshold == 0.9
    assert parse_dedupe_config(
        {
            "DEDUPE_EMBED_MODEL": "my-model",
            "DEDUPE_SIMILARITY_THRESHOLD": "0.9",
            "DEDUPE_MAX_CHARS": "1200",
        }
    ) == DedupeConfig("my-model", 0.9, 1200)


@pytest.mark.parametrize(
    "env",
    [
        {"DEDUPE_EMBED_MODEL": "   "},
        {"DEDUPE_SIMILARITY_THRESHOLD": "nope"},
        {"DEDUPE_SIMILARITY_THRESHOLD": "1.01"},
        {"DEDUPE_MAX_CHARS": "0"},
    ],
)
def test_invalid_config_is_rejected(env):
    with pytest.raises(UsageError):
        parse_dedupe_config(env)


def test_embedding_text_bounds_only_article_prefix():
    item = news(summary="Summary", content="abcdef")
    assert embedding_text(item, max_chars=3) == f"{item.title}\nSummary\nabc"


def test_duplicate_articles_keep_best_content_and_merge_related():
    first = news(
        title="Same announcement",
        content=None,
        related=("Company",),
    )
    richer_copy = news(
        title="Same announcement, more detail",
        url="https://example.test/richer",
        content="full article",
        related=("Sector",),
    )
    different = news(
        title="Different event",
        url="https://example.test/different",
        content="other",
        related=("Other",),
    )
    embedder = FakeEmbed(
        vectors=[[1, 0], [0.99, 0.01], [0, 1]]
    )
    sink, events = event_sink()

    result = deduplicate_news(
        [first, richer_copy, different],
        config=DedupeConfig(similarity_threshold=0.9),
        ollama=embedder,
        events=events,
    )

    assert [item.url for item in result] == [richer_copy.url, different.url]
    assert result[0].related == ("Sector", "Company")
    assert embedder.calls[0]["input"] == [
        f"{first.title}\n{first.summary}",
        f"{richer_copy.title}\n{richer_copy.summary}\nfull article",
        f"{different.title}\n{different.summary}\nother",
    ]
    stage = records(sink)[-1]
    assert stage["stage"] == "news_dedup"
    assert (stage["candidates"], stage["embedded"], stage["dropped"]) == (3, 3, 1)
    assert stage["degraded"] is False


def test_url_duplicates_are_not_embedded_and_related_entities_are_merged():
    one = news(url="https://example.test/same", related=("Company",))
    two = news(url="https://example.test/same", related=("Sector",))
    embedder = FakeEmbed(vectors=[[1, 0]])
    _sink, events = event_sink()

    result = deduplicate_news(
        [one, two],
        config=DedupeConfig(),
        ollama=embedder,
        events=events,
    )

    assert len(embedder.calls[0]["input"]) == 1
    assert len(result) == 1
    assert result[0].related == ("Company", "Sector")


def test_embedding_failure_fails_open_and_reports_degraded():
    item = news()
    sink, events = event_sink()
    embedder = FakeEmbed(error=RuntimeError("offline"))

    result = deduplicate_news(
        [item],
        config=DedupeConfig(),
        ollama=embedder,
        events=events,
    )

    assert result == (item,)
    event_records = records(sink)
    assert event_records[0]["event"] == "external_call"
    assert event_records[0]["provider"] == "ollama.embed"
    assert event_records[0]["status"] == "error"
    assert event_records[1]["degraded"] is True


def test_empty_input_skips_embedding_call_and_emits_zero_counts():
    sink, events = event_sink()
    embedder = FakeEmbed()

    assert deduplicate_news(
        [], config=DedupeConfig(), ollama=embedder, events=events
    ) == ()
    assert embedder.calls == []
    assert records(sink)[0]["candidates"] == 0
