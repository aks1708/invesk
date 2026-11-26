# Contract: Ollama embeddings boundary — contract version 1

This document's contract version is independent of the `NewsItem` entity
schema version.

Producer: the `src.dedupe` module (FR3b). Consumer: semantic deduplication.
Boundary: the `ollama`
Python client connected to the local Ollama server,
`client.embed(model=…, input=…)`.

## Model

`embeddinggemma-2` by default — a configuration value
(`DEDUPE_EMBED_MODEL`), not a module constant. The model is pulled once with
`ollama pull embeddinggemma-2`. It returns 768-dimension vectors with an
8K-token text context. A different local embedding model may be configured;
the same model must embed every item in a run.

## Auth

No API key. The local Ollama server must be running and the model must be
present locally. The Ollama Cloud session (`ollama signin`) is not used for
embeddings unless the configured model is itself a cloud model.

## Request

One or more batched `embed` calls. Items are sent in candidate order; the
response preserves input order.

| Argument | Value | Notes |
| --- | --- | --- |
| `model` | `DEDUPE_EMBED_MODEL` | `embeddinggemma-2` by default |
| `input` | list of strings | FR3b sends title, optional summary, and bounded content prefix. |
| `truncate` | `True` | The client/server truncates to the model context; the explicit character bound keeps the input deterministic and avoids embedding most of a long article |

Client options: `Client(timeout=120.0)`. The composition root builds the
client; the SDK import is deferred (constitution P3).

## Response (an `EmbedResponse`)

| Field | Used for |
| --- | --- |
| `response.embeddings` | One vector per input, in input order |
| `response.prompt_eval_count` | Optional `token_usage` accounting; ignored for dedupe decisions |

`total_duration`, `load_duration`, and everything else are ignored. The API
returns no request id, so `external_call` omits `request_id`.

Vectors are L2-normalized before comparison, regardless of whether the server
already returned unit-length vectors. Cosine similarity is therefore the dot
product of two vectors.

## Errors

The SDK raises `ollama.ResponseError` for failed HTTP calls, carrying the
provider HTTP status as `.status_code`; connection failures (a plain
`ConnectionError`) and malformed responses carry no status. The SDK applies no
built-in retries to `embed`.

FR3b does **not** retry and does **not** fail report generation on an embedding
failure. It proceeds with URL-deduplicated news. FR4 still requires its
separate synthesis model request.

## Similarity and grouping (FR3b)

1. Drop exact-URL duplicates first (FR3); only survivors are embedded.
2. Embed each survivor (title + summary + bounded content prefix).
3. Normalize vectors and compute all pairwise cosine similarities. At the
   default caps (10 searches × 5 results) there are at most 50 candidates and
   1,225 pairs, so no clustering or ANN index is used.
4. Order candidates by evidence quality: items with page text first, then run
   order (query priority, then Exa rank). Keep an item unless its cosine
   similarity to an already-kept item is at or above
   `DEDUPE_SIMILARITY_THRESHOLD`. This is deterministic and avoids transitive
   chaining.
5. Merge the `related` entities of every dropped item into the kept item.
6. Return the kept items in their original run order.

A pair is a duplicate when `cosine >= DEDUPE_SIMILARITY_THRESHOLD`. The default
is `0.9`; the value is tuned to separate same-story coverage from merely
related coverage, because embeddings capture relatedness as well as sameness.

## Config

| Setting | Env var | Default | Meaning |
| --- | --- | --- | --- |
| `embed_model` | `DEDUPE_EMBED_MODEL` | `embeddinggemma-2` | Local Ollama embedding model |
| `similarity_threshold` | `DEDUPE_SIMILARITY_THRESHOLD` | `0.9` | Cosine threshold in `[0, 1]`; pairs at or above it are duplicates |
| `max_chars` | `DEDUPE_MAX_CHARS` | `4000` | Page-text prefix included in the embedding input |

Invalid values are rejected before any provider call. The threshold and
character bound are configuration, not code (P7).

## Instrumentation

Each embedding request emits one `external_call` event
(`contracts/events.v1.md`): `provider` `ollama.embed`, `latency_ms`, `status`
(`ok`|`error`), and `http_status` on error when the SDK exposes it. The stage
then emits `stage_completed` `news_dedup` with `candidates`, `embedded`,
`duplicate_pairs`, `groups`, `kept`, `dropped`, `threshold`, `model`, and
`degraded`.

`duplicate_pairs` counts every pair at or above the threshold. `groups` counts
the resulting representative groups, including singleton items; on degraded
fallback each candidate is its own group.

Events contain counts, the threshold, and the model name — never article text,
vectors, or URLs.

## Privacy

Article text is sent only to the configured Ollama embedding model. With the
default local model it stays on the machine and adds no third-party data flow.
