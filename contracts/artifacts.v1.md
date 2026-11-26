# Contract: run artifacts — contract version 1

The payload `schema_version` values below describe the current artifact formats
and are independent of this document's contract version.

Producer: the `src.reporting.report` module. Consumers: anything reading a run's
`output/<fund-slug>/<run_id>/` directory (PRD §9). `events.jsonl` is covered
by [`events.v1.md`](./events.v1.md).

## Encoding

UTF-8. JSON artifacts are one JSON object with LF endings, written with
`indent=2` and `ensure_ascii=False`. The files are written in sequence:
`fund_profile.json`, `news.json`, then `report.md`. A write failure aborts the
run with exit `1`; the sequence is not an atomic transaction.

## `report.md`

Plain human-readable Markdown, returned by the browser API and rendered by the
frontend:

- `# <fund name> (Currency: <currency>)` title, followed by generated-at
  (UTC, formatted `DD-MM-YYYY HH:MM`) as plain text.
- `## Financial health` — metric values assembled directly from
  `FundProfile` (not LLM analysis).
- `## Company insights` and `## Sector insights` — the validated FR4
  `ReportSections` verbatim, written in simple language for a general reader.
- `## Data gaps` — one bullet per `FundProfile.gaps` entry; the section is
  omitted when there are none.
- `## Sources` — one numbered entry per cited `NewsItem`, with the number
  retaining its position in the complete `news.json` array. Entries use
  `[title](url)`; when the news list is empty, the report says
  "None found in this run." Uncited items remain in `news.json` only.

## `fund_profile.json`

One object: `schema_version` (int `3`), `fund`, `ticker`, `name`, `provider`,
`family`/`currency` (string or null), `holdings` (array of `{name, symbol,
weight}`, weight a formatted percent string, e.g. `"1.38%"`),
`sector_weights` (object of formatted percent strings, e.g.
`{"industrials": "20.55%"}`), `overview` (object of formatted strings —
ratio fields as percents (`"11.84%"`), amounts as magnitude words
(`"2.15 billion"`), anything else as text), `gaps` (array of strings).

Percent values are percent values (10 = 10%, never a fraction). Numbers are
presentation strings built by `src/core/formatting.py` — two decimals, trailing
zeros stripped, magnitude words above a thousand — so the artifact reads like
the report. Overview performance fields include `trailingThreeMonthReturns`,
`dividendYield`, `annualHoldingsTurnover`, `dividendRate`, `beta3Year`, the
Morningstar ratings, `inception`, and `category`. All are optional; only values
returned by Yahoo appear.

## `news.json`

One object: `schema_version` (int `2`), `news` (array of `{title, url,
source, published` (string or null)`, summary` (string or null)`, content`
(string or null, the result's full Markdown page text, stored as returned without
truncation or formatting changes)`,
relevance` (int)`, related` (array of strings)`}`) — the deduplicated
`NewsItem[]`, in run order.
