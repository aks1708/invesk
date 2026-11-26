# Invesk PRD

## 1. Problem

Investors are advised to put long-term money into low-to-medium risk
instruments — mutual funds, ETFs, and index funds (S&P 500, FTSE 100) — which
hold stocks across many industries and countries. Gauging the fund and the news
across everything it holds is time-consuming, so most investors skip it. No
investor should blindly invest in something they do not understand. Reports
should explain financial information in simple language that anyone can
understand.

## 2. Solution Overview

Invesk is a local browser application. The user enters a fund name (e.g.
Vanguard FTSE 250); Invesk then:

1. **Extracts** available fund data from Yahoo Finance — top holdings, sector
   weights, and fund-level overview metrics. Coverage varies by fund; the
   implementation does not retrieve country weights or company financial
   statements.
2. **Searches** the web in parallel (Exa) for news relevant to what the fund
   holds.
3. **Deduplicates** the collected articles semantically, discarding items that
   repeat a story already kept, before any of it reaches the report.
4. **Synthesizes** (Gemma 4 via Ollama) detailed, easy-to-understand company
   insights and sector insights (where each sector is heading) from relevant
   news and market views. Metric presentation is assembled from extracted data
   without LLM interpretation.
5. **Answers questions** about a completed run: the fund profile and every
   source collected in that run are available to a multi-turn Q&A session.
   Answers cite the same numbered saved sources, plus distinct web citations
   when the saved sources are insufficient. The report is displayed beside the
   chat but is not sent to the Q&A model.

When a report succeeds, the browser displays it alongside a chat initialized
from that run. The user can also search and browse the news articles collected
for that run.

The report output informs decisions — it is not personalized financial advice,
and it is never a dump of random news articles. Q&A starts with artifacts
saved by the original run and performs a bounded web search only when those
sources are insufficient.

## 3. Goals

- A user can start an analysis in the browser and get a complete, readable
  fund report.
- Every report uses simple language and explains financial terms so anyone can
  understand it.
- Every claim traces to extracted fund data or a searched news item.
- Every Q&A answer traces to a source collected in that run or a conditional
  web-search result, or explicitly says the available sources do not cover it.
- Coverage is proportional to the fund: largest holdings by weight drive the
  news searches.
- Redundant coverage is removed before synthesis: when many outlets report the
  same development, the report draws on one representative article, so
  distinct developments get the available space.

## 4. User Journey

1. User enters a fund name in the browser and starts an analysis.
2. Invesk validates the input and resolves the fund.
3. Extracts available fund information: top holdings, sector weights, and
   fund-level overview metrics.
4. Fans out parallel Exa searches over key holdings and sectors, then removes
   articles that repeat a story already collected.
5. Gemma 4 writes detailed company and sector insights in clear language.
6. User reads the report in the browser; the report and supporting artifacts
   are saved under `output/`.
7. User asks follow-up questions in the run-scoped browser chat. Invesk answers
   from the run's collected sources first.
    If they are insufficient, it can search the web, distinguish those
    citations, and show source links with supporting excerpts.

## 5. Tech Stack & Environment

| Concern | Choice |
| --- | --- |
| Backend language / runtime | Python 3.11+ (local web API, report/Q&A logic) |
| Frontend | React + TypeScript + Vite; shadcn/ui-style components built on Radix UI |
| Frontend toolchain | Node.js 18+ and npm |
| Packaging | Python package (`pyproject.toml`), installed into a venv |
| LLM | Gemma 4 (`gemma4:cloud`) served through Ollama |
| Embeddings | Ollama `embeddinggemma-2` (local, 768-dim) for semantic news deduplication |
| Q&A retrieval | Deterministic local BM25 and title-match scoring |
| Web search | Exa API |
| Fund data | yfinance (Yahoo Finance) — pinned library, no API key |
| Output | Browser report and chat; saved report/data/events under `output/` |

Environment: virtual environment with pinned dependencies; outbound calls to
Ollama Cloud, Exa, and Yahoo Finance (via yfinance), plus a local connection to
the Ollama embedding service.
Supply the Exa API key via an environment variable. Authenticate Ollama Cloud
in the terminal with `ollama signin`. Pull the local embedding model once with
`ollama pull embeddinggemma-2` (or configure another embedding model).

## 6. Architecture

The browser is the supported user interface. A local FastAPI service starts
report runs in background workers, exposes progress and artifacts, and handles
run-scoped Q&A. It binds to localhost by default. The React/Vite frontend uses
that API in development and is served from `frontend/dist/` by the API when
built. Report stages run in one process and write artifacts under `output/`;
Q&A operates on a completed run and appends its own events without changing
the report or saved research data.

```
Browser ──▶ FastAPI ──▶ report pipeline ──▶ saved run artifacts
                         │
                         ├─ Fund extraction ─▶ Yahoo Finance
                         ├─ News search ──────▶ Exa
                         ├─ Semantic dedupe ──▶ Ollama embeddings
                         ├─ Synthesis ────────▶ Ollama / Gemma 4
                         └─ Report assembly ──▶ report.md + JSONL events
```

News search and semantic dedupe are separate stages: dedupe runs in-process
over the collected `NewsItem[]`, never calls Exa again, and finishes before
synthesis and artifact writing. The stored article text remains in its original
Markdown form for report artifacts, article browsing, and Q&A retrieval.

Browser flow:

```
Browser: fund form ──▶ run report pipeline ──▶ successful run artifacts
                                               │
                       ┌───────────────────────┴──────────────────────┐
                       ▼                                              ▼
                Render report                              Initialize chat context
                                                         (profile + news;
                                                          report display only)
                       │                                              │
                       └──────── Search/browse saved news ────────────┘
```

- Pipeline stages are plain function calls from the composition root and pass
  internal entities explicitly; external services and configuration are not
  accessed through import-time side effects.
- External provider APIs and persisted artifacts have documented contracts.
  Internal stage data is passed in-process.
- Packaging: `pip install -e .`.
- Q&A reads a saved run directory and appends only its own events. It searches
  the saved Markdown corpus directly, calls Ollama to answer, and conditionally
  calls Exa only when saved evidence is insufficient. It never calls Yahoo or
  re-runs synthesis.

## 7. Components

| Module | Responsibility |
| --- | --- |
| `src.core` | Shared configuration, events, models, and report-stage orchestration |
| `src.fund_suggestions` | Yahoo-backed fund-name suggestions for the browser interface |
| `models` | `FundProfile`, `NewsItem`, report-section entities with validation |
| `extraction` | yfinance client and boundary adapter → `FundProfile` |
| `search` | Build Exa queries from top holdings and sector weights; run parallel; dedupe by URL and cap |
| `dedupe` | Embed collected articles, remove semantic duplicates, merge related entities, keep one representative per story |
| `synthesis` | Prompt building, Ollama client, structured-response parsing (one retry) |
| `report` | Render sections into markdown; write artifacts |
| `qa` | Load a completed run; retrieve run evidence; conditionally search the web; answer with validated citations and show supporting evidence |
| `events` | Emit JSONL events for every stage |
| `web` | Provide the local HTTP API for background report runs, progress, run artifacts, and multi-turn Q&A |
| `frontend` | Collect a fund name, show pipeline progress and report, initialize run-scoped chat on success, and search/browse that run's saved news |

## 8. External Interface Contracts

The current external API and saved-artifact behavior is documented in
`contracts/`. Those documents describe the implementation; their contract
versions are independent of payload schema versions.

| Boundary | Method / Endpoint | Auth | Notes |
| --- | --- | --- | --- |
| Ollama Cloud (Gemma 4) | `chat` (ollama Python client) | Ollama CLI session (`ollama signin`) | Insights-only structured JSON output; one retry on malformed output ([contract v1](../contracts/ollama.v1.md)) |
| Ollama Cloud (Gemma 4) — Q&A | `chat` (ollama Python client) | Ollama CLI session (`ollama signin`) | Analyst system prompt, answer + citation JSON over a saved run; one retry per model request ([contract v3](../contracts/qa.v1.md)) |
| Exa | `Exa.search()` SDK | `x-api-key` header | Parallel report news queries; one conditional Q&A web search on insufficiency |
| Ollama embeddings | `embed` (ollama Python client) | Local Ollama daemon; no key | Semantic news deduplication (FR3b) ([contract v1](../contracts/ollama_embed.v1.md)) |
| Yahoo Finance (yfinance) | Library call (ticker lookup + fund fields) | None | yfinance pinned in `pyproject.toml`; field mapping versioned in `contracts/` |
| Local browser API | `/api/runs`, `/api/runs/{id}/questions`, `/api/runs/{id}/chat/reset` (HTTP) | None; bound to localhost | Browser-to-Python contract ([contract v3](../contracts/web.v1.md)) |

The Q&A response contract fixes the answer, citation, and refusal schema so
the session can validate model output. Conditional web results are transient:
they do not change the saved artifact contracts or news corpus.

## 9. Data Model & Artifacts

Each report run writes versioned JSON artifacts plus the report to
`output/<fund-slug>/<run_id>/`: `report.md`, `fund_profile.json`, `news.json`,
`events.jsonl`. Artifact schemas carry a `schema_version`; changes bump it
when the payload shape changes. Q&A reads these artifacts directly; it does not
add to the required artifact set, and its conversation history is in memory
only.

Entities:

- **FundProfile** — fund name, provider, top holdings `[{name, weight}]`,
  sector weights, and available fund-level overview metrics (gaps flagged for
  anything Yahoo does not return; per-holding financial data is not available
  and is not part of the model).
- **NewsItem** — title, url, source, published date, summary, relevance,
  related entities, and the page text (full article, markdown-style, no HTML
  tags; see FR3 search options for verbosity and content controls). `related`
  names every holding or sector whose search returned the story; after FR3b it
  can name more than one. Every search result that survives URL and semantic
  deduplication is stored, whether or not the report cites it; items discarded
  as semantic duplicates are not stored.
- **Duplicate group** — an FR3b representative and the items classified as
  duplicates of it by the deterministic, non-transitive grouping pass. A
  candidate is grouped when its cosine similarity to an already-kept
  representative meets the threshold; the group's entities are merged into
  that representative, and the other items are dropped before `news.json` is
  written. Groups are reported as counts in `events.jsonl`, not persisted.
- **Source tiers** — *collected*: every `NewsItem` in `news.json` after FR3b;
  *supplied*: the capped subset included in the FR4 prompt; *cited*: the subset
  the report actually references. Q&A reads the collected tier.
- **Report** — fund, generated-at; fund-level metrics assembled from
  `FundProfile`, plus company insights and sector insights
  synthesized by the LLM. Report citations refer to stable source tokens for
  supplied `NewsItem.url` values; the renderer maps each token to its numbered
  source entry. Only cited sources appear in the report's Sources list, and
  numbering follows the full post-FR3b `NewsItem[]`, so that list can be
  non-contiguous.
- **QASession** — a completed run's report (for browser display), fund profile,
  and collected news, plus in-memory conversation turns. The report is excluded
  from the model prompt. Each browser answer carries validated saved-news
  and/or transient web citations with supporting excerpts.

## 10. Functional Requirements

**FR1 — Browser input.** The user enters a fund name in the browser. After two
characters, the app shows up to six best-effort Yahoo fund suggestions. When
suggestions are available, the user selects one with the arrow keys and Enter
or by clicking it; if no suggestions are available, free-text input is allowed.
The API trims and validates the name (1–200 characters) before starting a run.

**FR2 — Fund data extraction.** Fund name → Yahoo ticker lookup via yfinance →
`FundProfile`; weights and provider formats normalized at the boundary adapter.
Fund lookup or provider failures are shown as a run failure; partial data
proceeds with its gaps flagged in the report.

**FR3 — News search.** `FundProfile` + config caps (defaults, tunable: ≤ 10
searches — one per top-5 holding by weight plus one per top-5 sector by
weight, the sector queries asking where the sector is heading — ≤ 5 results
each, 90-day window) → URL-deduplicated `NewsItem[]` (FR3b then removes
semantic duplicates), each carrying the result's summary and page text (full
article, markdown-style, no HTML tags; verbosity=compact, max_characters=None
per Exa search options). The stage does not truncate article text. Individual
search failures are logged and skipped; total failure degrades to a
fund-data-only report when configured, or aborts. The returned Markdown is
stored as received; it is not chunked or rewritten for persistence.

**FR3b — Semantic news deduplication.** After URL dedupe and before synthesis
and artifact writing, Invesk embeds the collected articles and drops items that
report the same story as an item already kept. This keeps the FR4 prompt, the
saved corpus, and Q&A from spending space and citations on repeated coverage,
and it runs before FR4's per-entity cap so redundant items no longer crowd out
distinct developments.

- **Input text.** Each item is embedded from its title, summary, and a bounded
  prefix of its page text (default ~4,000 characters, configurable), so long
  articles do not exceed the model's context or dilute the vector; the opening
  of a news article carries the event it reports. The full page text is still
  stored and used by FR4/Q&A.
- **Embeddings.** Batched calls to the local Ollama embedding model
  (`embeddinggemma-2` by default, configurable; 768 dimensions). Vectors are
  L2-normalized before comparison, so cosine similarity is their dot product.
  At the default caps a run has at most 50 candidates, so the stage compares
  all pairs directly (≤ 1,225 comparisons). No clustering or ANN index is used.
- **Threshold.** A pair is a duplicate when cosine similarity is at or above
  the configured threshold (default 0.9, `DEDUPE_SIMILARITY_THRESHOLD`,
  range 0–1). The threshold separates same-story coverage from merely related
  coverage: embeddings measure relatedness as well as sameness, so a lower
  value would merge different developments about the same company.
- **Grouping and representative.** Candidates are ordered by evidence quality
  (items with page text first, then run order — query priority, then Exa
  rank); an item is kept unless it is similar to an already-kept item. This
  single-pass grouping is deterministic and avoids transitive chaining. The
  kept item's `related` set becomes the union of its group's entities, so a
  story returned by both a company and a sector query can inform both
  insights without feeding its text to the prompt twice. Survivors are
  returned in their original run order, so report and Q&A numbering stay
  stable.
- **Failure policy.** If the embedding call fails or returns unusable vectors,
  the stage logs `external_call` `status=error` and `stage_completed` with
  `degraded=true`, and the URL-deduplicated set proceeds. Dedupe is a quality
  improvement, so it never fails the run. The `news_search` stage reports the
  URL-deduplicated count; FR3b reports the survivors.
- **Determinism.** The same candidates, embedding model, threshold, and
  ordering produce the same survivors. With no candidates, the stage emits zero
  counts and makes no embedding call.

**FR4 — LLM synthesis.** `FundProfile` + `NewsItem[]` → structured
**company insights** (what the news says about the top holdings) and **sector
insights** (where each sector is heading), validated against the insights
schema. These are the only report sections the LLM writes; it does not write
the `Financial health` section or interpret financial metrics. Insights are grouped by
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
window. Malformed output → one corrective retry, then the run fails.

**FR5 — Report generation.** Validated insights plus `FundProfile` → the report
displayed in the browser and written to `output/<fund-slug>/<run_id>/report.md`
with the §9 artifact set. FR5 presents available fund-level metrics directly
from `FundProfile`; it does not infer a financial health assessment. Report
metadata shows the fund name and currency, and a UTC timestamp formatted
`DD-MM-YYYY HH:MM`. Inline citations use numbered
markers (`[1]`, `[2]`, …) that map to the corresponding numbered entries in
the report's Sources list. Only sources actually cited in the insight sections
appear in that list; collected but uncited items stay in `news.json` and are
not listed in the report. Numbering follows the post-FR3b `NewsItem[]` order,
so the Sources list can be non-contiguous (`2.`, `5.`, `9.`) and a number
means the same item in the report, in `news.json`, and in Q&A. A write
failure marks the run as failed.

**FR6 — Events & run status.** Every stage boundary emits the §15 events
(schema v2). The API exposes run progress and failure status to the browser;
invalid request input returns HTTP `422`.

**FR7 — Browser Q&A over a completed run.** The browser sends questions to
the run-scoped Q&A API, which loads `report.md` for browser display and uses
`fund_profile.json` and `news.json` for Q&A. The corpus is every post-FR3b `NewsItem`
in `news.json`, including items the report did not cite and items never
supplied to the FR4 prompt. Each turn ranks passages directly from the full
saved Markdown text with local BM25/title matching; follow-up turns first
rewrite the question for retrieval and answer focus. The highest-ranked,
non-redundant passages are provided to Gemma 4. Passages are extracted for
evidence without changing the stored article Markdown.

Before answering, the model must assess whether the supplied passages support a
relevant, correct, complete, and faithful answer. If local evidence is
insufficient and `EXA_API_KEY` is configured, Q&A performs one general-web Exa
search using the rewritten search query (or a fallback query from recent user
questions), obtains supporting web passages, and combines them with the
saved-source candidates before asking Gemma 4 to answer.
A sufficient answer from the run corpus does not trigger web search. Search
results are transient Q&A evidence: they do not modify `news.json`, the report,
or the article browser. If the saved sources and any web results do not support
the user's intent, Q&A marks the answer insufficient rather than filling fund-,
company-, event-, or transaction-specific gaps from model knowledge. It may use
clearly labeled general background to explain concepts or typical mechanisms,
without presenting that background as a fact about the specific fund or event.

The analyst persona and response principles are sent in an Ollama `system`
message. Fund profile context, retrieved evidence, conversation history, and the
current question are supplied in the following `user` message. The displayed
report is not included in the conversation context or sent to the model. Results
and citations are validated against the Q&A response schema in
`contracts/qa.v1.md`.

Citations use the run's existing numbering: `[n]` is the item's position in the
deduplicated `NewsItem[]`, so report and Q&A numbers agree. Every cited number
must refer to a collected `NewsItem` and to a passage supplied for that turn;
the report's own `[n]` markers are not valid unless the corresponding article
is supplied. Web citations use `[Wn]`, where `Wn` identifies a result returned
for that turn; they cannot collide with saved-news numbering. The answer's
citations array contains integers for saved-news sources and strings for web
sources (for example `[2, "W1"]`). A substantive answer must contain at least
one valid citation, and a refusal must contain none. The browser shows linked
citations with supporting excerpts and source links. The model uses supplied
evidence for claims about the fund, companies, events, or specific transactions;
it may use clearly labeled general background as described above. It does not
give buy/sell advice or price predictions, or treat profile claims as evidence.
Every factual claim about the fund, companies, events, or specific transactions
in a substantive answer must be supported by at least one supplied saved-source
or web passage and cite its source marker. Clearly labeled general background
does not need a citation. Citation IDs are validated against the passages
actually supplied; a source found by search but not supplied to the answer
model cannot be cited.
Follow-up questions use recent turns for local retrieval and the
bounded web query. Q&A never calls Yahoo or re-runs synthesis. Saved article
text is stored full-length (no 10000-char cap at ingest); transient web text and
evidence are bounded by the Q&A contract. Answer-generation output receives one
corrective retry if malformed; a failed follow-up rewrite falls back to the
recent-question query. A failed answer turn does not end the session.
Conversation history is in-memory for the session; persistence is an open
question (§16).

**FR8 — Web report, chat, and article search.** The React/TypeScript browser
frontend uses shadcn/ui-style components and a local FastAPI API to expose the
existing report-generation and Q&A behavior. As the user types at least two
characters, the frontend shows up to six best-effort Yahoo fund-name
suggestions, matching the fund-only filter. The up and down arrow
keys navigate the selection; the user must choose a suggestion before analysis
when matches are available. If no suggestions are available, analysis can use
the typed name. The user can see live stage progress and failure state, and view
the report when generation succeeds. A successful run automatically
initializes its chat from that run's
  `fund_profile.json` and `news.json`; the displayed report is excluded from
  chat context. The user does not select a run directory. The chat preserves
FR7's multi-turn history, evidence retrieval, source numbering, citations,
supporting passages, conditional web fallback, and refusal behavior.

The user can search and browse the collected articles for the active run,
including articles not cited in the report. Article search operates on the
saved `news.json` corpus (title, source, date, summary, and stored article text)
and does not make new Exa or Yahoo calls or modify the corpus. Chat retrieval
remains over the full run corpus, independent of the article list's current
search/filter state. Chat may use the FR7 web fallback after run evidence proves
insufficient; those transient results do not enter the article list or saved
corpus. A failed or incomplete report run does not start a chat.

The chat window provides a **Reset Chat** action. Resetting clears the visible
conversation and the server-side conversation history used for follow-up
questions and web searches. It retains the analyst system instructions and the
active run's fund profile context; the full saved news corpus remains available
for retrieval. The displayed report is not part of the conversation context.
Reset does not delete run artifacts, alter the article browser, or start new
research. Fund profile details remain orientation context, not citable
evidence, as specified by FR7.

Run artifacts and progress are stored under `output/`; active run registration
and chat history are in memory, so restarting the web server ends the session
but does not remove completed artifacts. The API binds to `127.0.0.1` by
default; deployment beyond a trusted local machine requires an authenticated
and appropriately secured hosting configuration.

## 11. Non-Functional Requirements

| Category | Requirement | Measurement |
| --- | --- | --- |
| Performance | Typical fund → report in ≤ 5 min wall clock | Timed runs on 3 sample funds |
| Semantic dedupe | ≤ 50 articles embedded and compared in ≤ 60 s on a laptop CPU; no additional paid provider calls | Timed on 3 sample funds |
| Q&A retrieval | Lexical retrieval returns supporting passages for representative factual and exact-number questions | Measure recall and citation support on an annotated query set |
| Q&A latency | Sufficient local evidence uses lexical retrieval and one answer-generation call (plus a rewrite call for follow-ups); only insufficient turns make one Exa search and a second answer-generation call | Timed turns on 3 saved runs |
| Observability | Structured events at every stage boundary | Event presence in `events.jsonl` |
| Security | No secrets in logs, reports, or the repository | Secret scan before each PR |

## 12. Security

- Exa API key (`EXA_API_KEY`) via environment variables; `.env` excluded from
  version control. Ollama Cloud authentication is managed by the Ollama CLI
  session (`ollama signin`), not application environment variables; yfinance
  requires no key.
- Keys are never logged and never embedded in prompts or reports; traffic is
  HTTPS.
- FR3b sends article text only to the configured Ollama embedding model (local
  by default) and adds no third-party data flow. Dedupe events carry counts,
  the threshold, and the model name, never article text.
- Q&A treats article, web, and conversation text as untrusted input. Retrieved
  passages are delimited as evidence, and the prompt instructs the model to
  ignore instructions embedded in those sources. The report is displayed only
  in the browser and is not sent to the model.
- Q&A sends a rewritten query (or a fallback query) derived from the current
  question and recent user questions in its conditional Exa search. It never
  sends the report, profile details, saved articles, prompts, conversation
  answers, or credentials as search-request content. Web results are transient
  and are not written to run artifacts; event records contain no query or
  result text.
- Q&A reads the saved run directory and appends its own events. It calls Ollama
  to answer and calls Exa only after the run's evidence is
  insufficient. It never calls Yahoo or re-runs synthesis.
- The structured event stream is the audit trail.

## 13. Testing Plan

The default test suite covers core transformations and browser API behavior
with provider calls replaced by local fakes.

- **Core and API tests** — FR1 browser input validation and suggestions; FR2 weight normalization and
  profile mapping; FR3 query construction, news mapping, URL deduplication, and
  failure/degrade policy; FR3b embedding-input bounds, threshold grouping,
  representative selection and entity merging, run-order numbering after
  dedupe, and embedding-failure degrade; FR4 prompt building, response/citation validation,
  and one-retry behavior; FR5 report rendering and versioned artifact
  documents; FR8 browser run lifecycle, progress, chat, and reset; FR7 artifact
  loading and source numbering, saved-Markdown lexical retrieval, evidence
  sufficiency and abstention, citation validation (unknown news/web ID,
   uncited answer, cited refusal), refusal path, report-excluded-from-prompt
   behavior, follow-up query rewriting, system/user message separation, and
  untrusted-source delimiting; conditional web search when the retrieved
  evidence is insufficient for a relevant, correct, complete, and faithful
  answer, with mixed citations when web evidence is available.
- **Not in the default suite** — live provider calls. Two optional smoke tests
  call real Exa and Ollama boundaries (`pytest -m smoke`); they are excluded
  from routine runs.
- **Performance** — timed runs on the 3 sample funds, including the dedupe
  stage; timed Q&A turns on 3 saved runs; investigate anything above the
  5-minute report budget.
- **Security** — secret scanning; artifacts contain no keys.

## 14. Running the Project

The browser app is the user workflow. For local development, commands are
documented in the README:

| Command | Purpose |
| --- | --- |
| `pip install -e .` | Install into a virtual environment |
| `python -m src.web` | Start the local browser API |
| `npm install` | Install browser frontend dependencies from the project root |
| `npm run dev` | Start the browser frontend |
| `npm run build` | Build static assets served by the local API |
| `pytest` | Core-logic transformation tests (offline) |

Search caps and the total-failure degrade behavior are configuration.

## 15. Observability

- **Events**: `run_started`, `stage_completed`, `external_call` (provider,
  latency, status), `token_usage`, `report_written`, `run_failed` (stage,
  error code).
- **Dedupe events**: `stage_completed` `news_dedup` records `candidates`,
  `embedded`, `duplicate_pairs`, `groups`, `kept`, `dropped`, `threshold`,
  `model`, and `degraded`; one `external_call` (`provider` `ollama.embed`) per
  embedding request records latency and status. No article text is recorded.
- **Q&A retrieval events**: record lexical candidate counts. Events do not
  record article text, query text, or URLs.
- **Q&A events**: `qa_started`, `qa_answered` (citations, evidence counts,
  latency), `qa_failed`; appended to the run's `events.jsonl`. Names and fields
  are documented in the events contract.
- **Fields**: `run_id`, stage, timestamp on every event; `fund` on
  `run_started`; request IDs on external calls when the provider supplies one.
- Events and run status are the instrumentation signals. Any future alerting
  can build on the event stream.

## 16. Open Questions

1. **yfinance fragility** — Yahoo rate limits and scraping fragility; fallback
   fund-data source if it breaks.
2. **Provider operations** — Ollama Cloud and Exa availability, rate limits,
   and a per-run cost budget.
3. **Q&A transcript persistence** — history is currently in memory only; decide
   whether a future release should persist it as a run artifact.
4. **Q&A quality** — evaluate lexical retrieval recall, answer correctness,
   citation support, and refusal accuracy on a
   representative set of saved runs.
5. **Claim support checks** — source excerpts are shown to users; consider
   whether automated entailment checks add value.
6. **Dedupe threshold** — 0.9 is the starting point; calibrate on saved runs
   and consider a cheap lexical confirmation (title/content overlap) for
   borderline pairs. A lower threshold removes more repetition but risks
   merging distinct developments about the same company.

## 17. Definition of Done

A work item is done when it is:

1. **Running** — a user can start an analysis in the browser, get the report,
   and ask follow-up questions in the run-scoped chat.
2. **Instrumented** — its effect is visible in `events.jsonl`.
3. **Verified** — relevant core transformation tests pass locally.
4. **Revertible** — the previous version can be restored cleanly.
