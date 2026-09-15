# mem0 memory backend

Uses mem0 (Platform hosted API, or any API-compatible self-hosted server) as
DeerFlow's memory store. Fully stateless in-process: dedup, fact extraction,
and storage are server-side, so it is safe for multi-worker Gateway
deployments.

## Configuration

```yaml
memory:
  enabled: true
  injection_enabled: true
  manager_class: mem0
  mode: middleware            # or "tool"
  backend_config:
    api_key_env: MEM0_API_KEY          # key read from env, never in config.yaml
    base_url: https://api.mem0.ai      # or your self-hosted mem0 server
    allow_insecure_http: false         # true only for trusted local HTTP dev
    top_k: 8
    score_threshold: 0.1
    max_injection_chars: 12000
    timeout_seconds: 10
    startup_policy: fail_fast          # fail_fast | tolerate
    failure_policy:
      read: fail_open                  # fail_open | fail_closed
      write: log_and_drop              # log_and_drop | raise
```

Set the key in the environment: `export MEM0_API_KEY=...`

`base_url` must use HTTPS because every request carries the API key. For a
trusted local-development server that only exposes HTTP, opt in explicitly
with `allow_insecure_http: true`; do not use that setting across an untrusted
network.

## Identity mapping

| DeerFlow | mem0 |
|---|---|
| `user_id` | `user_id` |
| `agent_name` | `agent_id` |
| `thread_id` | `run_id` |

## Limitations

- `mode: middleware` recall is query-less (the `get_context` contract carries
  no query): the bucket's most recent `top_k` memories are injected. For
  query-aware semantic recall use `mode: tool`.
- `mode: tool` retains the passive per-turn write middleware for this backend,
  because mem0 extracts and deduplicates facts from conversations through
  `add()`. The agent still gains query-aware `memory_search`, while new
  conversations continue accumulating memory even though fact CRUD is not
  available.
- Fact CRUD, `import_memory`, and Settings-page memory editing are not
  implemented (gateway returns 501). DeerMem remains the default backend.
- No migration of existing DeerMem data.
- `log_and_drop` write policy is at-most-once: a failed write is dropped.
- `memory_add`/`memory_update`/`memory_delete` are backed by fact CRUD, which
  this backend does not implement; they return a clear unsupported-operation
  error. Conversation writes still happen through the retained middleware.

## Async execution and failure behavior

The mem0 HTTP client is synchronous for compatibility with the
`MemoryManager` contract. DeerFlow offloads it at every async boundary: the
async middleware uses the manager's `a*` methods, and Gateway memory routes run
sync management calls in worker threads. A slow mem0 request therefore does
not block unrelated ASGI handlers or SSE heartbeats.

`failure_policy.read: fail_open` logs a recall failure and continues without
new memory context. `fail_closed` propagates the backend error through prompt
construction and aborts the run instead of silently degrading.
