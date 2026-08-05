# OpenViking memory backend

DeerFlow can use an independent OpenViking server for automatic long-term
memory. DeerMem remains the default.

The integration follows one ownership rule:

```text
DeerFlow MemoryManager
  decides when to recall and capture
          |
          v
OpenViking official LangChain adapters
  own retrieval, message conversion, batching, commits, and HTTP behavior
```

DeerFlow does not install a second OpenViking lifecycle middleware. This keeps
pre-compaction capture, shutdown, failure policy, user identity, and thread
mapping in DeerFlow's existing memory seam.

## Capabilities

- Query-aware recall from the latest real user message, scoped to the current
  DeerFlow thread when `retrieval.search_mode: search` is used.
- Each recall searches both the credential owner's self-memory root and the
  current agent peer's memory root. It does not search other peers, shared
  resources, or skills through this automatic-memory path.
- Request-local memory injection. Recalled text is not saved into LangGraph
  checkpoints or captured back into OpenViking.
- Append accepted messages after a completed turn. Immediately before
  summarization removes older messages, append any missing suffix and explicitly
  flush that conversation segment.
- Official OpenViking message filtering, conversion, 100-message batching,
  partial-write progress, commit retry, and retrieval.
- One shared credential-bound SDK client for recorder and retriever operations.
- A bounded local cursor containing message hashes and lifecycle metadata, but
  no message content. It prevents repeated full transcript snapshots from
  duplicating accepted messages, rebases after history compaction, and restores
  pending idle or failed commits after a process restart.
- Stable mapping from one DeerFlow thread to one OpenViking Session. Threshold,
  idle, and compaction commits create archives inside that same Session; they do
  not rotate the Session ID.
- Request-scoped actor peers. The default DeerFlow agent uses
  `default_peer_id`; compatible top-level agent names keep their lowercase
  identity, while DeerFlow-valid names outside OpenViking's peer syntax use a
  stable collision-resistant fallback. The `df-agent-` prefix is reserved for
  generated IDs, and a named agent matching `default_peer_id` is remapped so it
  cannot share the unnamed agent's memory partition.

The backend supports automatic memory with `memory.mode: middleware`. Explicit
OpenViking resources and model-invoked operations belong in MCP and are outside
this integration.

## Authentication and isolation

Use an ordinary OpenViking **USER API key** for memory reads and writes. The key
is already bound by OpenViking to one account and user. The official path does
not send trusted `account` or `user` impersonation headers and does not use a
root key.

`owner_user_id` binds that credential to exactly one DeerFlow user. If a request
arrives for another DeerFlow user, the backend fails closed before contacting
OpenViking. This identity-boundary error is never suppressed by `fail_open`.
With query-aware recall enabled it is reported before the model call, so an
invalid request does not spend model compute and then fail during capture. This
first setup is intended for a personal deployment or one pre-provisioned user
credential. Automatic provisioning and encrypted per-user credential storage
for hosted multi-user deployments require a separate integration phase.

OpenViking peers represent top-level DeerFlow agents within the credential-bound
user. Normal internal subagents do not create separate peers because they do not
own an independent memory lifecycle.

## Requirements

Run OpenViking as a user-managed local or remote service with its VLM,
embedding provider, and persistent workspace configured. DeerFlow includes
`langchain-openviking==0.1.0` and requires `openviking-sdk>=0.1.6,<0.2` for
request-scoped actor peers. Install the normal backend environment:

```bash
make install
```

The automatic-memory path does not require the full `openviking` server package
inside DeerFlow. The standalone adapter owns its SDK transport and talks to the
configured OpenViking service over HTTP.

## Configure DeerFlow

Put the USER API key in the repository root `.env`:

```dotenv
OPENVIKING_API_KEY=replace-with-your-user-api-key
```

Replace the `memory` section in `config.yaml` with:

```yaml
memory:
  enabled: true
  injection_enabled: true
  shutdown_flush_timeout_seconds: 30
  manager_class: openviking
  mode: middleware
  backend_config:
    base_url: https://your-openviking-server.example.com
    owner_user_id: default
    api_key_env: OPENVIKING_API_KEY
    default_peer_id: deerflow
    timeout_seconds: 30
    max_seen_message_ids: 512
    startup_policy: fail_fast
    failure_policy:
      read: fail_open
      write: fail_open
    commit:
      mode: pending_tokens
      pending_token_threshold: 8000
      idle_flush_seconds: 1800
    retrieval:
      search_mode: search
      top_k: 8
      score_threshold: 0.25
      max_injection_chars: 12000
      content_mode: auto
```

For DeerFlow with authentication disabled, the synthetic user ID is `default`.
For an authenticated personal deployment, set `owner_user_id` to the stable
DeerFlow user ID associated with the OpenViking USER key.

Plain HTTP is accepted by default only for `localhost`, `127.0.0.1`, and the
Compose service name `openviking`. For a trusted private network address, set
`allow_insecure_http: true` explicitly. Prefer HTTPS for remote services.

Start DeerFlow through its normal path after the OpenViking server is healthy:

```bash
make doctor
make dev
```

There is no separate OpenViking setup wizard yet. Configuration remains in
`config.yaml` and `.env`, matching other memory backends.

`commit.mode` controls the official recorder's post-append policy. `always`
commits every accepted capture, `pending_tokens` commits at the configured
token threshold, and `never` disables only that post-append auto-commit.
Pre-compaction flushes still run in every mode, and `idle_flush_seconds > 0`
remains an independent lifecycle boundary. Set it to `0` to disable idle
commits explicitly.

## Failure behavior

- Invalid configuration and missing credentials fail at manager construction.
- `startup_policy: fail_fast` makes the backend's startup probe raise for an
  unhealthy or unauthorized connection. The Gateway currently logs failed
  memory warm-up and continues serving; `warn` also returns a degraded result
  without raising.
- `failure_policy.read: fail_open` continues a turn without recalled memory
  after an operational retrieval failure. `fail_closed` rejects the read.
- Identity and authorization failures always fail closed. Availability policy
  cannot turn an owner mismatch into an anonymous or cross-user memory read.
- `failure_policy.write: fail_open` logs a write failure while retaining all
  unconfirmed cursor progress for the next capture. `fail_closed` also fails the
  host operation.
- Confirmed partial progress advances the cursor before the error is handled,
  so a retry starts from the unconfirmed suffix.
- A successful completed turn appends only its unseen suffix. The official
  `pending_tokens` policy commits when the configured threshold is reached.
  The adapter also records a durable idle deadline and commits after that
  session remains inactive for `idle_flush_seconds`.
- A failed threshold, idle, or compaction commit is marked pending. The next
  capture, idle retry, process restart, or graceful shutdown retries it without
  resubmitting accepted messages.
- Graceful shutdown stops the idle worker, waits for active operations, retries
  failed commits and idle deadlines that are already due, and closes the shared
  client. It deliberately does not commit every future deadline merely because
  the service is being restarted or deployed.

The cursor protects one running DeerFlow process from duplicate snapshot writes
and restores idle deadlines when that process restarts. Its `storage_path` must
be on persistent storage that survives DeerFlow restarts. Losing the cursor can
make the next capture submit the retained transcript again and loses pending
lifecycle intent. It is not a distributed outbox. Multiple Gateway replicas
sharing one credential and thread still require server-side idempotency keys and
cross-worker claiming before the integration can claim at-least-once delivery.

## Existing trusted configuration

Configurations containing an old custom-HTTP-only field, such as
`auth_mode`, `account`, connection-pool settings, or `retrieval.injection_query`,
continue to use the previous implementation and log a migration warning. This
compatibility path preserves existing deployments but is not used for new
setups. Remove the legacy fields, provide a USER API key, and add
`owner_user_id` to select the official adapter path.
