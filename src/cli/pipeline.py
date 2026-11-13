"""Run extraction, search, synthesis, and report stages in order."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from src.cli.config import EXIT_OK, EXIT_RUNTIME_FAILURE
from src.cli.spinner import spinner
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
    """Run the pipeline stages while a tty spinner shows progress.

    The spinner stops and erases its line before the report is printed, so
    no `Cooking` residue is left on the terminal. The spinner is
    interactive-only: with a non-tty stdout (piped input, tests) the stages
    run exactly as before with no output decoration.
    """
    with spinner("Cooking", stdout):
        status, report = _run_stages(
            run_input,
            events,
            yf,
            run_dir=run_dir,
            config=config,
            api_key=api_key,
            exa_factory=exa_factory,
            ollama_client_factory=ollama_client_factory,
            report_writer=report_writer,
            clock=clock,
        )
    if report is not None:
        write_terminal_report(report, stdout)
    return status


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
) -> tuple[int, str | None]:
    """Run the pipeline stages in order (PRD §7).

    Returns `(exit code, terminal report text)`; the report text is not None
    only on success, so the caller can print it after the spinner clears.
    The terminal report is intentionally not written here: it would race the
    spinner animation and the final line erase would hit the report.
    """
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

