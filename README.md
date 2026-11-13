# Invesk

**Understand a fund before you invest in it.**

Invesk is a command-line research tool that turns a fund name into a readable
overview of what it holds and what recent news could mean for its companies and
sectors. Instead of making you research every holding yourself, it gathers fund
data, looks for relevant news, and brings the findings together in one cited
report.

Invesk is an information and research aid—not personalized financial advice or
a buy/sell recommendation. Fund data availability varies by fund, and the
report calls out information it could not retrieve.

## What you get

For a fund you name, Invesk:

1. Retrieves available fund details, top holdings, sector weights, and overview
   metrics from Yahoo Finance.
2. Searches recent news about the largest holdings and sectors.
3. Uses Gemma 4 through Ollama to explain relevant company and sector
   developments in plain language, with numbered citations to sources.
4. Prints the report in your terminal and saves it, along with the supporting
   data, under `output/`.

The fund snapshot and metrics come from fund data; the AI writes only the news
insights. Invesk does not predict share prices.

## Get started

You’ll need **Python 3.11 or newer**, an [**Exa API key**](https://exa.ai/),
and the [**Ollama CLI**](https://ollama.com/download) with access to Ollama
Cloud.

From the project directory, create an environment and install Invesk:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Add your Exa key to a `.env` file in the project directory:

```dotenv
EXA_API_KEY=your_exa_api_key
```

Then sign in to Ollama Cloud in your terminal:

```bash
ollama signin
```

No Yahoo Finance key or local model download is required. Invesk uses Yahoo
Finance for fund data, Exa for news search, and Ollama Cloud's `gemma4:cloud`
model for writing insights.

## Run a report

Pass a fund name with `--fund` (use quotes when it contains spaces):

```bash
.venv/bin/python -m src --fund "Vanguard FTSE 250"
```

The report appears in your terminal and is saved in a new run folder, for
example:

```text
output/vanguard-ftse-250/<run-id>/
├── report.md          # Readable report with citations
├── fund_profile.json  # Retrieved fund details and metrics
├── news.json          # News collected for the report
└── events.jsonl       # Run progress and diagnostics
```

Open `report.md` to read or share the report. If a run fails, check
`events.jsonl` for the stage and error details.

## Configure news search (optional)

By default, Invesk searches the five largest holdings and five largest sectors
(up to 10 searches total), requests up to 5 results per search, and looks back
90 days. You can set these variables in `.env` or in your shell; shell
environment values take precedence over `.env`.

| Variable | Default | What it controls |
| --- | ---: | --- |
| `EXA_MAX_SEARCHES` | `10` | Maximum number of searches per run |
| `EXA_RESULTS_PER_SEARCH` | `5` | Maximum results per search |
| `EXA_WINDOW_DAYS` | `90` | How far back to search for news |
| `EXA_MAX_PARALLEL` | `4` | Number of searches run at once |
| `EXA_DEGRADE_ON_FAILURE` | `true` | Continue with fund data if all news searches fail |

For example, to change the lookback window, add `EXA_WINDOW_DAYS=30` to `.env`.
Keep your API key private; `.env` is excluded from version control.

## Run tests

The default test suite runs offline:

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Optional live smoke tests call Exa and Ollama, so they require a valid Exa key
and an Ollama Cloud sign-in:

```bash
.venv/bin/pytest -m smoke
```

## Contracts

The external boundaries and saved run formats are documented in the current
**v1 contracts**:

- [Yahoo Finance fund data](contracts/yahoo.v1.md)
- [Exa news search](contracts/exa.v1.md)
- [Ollama / Gemma synthesis](contracts/ollama.v1.md)
- [Run artifacts](contracts/artifacts.v1.md)
- [`events.jsonl`](contracts/events.v1.md)

The `v1` here is the contract document version. Schema versions inside the
contracts (for example, the versions of `FundProfile` and saved JSON files) are
tracked independently.
