# OpenViking memory backend

DeerFlow can use a remote OpenViking server as an optional long-term memory
backend. The integration is a pluggable `MemoryManager`; DeerMem remains the
default and the agent/Gateway runtime does not import the OpenViking Python
runtime.

## Supported behavior

- HTTP connection to an independent OpenViking server.
- Passive `memory.mode: middleware` capture after each completed turn.
- OpenViking Session commit and asynchronous memory extraction.
- Automatic prompt injection from OpenViking memory search.
- Explicit search through the backend-neutral `MemoryManager.search` API.
- Hard isolation by hashing each DeerFlow `(user_id, agent_name)` scope into a
  separate OpenViking trusted user identity.
- Local message watermarks under DeerFlow's runtime home to avoid resubmitting
  the same conversation history in a single-Gateway deployment.

The current backend does not implement DeerMem fact CRUD, import/export, or the
Settings memory document. Keep `mode: middleware`; tool mode is rejected
because its add/update/delete tools require fact CRUD.

## OpenViking requirements

OpenViking must be configured with:

- a VLM provider;
- an embedding provider;
- persistent workspace storage;
- `server.auth_mode: trusted`;
- a non-empty `server.root_api_key` when exposed beyond localhost.

DeerFlow passes trusted `X-OpenViking-Account` and
`X-OpenViking-User` headers. Do not expose a trusted-mode OpenViking endpoint
directly to untrusted clients.

## Configure DeerFlow

Put the trusted OpenViking key in the repository root `.env`:

```dotenv
OPENVIKING_API_KEY=replace-with-the-same-root-api-key
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
    base_url: http://openviking:1933
    auth_mode: trusted
    account: deerflow
    api_key_env: OPENVIKING_API_KEY
    startup_policy: fail_fast
    failure_policy:
      read: fail_open
      write: log_and_drop
    retrieval:
      top_k: 8
      score_threshold: 0.25
      max_injection_chars: 12000
```

For a locally installed DeerFlow process, use
`http://127.0.0.1:1933`. For a DeerFlow container connecting to OpenViking on
the host, use `http://host.docker.internal:1933` and set
`allow_insecure_http: true`.

## Docker first-time startup

Create the standard DeerFlow local files if they no longer exist:

```bash
make config
cp .env.example .env
cp frontend/.env.example frontend/.env
```

Set at least the normal DeerFlow secrets in `.env`, including
`BETTER_AUTH_SECRET`, model provider credentials, and
`OPENVIKING_API_KEY`.

The production Compose file expects the same path variables normally exported
by `scripts/deploy.sh`. Export them before using the OpenViking overlay
directly:

```bash
export DEER_FLOW_CONFIG_PATH="$PWD/config.yaml"
export DEER_FLOW_EXTENSIONS_CONFIG_PATH="$PWD/extensions_config.json"
export DEER_FLOW_HOME="$PWD/backend/.deer-flow"
export DEER_FLOW_REPO_ROOT="$PWD"
```

Start only OpenViking:

```bash
docker compose \
  -f docker/docker-compose.yaml \
  -f docker/docker-compose.openviking.yaml \
  up -d openviking
```

Initialize it interactively:

```bash
docker exec -it deer-flow-openviking openviking-server init
```

Choose trusted authentication, configure the same root API key stored in
`OPENVIKING_API_KEY`, and configure VLM and embedding providers. Validate the
configuration:

```bash
docker exec -it deer-flow-openviking openviking-server doctor
docker restart deer-flow-openviking
curl http://localhost:1933/health
```

Then start DeerFlow with the same overlay:

```bash
docker compose \
  -f docker/docker-compose.yaml \
  -f docker/docker-compose.openviking.yaml \
  up -d --build
```

Open DeerFlow at <http://localhost:2026> and OpenViking Studio at
<http://localhost:1933/studio>.

## Routine Docker operations

```bash
# Logs
docker compose \
  -f docker/docker-compose.yaml \
  -f docker/docker-compose.openviking.yaml \
  logs -f gateway openviking

# Stop containers but retain data
docker compose \
  -f docker/docker-compose.yaml \
  -f docker/docker-compose.openviking.yaml \
  down

# Restart
docker compose \
  -f docker/docker-compose.yaml \
  -f docker/docker-compose.openviking.yaml \
  up -d

# Pull a newer OpenViking image and recreate
docker compose \
  -f docker/docker-compose.yaml \
  -f docker/docker-compose.openviking.yaml \
  pull openviking
docker compose \
  -f docker/docker-compose.yaml \
  -f docker/docker-compose.openviking.yaml \
  up -d openviking
```

Do not add `-v` to `docker compose down` unless you intentionally want to
delete Redis and OpenViking persistent volumes.

## Local-process startup

Run OpenViking separately and verify:

```bash
openviking-server doctor
openviking-server
curl http://127.0.0.1:1933/health
```

Set `base_url: http://127.0.0.1:1933`, then start DeerFlow normally:

```bash
make doctor
make dev
```

The DeerFlow entrypoint is <http://localhost:2026>.

## Failure behavior

- Invalid backend configuration fails loudly; DeerFlow never silently writes
  to DeerMem instead.
- With `read: fail_open`, retrieval failures produce no injected memory and
  the main agent continues.
- With `write: log_and_drop`, a failed OpenViking commit is logged without
  failing an already generated assistant response.
- Once a message batch is accepted, DeerFlow persists a submitted-message
  watermark before committing the Session. If commit then fails, later updates
  do not resubmit those messages or retry the ambiguous commit; a future batch
  can commit the still-open Session together with new messages.
- OpenViking commit is eventually consistent: accepting a commit archives the
  messages immediately, while summary and memory extraction finish in a
  background task.
- Graceful shutdown stops admitting new memory operations, waits up to
  `shutdown_flush_timeout_seconds` for active reads and writes, and closes the
  shared HTTP client only after they drain.

For deployments where a lost memory update is unacceptable, a durable outbox
is still required; the initial plugin intentionally does not claim
at-least-once delivery.
