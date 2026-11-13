"""Parse, validate, and adapt synthesis model responses."""

import json
import re
from collections.abc import Mapping
from typing import Any, Final

from src.core.models import ReportSections
from src.synthesis.synthesis_errors import SynthesisError

_FENCE_RE = re.compile(r"\A```[^\n]*\n(.*)\n```\Z", re.DOTALL)


def _json_object(text: str) -> Mapping[str, Any]:
    """Model text → JSON object, tolerating fences and stray prose."""
    stripped = text.strip()
    fence = _FENCE_RE.match(stripped)
    candidates = [stripped, fence.group(1) if fence else stripped]
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise SynthesisError(
        "the reply was not a single JSON object", error_code="synthesis_failed"
    )


SECTION_KEYS: Final[tuple[str, ...]] = (
    "company_insights",
    "sector_insights",
)
_SOURCE_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"\[S([^\]]*)\]")


def _validated_citations(
    text: str,
    *,
    section: str,
    source_numbers: Mapping[str, int],
) -> str:
    """Validate model source tokens and render them as report source numbers.

    Prompt tokens (`[S<n>]`) use the source's position in the full deduplicated
    NewsItem list. Only tokens for items actually supplied to the model are
    accepted.
    """
    supplied_source_numbers = {
        str(number) for number in source_numbers.values()
    }
    citations = list(_SOURCE_TOKEN_RE.finditer(text))

    for citation in citations:
        citation_tokens = [
            token.strip() for token in citation.group(1).split(",")
        ]
        for token in citation_tokens:
            source_number = token.removeprefix("S")
            if source_number.isdecimal() and source_number in supplied_source_numbers:
                continue
            raise SynthesisError(
                f"{section} contains an unknown or malformed source citation "
                f"{citation.group(0)}",
                error_code="synthesis_failed",
            )

    if supplied_source_numbers and not citations:
        raise SynthesisError(
            f"{section} is missing source citations",
            error_code="synthesis_failed",
        )

    def render_citation(match: re.Match[str]) -> str:
        numbers = [
            token.strip().removeprefix("S")
            for token in match.group(1).split(",")
        ]
        return f"[{', '.join(numbers)}]"

    return _SOURCE_TOKEN_RE.sub(render_citation, text)


def parse_sections(
    text: str,
    *,
    source_numbers: Mapping[str, int] | None = None,
) -> ReportSections:
    """Boundary adapter: the model's reply text → validated ReportSections.

    Malformed means: not a JSON object, a missing/empty/non-string section,
    invalid/missing citation tokens. All are `synthesis_failed` — eligible
    for the one corrective retry (FR4).
    """
    data = _json_object(text)
    unexpected = sorted(set(data) - set(SECTION_KEYS))
    if unexpected:
        raise SynthesisError(
            f"unexpected response fields: {', '.join(unexpected)}",
            error_code="synthesis_failed",
        )
    bad = [
        key
        for key in SECTION_KEYS
        if not (isinstance(data.get(key), str) and data[key].strip())
    ]
    if bad:
        raise SynthesisError(
            f"sections missing or empty: {', '.join(bad)}",
            error_code="synthesis_failed",
        )
    citation_sources = source_numbers or {}
    company_insights = _validated_citations(
        data["company_insights"].strip(),
        section="company_insights",
        source_numbers=citation_sources,
    )
    sector_insights = _validated_citations(
        data["sector_insights"].strip(),
        section="sector_insights",
        source_numbers=citation_sources,
    )
    return ReportSections(
        company_insights=company_insights,
        sector_insights=sector_insights,
    )


def reply_text(response: Any) -> str | None:
    """ChatResponse → the assistant text, or None when there is none.

    `response.message.content` is the assistant reply; a response without a
    message or text (a stream-less error shape, a test double's stub) yields
    None. The read is guarded — a double may raise, the real client will
    not. None means malformed output, eligible for the FR4 corrective retry.
    """
    try:
        content = getattr(response, "message", None)
        text = getattr(content, "content", None)
    except Exception:
        return None
    return text if isinstance(text, str) and text.strip() else None


def usage_tokens(response: Any) -> tuple[int, int]:
    """response → (prompt_tokens, completion_tokens); 0 when absent.

    The chat endpoint reports `prompt_eval_count` and `eval_count`.
    """
    prompt = getattr(response, "prompt_eval_count", None)
    completion = getattr(response, "eval_count", None)
    return (
        prompt if isinstance(prompt, int) and not isinstance(prompt, bool) else 0,
        completion
        if isinstance(completion, int) and not isinstance(completion, bool)
        else 0,
    )


