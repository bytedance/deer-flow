# OpenViking memory backend

DeerFlow can use a remote OpenViking server as an optional long-term memory
backend. DeerMem remains the default. The OpenViking backend uses the maintained
[`langchain-openviking`](https://pypi.org/project/langchain-openviking/)
package instead of implementing OpenViking's HTTP protocol inside DeerFlow.

## Current scope

The OpenViking integration preserves DeerFlow's automatic-memory behavior across
both single-user and multi-user / multi-tenant deployments:

- memory is recalled through DeerFlow's existing fixed memory query;
- completed turns are captured by the existing memory middleware;
- messages about to be compacted are captured by the existing summarization hook;
- every accepted capture is committed to the thread's stable OpenViking Session;
- the official adapter handles message conversion, tool calls and results,
  100-message batching, partial-write progress, commit retry, and SDK transport;
- in single-user mode, one recorder-owned SDK client is shared with retrieval
  and closed on shutdown; in multi-user mode, a bounded LRU/TTL `client_pool`
  manages isolated per-scope SDK clients and drains/closes them cleanly on
  eviction, key rotation, revocation, and shutdown.

This backend supports `memory.mode: middleware`. It does not implement DeerMem
fact CRUD, import/export, or the Settings memory-document view. OpenViking MCP
tools are a separate integration surface and are not enabled by this backend.

## Authentication boundary

The supported server configuration is OpenViking `api_key` mode, where each
ordinary OpenViking **USER API key** determines the OpenViking account and user
server-side. DeerFlow supports two isolation modes on top of `api_key` mode:

- **Single-user mode** (`owner_user_id` + `api_key_env`): binds one DeerFlow
  user identity to one OpenViking USER API key. Use `owner_user_id: default`
  when DeerFlow authentication is disabled, or that user's DeerFlow ID in an
  authenticated single-user deployment. A request for another DeerFlow user is
  rejected before OpenViking is contacted, preventing one USER key from silently
  sharing memory across users. The failure policies below decide what that
  rejection does to the turn: with `write: log_and_drop` the other user's write
  is logged as refused, without message content, and dropped, and the run still
  completes.
- **Multi-user / multi-tenant isolation mode** (`user_credentials` and/or
  `credential_provider` / `host_hooks["credential_provider"]`, plus optional
  `tenant_id` and `client_pool`): resolves a distinct OpenViking USER API key
  (and optional `tenant_id`) per DeerFlow user and isolates each scope's
  client handle, headers, and session IDs. Multi-user configuration is mutually
  exclusive with `owner_user_id` and `api_key_env`.

### Why `auth_mode: trusted` / `account` remains unsupported

In OpenViking `api_key` mode, OpenViking derives `account` and `user`
server-side from the USER API key (`X-API-Key`). Accepting `auth_mode: trusted`
or `account` headers in DeerFlow would trust caller-asserted identity headers
instead of key-derived identity and is therefore rejected at configuration time
(pointing operators to `owner_user_id`, `user_credentials`, or
`credential_provider`). DeerFlow also must not receive a root key for normal
memory traffic, overrides any ambient actor peer during memory operations, and
passes an explicit empty `extra_headers={}` mapping so the SDK never inherits
arbitrary HTTP headers from `ovcli.conf`.

Before enabling this backend, remove legacy `OPENVIKING_ACCOUNT` and
`OPENVIKING_USER` values from DeerFlow's repository-root `.env` and service
environment, and remove `account` and `user` defaults from
`~/.openviking/ovcli.conf`. Those settings belong to trusted-mode configurations
and are outside this adapter's supported setup. In multi-user mode, do not rely
on a shared ambient `OPENVIKING_API_KEY`; per-user keys are never resolved from
an ambient fallback.

Existing trusted-mode configurations are not migrated automatically. Configure
the OpenViking server in `api_key` mode, replace `auth_mode`, `account`, and the
root key with either single-user (`owner_user_id` + `api_key_env`) or multi-user
(`user_credentials` / `credential_provider`) USER keys, and remove the legacy
ambient identity settings listed above. Because credential-bound user and Session
mappings differ from the old trusted-user mapping, previously captured
trusted-mode data remains in its old OpenViking namespace rather than being
silently reassigned.

## Configure DeerFlow

The dependency on `langchain-openviking==0.1.0` is declared by DeerFlow's
harness package and is installed by the normal `uv sync` flow.

### Single-user mode

Create or select an OpenViking user, then copy its USER API key into DeerFlow's
repository-root `.env`:

```dotenv
OPENVIKING_API_KEY=replace-with-an-openviking-user-api-key
```

Select the backend in `config.yaml`:

```yaml
memory:
  enabled: true
  injection_enabled: true
  shutdown_flush_timeout_seconds: 30
  manager_class: openviking
  mode: middleware
  backend_config:
    base_url: http://127.0.0.1:1933
    owner_user_id: default
    api_key_env: OPENVIKING_API_KEY
    startup_policy: fail_fast
    failure_policy:
      read: fail_open
      write: log_and_drop
    retrieval:
      top_k: 8
      score_threshold: 0.25
      max_injection_chars: 12000
      content_mode: overview
      injection_query: >-
        user profile preferences important entities events ongoing goals
        constraints and prior decisions
```

For a host-installed OpenViking used by Docker DeerFlow, set `base_url` to
`http://host.docker.internal:1933` and `allow_insecure_http: true`. The optional
Compose overlay uses the internal `http://openviking:1933` address.

### Multi-user and multi-tenant isolation mode

Use `user_credentials` for a static per-user mapping, `credential_provider`
for dynamic resolution, or both together (static `user_credentials` is checked
first, and `credential_provider` resolves users not listed statically). Do **not**
set `owner_user_id` or `api_key_env` at the `backend_config` top level when
using multi-user mode.

#### Static per-user mapping (`user_credentials`)

Put each user's OpenViking USER API key in DeerFlow's `.env` or service
environment:

```dotenv
OPENVIKING_API_KEY_ALICE=replace-with-alice-user-api-key
OPENVIKING_API_KEY_BOB=replace-with-bob-user-api-key
```

Configure `user_credentials` and `client_pool` in `config.yaml`:

```yaml
memory:
  enabled: true
  injection_enabled: true
  shutdown_flush_timeout_seconds: 30
  manager_class: openviking
  mode: middleware
  backend_config:
    base_url: http://127.0.0.1:1933
    user_credentials:
      alice:
        api_key_env: OPENVIKING_API_KEY_ALICE
        tenant_id: acme
      bob:
        api_key_env: OPENVIKING_API_KEY_BOB
        tenant_id: globex
    client_pool:
      max_clients: 64
      idle_ttl_seconds: 900.0
    startup_policy: fail_fast
    failure_policy:
      read: fail_open
      write: log_and_drop
    retrieval:
      top_k: 8
      score_threshold: 0.25
      max_injection_chars: 12000
      content_mode: overview
      injection_query: >-
        user profile preferences important entities events ongoing goals
        constraints and prior decisions
```

`user_credentials` rules:

- Each mapping key is the exact DeerFlow `user_id` (non-empty stripped string
  with no control characters or `\0`).
- Each user entry accepts only `api_key_env`, `api_key`, and optional
  `tenant_id`. Exactly **one** of `api_key_env` or `api_key` is required per
  entry; `api_key_env` is recommended so secret keys stay out of `config.yaml`.
- `tenant_id` is optional. When set, it must be a non-empty stripped string of
  at most 128 characters with no control characters or `\0`.
- When `credential_provider` (or `host_hooks["credential_provider"]`) is not
  configured, `user_credentials` must be non-empty.
- Every statically configured user must have a distinct API key.

#### Dynamic credential resolution (`credential_provider` and `host_hooks`)

For dynamic, KMS/vault-backed, or rotating user credentials, specify a dotted
Python import path in `credential_provider` (`pkg.module:Attr` or
`pkg.module.Attr`) and optional constructor/factory keyword arguments in
`credential_provider_config`:

```yaml
memory:
  enabled: true
  injection_enabled: true
  manager_class: openviking
  mode: middleware
  backend_config:
    base_url: http://127.0.0.1:1933
    credential_provider: my_company.openviking_auth:VaultCredentialProvider
    credential_provider_config:
      vault_url: https://vault.internal
      namespace: deerflow
    client_pool:
      max_clients: 128
      idle_ttl_seconds: 900.0
```

Provider resolution contract (`OpenVikingCredentialProvider`):

- `OpenVikingConfig.from_backend_config()` validates `credential_provider`
  path syntax without importing the module or performing I/O, keeping `make doctor`
  and policy checks side-effect-free.
- At manager initialization, DeerFlow imports the target attribute:
  - If the target is a class, DeerFlow instantiates
    `Attr(**credential_provider_config)` and expects a callable `.resolve`
    method or callable instance.
  - If the target is a callable factory/function and `credential_provider_config`
    is non-empty, DeerFlow calls `Attr(**credential_provider_config)` and uses
    the returned resolver (`.resolve` method or callable). If
    `credential_provider_config` is empty, `Attr` itself is used directly.
- Embedded hosts and custom extensions can also inject a provider instance or
  callable programmatically via `host_hooks["credential_provider"]` when calling
  `OpenVikingMemoryManager.from_config(..., credential_provider=...)`, without
  declaring an import path in `config.yaml`. Because Gateway and
  `DynamicContextMiddleware` config bootstrap consult
  `OpenVikingMemoryManager.read_failures_are_fatal_for_config(backend_config)`
  (which requires `user_credentials` or `credential_provider` in
  `backend_config`), `host_hooks["credential_provider"]` is intended for direct
  programmatic callers outside config-driven Gateway/`DynamicContextMiddleware`
  wiring.
- `credential_provider_config` applies only when DeerFlow instantiates a
  config-declared `credential_provider` and must be omitted or empty when
  `credential_provider` is not set in `backend_config` (including when passing an
  already-instantiated hook via `host_hooks["credential_provider"]`).
- At request time, the provider's `resolve(user_id)` returns one of:
  - `OpenVikingCredential(api_key=..., tenant_id=...)`
  - a mapping containing only `api_key` and optional `tenant_id`
  - a plain `str` (treated as `api_key` with `tenant_id=None`)
  - `None` (treated as unmapped or revoked; fails closed)
- If the provider defines a callable `.close()` method, DeerFlow invokes it
  during graceful shutdown (`shutdown_flush()` / `close()`).

#### Client pool (`client_pool`)

Multi-user mode caches scoped `(tenant_id, user_id, key_fingerprint)` SDK
recorder/retriever handles in a bounded pool:

- `max_clients` (integer `1..4096`, default `64`): maximum active client
  handles retained in the LRU pool. When full, the least-recently-used idle
  handle is evicted and closed; if an evicted handle still has active in-flight
  operations, `close()` is deferred until those operations finish.
- `idle_ttl_seconds` (positive finite float or `null`, default `900.0`): idle
  eviction threshold in seconds. Omitting `idle_ttl_seconds` keeps the
  `900.0`-second default; setting `idle_ttl_seconds: null` explicitly disables
  TTL-based eviction.

## Start the services

For a local OpenViking process, start and verify the server first:

```bash
openviking-server doctor
openviking-server
curl http://127.0.0.1:1933/health
```

Then start DeerFlow normally:

```bash
make doctor
make dev
```

DeerFlow is available at <http://localhost:2026>. OpenViking Studio is
available at <http://localhost:1933/studio>.

To use the optional Docker service instead:

```bash
docker compose \
  -f docker/docker-compose.yaml \
  -f docker/docker-compose.openviking.yaml \
  up -d openviking

docker exec -it deer-flow-openviking openviking-server init

docker compose \
  -f docker/docker-compose.yaml \
  -f docker/docker-compose.openviking.yaml \
  up -d --build
```

Configure OpenViking in `api_key` mode and obtain ordinary USER keys through
its identity management flow. Put only USER keys in DeerFlow's `OPENVIKING_API_KEY`
(single-user), per-user environment variables referenced by `user_credentials`,
or your `credential_provider` store.

In single-user mode, `warm()` verifies OpenViking health through the configured
client's `health()` check. In multi-user mode, because no single user key owns
the backend, `warm()` probes `GET {base_url}/health` without any user API key
or ambient `ovcli.conf` headers, checks for HTTP 200 and JSON `status == "ok"`,
and honors `startup_policy` (`fail_fast` vs `warn`).

## Identity and session mapping

One DeerFlow thread maps deterministically to one OpenViking Session. A commit
creates an archive inside that Session; it does not create a new Session, so a
thread keeps the same identity when the user returns later.

Session ID derivation depends on whether `tenant_id` is set:

- **Unscoped (`tenant_id` is unset / `None`)**: preserves the v1 derivation
  (`deerflow-openviking-adapter-v1`, hashing namespace, `user_id`, `peer_id`,
  and `thread_id`), so existing single-user deployments and unscoped multi-user
  entries keep their stable v1 `df_<hash>` session IDs.
- **Tenant-scoped (`tenant_id` is set)**: uses the v2 derivation
  (`deerflow-openviking-adapter-v2`, hashing namespace, `tenant_id`, `user_id`,
  `peer_id`, and `thread_id`). Even when two tenants use the same DeerFlow
  `user_id`, `agent_name`, and `thread_id`, their OpenViking `session_id`
  values and local capture cursors are completely disjoint from each other and
  from unscoped v1 sessions.

The default DeerFlow agent uses `default_peer_id` (`deerflow` by default).
Named agents use lowercase OpenViking peer IDs. Names that are not valid peer
IDs, conflict with the default, or enter the reserved `df-agent-` namespace are
mapped to collision-resistant IDs. USER-key identity remains the security
boundary; peers separate memory scopes within that user.

## Security and isolation invariants

- **Fail-closed user resolution**: in multi-user mode, `None`, empty, or
  whitespace-only `user_id` values, leading/trailing whitespace or control
  characters (`\0`) on runtime `user_id` values, unmapped users, revoked users
  (`None` from `credential_provider`), invalid/blank keys, and provider errors
  are all rejected before any OpenViking HTTP call is made or local cursor file
  is written: read paths raise `MemoryManagerError` (or `MemoryReadError` when
  `failure_policy.read: raise`), and write paths follow `failure_policy.write`
  (`log_and_drop` logs the refusal without message content or secrets and drops
  the write; `raise` propagates `MemoryManagerError`).
- **No fallback to shared or ambient credentials**: DeerFlow never falls back
  to another user's key, a default key, ambient `OPENVIKING_API_KEY`, or
  `ovcli.conf` headers.
- **Cross-user duplicate key rejection**: DeerFlow tracks each key by its
  SHA-256 `key_fingerprint` and refuses to share the same API key across
  different users—both statically during `user_credentials` config validation
  and dynamically in the runtime `client_pool`. Static `user_credentials`
  fingerprints are always checked globally (including in hybrid deployments even
  when a static user has not yet been called or was evicted); for purely dynamic
  providers, runtime duplicate-key detection covers currently cached and
  in-flight pool entries rather than evicted historical scopes.
- **Key validation without secret echoes**: API keys must contain printable
  ASCII (`0x21..0x7E`) only (rejecting whitespace, newlines, `\0`, control
  characters, and non-ASCII to prevent header injection). Config/validation
  errors and `repr(OpenVikingConfig)` never echo raw API keys.
- **Key rotation and revocation**: pool entries are keyed by
  `(tenant_id, user_id, key_fingerprint)`. When a provider rotates a user's key
  or reassigns their `tenant_id`, DeerFlow opens a fresh scoped handle and
  retires all previous cached and in-flight handles for that `user_id` so they
  close once active operations complete. When a provider revokes a user by
  returning `None`, DeerFlow immediately retires all cached and in-flight
  handles for that user and refuses the request.
- **Refcount-safe, lock-free handle lifecycle**: in-flight operations hold a
  reference count on the acquired entry so evicted, rotated, or revoked handles
  are never closed out from under an active request, and pool locks are never
  held while calling `credential_provider.resolve()`, constructing SDK clients,
  or calling `close()`.
- **Gateway `/api/memory/config` masking**: `GET /api/memory/config` masks
  `user_credentials` wholesale as `"***"` (hiding nested `api_key`,
  `api_key_env`, and `tenant_id` entries) and masks secret-named keys inside
  `credential_provider_config` (keys matching `api_key`, `secret`, `token`,
  `password`, `credentials`, `authorization`, `bearer`, or `cookie`), while
  keeping top-level non-secret settings (`base_url`, single-user `api_key_env`,
  `client_pool`, and non-secret provider options) visible. Providers that need
  DSNs or URLs with embedded credentials should read them from environment
  variables or secret stores inside the provider rather than passing them via
  non-secret keys in `credential_provider_config`. Note that `GET /api/memory/status`
  returns HTTP `501` for OpenViking (same as `GET /api/memory`).

## Retry and failure behavior

- `read: fail_open` logs retrieval failures and continues the turn without
  recalled OpenViking context. `read: raise` aborts the turn when recall fails.
  The same policy applies at DeerFlow's 5-second async injection deadline,
  even when the worker pool is full. If configuration or backend discovery
  has not finished by then, the unknown policy fails closed. This deadline
  limits request waiting, not the blocking operation: an in-flight read keeps
  its worker until the backend returns or reaches its own timeout
  (`timeout_seconds`, 30 seconds by default).
- `write: log_and_drop` logs capture failures without failing an already
  generated answer. `write: raise` propagates them.
- DeerFlow stores only hashes and counters in a bounded local capture cursor
  under `{storage_path}/openviking/sessions/{session_id}.json`. It never stores
  message text there.
- The cursor prevents full LangGraph transcript snapshots from being submitted
  again. It also records confirmed progress from partial batches and retries a
  failed commit before appending more messages.
- An unreadable cursor fails closed because replaying an unknown prefix could
  duplicate private conversation history.
- Capture cursors remain local per Gateway instance. Shared DB-backed capture
  cursors for multi-replica Gateways writing concurrently to the same thread
  remain a Phase 2 follow-up.
- Graceful shutdown stops new memory work, drains accepted operations, and
  bounds closing pooled recorder-owned SDK clients and
  `credential_provider.close()` (if defined) within the same
  `shutdown_flush_timeout_seconds` budget via a single-flight teardown, without
  introducing a new DeerFlow lifecycle or persistent background worker.

For deployments where a lost memory update is unacceptable, a durable outbox
is still required. This integration does not claim at-least-once delivery.
