# Context Compaction (Headroom)

DeerFlow can compress the message history sent to the LLM on every model call —
primarily large **tool outputs, logs, search results, and RAG chunks** — using
the [Headroom](https://github.com/chopratejas/headroom) compression layer. The
goal is the same answers for a fraction of the tokens.

Compaction is **disabled by default** and depends on the optional `headroom-ai`
package. When the package is not installed, the middleware is a transparent
no-op, so enabling the config on a host without Headroom is safe.

## Compaction vs. Summarization

DeerFlow ships two complementary context-reduction features. They solve
different problems and can be enabled together.

| | **Summarization** | **Compaction (Headroom)** |
|---|---|---|
| What it reduces | Conversation *history* (old turns) | Message *content* (large tool outputs) |
| Mechanism | LLM-generated summary replaces old messages | ML/heuristic compression of text in place |
| Touches persisted state? | **Yes** — rewrites `ThreadState.messages` | **No** — only the per-call request copy |
| Reversible? | No (originals are summarized away) | **Yes** (full originals stay in the checkpointer) |
| Extra LLM call? | Yes | No |
| Where it runs | `before_model` | `wrap_model_call` |
| Config key | `summarization` | `compaction` |

A common setup: enable compaction to keep individual tool results small on every
turn, and enable summarization to collapse very long histories once they cross a
token threshold.

## How it works

`HeadroomCompactionMiddleware`
(`packages/harness/deerflow/agents/middlewares/compaction_middleware.py`) runs
inside the model-call boundary:

1. On each model call it takes the request's messages and, if their estimated
   token count exceeds `min_total_tokens`, hands a flat `{role, content}` view to
   Headroom's `compress()`.
2. Any compressed **string** content is mapped back onto the *original* LangChain
   message objects via `model_copy(update={"content": ...})`. Message IDs,
   `tool_calls`, and `additional_kwargs` are preserved exactly, so AI/Tool call
   pairing is never broken.
3. The middleware forwards a new request via `request.override(messages=...)`.
   The persisted `ThreadState` is **not** modified — the full, original messages
   remain in the checkpointer, making compaction fully reversible.
4. If Headroom ever returns a different message count (e.g. a history-dropping
   transform), or if anything raises, the middleware conservatively falls back to
   the original messages. History reduction is left to summarization.

The middleware is wired into both the **lead agent** (after summarization) and
the **subagent runtime**.

## Installation

```bash
# from backend/
uv pip install "deerflow-harness[compaction]"
# or directly
pip install headroom-ai
```

## Configuration

Configured in `config.yaml` under the `compaction` key:

```yaml
compaction:
  enabled: false

  # Model name Headroom uses for token counting / context sizing.
  # null = resolve from the active model at call time (falls back to a default).
  model: null
  model_limit: 200000

  # Only run compaction once the estimated history exceeds this many tokens.
  min_total_tokens: 4000

  # Per-message floor: messages below this estimate are never compressed.
  min_tokens_to_compress: 250

  # Leave the most recent N messages uncompressed (the active conversation).
  protect_recent: 4

  # User/system messages are left byte-exact by default; only tool/assistant
  # content is compressed. Flip these on for document/RAG-style workloads.
  compress_user_messages: false
  compress_system_messages: false

  # Keep-ratio hint for Headroom's text compressor (e.g. 0.5 keeps ~50%).
  # null lets Headroom decide (most aggressive). Named profiles like "agent-90"
  # can be set via savings_profile instead.
  target_ratio: null
  savings_profile: null

  # If true, compaction errors are swallowed and originals are sent unchanged.
  fail_open: true
```

### Field reference

| Field | Default | Description |
|---|---|---|
| `enabled` | `false` | Master switch. No-op if `headroom-ai` is not installed. |
| `model` | `null` | Model name for Headroom's tokenizer. `null` resolves from the active model, falling back to a default. |
| `model_limit` | `200000` | Context window (tokens) Headroom assumes. |
| `min_total_tokens` | `4000` | Skip compaction below this estimated history size (keeps short chats prefix-cache-friendly). |
| `min_tokens_to_compress` | `250` | Per-message floor below which a message is never compressed. |
| `protect_recent` | `4` | Number of most-recent messages left uncompressed. |
| `compress_user_messages` | `false` | Also compress user/human messages. |
| `compress_system_messages` | `false` | Compress system messages embedded in history. |
| `target_ratio` | `null` | Keep-ratio hint (0.0–1.0) for the text compressor. |
| `savings_profile` | `null` | Named Headroom savings profile (e.g. `agent-90`). |
| `fail_open` | `true` | Swallow compaction errors and send originals unchanged. |

## Operational notes

- **Cache friendliness.** Because compaction rewrites message content, it can
  reduce prefix-cache hit rates on the provider side. `min_total_tokens` and
  `protect_recent` exist to keep small/recent context stable. Tune them up if you
  rely heavily on provider prompt caching.
- **Token accounting.** Token usage reported by `TokenUsageMiddleware` reflects
  what the model actually received (the compacted request), so savings show up in
  your usage metrics directly.
- **Observability.** When compaction changes content it logs an info line with
  the estimated tokens saved and compression ratio.

## Tests

- `tests/test_compaction_config.py` — config validation and `AppConfig` wiring.
- `tests/test_compaction_middleware.py` — gating, non-destructive behaviour,
  structure preservation, fail-open/closed, the optional-dependency no-op path,
  model-name resolution, and the async path. These use a `compress_fn` injection
  seam and never import the heavy `headroom-ai` ML stack.
