"""Lexical retrieval and evidence selection for FR7 Q&A."""

from __future__ import annotations

from collections.abc import Sequence

from src.core.events import EventEmitter
from src.qa.corpus import QANewsItem
from src.qa.retrieve import (
    QA_HISTORY_TURNS,
    QA_EVIDENCE_MAX_CHARS,
    QA_MAX_PASSAGES,
    Passage,
    retrieve,
)

QA_LEXICAL_CANDIDATES = 40


def _select(
    ranked: Sequence[Passage], *, max_passages: int, max_chars: int
) -> list[Passage]:
    selected: list[Passage] = []
    chars = 0
    for passage in ranked:
        if len(selected) >= max_passages or chars >= max_chars:
            break
        # Passage construction intentionally overlaps neighbors; return only
        # one copy of any shared text to avoid spending the evidence budget twice.
        if any(
            prior.source_number == passage.source_number
            and passage.start < prior.end
            and prior.start < passage.end
            for prior in selected
        ):
            continue
        remaining = max_chars - chars
        text = passage.text[:remaining]
        if not text:
            continue
        if len(text) != len(passage.text):
            passage = Passage(
                **{
                    **passage.__dict__,
                    "text": text,
                    "end": passage.start + len(text),
                }
            )
        selected.append(passage)
        chars += len(text)
    return selected


def retrieve_ranked(
    question: str,
    news: tuple[QANewsItem, ...] | list[QANewsItem],
    *,
    history_questions: Sequence[str] = (),
    events: EventEmitter,
    max_passages: int = QA_MAX_PASSAGES,
    max_chars: int = QA_EVIDENCE_MAX_CHARS,
) -> list[Passage]:
    """Retrieve and select evidence using deterministic lexical ranking."""
    sparse = retrieve(
        question,
        news,
        history_questions=history_questions,
        max_passages=QA_LEXICAL_CANDIDATES,
        max_chars=QA_LEXICAL_CANDIDATES * 1200,
    )
    events.emit(
        "stage_completed",
        stage="qa_retrieval",
        method="lexical",
        lexical_candidates=len(sparse),
    )
    return _select(sparse, max_passages=max_passages, max_chars=max_chars)
