"""Shared extraction, search, synthesis, and report pipeline."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.config import EXIT_OK, EXIT_RUNTIME_FAILURE
from src.core.events import EventEmitter
from src.core.models import RunInput
from src.extraction.extraction import ExtractionError, FundNotFoundError, extract_fund
from src.search.search import SearchConfig, SearchError, search_news
from src.synthesis.synthesis import SynthesisError, synthesize


def _fail_run(
    events: EventEmitter, *, stage: str, error_code: str, detail: str
) -> int:
    """Record a failed stage and return the runtime-failure status."""
    events.emit(
        "run_failed",
        stage=stage,
        error_code=error_code,
        detail=detail,
    )
    return EXIT_RUNTIME_FAILURE


def _run_stages(
    run_input: RunInput,
    events: EventEmitter,
    yf: Any,
    *,
    run_dir: Path,
    config: SearchConfig,
    api_key: str | None,
    exa_factory: Callable[[str], Any],
    ollama_client_factory: Callable[[], Any],
    report_writer: Callable[..., tuple[str, Path]],
    clock: Callable[[], datetime],
    on_stage_started: Callable[[str], None] | None = None,
) -> tuple[int, str | None]:
    """Run the report stages in order and return status plus Markdown."""
    if on_stage_started is not None:
        on_stage_started("fund_extraction")
    try:
        profile = extract_fund(run_input.fund, yf=yf, events=events)
    except FundNotFoundError as exc:
        return _fail_run(
            events,
            stage="fund_extraction",
            error_code="fund_not_found",
            detail=str(exc),
        ), None
    except ExtractionError as exc:
        return _fail_run(
            events,
            stage="fund_extraction",
            error_code="yahoo_unavailable",
            detail=str(exc),
        ), None

    events.emit(
        "stage_completed",
        stage="fund_extraction",
        ticker=profile.ticker,
        holdings=len(profile.holdings),
        sectors=len(profile.sector_weights),
        gaps=len(profile.gaps),
    )
    if on_stage_started is not None:
        on_stage_started("news_search")
    if api_key is None:
        return _fail_run(
            events,
            stage="news_search",
            error_code="exa_not_configured",
            detail="EXA_API_KEY is not set",
        ), None
    try:
        news = search_news(
            profile,
            config=config,
            exa=exa_factory(api_key),
            events=events,
            clock=clock,
        )
    except SearchError as exc:
        return _fail_run(
            events,
            stage="news_search",
            error_code="exa_unavailable",
            detail=str(exc),
        ), None
    if on_stage_started is not None:
        on_stage_started("synthesis")
    try:
        client = ollama_client_factory()
    except Exception as exc:
        return _fail_run(
            events,
            stage="synthesis",
            error_code="ollama_unavailable",
            detail=str(exc),
        ), None
    try:
        sections = synthesize(
            profile,
            news,
            ollama=client,
            events=events,
        )
    except SynthesisError as exc:
        return _fail_run(
            events,
            stage="synthesis",
            error_code=exc.error_code,
            detail=str(exc),
        ), None
    if on_stage_started is not None:
        on_stage_started("report")
    try:
        report, report_path = report_writer(
            run_dir, profile, news, sections, clock=clock
        )
    except OSError as exc:
        return _fail_run(
            events,
            stage="report",
            error_code="report_write_failed",
            detail=str(exc),
        ), None
    events.emit("report_written", stage="report", path=str(report_path))
    return EXIT_OK, report
