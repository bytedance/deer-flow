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

mem0 attributes every extracted fact to exactly ONE entity (per its
[entity-scoped memory](https://docs.mem0.ai/platform/features/entity-scoped-memory)
semantics), so each DeerFlow bucket maps to one single queryable mem0 entity
scope -- a joint `AND(user_id, agent_id)` filter can never match a record:

| DeerFlow | mem0 |
|---|---|
| default bucket (`agent_name` omitted) | the `user_id` entity (records without an `agent_id`) |
| agent bucket (`user_id`, `agent_name`) | composite `agent_id` `"{user_id}::{agent_name}"` |
| agent-bucket writes | `add` passes only the composite `agent_id`, plus `app_id={user_id}` (stamped on every record) |
| `thread_id` | `run_id` |

Default-bucket semantics: reading without an `agent_name` (the Settings "Main
memory" view, export, status, main-agent context injection, and main-agent
`memory_search`) returns only the user's unscoped records -- never another
custom agent's facts -- mirroring DeerMem's reserved `__default__` bucket.
mem0's filter syntax cannot express agent-id absence, so the default scope is
applied client-side after a user-wide listing (an over-fetched window for
search/context, since the server truncates to the requested `top_k` before
any client-side filtering).

`clear_memory` with no `agent_name` clears the user's whole memory (all
buckets), per the `MemoryManager` contract: two delete-all sweeps -- the
`user_id` entity (default bucket plus legacy pre-agent records) and the
`app_id` stamp (every agent bucket of that user). An agent-scoped clear
deletes exactly that composite `agent_id`, so it cannot touch another user's
bucket for the same agent name.

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
