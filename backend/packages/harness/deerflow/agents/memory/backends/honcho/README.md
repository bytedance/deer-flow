# Honcho memory backend

Uses Honcho (self-hosted or hosted, v3 API) as DeerFlow's
user-model memory store. Honcho covers the user dimension of memory — long-term
user modeling, preferences, and a cross-session working representation — built
by Honcho's own server-side deriver. Ingestion is cheap plain message writes;
this backend makes **no LLM calls** locally.

## Configuration

```yaml
memory:
  enabled: true
  injection_enabled: true
  manager_class: honcho
  mode: middleware            # or "tool"
  backend_config:
    base_url: http://localhost:8000
    # api_key: $HONCHO_API_KEY   # hosted Honcho; plain-http + api_key needs allow_insecure_http: true
    workspace_prefix: deerflow-u-   # one isolated workspace per user id
    # workspace_overrides: {}    # map specific user ids to custom workspaces
    # user_peer_overrides: {}    # map specific user ids to custom peer names
    assistant_peer: deerflow
    message_char_limit: 8000
    max_injection_chars: 6000
    timeout_seconds: 10
    connect_timeout_seconds: 3
    failure_policy:
      read: fail_open                  # fail_open | fail_closed
```

A configured `api_key` over a plain-`http://` base URL is rejected at startup
unless you explicitly set `allow_insecure_http: true` (local-development opt-in,
same posture as the mem0 backend). Use HTTPS for any non-local deployment.

Config errors (bad URL, insecure key combination) fail fast at Gateway startup;
connectivity is deliberately not probed, so a temporarily unreachable Honcho
does not block startup — reads then degrade per `failure_policy.read`.

## Multi-user isolation

Every operation resolves a workspace from `user_id`:
`workspace_overrides[user_id]` on exact match, else
`workspace_prefix + <stable id>`. The stable id is the sanitized user id plus
an 8-hex-char SHA-256 suffix of the original id, so distinct raw ids that
sanitize identically cannot silently merge into one workspace. Honcho scopes
all queries to a single workspace, so under the default derivation users
cannot see each other's memory by construction.

- A missing or empty `user_id` **fails closed**: writes become no-ops and reads
  return empty — there is never a shared fallback workspace.
- A `workspace_overrides` entry deliberately shared across users shares that
  workspace's search index (`search` is workspace-scoped; `get_context` /
  `get_memory` stay peer-scoped).
- Session ids reuse the same collision-resistant derivation
  (`df-` + stable id of `thread_id`).

## Recall and search

- `mode: middleware` recall is query-less: `get_context` fetches the user's
  working representation (up to 25 conclusions) and injects it truncated to
  `max_injection_chars`.
- `mode: tool` adds query-aware `memory_search` backed by Honcho's
  workspace-scoped search, while the passive per-turn write middleware is
  retained because Honcho's deriver learns from `add()` writes.

## Limitations

- No DeerMem-style fact CRUD: `create_fact`/`delete_fact`/`update_fact`,
  `import_memory`, and Settings-page fact editing are not implemented
  (`get_memory` returns a minimal DeerMem-shaped document with the working
  representation as the `workContext` summary and an empty fact list).
  `memory_add`/`memory_update`/`memory_delete` return a clear
  unsupported-operation error; conversation writes still happen through the
  retained middleware. DeerMem remains the default backend.
- No migration of existing DeerMem data.
- Writes are fire-and-forget per call: a failed write is logged and dropped
  (at-most-once); nothing is buffered locally, so `shutdown_flush` is a no-op.
- `agent_name` is not mapped — Honcho models the user, not per-agent facts.

## Async execution and failure behavior

The Honcho HTTP client is synchronous for compatibility with the
`MemoryManager` contract. DeerFlow offloads it at every async boundary via
`asyncio.to_thread` (the manager's `a*` methods), so a slow Honcho request
never blocks ASGI handlers or SSE heartbeats.

`failure_policy.read: fail_open` (default) logs a recall failure and continues
without new memory context. `fail_closed` propagates the backend error through
prompt construction and aborts the run instead of silently degrading.
