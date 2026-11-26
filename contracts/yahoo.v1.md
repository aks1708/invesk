# Contract: Yahoo Finance boundary — contract version 1

Producer: the `src.extraction.extraction` module (FR2). Consumers: downstream pipeline
stages — news search (FR3) and synthesis (FR4) — via the `FundProfile` entity.
Library: `yfinance==1.8.0`, pinned in `pyproject.toml`; library calls only,
no REST code and no API key (PRD §9).

## Lookup: fund name → ticker

| Step | Call | Notes |
| --- | --- | --- |
| 1 | `yfinance.Search(fund, max_results=5).quotes` | List of quote dicts. Empty list ⇒ not found. |
| 2 | Filter | First quote whose `quoteType` is `ETF` or `MUTUALFUND` **and** that has a non-empty `symbol`. Other quote types are skipped. Exception: when the requested name explicitly says ETF, a matching `EQUITY` quote may be tried only as a fallback after `funds_data` reports `No Fund data found`; its `Ticker.info.quoteType` must verify as `ETF` before use. |
| 3 | No match | `FundNotFoundError` → `run_failed` `fund_not_found`. |

Quote fields used: `symbol`, `longname`, `quoteType`; the guarded fallback also checks matching name tokens and `Ticker.info.quoteType`.

## Fetch: ticker → fund data

| Call | Yields | Used for |
| --- | --- | --- |
| `yfinance.Ticker(symbol).info` | Overview metrics dict | `overview` (curated: `totalAssets`, `expenseRatio`, `yield`, `navPrice`, `currency`, `ytdReturn`, `threeYearAverageReturn`, `fiveYearAverageReturn`, `trailingThreeMonthReturns`, `dividendRate`, `dividendYield`, `beta3Year`, `morningStarOverallRating`, `morningStarRiskRating`, `inception` — converted from `fundInceptionDate` epoch seconds), plus `longName`, `fundFamily` |
| `…funds_data.top_holdings` | DataFrame indexed by symbol, columns `Name`, `Holding Percent` (fractions, top 10) | `holdings` |
| `…funds_data.sector_weightings` | Dict of snake_case sector key → fraction | `sector_weights` |
| `…funds_data.fund_operations` | DataFrame indexed by attribute (`Annual Report Expense Ratio`, `Annual Holdings Turnover`, `Total Net Assets`), one column per symbol plus a category average | `overview` fallbacks: `expenseRatio`, `annualHoldingsTurnover` (never overrides `info`; `Total Net Assets` is never read — its units are unverifiable) |
| `…funds_data.fund_overview` | Dict of `categoryName`, `family`, `legalType` | `overview.category`; `family` fallback when `info.fundFamily` is absent (it is, for most funds) |

If Yahoo search returns a stale mutual-fund share class with no fund data,
the adapter can retry a matching ETF result that Yahoo mislabeled `EQUITY`;
the quote's `info.quoteType` must confirm it is an ETF. Other exceptions from
these calls (HTTPError, timeout, parse failure) become `ExtractionError` →
`run_failed` `yahoo_unavailable`.

## Boundary adapter normalization (Yahoo formats → FundProfile)

| Yahoo value | FundProfile value |
| --- | --- |
| Weight as fraction (`0.013818`) or percent (`"1.38%"`, `1.38`) | Percent value in `[0, 100]` (bare numbers ≤ 1 read as fractions × 100; `> 100` unusable); unusable values dropped and a gap recorded |
| Overview ratios — `expenseRatio`, `yield`, `threeYearAverageReturn`, `fiveYearAverageReturn` — as fractions | Percent values (0.2146 → 21.46) |
| Overview ratio `ytdReturn` as a percent (`11.73` = 11.73%) | Passes through (already a percent value) |
| Overview ratios `trailingThreeMonthReturns` and `dividendYield` as percents (1.07 = 1.07%) | Pass through (already percent values) |
| Overview ratios — `annualHoldingsTurnover` (from fund_operations) — as fractions | Percent values (0.02 → 2.0) |
| Overview field `beta3Year` as a plain ratio (0.97), Morningstar ratings as 1–5 integers | Pass through untouched — never multiplied by 100. Yahoo's fund UI labels `beta3Year` as `Beta (5Y monthly)`; use that reader-facing label rather than inferring the period from the API key. |
| Overview amounts — `totalAssets`, `navPrice`, `dividendRate` | Raw numbers in the fund's currency |
| Epoch `fundInceptionDate` (seconds) | ISO date string (`2010-09-07`) |
| `fund_overview.categoryName` | `overview.category` (readable Morningstar category) |
| `fund_overview.family` | `family` fallback when `info.fundFamily` is absent |
| Sector key `consumer_cyclical` | Label `Consumer Cyclical` (`realestate` → `Real Estate`) |
| Missing overview metric | Omitted from `overview`; an all-missing `info` ⇒ `overview metrics not available` gap |
| Missing holdings / sectors | Explicit entry in `gaps` — never silently empty, never invented |

Unit rule (verified against yfinance 1.8.0 payloads for ETFs and mutual
funds, 2026-11-12; new performance fields re-verified live 2026-11-13
against VOO, VFIAX, and 0P0000K0QF): **every percent-denominated value in a
FundProfile is a percent value — 10 means 10%, never 0.1.** `beta3Year`,
the Morningstar ratings, and amounts stay numeric; rendering them (2.15
billion, 3-year beta 0.97) is the FR4/FR5 presentation concern
(`src/core/formatting.py`). Re-verify the field units if the boundary changes.
Yahoo populates the performance fields unevenly per fund — missing
fields are omitted, never defaulted (see the normalization table).

## FundProfile entity

The serialized `fund_profile.json` artifact uses schema version 3 (see
[`artifacts.v1.md`](./artifacts.v1.md)). The current `FundProfile` includes
`overview` performance fields:
the fund-performance metrics — `trailingThreeMonthReturns`,
`annualHoldingsTurnover`, `dividendRate`, `dividendYield`, `beta3Year`,
`morningStarOverallRating`, `morningStarRiskRating`, `inception`, and
`category` — and `family` gains the `fund_overview.family` fallback. All
new fields are optional; only what Yahoo returned appears.

| Field | Type | Notes |
| --- | --- | --- |
| `fund` | string | The name the user requested |
| `ticker` | string | Resolved Yahoo symbol, e.g. `VMID.L` |
| `name` | string | Resolved name: `info.longName` → quote `longname` → requested `fund` |
| `provider` | string | `yahoo` |
| `family` | string \| null | `info.fundFamily` → `fund_overview.family` → null |
| `currency` | string \| null | From `info.currency` |
| `holdings` | `[{name: string, symbol: string, weight: number}]` | Top 10 by weight, weight a percent value in `[0, 100]` |
| `sector_weights` | `{label: number}` | Readable labels, percent values |
| `overview` | `{field: number\|string}` | Curated metrics that Yahoo returned; ratio fields are percent values, `beta3Year`/Morningstar ratings unitless, amounts raw, `inception` an ISO date, `category` a readable label |
| `gaps` | `[string]` | Human-readable, safe to print in the report |

Serialization to `fund_profile.json` is an FR5 artifact concern; FR2 passes the
entity in-process only.

## Instrumentation

Every Yahoo call emits one `external_call` event (`contracts/events.v1.md`):
`provider` (`yahoo.search` | `yahoo.quote_summary`), `latency_ms`, `status`
(`ok` | `error`). Library calls return no request id, so `request_id` is
omitted. A successful search that finds no fund is still `status=ok`; the
`fund_not_found` failure is recorded by the run's `run_failed` event.

## Rate limits / fragility

One run normally makes 2 Yahoo lookups (search + quote summary); the guarded
stale-share-class fallback may query quote summary for a second symbol. No
rate limiting is configured in v1. Yahoo rate limits and scraping fragility
remain operational risks (PRD §16); restore the previous working version if
the boundary breaks.
