# Running the Application

## Deployment Sizing

Use the table below as a practical starting point when choosing how to run DeerFlow:

| Deployment target | Starting point | Recommended | Notes |
|---------|-----------|------------|-------|
| Local evaluation / `make dev` | 4 vCPU, 8 GB RAM, 20 GB free SSD | 8 vCPU, 16 GB RAM | Good for one developer or one light session with hosted model APIs. `2 vCPU / 4 GB` is usually not enough. |
| Docker development / `make docker-start` | 4 vCPU, 8 GB RAM, 25 GB free SSD | 8 vCPU, 16 GB RAM | Image builds, bind mounts, and sandbox containers need more headroom than pure local dev. |
| Long-running server / `make up` | 8 vCPU, 16 GB RAM, 40 GB free SSD | 16 vCPU, 32 GB RAM | Preferred for shared use, multi-agent runs, report generation, or heavier sandbox workloads. |

- These numbers cover DeerFlow itself. If you also host a local LLM, size that service separately.
- Linux plus Docker is the recommended deployment target for a persistent server. macOS and Windows are best treated as development or evaluation environments.
- If CPU or memory usage stays pinned, reduce concurrent runs first, then move to the next sizing tier.

## Option 1: Docker (Recommended)

Requires Docker Desktop / Docker Engine and **Docker Compose v2.24+**
(`docker compose version`). Older Compose clients cannot parse the optional
`env_file` syntax in `docker/docker-compose.yaml` and `docker/docker-compose-dev.yaml`.

**Development** (hot-reload, source mounts):

```bash
make docker-init    # Pull sandbox image (only once or when image updates)
make docker-start   # Start services (auto-detects sandbox mode from config.yaml)
make docker-logs    # View logs
```

`make docker-start` starts `provisioner` only when `config.yaml` uses provisioner mode (`sandbox.use: deerflow.community.aio_sandbox:AioSandboxProvider` with `provisioner_url`). Direct Compose users can add `--profile provisioner` to the dev command for the same mode; the default stack does not require Kubernetes.
With `USERDATA_PVC_NAME`, sandbox data, extra mounts and Lark broker credentials share one `user-data` volume with separate `subPath` mounts, avoiding duplicate references to the same claim on NFS CSI drivers.

Docker builds use the upstream `uv` registry by default. The gateway image installs with `uv sync --locked`, and `uv.lock` pins `https://pypi.org/simple`, so `UV_INDEX_URL` has to keep that value: exporting a mirror such as `https://pypi.tuna.tsinghua.edu.cn/simple` fails the build with ``The lockfile at `uv.lock` needs to be updated, but `--locked` was provided`` (reproduce in an already-synced environment with `cd backend && UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple uv sync --locked --check`; if the environment itself is stale, `--check` reports that instead for either index, so use `uv lock --check` to see it without syncing). Installing from a mirror requires regenerating the lock or dropping `--locked`, and both change what the image installs, so keep the default index for a checkout you intend to contribute back. `NPM_REGISTRY=https://registry.npmmirror.com` is independent of this: it applies to the frontend image's `pnpm` install and to the gateway image's Lark CLI install (`@larksuite/cli`, which `backend/Dockerfile` installs with npm).

Local AIO sandbox control traffic is always direct: loopback/private addresses,
single-label cluster hosts, and Docker/Podman internal hostnames do not inherit
`HTTP_PROXY` or `HTTPS_PROXY`. External sandbox FQDNs and public IPs still
honor environment proxy settings.

After native runtime shutdown and MCP teardown, Gateway closes an initialized
sandbox provider, including AIO sandboxes first created by a worker-thread tool call.
It does not start an unused sandbox provider solely for cleanup.

Backend processes automatically pick up `config.yaml` changes on the next config access, so model metadata updates do not require a manual restart during development.

Gateway runs use the top-level `recursion_limit` in `config.yaml` when an API
request does not provide one. The default is `100`; valid per-request values
take precedence, and `max_recursion_limit` (default `1000`) caps both. Changes
apply to the next run without restarting the Gateway. This top-level setting
applies to Gateway API and IM channel runs. A `recursion_limit` in an IM
channel's `session.config` takes precedence, and GitHub channel runs keep
their own floor. Embedded `DeerFlowClient` runs retain their own defaults and
per-call override paths. A run that reaches its limit stops with a plain message
that names up to five files it created in `/mnt/user-data/outputs` without
presenting them; send a message to continue. IM channels reply with the same
message.

A custom frontend can add an optional `context.client` to a Gateway run request:
a client name, capabilities such as `artifacts` or `charts`, and display
preferences. DeerFlow sanitizes it and passes the values to the agent as
untrusted, request-scoped hints, so skills can pick an output shape the client
can show. It is never an authorization or identity signal. See
[Create Run](../../backend/docs/API.md#create-run).
Client hints are omitted from stored run configuration and must be sent again
for each run; later runs, including server-started tasks, do not inherit them.
The checkpoint storage settings `database.checkpoint_channel_mode` and
`database.checkpoint_delta.snapshot_frequency` (default `10`) are exceptions:
both are frozen when the process first builds an agent (including through
`DeerFlowClient`) and require a process restart to change safely.

In delta mode, a run selecting an older checkpoint reports an error before rewriting
state if either the selected checkpoint or the current head has pending tool
execution. For `Command(resume=...)`, other pending graph nodes also prevent the
rewrite, except for the synthetic input entry node. Resume pending work from the
latest checkpoint; to regenerate completed work, submit new input there. Full-mode
resumes and ordinary replay without pending execution keep their existing behavior.

The optional `database.checkpoint_cache` section (delta channel mode only)
caches materialized checkpoint histories: `type` is `memory` (default) or
`redis`, and `max_entries: 0` disables the cache. The `redis` backend is
Gateway/async-only; the sync TUI/embedded path supports `memory` only. The
cache is performance-only — results are identical with it disabled — so it is
never frozen and workers sharing one checkpoint database may safely run
different cache settings. Returned state snapshots have independent nested values,
so editing one cannot change later checkpoint reads. Redis thread cleanup treats a configured `key_prefix`
as literal text, including glob metacharacters, so deletion stays within that
namespace and thread. Redis rejects malformed write records on ingestion; malformed
or wrong-channel cached histories are rebuilt in full from authoritative checkpoints.
Seeds and write values remain opaque to the cache: these checks do not validate
schema-specific state contents.
Checkpoint reads, valid neighboring writes and optional-cache cleanup continue
even if a warning handler fails.

Gateway checkpoint cleanup runs when the next run wins durable same-thread
admission, before its first checkpoint read. It checks only the root head and
its parent, removes at most one metadata-only duration leaf without pending
writes, and preserves explicit checkpoint selections and delta replay state.
See [checkpoint operations](../../frontend/src/content/en/harness/checkpoints/operations.mdx)
for the retention constraints.

> [!TIP]
> On Linux, if Docker-based commands fail with `permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock`, add your user to the `docker` group and re-login before retrying. See [CONTRIBUTING.md](../../CONTRIBUTING.md#linux-docker-daemon-permission-denied) for the full fix.

**Production** (builds images locally, mounts runtime config and data):

```bash
make up     # Build images and start all production services
make down   # Stop and remove containers
```

Access: http://localhost:2026

`make up` waits for the Gateway `/health` endpoint before reporting success.
If the Gateway does not become healthy within the startup window, deployment
exits non-zero and prints the container status plus recent Gateway logs. The
production image starts from its already-built environment and never resolves
or installs Python dependencies at container startup.

Images built from a checkout never contain its local configuration:
`.dockerignore` keeps `config.yaml`, `config.yaml.bak`, `extensions_config.json`
and `mcp_config.json` (at the root or in the legacy `backend/` location), `.env`
and `.env*.local` files, local HTTPS keys (`frontend/*.pem`), and the credential
files the extension manager refuses inside `backend/extensions/sources/` out of
the build context. Compose mounts the config and passes the environment at
runtime, so pushing or sharing an image does not publish those credentials.
A locally built frontend image therefore no longer picks up `NEXT_PUBLIC_*`
values from `frontend/.env.local`: `next build` inlines them into the client
bundle, Compose's environment reaches only `next start`, and `frontend/Dockerfile`
takes no build arguments for them. The Docker stack serves the frontend and
Gateway from one nginx origin and needs none of them.

If `make up` reports an unwritable runtime home or an unreadable persisted secret
after `make docker-start`, run the printed `sudo chown -R <uid>:<gid> '<home>'`
recovery command and retry. The check honors secret overrides from the shell or
`.env`, accepts readable read-only secret files, and leaves `make down` available
without reading or generating secrets.

Production Docker commands can select a root dotenv profile with
`DEER_FLOW_COMPOSE_ENV_FILE=/srv/deer-flow/stage.env make up`. The same file
feeds Compose interpolation, Gateway/provisioner variables, and deployment
secret checks. YAML and runtime-state locations remain separate selectors;
see [production env files](../../backend/docs/CONFIGURATION.md#production-compose-env-files).

For persistent deployments, configure `database.backend` as `sqlite` or
`postgres`. The selected backend is shared by the LangGraph checkpointer,
LangGraph Store, and DeerFlow application data. The deprecated `checkpointer`
section, when present, overrides the first two for backward compatibility.

Gateway startup automatically repairs the missing run-change schema affecting
some existing databases (#5516). The repair preserves run history and existing
change positions; downgrading the repair to its predecessor also retains the
schema and positions required by that version.

For lightweight single-process event persistence, `run_events.backend: jsonl`
keeps Unicode message content intact, including line and paragraph separators.
Existing valid JSONL records remain readable without rewriting the files.

For per-call usage audits, an immediate LLM response replay with populated usage
updates both nested usage and top-level token counters, even if initial usage was absent or zero.
The original request, model, and status metadata stay intact; flushed events are
not rewritten. See the [run event contract](../../contracts/run_event_stream_contract.json).

The unified nginx endpoint is same-origin by default and does not emit browser CORS headers. If you run a split-origin or port-forwarded browser client, set `GATEWAY_CORS_ORIGINS` to comma-separated exact origins such as `http://localhost:3000`; the Gateway then applies the CORS allowlist and matching CSRF origin checks.

When fine-grained authorization is enabled, Live Browser connections require `threads:write` as well as ownership of the thread, even when only viewing frames: the same connection can control the browser. Permission checks run when connecting. Restart Gateway after upgrading to disconnect sessions admitted by older code.

The bundled Docker, local and Helm nginx configs proxy Live Browser WebSocket upgrades with a 600-second read timeout for quiet streams. Helm uses nginx's default connection and send timeouts for the in-cluster Gateway. Any additional Ingress or reverse proxy must also allow WebSocket upgrades.

Browser login uses `HttpOnly` session cookies. The login page offers a "keep me signed in" option that extends the browser session when the request is HTTPS (including trusted `X-Forwarded-Proto: https`) or localhost HTTP. The localhost exception uses the direct request `Host` and ignores forwarded host headers. Public HTTP deployments, including many temporary sandbox URLs, fall back to session cookies by default. DeerFlow never stores the password in browser storage; the UI may remember only the email address.

If an authentication refresh fails during a temporary network outage, a visible
tab rechecks the unknown session when connectivity returns or on a later tab
switch. Reconnects received in a background tab are remembered until it becomes
visible, without waiting for the tab-switch throttle. Identity is restored only
after a successful auth response; a confirmed expired session or explicit logout
still requires signing in again.

Password forms accept non-ASCII email addresses and trim surrounding email whitespace.
Sign-in requires at least six password characters; creating an account or choosing
a new password requires eight. These checks run before sending a request.
Passwords, including surrounding spaces, are submitted unchanged.

OIDC/SSO authorization endpoints may include provider query parameters such as `?prompt=login`. DeerFlow preserves those parameters when adding the login request, including for configured `authorization_endpoint` overrides.

After an SSO sign-in, DeerFlow returns you to the page that asked you to sign in instead of the default workspace. Opening the login page while already signed in does the same for its `next` target.

Administrators can suspend and restore accounts from **Settings → Users** (admin-only; the section is hidden for ordinary users). The page lists each account's email, role, and status and exposes the same enable/disable operation as `PATCH /api/v1/admin/users/{id}`; the last remaining active admin cannot be disabled, and the Gateway's rejection detail is shown verbatim. A disabled account is rejected by every authentication surface, and its live sessions end on the next request with a login page that states the account has been disabled. Password login for a disabled account deliberately still answers "incorrect email or password" so the state is not disclosed to whoever holds the credentials.

DeerFlow still uses `Forwarded` / `X-Forwarded-*` headers to recover the browser-facing scheme and origin behind a proxy. The bundled nginx sets `X-Forwarded-Proto`, but preserves an upstream HTTPS value and does not overwrite every forwarded header. Configure the outer trusted proxy to replace or strip client-supplied forwarding headers before traffic reaches DeerFlow.

> [!IMPORTANT]
> The Gateway still owns active run tasks in process, so production defaults to a single Gateway worker (`GATEWAY_WORKERS=1`). Multi-worker deployments require Postgres, the Redis stream bridge (`stream_bridge.type: redis`), `run_ownership.heartbeat_enabled: true`, and `run_events.backend: db`; process-local memory/JSONL event stores cannot enforce singleton delivery receipts across workers. Kubernetes replicas run one worker per Pod, which the worker count cannot see: declare them with `deployment.multi_instance: true` (or `DEER_FLOW_MULTI_INSTANCE=1`, which deploy tooling such as a Helm chart can set from its replica count) so the startup gate enforces the same prerequisites instead of staying inert. Declared instances that store credentials (`channel_connections`, or MCP servers using the OAuth `refresh_token` grant, whose rotating tokens they share through the database) must also share one at-rest `DEER_FLOW_CREDENTIALS_KEY` (the Helm chart and `make up` generate it; back it up, see [backend/docs/CONFIGURATION.md](../../backend/docs/CONFIGURATION.md#credentials-encryption-key-deer_flow_credentials_key)). The bridge shares SSE delivery and bounded `Last-Event-ID` replay across workers. When a trimmed reconnect cursor cannot be verified for complete replay, or a subscriber that already established an empty-stream wait falls behind before its first delivery, Memory and Redis emit a machine-readable SSE `gap` event instead of silently returning a partial replay; the Web UI reloads durable thread/event state and resumes from the retained tail. The Memory bridge can replay without recovery when the cursor is its exact last evicted event: every successor is still retained. Older or unverifiable evicted cursors still trigger recovery. An already-observed Redis stream removed during replay also signals a gap, so slow subscribers reload durable state instead of heartbeating forever after cleanup. Redis also tracks terminal stream producers with a short lease: if a worker dies after committing a terminal run status but before publishing END, SSE and `/wait` finish after the lease expires instead of waiting for the retained stream's TTL. Lease reconciliation marks runs from dead workers as errors, persists their delivery receipts, publishes the terminal stream marker, schedules retained-stream cleanup, and updates the affected thread status. Redis END publication is atomic and idempotent: owner and recovery retries confirm an existing marker without appending another, events cannot be appended once END is the stream tail, and an unowned recovery retry after cleanup does not recreate the stream. Legacy streams with an earlier END followed by late data can still accept data. The Redis compatibility scan (`stream_bridge.legacy_end_scan_enabled: true`) also runs on first END publication; disable it only after old writers stop and all legacy replay buffers expire or are removed, then restart every Gateway to use tail-only END detection. SSE, `/wait`, and internal stream consumers use `stream_bridge.heartbeat_interval_seconds` (default `15`) for idle liveness checks; changing it requires a Gateway restart. Malformed Redis reconnect IDs live-tail new events instead of replaying the retained buffer, and the rolling retained-buffer TTL (`stream_ttl_seconds`) remains a cleanup safety net rather than a run timeout. Failed-login counters and lockouts for `POST /api/v1/auth/login/local` (`auth.local.max_login_attempts` / `lockout_seconds`) are kept in the shared `login_throttle` table whenever the application database is SQLite or Postgres (`auth.local.throttle_storage: auto`, the default), so every replica enforces one lockout per client IP; `memory` keeps the historical per-process counter, which under N replicas hands an attacker N × `max_login_attempts` guesses and logs a startup warning. IM chat-to-thread bindings live in the shared `channel_thread_bindings` table whenever the application database is SQLite or Postgres (an existing `channels/store.json` is imported once at startup and renamed `store.json.migrated`); IM bot credentials entered in the web UI live in the shared `channel_runtime_configs` table, encrypted with `DEER_FLOW_CREDENTIALS_KEY` (an existing `channels/runtime-config.json` is imported once and then deleted), so a save on any instance reaches the provider's connection within one lease renewal; each provider's platform connection is held by one instance through the shared `channel_leases` table — `channels.leader_lease` (default `auto`, on wherever the multi-process signal is) hands it to another instance when the holder dies, and the startup gate refuses `enabled: false` while an IM channel other than GitHub is enabled (see [IM channel leader lease](../../backend/docs/CONFIGURATION.md#im-channel-leader-lease-channelsleader_lease)); follow-up buffers still need their own multi-worker coordination. To try this topology on one machine, `make dev-multi` starts two Gateways on shared Postgres, Redis and `DEER_FLOW_HOME`, and `make dev-multi-check` runs the cross-instance checks; see the local two-Gateway harness in [backend/docs/CONFIGURATION.md](../../backend/docs/CONFIGURATION.md#local-two-gateway-harness).
>
> The producer-lease recovery behavior above is gated by `stream_bridge.producer_lease_recovery_enabled`. Keep it disabled while old Gateway binaries or their runs remain; enable it on every instance only after the writer rollout and drain complete.
>
> With run ownership heartbeats enabled, terminal success requires acknowledgment
> from that worker's own durable write. Run creation and replacement serialize
> per conversation: a slow admission does not hold the manager-wide lock needed
> by another conversation's cached run reads or heartbeat snapshots. Their own
> Store I/O can still encounter database or pool contention. New runs remain
> hidden until their initial Store write succeeds. A matching database row alone cannot
> confirm success, and completion metadata cannot retry a rejected terminal
> transition. Each run renews independently, so a stalled store operation does
> not delay other runs. If acknowledgment remains unavailable when the last
> confirmed lease expires, the worker stops conservatively even if its commit
> actually reached the database. Expired leases cannot be renewed.
> Interrupt-and-replace admission acknowledges only the old runs actually claimed
> by its atomic transaction. Rollback keeps renewing its acknowledged interrupted
> row until restoration and the separate final error commit finish. An
> active-only renewal that raced that admission gets one bounded retry after the
> interrupted acknowledgment, without weakening the owner or live-lease checks.
> A failed renewal leaves a local expiry guard armed. Shutdown bounds its wait for orphan
> recovery, but cancellation-resistant storage may still be using its resources.

>
> The local two-Gateway harness disables IM providers under both `channels` and `channel_connections` by default. `DEERFLOW_MI_KEEP_CHANNELS=1` preserves them; `channels.leader_lease` stays as configured.
>
> Cleaning up an in-memory run stream, or closing its bridge, releases retained
> payloads and signals a replay gap to subscribers with unfinished replay. They
> reload durable state instead of waiting on a detached buffer or consuming stale
> history. Established readers that fully consumed a terminal stream retain their
> normal `end` signal. A new reader whose initial attachment loses the race with
> cleanup receives a gap so it can recover the saved result.
>
> In-memory stream events retain the payload as it was published. Reusing a
> producer's data object or editing a received event does not change another
> subscriber's output or reconnect replay.
>
> During SSE replay-gap recovery, the Web UI preserves a reconnect pointer claimed by another run while durable state is loading. An older recovery cannot overwrite that pointer when it rejoins its own stream. Even a stale foreign pointer is preserved, so the next reload may first check that run before active-run recovery rejoins, adding a reconnect cycle.
>
> Store-only SSE and `/wait` consumers can finish after a heartbeat when run-manager
> or scheduled-task reconciliation recovers a dead worker's run, even if no END
> marker was published. Ordinary completions still wait for END to preserve tail events.
>
> In single-process JSONL deployments, cancelling an admitted event-store mutation waits for its background file I/O, rollback, and bookkeeping to settle before releasing the thread write lock. This prevents an older cancelled write from recreating deleted records or rolling back a later successful write. Cancellation can therefore wait on slow storage; it does not stop an in-flight filesystem operation. Callers still waiting to acquire the lock can cancel without starting a mutation. A batch spanning multiple threads drains its current thread group before propagating cancellation; subsequent thread groups do not start.
>
> After a run publishes its terminal stream marker, its process-local `RunRecord` remains available for the existing five-minute grace period before cleanup; durable run history remains available through `RunStore`, while the stream bridge retains its delivery tail on its separate cleanup schedule.
>
> With in-memory run storage, replacing a run snapshot under another thread removes its previous thread membership. Old-thread history and usage queries exclude it, and deleting the old thread preserves the reassigned run.
>
> Run cancellation may land on any Gateway worker. A non-owning worker now persists the interrupt or rollback request for the live owner, which observes it during lease renewal and performs the normal cancellation flow; load-balancer routing alone no longer produces a 409. The first accepted action wins even if a retry lands on the owner, and accepted cancellation competes atomically with owner completion. Dead owners still follow lease takeover and orphan recovery. Cancellation latency is therefore bounded by the lease heartbeat interval.

> Cancelling a model recovery probe, including while it is queued or waiting to retry, lets the next call check whether the provider has recovered. Cancellation does not count as a provider failure or release another call's active recovery probe.
>
> Model retries honor valid provider `Retry-After` hints up to 24 hours, including waits longer than the local backoff cap. Malformed, non-finite, or over-limit hints use normal backoff instead. This applies to numeric and HTTP-date hints in LLM error handling and Codex's retry path, and integer-second hints in Claude's retry path. Codex prioritizes numeric `retry-after-ms` hints; past HTTP-date hints retry immediately.
>
> With lease heartbeat enabled, a transient RunStore renewal error is retried only until the last confirmed lease expires; the stale worker then cancels local execution and suppresses checkpoint, completion-hook, delivery-receipt, and thread-status finalization. A remote tool side effect already in flight may still be outside local cancellation.
>
> Reconciliation uses an atomic takeover claim that re-checks the lease after candidate selection, so a successful owner renewal wins over orphan recovery and only one reconciler can report a run as recovered. When multiple Gateway workers share the Docker/AIO or E2B sandbox backend, also configure `sandbox.ownership.type: redis`; E2B uses the leases during background startup and periodic reconciliation so duplicate/orphan cleanup cannot terminate a live peer's sandbox.

If a completed thread operation (such as a checkpoint, goal, or artifact write,
branch, or deletion) fails to release its database reservation, the same Gateway
worker retries cleanup when it receives a new run or mutation for that thread.
This also works in single-worker deployments with lease heartbeats disabled.
If cleanup fails again, admission returns a busy response. Completed requests
can still replay their saved results by idempotency key.

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for detailed Docker development guide.

## Upgrading an existing checkout

Keep `config.yaml`, `.env`, and `extensions_config.json`. Stop the services you
currently use, run `git pull --ff-only`, then start the same mode again. Do not run
`make config` or `make docker-init` again for a routine source upgrade. If the new
version requires configuration changes, run `make config-upgrade` before restarting.
See [Operations and Troubleshooting](../../frontend/src/content/en/application/operations-and-troubleshooting.mdx#upgrading-an-existing-checkout)
for the commands for each mode.

To continue a thread paused at a static `interrupt_before` or `interrupt_after`
breakpoint, submit `input: null` (or omit `input`) to its `/runs`, `/runs/wait`,
or `/runs/stream` endpoint. This continues pending graph work with the source
turn's knowledge scope from the selected checkpoint (the head by default).
An explicit empty object is new input, not a continuation; dynamic interrupts
still require `command.resume`. In delta mode, historical continuation rejects
rewrites that would discard pending execution; continue at the head instead.
Continuations retain the checkpoint's MCP `background_tasks` projection; only
dictionary input refreshes it from the task repository.
Old null-input runs stored as `{}` cannot safely match a keyed null-input retry
after upgrading and return 409. Check the original run before submitting a new key.

When rolling out the resume-command idempotency fix across multiple Gateway
workers or Pods, route **all keyed resume submissions and retries** (`command.resume`
with `Idempotency-Key`, on thread-scoped `/runs`, `/runs/stream`, or `/runs/wait`)
only to upgraded workers until every worker serving these endpoints is upgraded.
Older workers ignore the private resume identity and compare only `input`: with
`input: null`, retrying `deny` can incorrectly reuse an earlier `approve` run.
If the load balancer cannot isolate upgraded workers, pause keyed resume traffic
until the rollout finishes, or stop all old workers before restarting on the new
version. The additive database migration keeps old run-history readers compatible;
it does not make old workers safe for resume admission. An upgraded worker returns
409 when retrying an identity-less legacy resume run, even for the same decision;
inspect that run and the current thread state before deciding to submit a new
action. See the [run API contract](../../backend/docs/API.md#create-run).

Custom run stores must explicitly support every supplied idempotency field.
Keyed input and resume requests return HTTP 503 before run admission when the
store cannot guarantee that support. The built-in Memory and SQL stores support
both fields; older custom stores with an explicit `idempotency_key` parameter
continue to accept keyed input requests.

Gateway runs also assign IDs to input messages that omit one before storing the
run record and invoking the graph. This keeps the message visible as one turn
when the Web UI reconnects to an active run started by an API client. During a
rolling upgrade, route keyed runs with ID-less input and their retries to
upgraded workers until all Gateway workers are upgraded; older workers may
reject those retries with 409. See the [run API contract](../../backend/docs/API.md#create-run).

## Option 2: Local Development

If you prefer running services locally:

Prerequisite: complete the "Configuration" steps above first (`make setup`). `make dev` requires a valid `config.yaml` in the project root. Set `DEER_FLOW_PROJECT_ROOT` to define that root explicitly, or `DEER_FLOW_CONFIG_PATH` to point at a specific config file. Runtime state defaults to `.deer-flow` under the project root and can be moved with `DEER_FLOW_HOME`; skills default to `skills/` under the project root and can be moved with `DEER_FLOW_SKILLS_PATH`. Run `make doctor` to verify your setup before starting.

Configuration checks and agent-storage migrations use the installed backend environment through `uv run --no-sync --project backend` from the repository root. This preserves relative runtime paths and installed optional dependencies; see the [setup checks](../../backend/docs/SETUP.md#steps) and [agent-storage migration](../../backend/docs/CONFIGURATION.md#agent-storage).

On Windows, run the local development flow from Git Bash. Native `cmd.exe` and PowerShell shells are not supported for the bash-based service scripts, and WSL is not guaranteed because some scripts rely on Git for Windows utilities such as `cygpath`.

The documented root `make` commands invoke repository `.sh` files through Bash
explicitly. They therefore continue to work from source archives or filesystems
that do not preserve POSIX executable bits. When calling a script directly from
such a checkout, use `bash ./scripts/<name>.sh ...`.

1. **Check prerequisites**:
   ```bash
   make check  # Verifies Node.js 22+, pnpm, uv, nginx
   ```

   The local `make check`, `make install`, `make dev`, and `make start` entry points use a direct `pnpm` executable when available and otherwise fall back to `corepack pnpm`. With native Windows Python, the shared runner checks `pnpm.cmd` before the generic `pnpm` lookup, which follows `PATH`/`PATHEXT` and may select an `.exe` or `.bat` in the same or an earlier PATH directory. The Corepack fallback likewise checks `corepack.cmd` before `corepack`. POSIX Python keeps the generic names first, including when running under MSYS/Cygwin. The runner and diagnostics resolve repository paths absolutely, so these checks work regardless of the caller's current directory. Corepack runs from `frontend/`, so it honors the `packageManager` version pinned in `frontend/package.json`; enabling a global pnpm shim is not required.

   `make check` decodes tool diagnostics as UTF-8 and preserves Unicode pnpm
   errors on non-UTF-8 hosts. Invalid output bytes are replaced so the checker
   can report dependency failures instead of aborting while decoding output.

2. **Install dependencies**:
   ```bash
   make install  # Install backend + frontend dependencies + pre-commit hooks
   ```

   Hook setup calls pre-commit through uv, so uv's tool directory need not be on `PATH`.

3. **(Optional) Pre-pull sandbox image**:
   ```bash
   # Recommended if using Docker/Container-based sandbox
   make setup-sandbox
   ```
   Reads the configured sandbox image from UTF-8 `config.yaml`, with or without a leading BOM, using LF or CRLF line endings.
   On macOS, a successful Apple Container pull completes this step even when Docker is not installed. If Docker is available, its image is also pulled.

4. **Start services**:
   ```bash
   make dev
   ```

   Local nginx writes temporary files under the checkout's `temp/` directory.

5. **Access**: http://localhost:2026

6. **(Optional) Load sample memory data for local review**: open `Settings > Memory`, click **Import memory**, and select `backend/docs/memory-settings-sample.json`. The browser imports into the signed-in user's memory.

   To replace memory for every registered user in a disposable review environment:

   ```bash
   cd backend
   uv run python ../scripts/load_memory_sample.py --all-users
   ```

   Bulk mode supports SQLite/PostgreSQL user registries, creates a distinct timestamped backup directory for every import under `.deer-flow/memory-sample-backups/`, and rejects the non-persistent `database.backend: memory` mode. See [backend/docs/MEMORY_SETTINGS_REVIEW.md](../../backend/docs/MEMORY_SETTINGS_REVIEW.md) for the complete review flow.

Local services always use their internal ports (`8001`, `3000`, and `2026`).
The root `.env` variable `PORT` configures only the published Docker ingress;
it does not change the Next.js port used by `make dev`.

Local startup waits up to 30 seconds for the Gateway port. On a slow cold start,
set a longer wait without editing the launcher:

```bash
DEER_FLOW_GATEWAY_STARTUP_TIMEOUT=240 make dev
```

The value must be a positive integer in seconds. You can also set it in the
root `.env`, whose value takes precedence over the shell. It applies to local
`make dev`, `make start`, and their daemon variants, not Docker health checks
or LLM request timeouts. Check `logs/gateway.log` for startup errors before
increasing the wait; an expired deadline still stops the services.

## Startup Modes

DeerFlow runs the agent runtime inside the Gateway API. Development mode enables hot-reload; production mode uses a pre-built frontend.

| | **Local Foreground** | **Local Daemon** | **Docker Dev** | **Docker Prod** |
|---|---|---|---|---|
| **Dev** | `./scripts/serve.sh --dev`<br/>`make dev` | `./scripts/serve.sh --dev --daemon`<br/>`make dev-daemon` | `./scripts/docker.sh start`<br/>`make docker-start` | — |
| **Prod** | `./scripts/serve.sh --prod`<br/>`make start` | `./scripts/serve.sh --prod --daemon`<br/>`make start-daemon` | — | `./scripts/deploy.sh`<br/>`make up` |

| Action | Local | Docker Dev | Docker Prod |
|---|---|---|---|
| **Stop** | `./scripts/serve.sh --stop`<br/>`make stop` | `./scripts/docker.sh stop`<br/>`make docker-stop` | `./scripts/deploy.sh down`<br/>`make down` |
| **Restart** | `./scripts/serve.sh --restart [flags]` | `./scripts/docker.sh restart` | — |

Local and Docker development stop commands also stop running sandbox containers
whose names start with `deer-flow-sandbox-`. Containers with that text elsewhere
in their names are left alone.

`make start` and `make start-daemon` rebuild the frontend with `next build` on
every run. To reuse the last build instead, pass `SKIP_FRONTEND_BUILD=1` (or add
`--skip-frontend-build` when calling `./scripts/serve.sh --prod` directly). This
is opt-in: it fails fast when `frontend/.next` has no completed build.

Gateway owns `/api/langgraph/*` and translates those public LangGraph-compatible paths to its native `/api/*` routers behind nginx.

Cold agent imports during run creation use a dedicated worker pool, keeping
unrelated Gateway requests responsive while the agent stack loads. A failed
factory import prevents the run from being admitted.

For a read-only demo without the Gateway, run `make build-static` from `frontend/`,
then `HOSTNAME=127.0.0.1 PORT=3000 node --env-file=.env .next/standalone/server.js`
from the same directory. The build includes public demo assets and resolves
supported demo API reads locally; writes are unavailable. To display the homepage
GitHub star count, set `GITHUB_OAUTH_TOKEN` in `frontend/.env` before starting Node.
The token stays on the server; missing credentials or GitHub failures hide the
count. Restart Node after changing the token; no rebuild is needed.

## LangGraph Studio (Optional)

The default `make dev` topology uses DeerFlow's Gateway-embedded runtime and
does not require LangGraph Studio. To inspect and test the registered lead-agent
graph with the standalone development server, run the command from `backend/`
so the CLI discovers `langgraph.json`:

```bash
cd backend
uv run langgraph dev --allow-blocking
```

The command prints the local API and Studio UI URLs. This in-memory server is
for development and testing only. The flag permits DeerFlow's synchronous
configuration and graph-factory setup during local Studio requests; it must not
be treated as a production-server setting. Local Studio authentication is
handled automatically, so the connection does not require custom headers. Use
DeerFlow's documented production startup modes or a supported LangSmith
deployment for production workloads. Assistant ownership and provenance in this
standalone mode are server-owned: Studio can discover registered graphs and the
assistants it creates, and normal assistant-version selection remains available.
Before the locked local runtime loads its persisted development store, DeerFlow
repairs legacy assistant rows and version history so historical client metadata
cannot restore server privileges or be discarded by the runtime's startup
cleanup. Keep the backend dependencies synchronized with `uv sync`; this
compatibility path requires the declared LangGraph runtime versions and logs a
warning if the persisted-store contract no longer matches its expectations.
The documented command uses LangGraph's file-based custom-app loader, which is
also covered directly by DeerFlow's regression tests.

Standalone runs using `if_not_exists="create"` retain config and run metadata
on the newly created thread, including searchable tags; run metadata takes
precedence for duplicate keys. Thread ownership and MCP incarnation remain
server-owned, and later runs do not replace the thread's creation metadata.

For workflows that invoke `backend/langgraph.json` through LangGraph Studio or
a direct LangGraph Server, DeerFlow consumes the authenticated identity
published by that runtime and uses it for custom-agent configuration/SOUL, user
skills and skill policy, uploads, thread data, and memory reads/writes. This
keeps authenticated runs out of the shared `default` filesystem bucket, and the
server-owned identity takes precedence over ordinary client-supplied `user_id`
values. External identities such as email addresses are mapped to stable,
collision-resistant directory-safe user IDs before accessing DeerFlow storage.
The default DeerFlow service topology remains the Gateway-embedded runtime
described above.

Gateway runs automatically enforce native delivery for artifacts created or modified under `/mnt/user-data/outputs`: `present_files` must present at least one output produced by the current run, and the terminal `run.delivery` receipt must be durably recorded. Virtual artifact paths are resolved within the same authenticated user and thread scope that produced the output before the output-directory boundary is validated. Runs that do not produce output artifacts keep ordinary conversational behavior.

Thread-scoped `runs.wait()` calls that finish with `status: error` report the current run error instead of an earlier answer. The asynchronous Python LangGraph SDK raises by default; pass `raise_error=False` to inspect the returned status and error.

DeerFlow's built-in custom events are available through both LangGraph streaming interfaces: native clients can continue subscribing to `stream_mode="custom"`, while callback-based integrations can consume the same payloads as `on_custom_event` records from `astream_events(version="v2")`. The callback event name matches the payload's `type` field.

## Docker Production Deployment

`./scripts/deploy.sh` supports building and starting separately:

```bash
# One-step (build + start)
./scripts/deploy.sh

# Two-step (build once, start later)
./scripts/deploy.sh build       # build all images
./scripts/deploy.sh start       # start pre-built images

# Stop
./scripts/deploy.sh down
```
