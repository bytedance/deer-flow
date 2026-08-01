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

- Query-aware recall from the latest real user message.
- Request-local memory injection. Recalled text is not saved into LangGraph
  checkpoints or captured back into OpenViking.
- Capture after a completed turn and immediately before summarization removes
  messages.
- Official OpenViking message filtering, conversion, 100-message batching,
  partial-write progress, commit retry, and retrieval.
- One shared credential-bound SDK client for recorder and retriever operations.
- A bounded local cursor containing hashes only. It prevents repeated full
  transcript snapshots from duplicating accepted messages and rebases after
  history compaction.
- Stable mapping from a DeerFlow thread to an OpenViking Session.
- Request-scoped actor peers. The default DeerFlow agent uses
  `default_peer_id`; named top-level agents use their validated agent name.

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
OpenViking. This first setup is intended for a personal deployment or one
pre-provisioned user credential. Automatic provisioning and encrypted
per-user credential storage for hosted multi-user deployments require a
separate integration phase.

OpenViking peers represent top-level DeerFlow agents within the credential-bound
user. Normal internal subagents do not create separate peers because they do not
own an independent memory lifecycle.

## Requirements

Run OpenViking as a user-managed local or remote service with its VLM,
embedding provider, and persistent workspace configured. The DeerFlow Python
environment also needs an OpenViking release containing the official LangChain
adapters and request-scoped actor-peer support:

```bash
uv pip install "openviking[langchain]"
```

Until those changes are available in a release, contributors can install the
current OpenViking source in the DeerFlow development environment.

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

## Failure behavior

- Invalid configuration and missing credentials fail at manager construction.
- `startup_policy: fail_fast` makes the backend's startup probe raise for an
  unhealthy or unauthorized connection. The Gateway currently logs failed
  memory warm-up and continues serving; `warn` also returns a degraded result
  without raising.
- `failure_policy.read: fail_open` continues a turn without recalled memory.
  `fail_closed` rejects the read.
- `failure_policy.write: fail_open` logs a write failure while retaining all
  unconfirmed cursor progress for the next capture. `fail_closed` also fails the
  host operation.
- Confirmed partial progress advances the cursor before the error is handled,
  so a retry starts from the unconfirmed suffix.
- A failed post-write commit is marked pending. The next capture or graceful
  shutdown retries the commit without resubmitting accepted messages.
- Graceful shutdown stops new memory work, waits for active operations, retries
  known pending commits within the host budget, and closes the shared client.

The cursor protects one running DeerFlow process from duplicate snapshot writes.
It is not a distributed outbox. Multiple Gateway replicas sharing one
credential and thread still require server-side idempotency keys before the
integration can claim at-least-once delivery.

## Existing trusted configuration

Configurations containing an old custom-HTTP-only field, such as
`auth_mode`, `account`, connection-pool settings, or `retrieval.injection_query`,
continue to use the previous implementation and log a migration warning. This
compatibility path preserves existing deployments but is not used for new
setups. Remove the legacy fields, provide a USER API key, and add
`owner_user_id` to select the official adapter path.
