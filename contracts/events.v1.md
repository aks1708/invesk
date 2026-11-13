# Contract: `events.jsonl` — contract version 1

This document's contract version is independent of the event payload's
`schema_version`, which remains `2`.

Producer: the `src.core.events` module. Consumers: anything reading a run's
`output/<fund-slug>/<run_id>/events.jsonl` artifact (PRD §10, §16). On a
usage error (exit 2) no run directory exists yet, so the single `run_failed`
event is written to stderr instead.

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

## Error codes (exit 1 unless noted)

- `usage_error` — invalid CLI input (FR1) or invalid EXA_* configuration
  (FR3); the run exits 2. For config errors the stage is `config`, emitted
  to stderr because no run directory exists yet.
- `fund_not_found` — Yahoo lookup returned no fund quote for the name (FR2).
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
- `report_write_failed` — writing the §10 artifact set failed (FR5); no
  `report_written` event is emitted for that run.
