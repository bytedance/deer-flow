# User sandbox pools

This optional provider reuses a Docker sandbox across an authenticated user's
ordinary conversations. Each user has a separate container; different chats for
that user wait until the preceding sandbox lease ends. A per-conversation view
selects that chat's persistent files and shell sessions. Explicit Agent skill
allowlists retain separate, per-thread containers.

## Deployment boundary

Use one Gateway process on one Docker host. A held file lease rejects a second
pool owner sharing the same DeerFlow home. This implementation does not provide
distributed capacity accounting or multi-Gateway routing. Keep the original AIO
provider for those deployments until a distributed pool coordinator is added.

Conversations in a user pool share the user's installed environment, browser,
and ability to access that user's data mount. Directories and serial execution
prevent ordinary work from mixing files; they are not an adversarial security
boundary within one user. Use thread isolation for untrusted execution or Agent
policies requiring separate skills. Different users' mounts remain separate.

## Configuration

After the storage migration below, select:

```yaml
sandbox:
  use: deerflow.community.aio_sandbox.user_pool:UserAioSandboxProvider
  image: YOUR_EXISTING_AIO_IMAGE
  container_prefix: ddfw-pooled-sandbox
  replicas: 2
  acquire_timeout: 600
  idle_timeout: 3600
  prewarm_on_login: true
  ownership:
    type: memory
  network:
    mode: public
    proxy_image: YOUR_EXISTING_PROXY_IMAGE
    address_pool: 10.240.0.0/16
    subnet_prefix: 28
```

The sample address pool must first be checked against the company's LAN/VPN
routes and existing Docker networks. Each sandbox uses two /28 bridge networks,
16 addresses per network. Allocation skips existing subnets; Docker is the
atomic allocation authority if two creators race. This does not change Docker's
global daemon settings or other applications' networks.

`replicas` is a hard cap on active plus warm containers, including explicitly
isolated Agent containers. Active containers are never evicted for capacity;
idle ones are evicted first, otherwise callers wait. Admission is bounded to 64
async acquisitions on eight dedicated workers, separate from tool-execution
workers. Queue cancellation drains any started provisioning and rolls back its
result before returning. A timeout returns a retryable explanatory tool error.

Keep Docker resource limits enabled on the Gateway environment:
`DEER_FLOW_SANDBOX_MEMORY=2g`, `DEER_FLOW_SANDBOX_CPUS=1`, and the existing PID
limit. Size the hard cap with headroom for RAGFlow, Elasticsearch and Gateway.
The local 16 GiB Docker deployment uses two slots initially. Increase the cap
only after measuring simultaneous workloads.

Authenticated `/api/v1/auth/me` requests schedule optional prewarming after a
live `sandbox:execute` authorization check. It does not block the response, runs
at most once per user per five minutes, and skips when capacity is already full.
Initial startup, expiry, permission-policy changes and process cleanup can still
require a cold start. This is not a promise that all tasks start in one second.

After a task, managed shell sessions and the user's terminal server are closed.
Commands tag their subprocesses; containers with lingering tagged processes are
recycled instead of handing those jobs the next chat's current directory.
Runtime packages remain available while a container stays warm; persistent
workspace/upload/output files survive container recycling.

## Offline storage migration

Stop the Gateway and drain existing sandbox tasks first. Back up `config.yaml`
and the DeerFlow home as appropriate. From the backend's Python environment:

```python
from deerflow.community.aio_sandbox.user_storage import migrate_user_data
migrate_user_data("/absolute/path/to/.deer-flow")
```

For each user, this moves only:

* `threads/<thread>/user-data` to `sandbox-data/<thread>`;
* `threads/<thread>/acp-workspace` to `sandbox-acp/<thread>`.

Conversation metadata, checkpoints, credentials and skill projections stay out
of these data mounts. Existing files are never overwritten. A conflict fails the
migration; already-completed moves can resume. The `.user-sandbox-data-v1` marker
is written after all moves and selects the layout on process startup. Do not
remove the marker or start the Gateway halfway through an unfinished migration.
Thread deletion and artifact/upload paths understand both layouts.

Restart the Gateway after updating the provider configuration. Old thread
sandboxes must be drained/stopped before migration so they cannot keep writing
through obsolete mounts.

## Cleanup and rollback

The pool's periodic cleanup checks labels, exact prefix-derived network names,
creation age and all container references, including stopped containers. Only
its own old empty networks are removed, under the creation lock and single-owner
lease. It never runs a global Docker prune or removes application data volumes.

To revert execution mode, stop/drain the Gateway, switch `sandbox.use` back to
`deerflow.community.aio_sandbox:AioSandboxProvider`, and restart. Keep the storage
marker and migrated files: the original provider also reads this persistent
layout through `Paths`. Restore the old directory layout only as a separate
offline operation with an explicit file-integrity check.
