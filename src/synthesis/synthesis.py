"""FR4: Ollama synthesis stage and its public API."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, Final, Protocol

from src.core.events import EventEmitter
from src.core.models import FundProfile, NewsItem, ReportSections
from src.synthesis.synthesis_errors import SynthesisError
from src.synthesis.synthesis_prompt import (
    CORRECTIVE_TEXT_LIMIT,
    MAX_ITEMS_PER_ENTITY,
    build_prompt,
    corrective_prompt,
    news_for_prompt,
    partition_news,
    request_messages,
    request_options,
)
from src.synthesis.synthesis_response import (
    SECTION_KEYS,
    parse_sections,
    reply_text,
    usage_tokens,
)

SYNTHESIS_MODEL: Final[str] = "gemma4:cloud"
OLLAMA_TIMEOUT_SECONDS: Final[float] = 120.0
MAX_ATTEMPTS: Final[int] = 2  # FR4: one corrective retry on malformed output
PROVIDER: Final[str] = "ollama.gemma"
STAGE: Final[str] = "synthesis"


class OllamaClient(Protocol):
    """What invesk needs from an `ollama.Client` (or a test double)."""

    def chat(
        self, *, model: str, messages: Any, options: Any
    ) -> Any: ...


def ollama_client() -> OllamaClient:
    """Construct the real client at the composition root (P3)."""
    from ollama import Client

    return Client(timeout=OLLAMA_TIMEOUT_SECONDS)


def _provider_error_fields(exc: Exception) -> dict[str, object]:
    """Provider HTTP status of a failed call, for the external_call event.

    ollama raises `ResponseError` carrying the provider HTTP status as
    `status_code` for failed HTTP calls; connection failures and response-
    parse failures carry none.
    """
    status = getattr(exc, "status_code", None)
    return {"http_status": status} if isinstance(status, int) else {}


def synthesize(
    profile: FundProfile,
    news: Sequence[NewsItem],
    *,
    ollama: OllamaClient,
    events: EventEmitter,
) -> ReportSections:
    """FR4 stage: FundProfile + NewsItem[] → validated ReportSections.

    One prompt to Gemma, validated against the report schema; malformed
    output gets one corrective retry (with the failure reason and the
    previous reply), then SynthesisError. Provider failures are logged and
    raise immediately. Only the top MAX_ITEMS_PER_ENTITY news items per
    entity are fed to the prompt. Emits one external_call per attempt, one
    token_usage per successful call, and one stage_completed synthesis.
    """
    prompt_news = news_for_prompt(news)
    source_numbers = {item.url: index for index, item in enumerate(news, start=1)}
    prompt_source_numbers = {
        item.url: source_numbers[item.url] for item in prompt_news
    }
    prompt = build_prompt(
        profile, prompt_news, source_numbers=prompt_source_numbers
    )
    messages = request_messages(prompt)
    options = request_options()
    attempts = 1
    while True:
        started = time.monotonic()
        try:
            response = ollama.chat(
                model=SYNTHESIS_MODEL, messages=messages, options=options
            )
        except Exception as exc:
            events.emit(
                "external_call",
                stage=STAGE,
                provider=PROVIDER,
                latency_ms=int((time.monotonic() - started) * 1000),
                status="error",
                **_provider_error_fields(exc),
            )
            raise SynthesisError(
                f"gemma request failed: {exc}", error_code="ollama_unavailable"
            ) from exc
        events.emit(
            "external_call",
            stage=STAGE,
            provider=PROVIDER,
            latency_ms=int((time.monotonic() - started) * 1000),
            status="ok",
        )
        prompt_tokens, completion_tokens = usage_tokens(response)
        events.emit(
            "token_usage",
            stage=STAGE,
            provider=PROVIDER,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        previous_text: str | None = None
        reason = ""
        try:
            previous_text = reply_text(response)
            if previous_text is None:
                raise SynthesisError(
                    "the reply contained no candidate text",
                    error_code="synthesis_failed",
                )
            sections = parse_sections(
                previous_text, source_numbers=prompt_source_numbers
            )
            break
        except SynthesisError as exc:
            if attempts >= MAX_ATTEMPTS:
                raise
            reason = str(exc)
        attempts += 1
        messages = request_messages(corrective_prompt(prompt, reason, previous_text))

    events.emit(
        "stage_completed",
        stage=STAGE,
        news=len(prompt_news),
        attempts=attempts,
        retried=attempts > 1,
    )
    return sections
