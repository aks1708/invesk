# Contract: local browser API — contract version 3

Producer: `src.web.app`. Consumer: the React frontend in `frontend/`. This is an
HTTP boundary over the existing report pipeline and Q&A logic. Q&A may use the
conditional Exa web fallback defined by the Q&A contract.

The API binds to `127.0.0.1:8001` by default and is intended for a trusted local
machine. It has no authentication; do not expose it on a network-facing
interface without adding authentication and deployment security.

## Endpoints

### `GET /api/health`

Returns `{"status":"ok"}` when the API is available.

### `GET /api/suggestions?query={prefix}`

Returns Yahoo Finance fund-name suggestions using the fund-only quote filter
and Yahoo's relevance order:

```json
{"suggestions":["Vanguard S&P 500 ETF","Vanguard Total Stock Market ETF"]}
```

Queries shorter than two characters return an empty array without contacting
Yahoo. At most six names are returned. Suggestions are best-effort; Yahoo,
network, or yfinance failures return HTTP `200` with `{"suggestions":[]}` and
do not block free-text fund entry.

### `POST /api/runs`

Start report generation in a background worker.

Request:

```json
{"fund":"Vanguard S&P 500 ETF"}
```

`fund` is trimmed and must contain 1–200 characters. A successful request
returns HTTP `202`:

```json
{"id":"<run_id>","fund":"Vanguard S&P 500 ETF","status":"queued"}
```

The worker validates the existing search configuration and runs the shared
extraction, news search, synthesis, and report-writing pipeline. The
run artifacts and JSONL events are written under
`output/<fund-slug>/<run_id>/`. Provider credentials and exception details are
not returned in API responses.

Invalid JSON or fund input returns HTTP `422`.

### `GET /api/runs/{run_id}`

Returns the run status:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | Run directory basename / event `run_id` |
| `fund` | string | Submitted fund name |
| `status` | string | `queued`, `running`, `succeeded`, or `failed` |
| `stage` | string or null | Current stage: `fund_extraction`, `news_search`, `synthesis`, or `report` |
| `completed_stages` | string[] | Completed pipeline stages in run order |
| `failure` | object or null | Public-safe `{stage, error_code, message}` on failure |

On success the response also includes:

- `report`: the complete, unmodified `report.md` Markdown string, rendered by
  the frontend;
- `profile`: the saved `fund_profile.json` object;
- `articles`: every saved `news.json` item in stored order, with its stable
  1-based `source_number`, `title`, `url`, `source`, `published`, `summary`,
  and `content` fields.

The frontend searches and browses this saved article list locally. Search
results and selected articles do not narrow or mutate the corpus used by Q&A.
Unknown run IDs return HTTP `404`.

### `GET /api/runs/{run_id}/qa-status`

Returns the current Q&A activity for the run, for rendering the chat's
in-progress indicator:

```json
{"status":"thinking"}
```

`status` is `"thinking"`, `"searching_web"`, or `null` when no question is being
answered. Unknown run IDs return HTTP `404`.

### `POST /api/runs/{run_id}/questions`

Ask a follow-up question about a successfully completed run.

Request:

```json
{"question":"What could this development mean for the fund?"}
```

`question` is trimmed and must contain 1–2000 characters. The API uses the FR7
retrieval, system/user prompts, Ollama model, conditional Exa fallback,
response validation, citation identifiers, and in-memory recent conversation
history defined by the Q&A contract.

Successful response:

```json
{
  "question":"What could this development mean for the fund?",
  "answer":"… [3, W1]",
  "citations":[3,"W1"],
  "insufficient":false,
  "evidence":[{
    "source_id":"3",
    "source_number":3,
    "kind":"news",
    "title":"…",
    "url":"https://example.test/article",
    "source":"…",
    "published":"2026-11-20",
    "passages":["Exact supporting passage from the saved article."]
  },{
    "source_id":"W1",
    "source_number":null,
    "kind":"web",
    "title":"…",
    "url":"https://example.test/web-result",
    "source":"…",
    "published":"2026-11-24",
    "passages":["Exact supporting passage from the web result."]
  }],
  "web_search_attempted":true
}
```

When neither saved nor web evidence covers a question (or web search is
unavailable), `citations` and `evidence` are empty and `insufficient` is true.
A general-concept explanation may also have empty `citations` and `evidence`
with `insufficient` false, without a special preface. Saved-news citations remain
integer source numbers; transient web citations are `Wn` strings and are never
added to the saved articles. The API appends the
existing Q&A events to that run's
`events.jsonl`. Questions for a run that is not yet complete return HTTP `409`;
invalid question input returns `422`; invalid model output after its corrective
retry returns `422`; an unavailable Ollama provider returns `503`.

### `POST /api/runs/{run_id}/chat/reset`

Reset the active run's browser chat conversation without changing its report,
fund context, saved news corpus, or run artifacts.

No request body is required. A successful reset returns HTTP `200`:

```json
{"reset":true}
```

The endpoint clears the in-memory conversation history used by subsequent
questions and web-search follow-ups. The analyst system instructions and
run-scoped fund profile context continue to be supplied for every question;
the displayed report is not sent to the model. Retrieval continues to use the
complete saved news corpus. It does not remove
the run's Q&A event records. Unknown run IDs return HTTP `404`; runs whose
reports are not complete return HTTP `409`.

## Session and corpus lifecycle

Run artifacts are durable files under `output/`. Active run registration and
chat history are held in memory by the web server and are lost when it stops.
The next server process does not automatically reopen runs from disk.

Q&A reads the complete collected `news.json` corpus and uses the Ollama chat
boundary. Only when Ollama determines that this evidence is insufficient does
it make one Exa web search, if configured. Article search/browsing remains
local and never uses Exa. Web results are transient and are not persisted.
Saved article content is stored full-length (no 10000-char cap at ingest per FR3
search options with max_characters=None); per-article content is available in
its entirety for Q&A and article browser.

## Frontend hosting

During development, Vite serves the frontend and proxies `/api` to port 8001
by default. Set `VITE_API_TARGET` if `INVESK_WEB_PORT` is changed.
When `frontend/dist/` exists, the FastAPI app serves its static files at `/`.
