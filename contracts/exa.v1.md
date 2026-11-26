# Contract: Exa boundary — contract version 1

Producer: the `src.search.search` module (FR3). Consumer: downstream pipeline
stages — synthesis (FR4) — via the `NewsItem` entity. Boundary: the `exa-py`
SDK (2.28.0, pinned in `pyproject.toml`) calling `Exa.search()`, which wraps
REST `POST https://api.exa.ai/search` (Exa Public API spec 2.0.0, verified
against https://exa.ai/docs/exa-spec.yaml on 2026-11-12; swapped from stdlib
`urllib` to the SDK on 2026-11-12. The Exa contract version is independent of
the `NewsItem` artifact schema version (currently 2).

## Auth

`x-api-key: <EXA_API_KEY>` header, sent by the SDK. The key comes from the
`EXA_API_KEY` environment variable (read at the composition root) and is passed
to `Exa(api_key, timeout=30.0)` — the client factory lives in
`src.search.search`. The key is never logged, never written to events or
artifacts, and never embedded in prompts.

## Request

One SDK call per query — `exa.search(query, **options)`:

| Argument | Type | Sent as |
| --- | --- | --- |
| `query` | string (required, positional) | Holding: `"{name} company news"`. Sector: `"{label} sector outlook"` (FR4's sector-insights input: where the sector is heading) |
| `num_results` | int 1–100 | `results_per_search` config (default 5) → wire `numResults` |
| `type` | `"auto"` | Exa's balanced default |
| `category` | `"news"` | Focus news; supports the published-date window (only `company`/`people` do not) |
| `start_published_date` | ISO 8601 date-time | `now - window_days`, e.g. `2026-08-14T12:00:00.000Z` → wire `startPublishedDate` |
| `end_published_date` | ISO 8601 date-time | `now` → wire `endPublishedDate` |
| `contents` | `{"summary": {"query": "Key facts, figures, and dates"}, "text": {"maxCharacters": null, "verbosity": "compact", "includeHtmlTags": false}}` | Request both the per-result summary (query-biased) and the page text (full article, markdown-style, no HTML tags; verbosity=compact excludes navigation/footers) for the FR4 digest |

The SDK converts the snake_case options to the camelCase wire fields shown
above. The client is constructed with `timeout=30.0` (the previous `urllib`
read timeout).

## Response 200

The SDK returns a `SearchResponse` whose `results` are `Result` objects:

| Field | Used for |
| --- | --- |
| `result.title`, `result.url` | News items (adapter table below) |
| `result.published_date` | ISO 8601, may be `None` |
| `result.summary` | Present when requested (FR4 digest) |
| `result.text` | Present when requested — the page text (full article, markdown-style, no HTML tags; verbosity=compact, maxCharacters=null per search options); FR4 digest |
| `result.author`, `result.id`, `result.score` | Unused in v1 |

`requestId`: the SDK does **not** surface it on a 200 response, so successful
`external_call` events carry no `request_id` (the `x-request-id` header
fallback is gone with `urllib`). `costDollars`, `searchTime`, `warnings`,
`notices`, `resolvedSearchType` are ignored in v1.

## Errors

The SDK raises unstructured errors: `ValueError("Request failed with status
code <N>: <body>")` for any HTTP failure (the body carries the
`{requestId, error, tag}` envelope), `"Expected a JSON response ... (status
<N>)"` for a 2xx with a non-JSON body, and `ExaTimeoutError`/`requests`
exceptions for timeouts and network failures. HTTP statuses are the familiar
ones: 400 invalid request, 401 auth, 402 credits exhausted, 403 forbidden,
429 rate limit (honor `Retry-After`), 500/503 provider failure.

`src.search.search.exa_error_details` parses the status and `requestId` out of
that message — best effort, both may be absent.

v1 does **not** retry: a failed search is logged (`external_call` `status=error`)
and skipped (FR3).

## Rate limits

`/search` allows **10 queries per second** per team (Free and pay-as-you-go
tiers; 5 QPS for `deep` types, which invesk does not use). Default
`max_parallel=4` workers keep ≤ 10 searches well under that limit. Exceeding it
returns 429, which v1 logs and skips.

## Config caps (FR3)

| Setting | Env var | Default | Meaning |
| --- | --- | --- | --- |
| `max_searches` | `EXA_MAX_SEARCHES` | 10 | Total queries per run (FR3 cap) |
| `results_per_search` | `EXA_RESULTS_PER_SEARCH` | 5 | `numResults` per query |
| `window_days` | `EXA_WINDOW_DAYS` | 90 | Published-date window |
| `max_parallel` | `EXA_MAX_PARALLEL` | 4 | Worker threads (QPS guard) |
| `degrade_on_total_failure` | `EXA_DEGRADE_ON_FAILURE` | true | Total search failure → fund-data-only run (`degraded` event) instead of aborting |

Invalid values are rejected before any provider search. A browser run fails
with a configuration error recorded in its event stream.

## Query fan-out (FR3)

1. One query per top-5 holding, ordered by weight descending (ties keep Yahoo
   order), skipping holdings with empty names — at most
   `MAX_HOLDING_QUERIES` (5) holdings.
2. Then one query per top-5 sector ordered by weight descending — at most
   `MAX_SECTOR_QUERIES` (5) sectors — until `max_searches` is reached.
   The FR3 focus is the top 5 companies and the top 5 sectors: 10 queries
   at the default cap.
3. Queries deduplicate by their text.

## Boundary adapter normalization (Exa → NewsItem)

| Exa value | NewsItem value |
| --- | --- |
| `result.title` | `title`; results with an empty/missing title are dropped |
| `result.url` | `url` (trimmed); results without an `http(s)` URL are dropped |
| `result.url` hostname | `source` (publication), e.g. `reuters.com` |
| `result.published_date` | `published` (ISO 8601 string, passed through; `None` when absent) |
| `result.summary` | `summary` (`None` when absent) |
| `result.text` | `content` (`None` when absent or blank; full Markdown text stored as returned, without truncation or formatting changes) |
| position in `results` | `relevance` — 1-based rank within its originating query (spec 2.0.0 returns no per-result score) |
| — | `related` — the single holding/sector label targeted by this query; URL deduplication may merge labels from multiple queries |

Deduplication across queries: by exact trimmed URL, first-seen article fields
win (query importance order, then rank); `related` unions the targeted entities
from every matching result. Counted drops are not errors.

## NewsItem entity (schema_version 2)

Schema 2 note (changed from 1): `content` is added — the result's page
text, requested (full article, markdown-style, no HTML tags) alongside the summary.

| Field | Type | Notes |
|---|---|---|
| `title` | string | Non-empty; citation headline |
| `url` | string | `http(s)`, unique after dedupe |
| `source` | string | Publication hostname |
| `published` | string \| null | ISO 8601 date-time from Exa |
| `summary` | string \| null | Exa-generated summary |
| `content` | string \| null | The result's page text (full article, markdown-style, no HTML tags) |
| `relevance` | int | 1-based rank within its query |
| `related` | `[string]` | Entities the query targeted |

Serialization to `news.json` is an FR5 artifact concern; FR3 passes the entity
in-process only.

## Instrumentation

Each search emits one `external_call` event (`contracts/events.v1.md`):
`provider` `exa.search`, `entity` (the targeted holding/sector label),
`latency_ms`, `status` (`ok`|`error`); on error, `http_status` (int) and
`request_id` when they could be parsed from the SDK error message — a
successful search carries neither, since the SDK does not surface a request
id. The stage then emits `stage_completed` `news_search` with `searches`,
`ok`, `failed`, `results`, `news`, `degraded`.

## Rate/fragility notes

One run makes ≤ `max_searches` Exa calls after a successful extraction. If the
boundary breaks, restore the previous working version; caps and degrade mode
are configuration.
