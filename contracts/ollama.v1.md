# Contract: Ollama boundary — contract version 1

This document's contract version is independent of the current
`ReportSections` entity schema version.

Producer: the `src.synthesis.synthesis` module (FR4). Consumer: downstream pipeline
stages — report assembly (FR5) — via the `ReportSections` entity. Boundary:
the `ollama` Python client connected to the local Ollama server, which uses the
Ollama Cloud session, `client.chat(model=…, messages=…, options=…)`.

All reports use simple language. The model response contains only company and
sector insights; FR5 builds the metric summary directly from `FundProfile`.
`ReportSections` carries only the two LLM-written insight sections; report
rendering consumes those insights and the fund profile separately.

## Model

`gemma4:cloud` — a module constant (`SYNTHESIS_MODEL`), not configuration
(the Google boundary used `gemma-4-31b-it`). Passed as the
`model` argument of every `chat` call.

## Auth

Authenticate Ollama Cloud in the terminal with `ollama signin`. The local
Ollama server uses that signed-in session for `gemma4:cloud`; the application
does not need `OLLAMA_HOST` or `OLLAMA_API_KEY` configuration (PRD §12). No
credentials are logged, written to events or artifacts, or embedded in a prompt.

## Request

One `chat` call per attempt:

| Argument | Value | Notes |
| --- | --- | --- |
| `model` | `SYNTHESIS_MODEL` | `gemma4:cloud` |
| `messages` | `[{"role": "user", "content": <prompt>}]` | FR4 intentionally sends one user prompt containing the insights-only task, simple-language guidance, fund composition context, news, and output schema. This is independent of FR7's Q&A system/user message structure. |
| `options` | `{"temperature": 0}` | Deterministic synthesis; the context window and generation cap stay at the server's defaults. No `format` (Gemma does not reliably support JSON mode), no tools, no thinking config. |

Client options: `Client(timeout=120.0)` — the 120 s of the Google boundary's
`GOOGLE_TIMEOUT_SECONDS`, in seconds. The composition root builds the client
via `synthesis.ollama_client`, whose SDK import is deferred.

## Response (a `ChatResponse`)

| Field | Used for |
| --- | --- |
| `response.message.content` | The assistant text → the JSON sections to parse. A response without a message or text (None) → malformed output, eligible for the corrective retry. |
| `response.prompt_eval_count` | `prompt_tokens` on the `token_usage` event (0 when absent/None) |
| `response.eval_count` | `completion_tokens` on the `token_usage` event (0 when absent/None) |

`done_reason`, `total_duration`, and everything else are ignored. The API
returns no request id, so `external_call` omits `request_id`.

## Errors

The SDK raises `ollama.ResponseError` for failed HTTP calls, carrying the
provider HTTP status as `.status_code` and the provider error message in its
text; connection failures (a plain `ConnectionError`) and response-parse
failures carry no status. The SDK applies no built-in retries to `chat`.

This boundary does **not** retry provider errors (the FR4 corrective retry
is for malformed *output* only): a failed call is logged (`external_call`
`status=error`, `http_status` when the exception carries an int
`.status_code`) and raises `SynthesisError` → `run_failed`
`ollama_unavailable` and marks the report run as failed. A client-construction failure (e.g. the SDK is
not installed) is also `ollama_unavailable`, before any dial-out. Error
messages contain provider text only — never a key or prompt.

## Prompt (built by `build_prompt`, tested as a transformation)

Sections, in order:

1. Role and task: write only company insights and sector insights for the
   named fund; do not write the snapshot or interpret financial metrics.
2. Writing style: use simple, everyday language for a general reader. Use
   short, clear sentences. Briefly explain a useful financial/industry term or
   acronym in plain words at first use, in the same sentence and in a way that
   fits the specific company or sector context; connect the explanation to why
   the development matters. Avoid detached glossary definitions and unnecessary
   jargon; spell out acronyms at first use (PRD FR4).
3. Constraints: English only; every claim traces to fund context or news;
   never guess. Percentages in fund context are shown as percents
   (10%, never 0.1).
4. `Fund data:` block — name, ticker, family, currency, sector weights
   (percent, weight-descending) and top-10 holdings (percent). Overview
   metrics and data gaps are not sent because they are not the LLM's task.
5. `News:` block — the top `MAX_ITEMS_PER_ENTITY` (3) items per entity
   (run order, so the highest-relevance results win; the full searched set
   would make the reply outgrow the model's output window), each tagged
   with its stable citation token (`[S<n>]`) and the entity its query
   targeted (`[about: <entity>]`), split by `partition_news` into two
   sub-blocks: `Company news:` (items whose entity is a holding) and
   `Sector news:` (items whose entity is a sector weight). Each line is
   `[S<n>] [about: entity] title — source (published): summary URL`, followed
   by an indented `Content: <page text>` line when text was retrieved (first
   10000 characters, FR3); the prompt tells the model to draw on it for depth,
   paraphrasing rather than quoting wholesale. When news is empty (FR3 degrade
   mode), the block says so and both insight sections must report it.
6. Output schema: reply with ONLY one JSON object —
   `{"company_insights": ..., "sector_insights": ...}` — no markdown,
   no fences, no commentary; each value a non-empty English paragraph.
    Only these two keys are allowed — never omit a key or leave one empty —
    and the whole reply stays within about 1500 words, with several
     substantive sentences per company or sector. Use simple language and
     weave any necessary plain-language jargon explanation into the insight's
     context and reasoning rather than adding a separate definition.
    - `company_insights` — detailed and informative: news grouped by company;
      connect each material development to its supported business mechanism
      (such as revenue, costs, cash flow, contracts/order book, competition,
      or regulation), then explain why that could matter to an investor in
      this fund. Relate to the holding/weight when useful and available without
      claiming one holding determines fund performance. Separate reported
      facts from evidence-based interpretation, qualify uncertainty, and do
       not predict share-price moves or give buy/sell advice. Explain any
       useful specialist terms naturally at first use, in context; cite factual
       claims and source-grounded reasoning using the
      exact `[S<n>]` token shown beside the relevant item; omit companies
      without news.
    - `sector_insights` — detailed and informative: news grouped by sector;
      connect supported drivers to their effects on companies (for example
      demand, pricing, costs, investment, or regulation), who may benefit or
      face pressure, and what that could mean to an investor in this fund.
      Relate implications to the sector allocation when available without
      assuming all companies are affected equally. Distinguish facts from
      outlook and interpretation, qualify uncertainty, and do not predict
       share-price moves or give buy/sell advice. Explain any useful specialist
       terms naturally at first use, in context, and cite factual claims and
       source-grounded reasoning using the exact
      `[S<n>]` token shown beside the relevant item.
    - For both sections, make the chain explicit: sourced development →
      business/sector effect → why it matters to the fund's investor. Do not
      add implications that are not supported by the supplied news or fund
      context.

### Corrective retry (FR4: malformed output → one retry)

If parsing or validation fails, the second call repeats the same prompt
followed by:

```
Your previous reply was invalid: <reason>

<previous text, truncated to 4000 chars>

Reply again with only the corrected JSON object. Every key in the
output schema is required — do not omit any, and leave none empty.
```

A second malformed response raises `SynthesisError` → `run_failed`
`synthesis_failed` and marks the report run as failed.

## Boundary adapter validation (model text → ReportSections)

Trivially tolerated wrappers (before JSON parsing): a ` ```json … ``` `
code fence is stripped; if the text still does not parse as JSON, the
substring from the first `{` to the last `}` is parsed. Anything else is
malformed.

| Check | Failure |
| --- | --- |
| Text parses to a JSON object | `synthesis_failed` after the retry |
| Both insight keys present, each a non-empty trimmed string | `synthesis_failed` after the retry |
| No fields beyond `company_insights` and `sector_insights` are present | `synthesis_failed` after the retry |
| Every `[S<n>]` token refers to an item included in the prompt; when news was supplied, each section has at least one citation | `synthesis_failed` after the retry |

Accepted source tokens are mapped to the matching 1-based position in the
full deduplicated `NewsItem[]`, so `ReportSections` contains the final report
markers (`[1]`, `[2]`, …). Multiple tokens may be grouped in one bracket pair
(for example `[S2, S5]`); each token is validated and mapped independently.
The validator checks citation references and presence, not whether the cited
article substantively supports each claim.

## ReportSections entity (schema_version 5)

| Field | Type | Notes |
|---|---|---|
| `company_insights` | string | Detailed news-based company insights, in clear language, with supported context, outlook, risks, and source citations |
| `sector_insights` | string | Detailed news-based sector direction, trends, drivers, risks, and outlook in clear language, with source citations |

Serialization is an FR5 artifact concern; FR4 passes the entity in-process
only.

## Instrumentation

Per attempt, one `external_call` event (`contracts/events.v1.md`):
`provider` `ollama.gemma`, `latency_ms`, `status` (`ok`|`error`),
`http_status` on provider errors. One `token_usage` event per successful
call. The stage then emits `stage_completed` `synthesis` with
`news` (item count fed to the prompt), `attempts` (1 or 2), `retried`.

## Fragility

One run makes 1–2 Ollama calls after a successful search stage. A cloud
model needs an authenticated Ollama session (`ollama signin`); otherwise the
call fails and the run aborts (see Errors). If the
boundary breaks, restore the previous working version; there are no
synthesis knobs to reconfigure.
