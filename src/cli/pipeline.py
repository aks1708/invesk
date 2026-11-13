"""Run extraction, search, synthesis, and report stages in order."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from src.cli.config import EXIT_OK, EXIT_RUNTIME_FAILURE
from src.core.events import EventEmitter
from src.extraction.extraction import ExtractionError, FundNotFoundError, extract_fund
from src.core.models import RunInput
from src.search.search import SearchConfig, SearchError, search_news
from src.synthesis.synthesis import SynthesisError, synthesize
from src.reporting.terminal import write_terminal_report

def _fail_run(
    events: EventEmitter, *, stage: str, error_code: str, detail: str
) -> int:
    """Record a failed stage and return the runtime-failure exit code."""
    events.emit(
        "run_failed",
        stage=stage,
        error_code=error_code,
        detail=detail,
    )
    return EXIT_RUNTIME_FAILURE


def _run_pipeline(
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
    stdout: TextIO,
) -> int:
    """Run the pipeline stages in order (PRD §7).

    FR2 wires fund data extraction, FR3 news search, and FR4 synthesis;
    FR5 renders and writes the report. The Exa client is built here from the
    key the composition root read — only after that key is known to be
    present; the ollama client needs no key, so it is built unconditionally.
    """
    try:
        profile = extract_fund(run_input.fund, yf=yf, events=events)
    except FundNotFoundError as exc:
        return _fail_run(
            events,
            stage="fund_extraction",
            error_code="fund_not_found",
            detail=str(exc),
        )
    except ExtractionError as exc:
        return _fail_run(
            events,
            stage="fund_extraction",
            error_code="yahoo_unavailable",
            detail=str(exc),
        )

    events.emit(
        "stage_completed",
        stage="fund_extraction",
        ticker=profile.ticker,
        holdings=len(profile.holdings),
        sectors=len(profile.sector_weights),
        gaps=len(profile.gaps),
    )
    if api_key is None:
        return _fail_run(
            events,
            stage="news_search",
            error_code="exa_not_configured",
            detail="EXA_API_KEY is not set",
        )
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
        )
    try:
        client = ollama_client_factory()
    except Exception as exc:
        return _fail_run(
            events,
            stage="synthesis",
            error_code="ollama_unavailable",
            detail=str(exc),
        )
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
        )
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
        )
    events.emit("report_written", stage="report", path=str(report_path))
    write_terminal_report(report, stdout)
    return EXIT_OK

