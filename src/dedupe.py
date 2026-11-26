"""FR3b: deterministic semantic deduplication for searched news."""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from src.core.events import EventEmitter
from src.core.models import NewsItem

STAGE = "news_dedup"
PROVIDER = "ollama.embed"
DEFAULT_EMBED_MODEL = "embeddinggemma-2"


@dataclass(frozen=True)
class DedupeConfig:
    """FR3b embedding and similarity controls."""

    embed_model: str = DEFAULT_EMBED_MODEL
    similarity_threshold: float = 0.9
    max_chars: int = 4000


class EmbedClient(Protocol):
    """The embedding subset of an Ollama client."""

    def embed(self, *, model: str, input: list[str], truncate: bool) -> Any: ...


def embedding_text(item: NewsItem, *, max_chars: int) -> str:
    """Build the bounded, stable text sent to the embedding model."""
    parts = [item.title]
    if item.summary:
        parts.append(item.summary)
    if item.content:
        parts.append(item.content[:max_chars])
    return "\n".join(parts)


def _unit_vectors(raw_vectors: Any, expected: int) -> list[list[float]]:
    """Validate and L2-normalize an Ollama embedding response."""
    if not isinstance(raw_vectors, (list, tuple)) or len(raw_vectors) != expected:
        raise ValueError("embedding response count did not match input count")
    vectors: list[list[float]] = []
    dimension: int | None = None
    for raw in raw_vectors:
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ValueError("embedding response contained an empty vector")
        vector: list[float] = []
        for value in raw:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("embedding response contained a non-numeric value")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("embedding response contained a non-finite value")
            vector.append(number)
        if dimension is None:
            dimension = len(vector)
        elif len(vector) != dimension:
            raise ValueError("embedding response vectors had inconsistent dimensions")
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            raise ValueError("embedding response contained a zero vector")
        vectors.append([value / norm for value in vector])
    return vectors


def _related_union(first: tuple[str, ...], second: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*first, *second)))


def _cosine(first: Sequence[float], second: Sequence[float]) -> float:
    """Dot product of normalized vectors, clamped for floating-point drift."""
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(first, second))))


def _provider_error_fields(exc: BaseException) -> dict[str, object]:
    status = getattr(exc, "status_code", None)
    return {"http_status": status} if isinstance(status, int) else {}


def deduplicate_news(
    items: Sequence[NewsItem],
    *,
    config: DedupeConfig,
    ollama: EmbedClient | None,
    events: EventEmitter,
    embedding_error: BaseException | None = None,
) -> tuple[NewsItem, ...]:
    """URL-dedupe then group semantically repeated coverage (FR3b).

    Any embedding error degrades to the URL-deduplicated input. Representatives
    are selected by evidence quality and run order, then returned in run order.
    """
    unique: list[NewsItem] = []
    positions: dict[str, int] = {}
    for item in items:
        position = positions.get(item.url)
        if position is None:
            positions[item.url] = len(unique)
            unique.append(item)
        else:
            first = unique[position]
            unique[position] = replace(
                first, related=_related_union(first.related, item.related)
            )

    if not unique:
        events.emit(
            "stage_completed",
            stage=STAGE,
            candidates=0,
            embedded=0,
            duplicate_pairs=0,
            groups=0,
            kept=0,
            dropped=0,
            threshold=config.similarity_threshold,
            model=config.embed_model,
            degraded=False,
        )
        return ()

    error = embedding_error
    vectors: list[list[float]] = []
    started = time.monotonic()
    if error is None:
        if ollama is None:
            error = RuntimeError("Ollama embedding client is unavailable")
        else:
            try:
                response = ollama.embed(
                    model=config.embed_model,
                    input=[
                        embedding_text(item, max_chars=config.max_chars)
                        for item in unique
                    ],
                    truncate=True,
                )
                vectors = _unit_vectors(
                    getattr(response, "embeddings", None), len(unique)
                )
            except Exception as exc:
                error = exc

    latency_ms = int((time.monotonic() - started) * 1000)
    if error is not None:
        events.emit(
            "external_call",
            stage=STAGE,
            provider=PROVIDER,
            latency_ms=latency_ms,
            status="error",
            **_provider_error_fields(error),
        )
        events.emit(
            "stage_completed",
            stage=STAGE,
            candidates=len(unique),
            embedded=0,
            duplicate_pairs=0,
            groups=len(unique),
            kept=len(unique),
            dropped=0,
            threshold=config.similarity_threshold,
            model=config.embed_model,
            degraded=True,
        )
        return tuple(unique)

    events.emit(
        "external_call",
        stage=STAGE,
        provider=PROVIDER,
        latency_ms=latency_ms,
        status="ok",
    )

    # Count every threshold-qualified pair for observability. Group assignment
    # below is deliberately non-transitive: only compare to kept representatives.
    duplicate_pairs = 0
    for left in range(len(vectors)):
        for right in range(left + 1, len(vectors)):
            if _cosine(vectors[left], vectors[right]) >= config.similarity_threshold:
                duplicate_pairs += 1

    # Prefer the copy with full article text as the group's citation target,
    # but restore the original result order after representatives are chosen.
    priority = sorted(
        range(len(unique)),
        key=lambda index: (not unique[index].content, index),
    )
    kept_indices: list[int] = []
    grouped_related: dict[int, tuple[str, ...]] = {}
    for candidate in priority:
        representative = next(
            (
                kept
                for kept in kept_indices
                if _cosine(vectors[candidate], vectors[kept])
                >= config.similarity_threshold
            ),
            None,
        )
        if representative is None:
            kept_indices.append(candidate)
            grouped_related[candidate] = unique[candidate].related
        else:
            grouped_related[representative] = _related_union(
                grouped_related[representative], unique[candidate].related
            )

    survivors = [
        replace(unique[index], related=grouped_related[index])
        for index in sorted(kept_indices)
    ]
    events.emit(
        "stage_completed",
        stage=STAGE,
        candidates=len(unique),
        embedded=len(vectors),
        duplicate_pairs=duplicate_pairs,
        groups=len(kept_indices),
        kept=len(survivors),
        dropped=len(unique) - len(survivors),
        threshold=config.similarity_threshold,
        model=config.embed_model,
        degraded=False,
    )
    return tuple(survivors)
