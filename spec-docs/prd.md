# Invesk PRD

Governed by [`constitution.md`](./constitution.md); inline references P1–P10
point to its Core Principles.

## 1. Problem

Investors are advised to put long-term money into low-to-medium risk
instruments — mutual funds, ETFs, and index funds (S&P 500, FTSE 100) — which
hold stocks across many industries and countries. Gauging the fund and the news
across everything it holds is time-consuming, so most investors skip it. No
investor should blindly invest in something they do not understand. Reports
should explain financial information in simple language that anyone can
understand.

## 2. Solution Overview

Invesk is a Python CLI. The user names a fund (e.g. Vanguard FTSE 250); Invesk
then:

1. **Extracts** the fund's data — composition (companies, industries, countries
   with percentages) and financial statements.
2. **Searches** the web in parallel (Exa) for news relevant to what the fund
   holds.
3. **Synthesizes** (Gemma 4 via Ollama) detailed, easy-to-understand company
   insights and sector insights (where each sector is heading) from relevant
   news and market views. Fund snapshot and metric presentation are assembled
   from extracted data without LLM interpretation.

The output informs decisions — it is not personalized financial advice, and it
is never a dump of random news articles.

## 3. Goals

- One command produces a complete, readable fund report.
- Every report uses simple language and explains financial terms so anyone can
  understand it.
- Every claim traces to extracted fund data or a searched news item.
- Coverage is proportional to the fund: largest holdings by weight drive the
  news searches.

## 4. User Journey

1. User submits a fund name to the CLI.
2. Invesk validates input and resolves the fund.
3. Extracts fund information: composition + financial statements.
4. Fans out parallel Exa searches over key holdings and industries.
5. Gemma 4 writes detailed company and sector insights in clear language.
6. User reads the Markdown report printed to stdout and saved under `output/`.

## 5. Tech Stack & Environment

| Concern | Choice |
| --- | --- |
| Backend language / runtime | Python 3.11+ (CLI) |
| Packaging | Python package (`pyproject.toml`), installed into a venv |
| LLM | Gemma 4 (`gemma4:cloud`) served through Ollama |
| Web search | Exa API |
| Fund data | yfinance (Yahoo Finance) — pinned library, no API key |
| Output | Markdown report (stdout + `output/`) + JSONL events |

Environment: virtual environment with pinned dependencies; outbound calls to
Ollama Cloud, Exa, and Yahoo Finance (via yfinance). Supply the Exa API key via
an environment variable. Authenticate Ollama Cloud in the terminal with
`ollama signin`. 

## 6. Architecture

One process, one data location (P1). Stages are stateless; all external clients
and configuration are injected at a single composition root (P3). The CLI
invokes the pipeline directly from that composition root (P2).

```
CLI input ──▶ composition root ──▶ pipeline stages
(fund name)          │
                     │
         [1] Fund extraction ──────▶ yfinance (Yahoo)        → FundProfile
                │
                ▼
        [2] Search orchestration ─▶ Exa (parallel, capped)  → NewsItem[]
                │
                ▼
        [3] Synthesis ────────────▶ Gemma 4 / Ollama        → structured report sections
                │
                ▼
        [4] Report assembly ────────────────────────────────→ markdown report + JSONL events
                          │
                          ▼
               Markdown report → stdout + output/; supporting data/events → output/
```

- One module per pipeline stage (§8); modules communicate through the §10
  entities passed as explicit parameters — no globals, no import-time side
  effects (P3).
- Stages are plain function calls from the composition root; no interface or
  plugin layers (P2).
- Modules exchange data only across versioned external HTTP/file boundaries (P4).
- Packaging: `pip install -e .`; reverting a change means restoring the
  previous installed version (P7).

## 7. Components

| Module | Responsibility |
| --- | --- |
| `cli` | Validate fund name; wire dependencies; orchestrate stages; set exit codes |
| `models` | `FundProfile`, `NewsItem`, report-section entities with validation |
| `extraction` | yfinance client and boundary adapter → `FundProfile` |
| `search` | Build Exa queries from top holdings/sectors/countries; run parallel; dedupe and cap |
| `synthesis` | Prompt building, Ollama client, structured-response parsing (one retry) |
| `report` | Render sections into markdown; write artifacts |
| `events` | Emit JSONL events for every stage |

## 8. External Interface Contracts

Request/response schemas for each boundary are versioned in `contracts/` and
written **before** the consuming code (P4). Each contract records: endpoint,
method, auth, request/response schemas, error codes, rate limits.

| Boundary | Method / Endpoint | Auth | Notes |
| --- | --- | --- | --- |
| Ollama Cloud (Gemma 4) | `chat` (ollama Python client) | Ollama CLI session (`ollama signin`) | Insights-only structured JSON output; one retry on malformed output ([contract v1](../contracts/ollama.v1.md)) |
| Exa | `/search` (REST) | `x-api-key` header | Parallel news queries |
| Yahoo Finance (yfinance) | Library call (ticker lookup + fund fields) | None | yfinance pinned in `pyproject.toml`; field mapping versioned in `contracts/` |

## 9. Data Model & Artifacts

Each run writes versioned JSON artifacts plus the report to
`output/<fund-slug>/<run_id>/`: `report.md`, `fund_profile.json`, `news.json`,
`events.jsonl`. Artifact schemas carry a `schema_version`; changes bump it
(P4).

Entities:

- **FundProfile** — fund name, provider, holdings `[{name, weight}]`, sector
  weights, and the fund's overview metrics (gaps flagged for anything Yahoo
  does not return; per-holding data is not available from the provider and
  is not part of the model).
- **NewsItem** — title, url, source, published date, summary, relevance,
  related entities.
- **Report** — fund, generated-at; sections: snapshot and fund-level metrics
  assembled from `FundProfile`, plus company insights and sector insights
  synthesized by the LLM. Report citations refer to stable source tokens for
  supplied `NewsItem.url` values; the renderer maps each token to its numbered
  source entry.

## 10. Functional Requirements

**FR1 — Input handling.** Input: fund name (string). It must not be empty.
The application prompts for the fund name; while typing, it shows live fund
name suggestions from Yahoo (best-effort; selection via Tab, submission via
Enter with an explicit `[Y/n]` confirmation before the run starts). When
stdin is not an interactive terminal, the app falls back to a plain prompt.
Usage errors (empty input, cancelled confirmation) exit `2` before any
external call. Fund names are accepted as free text.

**FR2 — Fund data extraction.** Fund name → Yahoo ticker lookup via yfinance →
`FundProfile`; weights and provider formats normalized at the boundary adapter.
Fund not found or provider failure → exit `1`; partial data → proceed and flag
gaps in the report.

**FR3 — News search.** `FundProfile` + config caps (defaults, tunable: ≤ 10
searches — one per top-5 holding by weight plus one per top-5 sector by
weight, the sector queries asking where the sector is heading — ≤ 5 results
each, 90-day window) → deduplicated `NewsItem[]` (by URL), each carrying the
result's summary and page text (first 10000 characters). Individual search
failures
are logged and skipped; total failure degrades to a fund-data-only report via
config flag (P7) or aborts.

**FR4 — LLM synthesis.** `FundProfile` + `NewsItem[]` → structured
**company insights** (what the news says about the top holdings) and **sector
insights** (where each sector is heading), validated against the insights
schema. These are the only report sections the LLM writes; it does not write
the fund snapshot or interpret financial metrics. Insights are grouped by
company or sector, detailed and informative, and written in simple language
for a general reader. They connect sourced developments to business or sector
effects and explain why those effects could matter to an investor in the fund,
relating implications to holdings or sector weights where useful and available.
Facts are distinguished from qualified, evidence-based interpretation;
outlook, risks, and opportunities are included when supported by the supplied
news, without unsupported share-price predictions or buy/sell advice. Claims
and source-grounded reasoning cite supplied news. Financial and industry terms
are briefly explained in plain language at first use, within the relevant
insight so the explanation connects to its company/sector context and why the
development matters; avoid detached glossary-style definitions. Acronyms are
spelled out at first use. Source citations in the structured response use
stable tokens attached to supplied news items. FR4 validates that tokens refer
only to items included in the prompt and maps them to the corresponding
numbered source entries; unknown tokens and missing section citations are
malformed. This validates citation references, not whether a source
substantively supports each claim. At most the top few news items per entity
are fed to the prompt, and the reply is bounded so it fits the model's output
window. Malformed output → one corrective retry, then exit `1`.

**FR5 — Report generation.** Validated insights plus `FundProfile` → the report
printed to stdout and written to `output/<fund-slug>/<run_id>/report.md` with
the §10 artifact set. FR5 assembles the snapshot and presents available
fund-level metrics directly from `FundProfile`; it does not infer a financial
health assessment. Report metadata shows the fund name and currency, and a UTC
timestamp formatted `DD-MM-YYYY HH:MM`. Inline citations use numbered
markers (`[1]`, `[2]`, …) that map
to the corresponding numbered entries in the report's Sources list. Numbering
follows the deduplicated `NewsItem[]` order and is consistent between the
markers and source entries within a run. Write failure → exit `1`.

**FR6 — Events & exit codes.** Every stage boundary emits the §16 events (schema v2).
Exit codes: `0` success, `1` runtime failure, `2` usage error.

## 11. Non-Functional Requirements

| Category | Requirement | Measurement |
| --- | --- | --- |
| Performance | Typical fund → report in ≤ 5 min wall clock | Timed runs on 3 sample funds |
| Observability | Structured events at every stage boundary | Event presence in `events.jsonl` (P6) |
| Security | No secrets in logs, reports, or the repository | Secret scan before each PR |

## 12. Security

- Exa API key (`EXA_API_KEY`) via environment variables; `.env` excluded from
  version control. Ollama Cloud authentication is managed by the Ollama CLI
  session (`ollama signin`), not application environment variables; yfinance
  requires no key.
- Keys are never logged and never embedded in prompts or reports; traffic is
  HTTPS.
- The structured event stream is the audit trail (P6).

## 13. Testing Plan

Testing follows P5: cover core transformations, not application plumbing.

- **Core unit tests** — FR1 input validation; FR2 weight normalization and
  profile mapping; FR3 query construction, news mapping, deduplication, and
  failure/degrade policy; FR4 prompt building, response/citation validation,
  and one-retry behavior; FR5 report rendering and versioned artifact
  documents.
- **Not in the default suite** — CLI orchestration, event emission, terminal
  presentation, and filesystem writes. Two optional smoke tests call real Exa
  and Ollama boundaries (`pytest -m smoke`); they are excluded from routine runs.
- **Performance** — timed runs on the 3 sample funds; investigate anything
  above the 10-minute budget.
- **Security** — secret scanning; artifacts contain no keys.

## 14. Running the Project

Commands (P10) are documented in the README:

| Command | Purpose |
| --- | --- |
| `pip install -e .` | Install into a virtual environment |
| `python -m src` | Ask for a fund name, then generate a report (print and write artifacts) |
| `pytest` | Core-logic transformation tests (offline) |

Rollback (P7): restore the previous installed version. Degrade mode and
search caps are configuration, not code.

## 15. Observability

- **Events**: `run_started`, `stage_completed`, `external_call` (provider,
  latency, status), `token_usage`, `report_written`, `run_failed` (stage,
  error code).
- **Fields**: `run_id`, fund, stage, timestamp; request ids on
  external calls.
- Events and exit codes are the only signals, from one instrumentation source
  (P6). Any future alerting follows P8.

## 16. Open Questions

1. **Yahoo coverage** — does yfinance expose full holdings (companies,
   industries, and country weights) for funds like Vanguard FTSE 250, or only
   sector weightings and top holdings? (Blocks FR2.)
2. **Holdings-derived statements** — per-holding data is not available from
   Yahoo; the report presents fund-level overview metrics only and does not
   assess the individual companies held by the fund (resolved 2026-11-13).
3. **yfinance fragility** — Yahoo rate limits and scraping fragility; fallback
   fund-data source if it breaks.
4. **Gemma 4 variant/size** and Ollama Cloud availability/auth; behavior on provider failure.
5. **Rate limits & cost budget** per run for Exa and Ollama Cloud.
6. **Search defaults** — confirm FR3 caps after first real runs.

## 17. Definition of Done

Per P9, a work item is done when it is:

1. **Running** — a user can run one command and get the report.
2. **Instrumented** — its effect is visible in `events.jsonl`.
3. **Verified** — relevant core transformation tests pass locally.
4. **Revertible** — the previous version reinstalls cleanly.