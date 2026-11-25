"""FastAPI bridge from the browser to Invesk's report and Q&A flows."""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from src.core.config import (
    EXIT_OK,
    UsageError,
    compose_env,
    default_run_id,
    parse_search_config,
    slugify,
)
from src.core.pipeline import _run_stages
from src.core.events import EventEmitter
from src.core.models import RunInput
from src.fund_suggestions import (
    MAX_SUGGESTIONS,
    MIN_QUERY_LEN,
    cached_suggester,
    yf_suggester,
)
from src.qa.corpus import QARun, load_run
from src.qa.errors import QAError, QAResponseError
from src.qa.qa import (
    QA_MODEL,
    _ask_turn,
    ollama_client,
)
from src.reporting.report import write_report
from src.search.search import exa_client
from src.synthesis.synthesis import ollama_client as synthesis_ollama_client

STAGES = ("fund_extraction", "news_search", "synthesis", "report")
_fund_suggester: Any | None = None
_fund_suggester_lock = threading.Lock()


def _load_yf() -> Any:
    """Load yfinance lazily so importing the API does not require it."""
    import yfinance

    return yfinance


PUBLIC_FAILURES = {
    "fund_not_found": "We couldn't find that fund. Check the name and try again.",
    "exa_not_configured": "News search is not configured. Set EXA_API_KEY and restart Invesk.",
    "exa_unavailable": "News search failed. Please try again later.",
    "ollama_unavailable": "The AI service is unavailable. Please try again later.",
    "yahoo_unavailable": "Fund data is temporarily unavailable. Please try again later.",
    "report_write_failed": "The report could not be saved.",
}


class CreateRunRequest(BaseModel):
    fund: str = Field(min_length=1, max_length=200)

    @field_validator("fund")
    @classmethod
    def trim_fund(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("fund name must not be blank")
        return value


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def trim_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


@dataclass
class RunJob:
    run_id: str
    fund: str
    run_dir: Path
    status: str = "queued"
    stage: str | None = None
    failure: dict[str, str] | None = None
    qa_started: bool = False
    qa_status: str | None = None
    qa_history: list[tuple[str, str]] = field(default_factory=list)
    qa_lock: threading.Lock = field(default_factory=threading.Lock)


class RunManager:
    """Tracks browser runs in memory while artifacts remain the source of truth."""

    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root
        self._lock = threading.RLock()
        self._jobs: dict[str, RunJob] = {}
        self._workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="invesk")

    def create(self, fund: str) -> RunJob:
        run_id = default_run_id()
        run_dir = self.output_root / slugify(fund) / run_id
        job = RunJob(run_id=run_id, fund=fund, run_dir=run_dir)
        with self._lock:
            self._jobs[run_id] = job
        self._workers.submit(self._execute, job)
        return job

    def get(self, run_id: str) -> RunJob:
        with self._lock:
            job = self._jobs.get(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return job

    def _execute(self, job: RunJob) -> None:
        job.status = "running"
        current_stage = "startup"
        clock = lambda: datetime.now(timezone.utc)
        try:
            job.run_dir.mkdir(parents=True, exist_ok=True)
            with (job.run_dir / "events.jsonl").open("a", encoding="utf-8") as sink:
                events = EventEmitter(run_id=job.run_id, clock=clock, sink=sink)
                events.emit("run_started", stage="startup", fund=job.fund)
                try:
                    env = compose_env(None)
                    config = parse_search_config(env)
                except UsageError as exc:
                    events.emit(
                        "run_failed",
                        stage="config",
                        error_code="usage_error",
                        detail=str(exc),
                    )
                    job.failure = {
                        "stage": "config",
                        "error_code": "usage_error",
                        "message": str(exc),
                    }
                    job.status = "failed"
                    return
                api_key = (env.get("EXA_API_KEY") or "").strip() or None

                def on_stage_started(stage: str) -> None:
                    job.stage = stage

                job.stage = "fund_extraction"
                try:
                    yf = _load_yf()
                except ImportError as exc:
                    events.emit(
                        "run_failed",
                        stage="fund_extraction",
                        error_code="yahoo_unavailable",
                        detail=str(exc),
                    )
                    job.failure = {
                        "stage": "fund_extraction",
                        "error_code": "yahoo_unavailable",
                        "message": PUBLIC_FAILURES["yahoo_unavailable"],
                    }
                    job.status = "failed"
                    return

                current_stage = "fund_extraction"
                status, _report = _run_stages(
                    RunInput(fund=job.fund),
                    events,
                    yf,
                    run_dir=job.run_dir,
                    config=config,
                    api_key=api_key,
                    exa_factory=exa_client,
                    ollama_client_factory=synthesis_ollama_client,
                    report_writer=write_report,
                    clock=clock,
                    on_stage_started=on_stage_started,
                )
                if status == EXIT_OK and (job.run_dir / "report.md").is_file():
                    job.stage = None
                    job.status = "succeeded"
                else:
                    job.status = "failed"
                    job.failure = self._read_failure(job.run_dir) or {
                        "stage": job.stage or current_stage,
                        "error_code": "run_failed",
                        "message": "The report could not be completed.",
                    }
        except Exception as exc:
            job.status = "failed"
            job.failure = {
                "stage": job.stage or current_stage,
                "error_code": "run_failed",
                "message": "The report could not be completed. Check the server logs.",
            }
            try:
                with (job.run_dir / "events.jsonl").open("a", encoding="utf-8") as sink:
                    EventEmitter(run_id=job.run_id, clock=clock, sink=sink).emit(
                        "run_failed",
                        stage=job.stage or current_stage,
                        error_code="run_failed",
                        detail=str(exc),
                    )
            except OSError:
                pass

    @staticmethod
    def _read_failure(run_dir: Path) -> dict[str, str] | None:
        path = run_dir / "events.jsonl"
        try:
            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError):
            return None
        for record in reversed(records):
            if record.get("event") == "run_failed":
                error_code = str(record.get("error_code", "run_failed"))
                return {
                    "stage": str(record.get("stage", "unknown")),
                    "error_code": error_code,
                    "message": PUBLIC_FAILURES.get(
                        error_code, "The report could not be completed."
                    ),
                }
        return None

    def snapshot(self, job: RunJob) -> dict[str, Any]:
        completed: list[str] = []
        try:
            for line in (job.run_dir / "events.jsonl").read_text(
                encoding="utf-8"
            ).splitlines():
                event = json.loads(line)
                if (
                    event.get("event") == "stage_completed"
                    and event.get("stage") in STAGES
                    and event["stage"] not in completed
                ):
                    completed.append(event["stage"])
        except (OSError, json.JSONDecodeError):
            pass

        result: dict[str, Any] = {
            "id": job.run_id,
            "fund": job.fund,
            "status": job.status,
            "stage": job.stage,
            "completed_stages": completed,
            "failure": job.failure,
        }
        if job.status == "succeeded":
            try:
                run = load_run(job.run_dir)
            except QAError as exc:
                raise HTTPException(
                    status_code=500, detail="Completed run artifacts are invalid"
                ) from exc
            result.update(
                {
                    "report": run.report,
                    "profile": run.profile,
                    "articles": [
                        {
                            "source_number": number,
                            "title": item.title,
                            "url": item.url,
                            "source": item.source,
                            "published": item.published,
                            "summary": item.summary,
                            "content": item.content,
                        }
                        for number, item in enumerate(run.news, start=1)
                    ],
                }
            )
        return result


def _get_fund_suggester():
    """Create and cache the Yahoo-backed fund suggester."""
    global _fund_suggester
    if _fund_suggester is None:
        with _fund_suggester_lock:
            if _fund_suggester is None:
                _fund_suggester = cached_suggester(yf_suggester(_load_yf()))
    return _fund_suggester


manager = RunManager(Path(os.environ.get("INVESK_OUTPUT_DIR", "output")))
app = FastAPI(title="Invesk", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/suggestions")
def fund_suggestions(query: str = "") -> dict[str, list[str]]:
    query = query.strip()
    if len(query) < MIN_QUERY_LEN:
        return {"suggestions": []}
    try:
        suggestions = _get_fund_suggester()(query)
    except Exception:
        # Suggestions are best-effort; never block fund entry.
        return {"suggestions": []}
    return {"suggestions": suggestions[:MAX_SUGGESTIONS]}


@app.post("/api/runs", status_code=202)
def create_run(request: CreateRunRequest) -> dict[str, str]:
    job = manager.create(request.fund)
    return {"id": job.run_id, "fund": job.fund, "status": "queued"}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    return manager.snapshot(manager.get(run_id))


@app.get("/api/runs/{run_id}/qa-status")
def get_qa_status(run_id: str) -> dict[str, str | None]:
    return {"status": manager.get(run_id).qa_status}


@app.post("/api/runs/{run_id}/chat/reset")
def reset_chat(run_id: str) -> dict[str, bool]:
    job = manager.get(run_id)
    if job.status != "succeeded":
        raise HTTPException(
            status_code=409, detail="Chat is available after the report is complete"
        )
    with job.qa_lock:
        job.qa_history.clear()
    return {"reset": True}


@app.post("/api/runs/{run_id}/questions")
def ask_question(run_id: str, request: QuestionRequest) -> dict[str, Any]:
    job = manager.get(run_id)
    if job.status != "succeeded":
        raise HTTPException(
            status_code=409, detail="Chat is available after the report is complete"
        )

    with job.qa_lock:
        try:
            run: QARun = load_run(job.run_dir)
            events_path = job.run_dir / "events.jsonl"
            with events_path.open("a", encoding="utf-8") as sink:
                events = EventEmitter(
                    run_id=job.run_id,
                    clock=lambda: datetime.now(timezone.utc),
                    sink=sink,
                )
                if not job.qa_started:
                    events.emit(
                        "qa_started",
                        stage="qa",
                        news=len(run.news),
                        model=QA_MODEL,
                    )
                    job.qa_started = True
                try:
                    client = ollama_client()
                    job.qa_status = "thinking"
                    try:
                        result = _ask_turn(
                            run,
                            request.question,
                            job.qa_history,
                            client,
                            events,
                            exa_api_key=(
                                (compose_env(None).get("EXA_API_KEY") or "").strip()
                                or None
                            ),
                            exa_factory=exa_client,
                            status_callback=lambda status: setattr(
                                job, "qa_status", status
                            ),
                        )
                    finally:
                        job.qa_status = None
                except QAResponseError as exc:
                    events.emit(
                        "qa_failed",
                        stage="qa",
                        error_code=exc.error_code,
                        detail=str(exc),
                        turn=len(job.qa_history) + 1,
                    )
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                except QAError as exc:
                    events.emit(
                        "qa_failed",
                        stage="qa",
                        error_code=exc.error_code,
                        detail=str(exc),
                        turn=len(job.qa_history) + 1,
                    )
                    raise HTTPException(
                        status_code=503,
                        detail="The AI service is unavailable. Please try again.",
                    ) from exc
                except Exception as exc:
                    events.emit(
                        "qa_failed",
                        stage="qa",
                        error_code="ollama_unavailable",
                        detail=str(exc),
                        turn=len(job.qa_history) + 1,
                    )
                    raise HTTPException(
                        status_code=503,
                        detail="The AI service is unavailable. Please try again.",
                    ) from exc

                (
                    answer,
                    citations,
                    insufficient,
                    passages,
                    attempts,
                    latency_ms,
                    web_search_attempted,
                ) = result
                event_fields: dict[str, object] = {}
                if web_search_attempted:
                    event_fields["web_search_attempted"] = True
                events.emit(
                    "qa_answered",
                    stage="qa",
                    citations=list(citations),
                    passages=len(passages),
                    evidence_chars=sum(len(passage.text) for passage in passages),
                    latency_ms=latency_ms,
                    attempts=attempts,
                    insufficient=insufficient,
                    **event_fields,
                )
                job.qa_history.append((request.question, answer))
                evidence = []
                for citation in citations:
                    citation_id = str(citation)
                    source_passages = [
                        passage
                        for passage in passages
                        if passage.source_id == citation_id
                    ]
                    if not source_passages:
                        continue
                    first = source_passages[0]
                    evidence.append(
                        {
                            "source_id": citation_id,
                            "source_number": first.source_number,
                            "kind": "web" if first.source_number is None else "news",
                            "title": first.title,
                            "url": first.url,
                            "source": first.source,
                            "published": first.published,
                            "passages": [passage.text for passage in source_passages],
                        }
                    )
                return {
                    "question": request.question,
                    "answer": answer,
                    "citations": list(citations),
                    "insufficient": insufficient,
                    "evidence": evidence,
                    "web_search_attempted": web_search_attempted,
                }
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail="Could not access this run's artifacts"
            ) from exc


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
