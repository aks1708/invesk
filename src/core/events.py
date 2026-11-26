"""Structured JSONL event stream (PRD §16, constitution P6).

Every run writes one JSON object per line to its `events.jsonl` artifact;
the schema is versioned in `contracts/events.v1.md`. There are no other
signals: exit codes and these events are the audit trail.
"""

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Final, TextIO

SCHEMA_VERSION: Final[int] = 2

#: Required fields per event name (contracts/events.v1.md). `stage` is a
#: common field and required on every event. Optional fields (`request_id`,
#: `http_status`) are not listed — they appear only when the provider
#: supplies them.
EVENT_FIELDS: Final[Mapping[str, tuple[str, ...]]] = {
    "run_started": ("fund",),
    "stage_completed": (),
    "external_call": ("provider", "latency_ms", "status"),
    "token_usage": ("provider", "prompt_tokens", "completion_tokens"),
    "report_written": ("path",),
    "run_failed": ("error_code", "detail"),
    "qa_started": ("news", "model"),
    "qa_answered": (
        "citations",
        "passages",
        "evidence_chars",
        "latency_ms",
        "attempts",
        "insufficient",
    ),
    "qa_failed": ("error_code", "detail"),
}

Clock = Callable[[], datetime]


def format_timestamp(moment: datetime) -> str:
    """UTC ISO-8601 timestamp with second precision."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EventEmitter:
    """Appends one JSON object per event to an explicitly injected sink."""

    def __init__(self, run_id: str, clock: Clock, sink: TextIO) -> None:
        self._run_id = run_id
        self._clock = clock
        self._sink = sink

    @property
    def run_id(self) -> str:
        """The run scope used by downstream artifact and index writers."""
        return self._run_id

    def emit(self, event: str, **fields: object) -> None:
        """Append one contract-valid record to the sink (contracts/events.v1.md).

        Rejects an unknown event name or a missing required field with
        `ValueError`: the stream is the audit trail (P6), so a malformed
        record must never be written — better a loud failure than a silent
        gap in the audit trail.
        """
        required_fields = EVENT_FIELDS.get(event)
        if required_fields is None:
            raise ValueError(
                f"unknown event {event!r}; expected one of {sorted(EVENT_FIELDS)}"
            )
        missing_fields = [
            name for name in ("stage", *required_fields) if name not in fields
        ]
        if missing_fields:
            raise ValueError(
                f"{event} is missing required fields: {', '.join(missing_fields)}"
            )
        record: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "event": event,
            "run_id": self._run_id,
            "timestamp": format_timestamp(self._clock()),
            **fields,
        }
        self._sink.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._sink.flush()
