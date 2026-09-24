# Text-list classification — independent plugin example

An opt-in Python plugin that gives the agent a `classify_texts` tool: label a
list of short texts with one of the categories supplied in the call. The
backend is chosen by the deployment: **Jev** (TypeSafe System One, one typed
`choice` question per item) or an **OpenAI-compatible chat endpoint** (one JSON
label list per batch). It uses extension API 0.2.2 and the full-stack plugin
catalog, with no host code changes and no browser code. The measurements behind
the design are in [RFC #5653](https://github.com/bytedance/deer-flow/issues/5653).

## Install and configure

From `backend/` in a compatible DeerFlow deployment:

```sh
uv run deerflow extensions install ../examples/deerflow-extension-jev-classify --yes
export TYPESAFE_API_KEY='your-deployment-secret'
```

Set the registered entry in the deployment configuration:

```yaml
plugins:
  - use: deerflow_extension_jev_classify:install
    enabled: true
    config:
      enabled: true
      backend: jev
```

For a chat-model backend instead:

```yaml
plugins:
  - use: deerflow_extension_jev_classify:install
    enabled: true
    config:
      enabled: true
      backend: llm
      llm_url: https://api.deepseek.com/chat/completions
      llm_model: deepseek-flash
```

and export `CLASSIFY_LLM_API_KEY` (or the name set in `llm_api_key_env`).

Provide the environment variable to the actual Gateway process (including its
container, if applicable). Restart Gateway after installing or changing deployment
configuration; refresh Capability Center to see **Text classification**. The outer
switch loads the package; `config.enabled` enables the tool and catalog entry.
It is disabled by default. The plugin catalog is read-only; there is no online
key editor and no browser page. The authenticated `status` backend action reports
enabled/backend/configured/limits without exposing credentials.

**Deployment opt-in sends the item texts, the category names and descriptions,
and the instruction to the configured backend** (`https://api.typesafe.ai/v1/systemone`
for Jev, or the configured `llm_url`). This is a separate API from the main chat
model; a free main model does not make the classifier free. Keys are read only
from the named environment variables, never from plugin settings or messages.

## How the agent uses it

The tool takes a text list, not a file. For a CSV, the agent reads the file with
its normal file tool, sends the rows as items with the row number as `id`, and
writes the returned labels back itself:

```json
{
  "items": [{"id": "2", "text": "My card was charged twice"}, {"id": "3", "text": "The webhook returns 500"}],
  "categories": [{"name": "billing", "description": "Payments, invoices and refunds."}, {"name": "technical", "description": "Product bugs and integration failures."}],
  "instruction": "When a text mentions both, prefer the customer's main request."
}
```

The result lists one entry per item, in input order:

```json
{"backend": "jev", "model": "jev-1.13.0", "results": [{"id": "2", "label": "billing", "status": "ok", "error": ""}, {"id": "3", "label": "technical", "status": "ok", "error": ""}], "counts": {"ok": 2}, "requests": 1}
```

`status` is `ok`, `empty_text`, `too_long`, `error` or `not_processed`; `error`
carries a code such as `http_401`, `timeout`, `network`, `invalid_response`,
`internal`, `stopped` (after an authentication or rate-limit failure) or
`deadline`. A request the plugin cannot serve at all returns
`{"error": {"code": ..., "message": ...}}` with `backend_not_configured`,
`invalid_items`, `invalid_categories` or `too_many_items`.

## Behavior and limits

- Items are grouped up to `batch_size` per request (default 10) and each
  request is kept under 256 KiB, so large category descriptions or long texts
  simply produce more requests. Outbound sizes use httpx's compact UTF-8 JSON,
  including the extra escaping of JSON embedded in chat messages.
  Requests run with bounded concurrency (default 4). Caller ids are reconciled
  by position; they never become wire ids,
  question keys or prompt text.
- Jev sends one `choice` question per item over the shared batch state, so the
  classifier sees the batch context, and each item's answer is checked on its
  own: a missing, mistyped or out-of-set answer fails only that item. The chat
  backend asks for a JSON object `{"labels": [{"id", "label"}]}` with
  `response_format: json_object` and temperature 0 (the endpoint must accept
  both), then validates the id set and every label in code; a bad list fails
  its batch. A label that differs from a category name only by case or
  surrounding whitespace is mapped to the name when that mapping is unambiguous.
- At most `max_items` per call (default 200, hard limit 300), 2 to 32 categories,
  texts up to `max_text_chars` (default 2000). Ids and category names are at
  most 64 bytes in both UTF-8 and JSON-encoded output, so 300 results fit the
  host's 64 KiB output bound. Blank and over-long texts are reported, not sent.
  The host measures the call input as JSON with non-ASCII escaped and rejects
  more than 256 KiB before
  the plugin runs, which is roughly 200,000 ASCII or 40,000 CJK characters per
  call; the tool description tells the agent to split longer lists.
- The whole call is bounded by `deadline_seconds` (default 25, under the host's
  30-second tool limit). Every batch runs under an asyncio timeout equal to the
  smaller of `timeout_seconds` and the remaining budget, so a slow or trickling
  upstream cannot push the call past the deadline; batches that would start
  with under half a second left are `not_processed`.
- There are no automatic retries and no payload logs. Cancellation propagates
  and closes the client. An HTTP 401, 402, 403 or 429 stops further batches.
  A plugin bug fails its batch with `internal` and a type-name-only log line,
  never the whole call.
- Item text is data: the default instruction says so, and nothing from the
  items or responses is copied into error messages. The only backend-supplied
  text in a result is the served model name, kept to a short identifier.

Optional deployment fields (all validated; unknown fields rejected):

| Field | Default | Meaning |
| --- | --- | --- |
| `backend` | `jev` | `jev` or `llm` |
| `batch_size` | `10` | Items per request, 1–20 |
| `concurrency` | `4` | Concurrent requests, 1–8 |
| `max_items` | `200` | Items per tool call, at most 300 |
| `max_text_chars` | `2000` | Longer texts are reported as `too_long` |
| `timeout_seconds` | `10` | Per-batch bound and per-phase socket timeout, at most 25 |
| `deadline_seconds` | `25` | Whole-call budget, at most 28 |
| `instruction` | built-in | Default instruction prepended to any caller instruction |
| `jev_model` | `jev-latest` | Pin a version when controlled revisions are required |
| `jev_base_url` | `https://api.typesafe.ai` | HTTPS, or HTTP on localhost only; no query, fragment or credentials |
| `jev_api_key_env` | `TYPESAFE_API_KEY` | Environment variable name, never the key itself |
| `llm_url` | none | Full chat-completions URL (same rules as above); required for `backend: llm` |
| `llm_model` | none | Model name for `backend: llm` |
| `llm_api_key_env` | `CLASSIFY_LLM_API_KEY` | Environment variable name, never the key itself |

The chat backend holds its own key because the extension API has no host model
capability yet. Once the host model invocation proposed in
[#5679](https://github.com/bytedance/deer-flow/issues/5679) exists, that backend
is the place to switch to it; the Jev backend stays plugin-owned by design.

## Verify

From `backend/`:

```sh
uv run pytest tests/test_jev_classify_extension.py
```

Coverage includes registration and the disabled state, the Jev request shape and
label mapping, batching, size-based packing, bounded concurrency, per-item and
per-batch failures, label canonicalisation, HTTP, authentication and rate-limit
failures, transport timeouts, the enforced call deadline, cancellation, a backend
bug, the chat backend's output contract and prompt escaping, missing credentials,
invalid requests, the output bound at the largest allowed call, served model
names, real tool-node dispatch, the status action and rejected configuration.

An opt-in smoke test classifies 20 synthetic English and Chinese sentences plus a
blank and an over-long item through the real plugin path against the configured
backend. It costs money, prints labels and statuses only, and never prints the key:

```sh
export TYPESAFE_API_KEY='your-deployment-secret'
uv run python ../examples/deerflow-extension-jev-classify/scripts/verify_live.py
```

Add `--backend llm --llm-url ... --llm-model ... --api-key-env NAME` for a chat
endpoint. A label that differs from the obvious one is printed with the expected
value; that is a prompt to look, not a test failure.
