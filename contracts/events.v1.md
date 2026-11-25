# Contract: `events.jsonl` — contract version 2

This document's contract version is independent of the event payload's
`schema_version`, which remains `2`.

Producer: the `src.core.events` module. Consumers: anything reading a run's
`output/<fund-slug>/<run_id>/events.jsonl` artifact (PRD §9, §15). Browser
request validation failures are returned by the API before a run is created and
do not emit run events. Invalid run configuration is recorded in the run's
event stream when the worker starts.

## Encoding

UTF-8, one JSON object per line (JSONL, LF line endings), flush after each
line so the artifact is complete even if a run crashes.

## Common fields (every event)

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | int | `2` |
| `event` | string | one of the event names below |
| `run_id` | string | unique per run: `YYYYMMDDTHHMMSSZ-<8 hex>` |
| `timestamp` | string | UTC ISO-8601, second precision, `Z` suffix |
| `stage` | string | pipeline stage the event belongs to |

## Event-specific fields

| Event | Extra fields |
| --- | --- |
| `run_started` | `fund` (string) |
| `stage_completed` | Stage `fund_extraction` (FR2): `ticker`, `holdings`, `sectors`, `gaps` (counts). Stage `news_search` (FR3): `searches`, `ok`, `failed`, `results` (raw), `news` (after dedupe) (counts), `degraded` (bool — true only when every search failed in degrade mode). Stage `synthesis` (FR4): `news` (items fed to the prompt) (counts), `attempts` (1 or 2), `retried` (bool). |
| `external_call` | `provider` (e.g. `yahoo.search`, `exa.search`, `ollama.gemma`), `latency_ms` (int), `status` (`ok\|error`); `request_id` only when the provider returns one (library calls omit it). Exa adds `entity` (the holding/sector queried) and, on error, `http_status` (int) when the provider returned one. Ollama adds `http_status` on error; it returns no request id. |
| `token_usage` | `provider`, `prompt_tokens`, `completion_tokens` (FR4+) |
| `report_written` | `path` (FR5) |
| `run_failed` | `error_code`, `detail` (free text, no secrets) |
| `qa_started` | Q&A session start (FR7): `news` (collected item count, int), `model` (string) |
| `qa_answered` | Successful Q&A turn (FR7): `citations` (array of saved-news source-number ints and/or web source-ID strings), `passages` (count supplied, int), `evidence_chars` (int), `latency_ms` (int), `attempts` (1–4 total model attempts), `insufficient` (bool); optional `web_search_attempted` (bool) |
| `qa_failed` | Failed Q&A session or turn (FR7): `error_code`, `detail` (free text, no secrets), `turn` (1-based int when failure is turn-specific; omitted for startup/session failures) |

Q&A events use `stage: "qa"`. Q&A event payloads use the same common
`schema_version: 2`. This contract version documents the Q&A event fields and
mixed saved-news/web citation IDs; consumers that only process
report-generation events can continue to ignore Q&A event names.

Q&A does not emit `run_started`, `stage_completed`, `report_written`, or
`run_failed`; it appends `qa_*`, `external_call`, and `token_usage` events to
the existing run's `events.jsonl`. `qa_started` is emitted after the required
artifacts are loaded and validated. A malformed response after the corrective
retry emits `qa_failed` with `error_code: "qa_response_invalid"` and fails that
question request while leaving the browser app available. An Ollama provider
failure emits `qa_failed` with `error_code: "ollama_unavailable"`; the API
returns an error for that request.
Invalid question requests do not append a Q&A event.
Artifact-loading failures also occur before `qa_started` and do not append a
Q&A event; the API responds according to the browser API contract.
Conditional web fallback calls emit `external_call` with `provider:
exa.qa_search`. Event payloads never contain the query, result text, or API key.

## Failure codes

- `usage_error` — invalid EXA_* search configuration (FR3); the failed run
  records the event at stage `config`.
- `fund_not_found` — Yahoo lookup returned no fund quote for the name (FR2);
  recorded in `run_failed`.
- `yahoo_unavailable` — Yahoo call failed (network, HTTP, parse) or
  yfinance is not installed (FR2).
- `exa_not_configured` — `EXA_API_KEY` is not set; news search cannot run
  (FR3). Degrade mode does not apply: without a key there is no search.
- `exa_unavailable` — every Exa search failed and
  `EXA_DEGRADE_ON_FAILURE` is off (FR3).
- `ollama_unavailable` — the Ollama call failed (network, HTTP,
  parse) (FR4). Synthesis retries malformed output, not the provider, so this
  aborts the run.
- `synthesis_failed` — Gemma's reply was malformed (not one JSON object, a
  missing/empty section, or an unexpected response field)
  after the one corrective retry (FR4).
- `report_write_failed` — writing the §9 artifact set failed (FR5); no
  `report_written` event is emitted for that run.
- `qa_run_not_found` — the Q&A run directory does not exist or is not a
  directory (FR7).
- `qa_artifact_missing` — a required Q&A artifact is missing (FR7).
- `qa_artifact_invalid` — a required artifact is unreadable, invalid JSON, or
  has an unsupported schema version (FR7).
- `qa_response_invalid` — the Q&A model response is malformed after one
  corrective retry (FR7); the session continues.
