"""Deterministic local lexical passage retrieval for saved news."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from src.qa.corpus import QANewsItem

QA_MAX_PASSAGES = 15
QA_EVIDENCE_MAX_CHARS = 24000
QA_HISTORY_TURNS = 3
QA_PASSAGE_MAX_CHARS = 1200
QA_PASSAGE_OVERLAP_CHARS = 150
_PASSAGE_STEP_CHARS = QA_PASSAGE_MAX_CHARS - QA_PASSAGE_OVERLAP_CHARS

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Passage:
    source_id: str
    source_number: int | None
    url: str
    title: str
    source: str | None
    published: str | None
    field: str
    text: str
    start: int
    end: int
    score: float = 0.0


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]


def _paragraph_ranges(text: str) -> list[tuple[int, int]]:
    return [
        (match.start(), match.end())
        for match in re.finditer(r"\S.*?(?=\n[ \t]*\n|\Z)", text, re.DOTALL)
    ]


def _sentence_ranges(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split an oversized paragraph on sentence boundaries, then as a last resort."""
    ranges: list[tuple[int, int]] = []
    cursor = start
    for match in _SENTENCE_END_RE.finditer(text, start, end):
        stop = match.start()
        while stop - cursor > _PASSAGE_STEP_CHARS:
            split = text.rfind(" ", cursor, cursor + _PASSAGE_STEP_CHARS)
            if split <= cursor:
                split = cursor + _PASSAGE_STEP_CHARS
            ranges.append((cursor, split))
            cursor = split
            while cursor < end and text[cursor].isspace():
                cursor += 1
        if stop > cursor:
            ranges.append((cursor, stop))
        cursor = match.end()
    while end - cursor > _PASSAGE_STEP_CHARS:
        split = text.rfind(" ", cursor, cursor + _PASSAGE_STEP_CHARS)
        if split <= cursor:
            split = cursor + _PASSAGE_STEP_CHARS
        ranges.append((cursor, split))
        cursor = split
        while cursor < end and text[cursor].isspace():
            cursor += 1
    if cursor < end:
        ranges.append((cursor, end))
    return ranges


def _passage_ranges(text: str) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    for start, end in _paragraph_ranges(text):
        if end - start <= _PASSAGE_STEP_CHARS:
            blocks.append((start, end))
        else:
            blocks.extend(_sentence_ranges(text, start, end))

    passages: list[tuple[int, int]] = []
    pending_start: int | None = None
    pending_end = 0
    for start, end in blocks:
        if pending_start is None:
            pending_start, pending_end = start, end
        elif end - pending_start <= _PASSAGE_STEP_CHARS:
            pending_end = end
        else:
            passages.append((pending_start, pending_end))
            pending_start, pending_end = start, end
        # Avoid indexing very short fragments by joining them with the next block.
        if pending_start is not None and pending_end - pending_start >= 400:
            passages.append((pending_start, pending_end))
            pending_start = None
    if pending_start is not None:
        passages.append((pending_start, pending_end))
    nonempty = [
        (start, end)
        for start, end in passages
        if text[start:end].strip()
    ]
    # Keep a small overlap so a fact or caveat near a chunk boundary remains
    # available when either neighboring passage is retrieved on its own.
    overlapping: list[tuple[int, int]] = []
    for start, end in nonempty:
        if overlapping:
            previous_start, previous_end = overlapping[-1]
            start = min(start, previous_end - QA_PASSAGE_OVERLAP_CHARS)
            start = max(start, end - QA_PASSAGE_MAX_CHARS, previous_start)
        overlapping.append((start, end))
    return overlapping


def build_passages(news: tuple[QANewsItem, ...] | list[QANewsItem]) -> list[Passage]:
    """Build exact-substring passages; use summary only when content is absent."""
    output: list[Passage] = []
    for number, item in enumerate(news, start=1):
        field = "content" if item.content and item.content.strip() else "summary"
        text = item.content if field == "content" else (item.summary or "")
        for start, end in _passage_ranges(text):
            passage_text = text[start:end]
            left = len(passage_text) - len(passage_text.lstrip())
            right = len(passage_text.rstrip())
            actual_start, actual_end = start + left, start + right
            output.append(
                Passage(
                    source_id=str(number),
                    source_number=number,
                    url=item.url,
                    title=item.title,
                    source=item.source,
                    published=item.published,
                    field=field,
                    text=text[actual_start:actual_end],
                    start=actual_start,
                    end=actual_end,
                )
            )
    return output


def _bm25(query_terms: list[str], documents: list[list[str]]) -> list[float]:
    # BM25's k1=1.2 and b=0.75 balance term frequency against document length.
    if not query_terms or not documents:
        return [0.0] * len(documents)
    doc_lengths = [len(doc) for doc in documents]
    average = sum(doc_lengths) / len(doc_lengths) if documents else 0
    frequencies = [Counter(document) for document in documents]
    df = Counter(term for term in set(query_terms) for doc in frequencies if doc[term])
    scores: list[float] = []
    for doc, length in zip(frequencies, doc_lengths):
        score = 0.0
        for term in query_terms:
            count = doc[term]
            if count == 0:
                continue
            idf = math.log(1 + (len(documents) - df[term] + 0.5) / (df[term] + 0.5))
            denominator = count + 1.2 * (1 - 0.75 + 0.75 * length / (average or 1))
            score += idf * count * 2.2 / denominator
        scores.append(score)
    return scores


def retrieve(
    question: str,
    news: tuple[QANewsItem, ...] | list[QANewsItem],
    *,
    history_questions: tuple[str, ...] | list[str] = (),
    max_passages: int = QA_MAX_PASSAGES,
    max_chars: int = QA_EVIDENCE_MAX_CHARS,
) -> list[Passage]:
    """Rank evidence with BM25 plus title/entity matching, then cap evidence."""
    query = " ".join([*history_questions[-QA_HISTORY_TURNS:], question])
    query_terms = _tokens(query)
    passages = build_passages(news)
    documents = [_tokens(passage.text) for passage in passages]
    scores = _bm25(query_terms, documents)
    query_set = set(query_terms)
    ranked: list[Passage] = []
    for passage, score in zip(passages, scores):
        title_terms = set(_tokens(passage.title))
        # Headlines often contain the entity even when the article text uses a
        # pronoun, so give exact title-term matches a modest retrieval boost.
        score += 0.35 * len(query_set & title_terms)
        if score <= 0:
            continue
        ranked.append(Passage(**{**passage.__dict__, "score": score}))
    ranked.sort(key=lambda p: (-p.score, p.source_number, p.start))

    selected: list[Passage] = []
    used_chars = 0
    for passage in ranked:
        if any(
            previous.source_number == passage.source_number
            and passage.start < previous.end
            and previous.start < passage.end
            for previous in selected
        ):
            continue
        if len(selected) >= max_passages:
            break
        remaining = max_chars - used_chars
        if remaining <= 0:
            break
        if len(passage.text) > remaining:
            passage = Passage(**{**passage.__dict__, "text": passage.text[:remaining], "end": passage.start + remaining})
        if not passage.text:
            continue
        selected.append(passage)
        used_chars += len(passage.text)
    return selected
