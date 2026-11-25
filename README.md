# Invesk

**Understand a fund before you invest in it.**

Invesk is a local browser research tool that turns a fund name into a readable
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
4. Shows the report and a run-scoped chat together in the browser, and lets you
   search all articles collected for that run.
5. Grounds follow-up questions in the run's saved news first, with a web-search
   fallback when those sources are insufficient.

Fund-level metrics come directly from fund data; the AI writes only the news
insights. Invesk does not predict share prices.

## Get started

You’ll need **Python 3.11 or newer**, **Node.js 18 or newer** to build and run
the browser frontend in development, an [**Exa API key**](https://exa.ai/),
and the [**Ollama CLI**](https://ollama.com/download) to sign in to Ollama
Cloud. Invesk itself is used through the browser.

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
Finance for fund data, Exa for report news search and optional Q&A web search,
and Ollama Cloud's `gemma4:cloud` model for insights and answers. Completed
reports and their supporting artifacts are saved under `output/`.

## Run Invesk in your browser

The browser app generates a report and opens a run-scoped chat automatically.
It also lets you search and read all articles collected for that run; searching
the article list does not make new web requests.
As you type at least two characters in the fund field, Yahoo fund suggestions
appear. Use the up and down arrow keys to choose a suggestion, or click one;
**Analyze fund** is enabled after you choose a match. If no suggestions are
available, you can analyze the fund name you typed.

Install the frontend dependencies from the project root:

```bash
npm install
```

For local development, start the API and frontend in separate terminals from
the project directory:

```bash
INVESK_WEB_PORT=8001 .venv/bin/python -m src.web
```

```bash
VITE_API_TARGET=http://127.0.0.1:8001 npm run dev
```

Open <http://127.0.0.1:5173>. The API is available on localhost port 8001
by default; set `INVESK_WEB_PORT` and `VITE_API_TARGET` together to use a
different port. Report generation requires `EXA_API_KEY` and an Ollama Cloud
sign-in. Chat requires Ollama sign-in; `EXA_API_KEY` enables its optional web
fallback. To build the browser app, run `npm run build` from the project root.
Then start `.venv/bin/python -m src.web` and open <http://127.0.0.1:8001>;
the API serves the built frontend from `frontend/dist/`.

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

The external boundaries and saved run formats are documented in the contracts
below. A contract document's version is separate from payload schema versions;
for example, the Q&A contract is v2, the browser API contract is v3, and the
event contract is v2.

- [Yahoo Finance fund data](contracts/yahoo.v1.md)
- [Exa news search](contracts/exa.v1.md)
- [Ollama / Gemma synthesis](contracts/ollama.v1.md)
- [Q&A over a saved run](contracts/qa.v1.md)
- [Local browser API](contracts/web.v1.md)
- [Run artifacts](contracts/artifacts.v1.md)
- [`events.jsonl`](contracts/events.v1.md)

The filename suffix reflects the original contract file name; the current
document version is stated in each contract heading. Payload schema versions
(for example, `FundProfile` and saved JSON files) are tracked independently.
