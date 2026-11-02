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

`allow_insecure_http` also accepts an environment reference such as
`allow_insecure_http: $HONCHO_ALLOW_INSECURE`. The value is validated with
Pydantic's boolean vocabulary, case-insensitively: `true`, `t`, `y`, `yes`,
`on` and `1` enable the opt-in, while `false`, `f`, `n`, `no`, `off` and `0`
keep it off. Any other value is rejected when the backend loads its
configuration, so a typo cannot silently enable the opt-in.

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

## Incremental conversation capture

Checkpoint history is cumulative. For messages with stable source IDs, the
adapter stores an opaque `deerflow_source_id` in Honcho message metadata and
checks the session's metadata-filtered `messages/list` endpoint before appending
new messages. This requires session-read access as well as message-write access.
Lookups and writes use batches of at most 100 messages. Each lookup requests
100 records per page and consumes at most 10 pages before publishing that batch.
All advertised pages must be consumed; a larger page count aborts capture rather
than using partial results. The budget allows multiple stored records per source
identity, but exceptionally duplicate-heavy histories may exceed it.

The identity includes the owner, source message ID, role, peer and normalized
text. Distinct messages with identical text are retained; edited source messages
are captured as new versions, not replacements of old Honcho records. Stored
identities survive manager/process restarts and overlapping compacted history.
An unavailable, malformed or over-budget lookup aborts that capture with a
`capture lookup failed` warning instead of assuming the history is new.
This is distinct from `write failed` for setup or message-write errors; a later
capture can retry normally once the lookup succeeds.

Lookup and append are serialized per endpoint/workspace/session within one
process, including across manager instances. This is **not exactly-once delivery**:
independent processes must serialize access to a session upstream. A retry can
recognize an earlier write whose response was lost once the committed records
are visible to the lookup, but Honcho does not provide an atomic deduplication
constraint here.

Direct callers without stable message IDs retain append-on-every-call behavior.
Records written before this metadata was introduced cannot be matched reliably:
the first capture after upgrading may replay that older history once. This
change does not remove historical duplicates or migrate existing records.

## Limitations

- No DeerMem-style fact CRUD: `create_fact`/`delete_fact`/`update_fact`,
  `import_memory`, and Settings-page fact editing are not implemented
  (`get_memory` returns a minimal DeerMem-shaped document with the working
  representation as the `workContext` summary and an empty fact list).
  `memory_add`/`memory_update`/`memory_delete` return a clear
  unsupported-operation error; conversation writes still happen through the
  retained middleware. DeerMem remains the default backend.
- No migration of existing DeerMem data.
- Writes run synchronously within each call. Failed captures are logged; no
  retry is scheduled or buffered locally, so `shutdown_flush` is a no-op.
  A later call can retry messages still present in its history, while stored
  source identities suppress already committed messages.
- `agent_name` is not mapped — Honcho models the user, not per-agent facts.

## Async execution and failure behavior

The Honcho HTTP client is synchronous for compatibility with the
`MemoryManager` contract. DeerFlow offloads it at every async boundary via
`asyncio.to_thread` (the manager's `a*` methods), so a slow Honcho request
never blocks ASGI handlers or SSE heartbeats.

`failure_policy.read: fail_open` (default) logs a recall failure and continues
without new memory context. `fail_closed` propagates the backend error through
prompt construction and aborts the run instead of silently degrading.
