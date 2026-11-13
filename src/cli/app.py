"""CLI entry point and composition root (PRD §8).

FR1 implements input handling: the application prompts for the fund name on
stdin; the name must be non-empty and a blank answer exits 2 before any
external call. FR2 wires fund data extraction; FR3 wires news search — the
composition root reads EXA_API_KEY and the EXA_* search caps from the
environment (a `.env` file fills unset variables), with `.env` never logged.
FR4 wires synthesis — the ollama client factory, injected, which reads
OLLAMA_HOST / OLLAMA_API_KEY from the environment itself (no key is
required; never logged).
FR5 wires report generation: the validated sections render to markdown,
print to stdout, and are written with the §10 artifact set (report.md,
fund_profile.json, news.json) into the run directory; a write failure exits
1. Exit codes (FR6): 0 success, 1 runtime failure, 2 usage error; the
injected event emitter rejects a §16 record that breaks its contract.
"""

import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from src.cli.config import (
    EXIT_OK,
    EXIT_RUNTIME_FAILURE,
    EXIT_USAGE,
    UsageError,
    compose_env,
    default_run_id,
    parse_search_config,
    read_env_file,
    slugify,
    validate,
)
from src.cli.pipeline import _fail_run, _run_pipeline
from src.cli.suggest import (
    Suggester,
    cached_suggester,
    prompt_with_suggestions,
    yf_suggester,
)
from src.core.events import EventEmitter
from src.core.models import RunInput
from src.reporting.report import write_report
from src.search.search import SearchConfig, exa_client
from src.synthesis.synthesis import ollama_client

DEFAULT_OUTPUT_ROOT = Path("output")


def _prompt_fund_name(stdin: TextIO, stdout: TextIO) -> str:
    """Ask for the fund name on stdin (FR1)."""
    print("Fund name: ", end="", flush=True, file=stdout)
    answer = stdin.readline()
    if answer == "":  # EOF with no input
        raise UsageError("no fund name provided")
    return answer.strip()


def _is_tty(stdin: TextIO) -> bool:
    try:
        return stdin.isatty()
    except Exception:
        return False


def _read_input(
    stdin: TextIO,
    stdout: TextIO,
    suggest: Suggester | None,
) -> RunInput:
    """Prompt for the fund name and validate it (FR1).

    With a suggestion function and a tty, the prompt shows live Yahoo
    suggestions while typing; otherwise it is the plain line prompt.
    """
    if suggest is not None and _is_tty(stdin):
        return validate(prompt_with_suggestions(suggest, stdout))
    return validate(_prompt_fund_name(stdin, stdout))


def _load_yf() -> Any:
    """Deferred third-party import; usage errors never touch it (P3)."""
    import yfinance

    return yfinance


def main(
    *,
    stderr: TextIO | None = None,
    stdout: TextIO | None = None,
    stdin: TextIO | None = None,
    clock: Callable[[], datetime] | None = None,
    new_run_id: Callable[[], str] | None = None,
    output_root: Path | None = None,
    yf: Any | None = None,
    env: Mapping[str, str] | None = None,
    exa_factory: Callable[[str], Any] | None = None,
    ollama_client_factory: Callable[[], Any] | None = None,
    report_writer: Callable[..., tuple[str, Path]] | None = None,
    suggester: Suggester | None = None,
) -> int:
    """Composition root (P3): parse, validate, wire dependencies, orchestrate.

    Every dependency main needs is an explicit parameter, so tests inject
    fixed values (including the yfinance module, the Exa client factory and
    the ollama client factory, the report writer, and the environment
    mapping) instead of patching globals. Only this function reads the
    environment: EXA_API_KEY and the EXA_* caps (with `.env` filling unset
    variables); the ollama client reads its own settings. Keys are passed on
    as values and never logged. The report is printed to stdout and written
    to the run directory. The default suggester (interactive tty input only)
    asks Yahoo for fund names while typing; suggestions are best-effort and
    never fatal. Returns the process exit code.
    """
    stderr = sys.stderr if stderr is None else stderr
    stdout = sys.stdout if stdout is None else stdout
    stdin = sys.stdin if stdin is None else stdin
    clock = (lambda: datetime.now(timezone.utc)) if clock is None else clock
    new_run_id = default_run_id if new_run_id is None else new_run_id
    output_root = DEFAULT_OUTPUT_ROOT if output_root is None else output_root
    exa_factory = exa_client if exa_factory is None else exa_factory
    ollama_client_factory = (
        ollama_client if ollama_client_factory is None else ollama_client_factory
    )
    report_writer = write_report if report_writer is None else report_writer

    run_id = new_run_id()
    usage_events = EventEmitter(run_id=run_id, clock=clock, sink=stderr)
    if suggester is None and _is_tty(stdin):
        try:
            suggester = cached_suggester(yf_suggester(_load_yf()))
        except ImportError:
            suggester = None  # plain prompt still works without yfinance
    try:
        run_input = _read_input(stdin, stdout, suggester)
    except UsageError as exc:
        usage_events.emit(
            "run_failed",
            stage="input_validation",
            error_code="usage_error",
            detail=str(exc),
        )
        print(f"error: {exc}", file=stderr)
        return EXIT_USAGE

    composed_env = compose_env(env)
    try:
        search_config = parse_search_config(composed_env)
    except UsageError as exc:
        usage_events.emit(
            "run_failed",
            stage="config",
            error_code="usage_error",
            detail=str(exc),
        )
        print(f"error: {exc}", file=stderr)
        return EXIT_USAGE
    api_key = (composed_env.get("EXA_API_KEY") or "").strip() or None

    run_dir = output_root / slugify(run_input.fund) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "events.jsonl").open("a", encoding="utf-8") as events_file:
        events = EventEmitter(run_id=run_id, clock=clock, sink=events_file)
        events.emit(
            "run_started",
            stage="startup",
            fund=run_input.fund,
        )
        try:
            yf = _load_yf() if yf is None else yf
        except ImportError as exc:
            events.emit(
                "run_failed",
                stage="fund_extraction",
                error_code="yahoo_unavailable",
                detail=str(exc),
            )
            print(f"error: yfinance is not installed: {exc}", file=stderr)
            return EXIT_RUNTIME_FAILURE
        status = _run_pipeline(
            run_input,
            events,
            yf,
            run_dir=run_dir,
            config=search_config,
            api_key=api_key,
            exa_factory=exa_factory,
            ollama_client_factory=ollama_client_factory,
            report_writer=report_writer,
            clock=clock,
            stdout=stdout,
        )

    if status != EXIT_OK:
        print(
            f"error: run failed — see {run_dir / 'events.jsonl'} for the stage and error code",
            file=stderr,
        )
    return status
