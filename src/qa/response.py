"""Parse and validate model answers and their run-global source citations."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from src.qa.errors import QAResponseError

_FENCE_RE = re.compile(r"\A```[^\n]*\n(.*)\n```\Z", re.DOTALL)
_BRACKET_RE = re.compile(r"\[([^\]]*)\]")
_MARKER_BODY_RE = re.compile(r"(?:\d+|W\d+)(?:\s*,\s*(?:\d+|W\d+))*\Z")


class QAResponse:
    def __init__(
        self, answer: str, citations: tuple[int | str, ...], insufficient: bool
    ):
        self.answer = answer
        self.citations = citations
        self.insufficient = insufficient


def _json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fence = _FENCE_RE.match(stripped)
    candidates = [stripped, fence.group(1) if fence else stripped]
    start, end = stripped.find("{"), stripped.rfind("}")
    if start >= 0 and end > start:
        candidates.append(stripped[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise QAResponseError("reply was not a JSON object")


def _answer_markers(answer: str) -> set[str]:
    found: set[str] = set()
    for match in _BRACKET_RE.finditer(answer):
        body = match.group(1)
        if not _MARKER_BODY_RE.fullmatch(body):
            raise QAResponseError(f"malformed citation marker [{body}]")
        values = [part.strip() for part in body.split(",")]
        if any(
            value.startswith("0")
            or (value.startswith("W") and value[1:].startswith("0"))
            for value in values
        ):
            raise QAResponseError("citation numbers must be canonical positive decimals")
        found.update(str(int(value)) if value.isdigit() else value for value in values)
    if answer.count("[") != len(list(_BRACKET_RE.finditer(answer))) or answer.count("]") != len(list(_BRACKET_RE.finditer(answer))):
        raise QAResponseError("unclosed or malformed citation marker")
    return found


def parse_qa_response(
    text: str,
    *,
    news_count: int,
    supplied_source_numbers: Iterable[int],
    supplied_web_source_ids: Iterable[str] = (),
) -> QAResponse:
    """Validate exact response keys and enforce evidence-only citations."""
    data = _json_object(text)
    if set(data) != {"answer", "citations", "insufficient"}:
        raise QAResponseError("reply must contain exactly answer, citations, and insufficient")
    answer = data["answer"]
    citations = data["citations"]
    insufficient = data["insufficient"]
    if not isinstance(answer, str) or not answer.strip():
        raise QAResponseError("answer must be a non-empty string")
    if not isinstance(citations, list) or any(
        not (
            isinstance(value, int)
            and not isinstance(value, bool)
            or isinstance(value, str)
            and re.fullmatch(r"W[1-9]\d*", value)
        )
        for value in citations
    ):
        raise QAResponseError("citations must contain news numbers or W-prefixed web IDs")
    citation_ids = [
        str(value) if isinstance(value, str) else str(value) for value in citations
    ]
    if len(set(citation_ids)) != len(citation_ids):
        raise QAResponseError("citations must be unique")
    news_citations = [value for value in citations if isinstance(value, int)]
    web_citations = [value for value in citations if isinstance(value, str)]
    if any(number < 1 or number > news_count for number in news_citations):
        raise QAResponseError("citation refers to an unknown source number")
    if not isinstance(insufficient, bool):
        raise QAResponseError("insufficient must be a boolean")
    markers = _answer_markers(answer)
    if insufficient:
        if citations or markers:
            raise QAResponseError("a refusal must contain no citations")
    else:
        supplied = set(supplied_source_numbers)
        supplied_web = set(supplied_web_source_ids)
        if not citations:
            raise QAResponseError("a substantive answer requires a citation")
        if not set(news_citations) <= supplied or not set(web_citations) <= supplied_web:
            raise QAResponseError("citation was not supplied as evidence for this turn")
        if markers != set(citation_ids):
            raise QAResponseError("citation markers do not match the citations array")
    return QAResponse(answer.strip(), tuple(citations), insufficient)


def reply_text(response: Any) -> str | None:
    try:
        text = getattr(getattr(response, "message", None), "content", None)
    except Exception:
        return None
    return text if isinstance(text, str) and text.strip() else None


def usage_tokens(response: Any) -> tuple[int, int]:
    prompt = getattr(response, "prompt_eval_count", 0)
    completion = getattr(response, "eval_count", 0)
    return (
        prompt if isinstance(prompt, int) and not isinstance(prompt, bool) else 0,
        completion
        if isinstance(completion, int) and not isinstance(completion, bool)
        else 0,
    )
