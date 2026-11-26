"""FR7 Q&A logic and Ollama boundary."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from typing import Any, Final, Protocol

from src.core.events import EventEmitter
from src.qa.corpus import QARun
from src.qa.errors import QAError, QAResponseError
from src.qa.ranking import retrieve_ranked
from src.qa.prompt import (
    corrective_prompt,
    build_qa_prompt,
    request_messages,
    request_options,
)
from src.qa.query_rewrite import rewrite_followup
from src.qa.response import QAResponse, parse_qa_response, reply_text, usage_tokens
from src.qa.retrieve import (
    QA_EVIDENCE_MAX_CHARS,
    QA_HISTORY_TURNS,
    QA_MAX_PASSAGES,
    Passage,
)
from src.synthesis.synthesis import OLLAMA_TIMEOUT_SECONDS, _provider_error_fields
from src.search.queries import exa_error_details
from src.search.search import exa_client
from src.qa.web_search import ExaClient, search_web

QA_MODEL: Final[str] = "gemma4:cloud"
PROVIDER: Final[str] = "ollama.gemma"
STAGE: Final[str] = "qa"
MAX_ATTEMPTS: Final[int] = 2


class OllamaClient(Protocol):
    def chat(
        self, *, model: str, messages: Any, options: Any, stream: bool = False
    ) -> Any: ...


def ollama_client() -> OllamaClient:
    """Deferred SDK construction for the Q&A model boundary."""
    from ollama import Client

    return Client(timeout=OLLAMA_TIMEOUT_SECONDS)


def _ask_turn(
    run: QARun,
    question: str,
    history: list[tuple[str, str]],
    client: OllamaClient,
    events: EventEmitter,
    *,
    exa_api_key: str | None = None,
    exa_factory: Callable[[str], ExaClient] = exa_client,
    status_callback: Callable[[str], None] | None = None,
    token_callback: Callable[[str | None], None] | None = None,
) -> tuple[str, tuple[int | str, ...], bool, list[Passage], int, int, bool]:
    turn_started = time.monotonic()
    if status_callback is not None:
        status_callback("thinking")
    recent_history = history[-QA_HISTORY_TURNS:]
    rewritten_question = rewrite_followup(
        question,
        recent_history,
        fund_name=str(run.profile.get("name", "Unknown")),
        ticker=str(run.profile.get("ticker", "Unknown")),
        client=client,
        model=QA_MODEL,
        options=request_options(),
        events=events,
    )
    local_passages = retrieve_ranked(
        rewritten_question.search_query,
        run.news,
        events=events,
    )
    prompt = build_qa_prompt(
        run,
        question,
        local_passages,
        recent_history,
        standalone_question=rewritten_question.standalone_question,
    )
    parsed, attempts = _ask_model(
        run,
        prompt,
        local_passages,
        client,
        events,
        token_callback=token_callback,
    )
    final_passages = local_passages
    web_search_attempted = False

    # Let the evidence-quality assessment, not the phrasing of the question,
    # decide whether the saved corpus needs web evidence.
    if parsed.insufficient and exa_api_key:
        if token_callback is not None:
            token_callback(None)
        web_search_attempted = True
        if status_callback is not None:
            status_callback("searching_web")
        # Keep broad questions broad: appending the fund name/ticker can skew
        # web search away from a topic the user is asking about generally.
        standalone_query = rewritten_question.search_query[:1000]
        search_started = time.monotonic()
        try:
            exa = exa_factory(exa_api_key)
        except Exception as exc:
            http_status, request_id = exa_error_details(exc)
            fields: dict[str, object] = {
                "stage": STAGE,
                "provider": "exa.qa_search",
                "latency_ms": int((time.monotonic() - search_started) * 1000),
                "status": "error",
            }
            if http_status is not None:
                fields["http_status"] = http_status
            if request_id is not None:
                fields["request_id"] = request_id
            events.emit("external_call", **fields)
            exa = None
        web_passages = (
            search_web(
                standalone_query,
                exa=exa,
                events=events,
                excluded_urls={item.url for item in run.news},
            )
            if exa is not None
            else []
        )
        if web_passages:
            if status_callback is not None:
                status_callback("thinking")
            # Web search is the fallback for gaps in the saved fund corpus, so
            # give relevant web evidence first claim on the answer budget.
            web_for_fallback = _limit_passages(
                web_passages,
                max_passages=QA_MAX_PASSAGES,
                max_chars=QA_EVIDENCE_MAX_CHARS,
            )
            local_for_fallback = _limit_passages(
                local_passages,
                max_passages=QA_MAX_PASSAGES - len(web_for_fallback),
                max_chars=QA_EVIDENCE_MAX_CHARS
                - sum(len(item.text) for item in web_for_fallback),
            )
            final_passages = [*web_for_fallback, *local_for_fallback]
            web_prompt = build_qa_prompt(
                run,
                question,
                final_passages,
                recent_history,
                standalone_question=rewritten_question.standalone_question,
            )
            parsed, fallback_attempts = _ask_model(
                run,
                web_prompt,
                final_passages,
                client,
                events,
                token_callback=token_callback,
            )
            attempts += fallback_attempts

    latency_ms = int((time.monotonic() - turn_started) * 1000)
    return (
        parsed.answer,
        parsed.citations,
        parsed.insufficient,
        final_passages,
        attempts,
        latency_ms,
        web_search_attempted,
    )


def _limit_passages(
    passages: Iterable[Passage], *, max_passages: int, max_chars: int
) -> list[Passage]:
    selected: list[Passage] = []
    remaining = max_chars
    for passage in passages:
        if len(selected) >= max_passages or remaining <= 0:
            break
        text = passage.text[:remaining]
        if text:
            selected.append(
                Passage(**{**passage.__dict__, "text": text, "end": passage.start + len(text)})
            )
            remaining -= len(text)
    return selected


def _ask_model(
    run: QARun,
    prompt: str,
    passages: list[Passage],
    client: OllamaClient,
    events: EventEmitter,
    *,
    token_callback: Callable[[str | None], None] | None = None,
) -> tuple[QAResponse, int]:
    messages = request_messages(prompt)
    attempts = 0
    while True:
        attempts += 1
        started = time.monotonic()
        try:
            if token_callback is None:
                response = client.chat(
                    model=QA_MODEL, messages=messages, options=request_options()
                )
                text = reply_text(response)
            else:
                response_stream = client.chat(
                    model=QA_MODEL,
                    messages=messages,
                    options=request_options(),
                    stream=True,
                )
                response = None
                response_parts: list[str] = []
                answer_stream = _JSONAnswerStream()
                for chunk in response_stream:
                    response = chunk
                    try:
                        content = getattr(
                            getattr(chunk, "message", None), "content", None
                        )
                    except Exception:
                        content = None
                    # A whitespace-only model chunk is meaningful; reply_text
                    # intentionally strips those for complete, non-streamed replies.
                    if not isinstance(content, str) or not content:
                        continue
                    response_parts.append(content)
                    delta = answer_stream.feed(content)
                    if delta is not None:
                        token_callback(delta)
                text = "".join(response_parts)
        except Exception as exc:
            events.emit(
                "external_call",
                stage=STAGE,
                provider=PROVIDER,
                latency_ms=int((time.monotonic() - started) * 1000),
                status="error",
                **_provider_error_fields(exc),
            )
            raise QAError(
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
        try:
            if text is None:
                raise QAResponseError("reply contained no text")
            parsed = parse_qa_response(
                text,
                news_count=len(run.news),
                supplied_source_numbers=(
                    p.source_number for p in passages if p.source_number is not None
                ),
                supplied_web_source_ids=(
                    p.source_id for p in passages if p.source_number is None
                ),
            )
            return parsed, attempts
        except QAResponseError as exc:
            if attempts >= MAX_ATTEMPTS:
                raise
            if token_callback is not None:
                token_callback(None)
            messages = request_messages(corrective_prompt(prompt, str(exc), text))


class _JSONAnswerStream:
    """Extract decoded answer text from a JSON response as model chunks arrive."""

    def __init__(self) -> None:
        self.raw = ""
        self.emitted = ""
        self.answer_start: int | None = None

    def feed(self, chunk: str) -> str | None:
        self.raw += chunk
        if self.answer_start is None:
            match = re.search(r'"answer"\s*:\s*"', self.raw)
            if match is None:
                return None
            self.answer_start = match.end()

        fragment = self.raw[self.answer_start :]
        index = 0
        while index < len(fragment):
            char = fragment[index]
            if char == '"':
                break
            if char == "\\":
                if index + 1 >= len(fragment):
                    break
                if fragment[index + 1] == "u" and index + 6 > len(fragment):
                    break
                index += 6 if fragment[index + 1] == "u" else 2
                continue
            index += 1

        try:
            decoded = json.loads('"' + fragment[:index] + '"')
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(decoded, str):
            return None
        if not decoded.startswith(self.emitted):
            self.emitted = decoded
            return None
        delta = decoded[len(self.emitted) :]
        self.emitted = decoded
        return delta or None
