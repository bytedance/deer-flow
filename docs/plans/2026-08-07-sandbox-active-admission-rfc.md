<!-- Responds to https://github.com/bytedance/deer-flow/issues/4702.
     Current-system claims are pinned to the code as of 2026-08-08. -->

# RFC: Sandbox Active Admission and Per-User Quotas

**Status:** Draft for feedback.
**Scope:** Active sandbox-use admission, hierarchical deployment/user limits,
admin-managed user overrides, and observable rejection behavior.
**Non-goals:** Refactoring provider acquire locks or identity helpers; replacing
provider `replicas`; unifying warm-pool implementations.

## 1. Summary

DeerFlow needs a deployment-wide limit on concurrently active sandbox work and
an independently configurable limit for each user. This RFC introduces a small
`SandboxAdmissionController` above `SandboxProvider` and a pluggable
memory/Redis permit store.

The controller owns **active-use permits only**. A permit starts immediately
before the provider acquire path and ends when the run, request, or channel
operation releases the sandbox. Warm sandboxes do not hold active permits
because no execution is using them.

Provider capacity remains separate:

- `sandbox.replicas` continues to describe provisioned provider resources using
  each provider's existing semantics.
- E2B keeps its current reservation, remote tracking, reconciliation, and
  `wait`/`reject`/`burst` behavior unchanged.
- This RFC does not claim that an active admission limit bounds the number of
  warm or otherwise provisioned resources.

That separation is the main design decision. User fairness and physical
resource safety have different states, failure policies, and recovery sources.

## 2. Motivation and current state

Issue [#4702](https://github.com/bytedance/deer-flow/issues/4702) asks for user A
to have one concurrency limit, user B another, while all users remain bounded by
a service-level limit.

Today:

- `SandboxProvider.acquire()` already receives the effective `user_id` and
  `thread_id`, so the execution identity exists at the lifecycle boundary.
- sandbox acquisition is lazy by default and release runs from
  `SandboxMiddleware.after_agent` / `aafter_agent`;
- AIO, BoxLite, and Tenki treat `replicas` as a soft provisioned-resource cap;
- E2B has a hard provider-specific capacity mechanism that counts active, warm,
  reserved, transitioning, and uncertain remote resources;
- no provider enforces a user-level active concurrency limit.

Adding user counters independently inside every provider would duplicate Redis
atomicity, TTL recovery, error handling, configuration, metrics, and tests. But
generalizing E2B physical capacity into active admission would discard important
E2B semantics. The correct shared seam is therefore above providers.

## 3. Definitions

### 3.1 Active admission permit

One permit represents one `AdmissionIdentity` admitted to use a sandbox. It
includes the provider-acquire interval, so queued or creating work cannot bypass
the concurrency gate, and then covers active work until release.

```python
class AdmissionKind(enum.StrEnum):
    RUN = "run"
    UPLOAD = "upload"
    ARTIFACT_UPDATE = "artifact_update"
    CHANNEL_ATTACHMENT = "channel_attachment"


@dataclass(frozen=True)
class AdmissionIdentity:
    user_id: str
    execution_id: str
    thread_id: str
    kind: AdmissionKind
```

For agent work, `execution_id` is the stable Gateway `run_id`; embedded paths
without one stamp a `run_attempt_id` once before middleware execution. Re-admit
by the same holder is idempotent and does not increment a counter twice. The
store also maintains an exclusive logical-sandbox-scope index derived from
`(user_id, thread_id)`. A different live identity for that scope receives
`SCOPE_BUSY` rather than sharing the sandbox. Including `thread_id` in the
permit identity allows one execution to use more than one independently
isolated sandbox scope without undercounting.

DeerFlow's run persistence already enforces at most one pending/running run per
thread through `uq_runs_thread_active`. Admission preserves that invariant; it
does not make one provider sandbox safe for concurrent runs. If an abnormal or
embedded path bypasses the database constraint and attempts a second live
execution for the same user/thread scope, the store's scope index rejects it
rather than sharing the physical sandbox. Provider capacity continues to govern
the physical resource (§3.2).

The deployment and user checks happen atomically:

```text
user_active < effective_user_limit
AND deployment_active < deployment_active_limit
```

A zero limit means unlimited. A user override may change the user limit but
never bypasses the deployment limit.

### 3.2 Provider capacity slot

A provider capacity slot represents a provisioned or provision-in-progress
resource according to that provider. Warm resources normally continue to hold
capacity slots. E2B reservations and transition tombstones are capacity state,
not active-admission state.

### 3.3 Admission key

The admission key is a versioned, domain-separated digest of the complete
`AdmissionIdentity`, including `kind`, for example
`admission:v1:<sha256(canonical_identity_bytes)>`. It is an opaque ledger key,
not the provider sandbox id and not a reversible identifier. The full identity
fields are also stored with the permit so a mismatch fails closed.

Using a logical scope instead of a provider sandbox id allows admission to occur
before E2B has returned a remote id and keeps admission independent of provider
identity algorithms.

Key derivation belongs to `deerflow.sandbox.admission.identity`, next to the
canonical `AdmissionIdentity` encoding. It deliberately does not reuse the
provider identity helper: provider resource identity and admission permit
identity are separate compatibility domains. The two RFCs can therefore land in
either order.

### 3.4 Non-run acquisitions

Four call sites acquire sandboxes outside any run context:

- channel file receive (`app/channels/dingtalk.py`, `app/channels/feishu.py`);
- upload sync into the sandbox (`app/gateway/routers/uploads.py`);
- artifact update (`app/gateway/routers/artifacts.py`).

V1 charges all four paths. Each already has a bounded coroutine/request
lifecycle and receives a synthetic, stable-for-that-operation `execution_id`:

- upload and artifact HTTP paths use the trusted request id;
- channel attachment paths use a domain-separated channel/message/resource id;
- a generated UUID is allowed only when no stable external id exists, and is
  retained for the entire coroutine.

Every path acquires through the controller and releases in `finally`. Artifact
update already does this at the provider level; upload and channel attachment
paths are changed to do the same. This moves their provider entry to the warm
pool after synchronization rather than leaving it indefinitely active. The
resource remains available for fast reclaim, while user and deployment active
limits cannot be bypassed through concurrent non-run requests.

## 4. Architecture

```text
trusted run/request/channel context
  AdmissionIdentity + effective user limit
                |
                v
SandboxMiddleware / sandbox lazy-init helper
                |
                v
SandboxAdmissionController ---- SandboxAdmissionStore
                |                  memory | redis
                v
         SandboxProvider
        AIO | E2B | BoxLite | Tenki | Local
                |
                v
 provider-private capacity and lifecycle
```

`SandboxAdmissionController` is owned alongside the sandbox-provider singleton
and exposes orchestration methods rather than changing `SandboxProvider`:

```python
class SandboxAdmissionController:
    def acquire(
        self,
        provider: SandboxProvider,
        identity: AdmissionIdentity,
        *,
        user_limit: int,
    ) -> str: ...

    async def acquire_async(... ) -> str: ...

    def release(
        self,
        provider: SandboxProvider,
        sandbox_id: str,
        identity: AdmissionIdentity,
    ) -> None: ...
    async def release_async(... ) -> None: ...

    def release_execution(
        self,
        provider: SandboxProvider,
        *,
        user_id: str,
        execution_id: str,
        kind: AdmissionKind,
    ) -> None: ...
```

The controller records the local `(sandbox_id, AdmissionIdentity)` binding after a
successful provider acquire. Release receives the same trusted identity,
verifies that binding, and ends both lifecycles exactly once. If provider acquire
fails, the controller releases the permit as a compensating action.

`after_agent` is the normal fast release path for runs, but it is not the sole cleanup
authority: exceptions and cancellation may bypass it. The Gateway run task calls
`release_execution()` from its outer `finally`, releasing every binding owned by
that execution. This finalizer is idempotent with middleware release. It prevents
a live Gateway heartbeat from renewing a permit forever after its run ended.

The controller, not individual providers, owns permit renewal. Its heartbeat
renews all locally active permits regardless of whether the selected provider
uses the ownership component. This is required for BoxLite and Tenki, which do
not have an ownership renewal loop.

## 5. Store contract

```python
class AdmissionStatus(enum.StrEnum):
    GRANTED = "granted"
    USER_LIMIT = "user_limit"
    DEPLOYMENT_LIMIT = "deployment_limit"
    SCOPE_BUSY = "scope_busy"


@dataclass(frozen=True)
class AdmissionLimits:
    user_limit: int
    deployment_limit: int


class SandboxAdmissionStore(abc.ABC):
    supports_cross_process: bool

    def admit(
        self,
        identity: AdmissionIdentity,
        *,
        limits: AdmissionLimits,
        holder_id: str,
    ) -> AdmissionDecision: ...

    def renew(
        self, identity: AdmissionIdentity, *, holder_id: str
    ) -> RenewOutcome: ...
    def release(self, identity: AdmissionIdentity, *, holder_id: str) -> None: ...
    def usage(self, *, user_id: str | None = None) -> AdmissionUsage: ...
    def close(self) -> None: ...
```

Required semantics:

- checking both limits and creating a permit is one atomic operation;
- the store derives the admission key from the complete identity using the
  canonical admission encoding for admit, renew, and release; callers do not
  supply an independently constructed ledger key;
- in that same operation, the store claims an exclusive scope index derived
  from `(user_id, thread_id)`; another live identity for that scope receives
  `SCOPE_BUSY`;
- the same identity and holder is idempotent;
- a different live holder for the same identity receives `SCOPE_BUSY`;
- release and TTL expiry remove both the permit and its scope-index claim;
- a key associated with another user is an integrity error;
- a live holder cannot be released by a different holder;
- permits have a finite TTL and are renewed while locally active;
- a crashed Gateway frees its permits after the TTL;
- lowering a limit below current usage prevents new admits but does not kill
  active work;
- changing an admin user override is expected and is not configuration drift.

The deployment limit may have a Redis metadata drift guard because it is static
operator configuration. Per-user limits must not use such a guard because they
are intentionally mutable database values.

### 5.1 Memory backend

The memory backend uses one process-local lock and a monotonic expiry timestamp.
It is the zero-dependency default and is honest about
`supports_cross_process=False`.

When a non-zero limit is enabled with multiple Gateway instances, startup emits
a warning unless the Redis backend is configured.

### 5.2 Redis backend

The Redis backend performs admit, renew, release, and expired-entry cleanup
atomically with Lua. Its endpoint resolution follows the existing sandbox
ownership/stream-bridge Redis resolution rules.

Redis admission uses its own key prefix and schema. It does not reuse or migrate
the E2B capacity hash; the ledgers represent different facts.

## 6. Quota source and trust boundary

The nullable `sandbox_quota` column is added to the user record:

```text
effective_user_limit = user.sandbox_quota
                       ?? sandbox.admission.per_user_limit
```

The Gateway resolves this value while building an authenticated run, request, or
channel-operation context. The quota and identity context keys are internally
stamped after authentication; client-supplied values for those keys are dropped,
following the existing trusted-context pattern. Run setup guarantees a non-empty
`run_id` or stamps one `run_attempt_id` for embedded execution. HTTP and channel
paths build their synthetic identities from trusted request/message data.
Scheduled/internal runs resolve against their owning user. Auth-disabled mode
uses the default user and therefore remains configurable.

Harness code receives only the resolved integer. It does not import the Gateway
user repository or perform synchronous database reads from a provider.

DB changes include the ORM field, Pydantic user model, repository mappings, and
an idempotent Alembic revision.

## 7. Configuration and admin API

```yaml
sandbox:
  admission:
    type: redis                 # memory | redis
    per_user_limit: 0           # 0 = unlimited
    deployment_active_limit: 0  # 0 = unlimited
    backend_failure_policy: closed  # closed | open
    renewal_interval_seconds: 30
    ttl_multiplier: 4
```

`backend_failure_policy` defaults to `closed`: an unavailable ledger must not
silently defeat an operator's hard limit. Operators who prioritize availability
may explicitly choose `open`; that mode logs an error and increments a metric on
every bypass.

Admin endpoints, gated by `require_admin_user`:

```text
GET /api/users?cursor=...
  -> [{ id, email, sandbox_quota, effective_limit, active_usage }]

GET /api/users/{id}/sandbox-quota
  -> { sandbox_quota, effective_limit, active_usage }

PUT /api/users/{id}/sandbox-quota
  <- { sandbox_quota: integer|null }
```

The list endpoint is included because an API keyed only by an unknown user UUID
is not an operable admin surface. A dedicated authorization permission can
replace the initial `system_role == admin` gate when pluggable authorization owns
user-administration permissions.

## 8. Rejection behavior

`SandboxAdmissionRejected` is a `SandboxError` carrying a stable code, scope,
current usage, limit, and retryability.

For the production lazy-init path, sandbox tools convert this exception into a
`ToolMessage` whose `deerflow_tool_meta` explicitly classifies the result as a
recoverable capacity error. It is not left to string heuristics. Repeated quota
rejections participate in the existing ToolProgress policy and must not be
mistaken for new information.

For an explicitly configured eager-init path, no tool call exists to receive a
`ToolMessage`; the middleware raises a typed run error. The Gateway maps it to a
stable run failure payload rather than promising tool-level recovery where none
is possible.

For non-run HTTP paths, rejection maps to HTTP 429 with the same stable error
code and usage details. Channel attachment paths return their existing
user-visible failed-load marker and emit the structured rejection to logs and
metrics; they do not start an agent run merely to report quota exhaustion.

## 9. Lifecycle and race rules

```text
admit permit
  -> provider.acquire
     -> bind sandbox id to permit
        -> agent/tool work
           -> provider.release
              -> release permit
```

- Provider acquire failure releases the permit.
- When a synchronous provider acquire is offloaded to a worker thread, it runs
  in a shielded future. Cancellation of the awaiting coroutine does not cancel
  or forget the blocking worker.
- If that future later fails, its completion cleanup releases the permit. If it
  later succeeds, cleanup releases the returned sandbox first and then releases
  the permit. The permit remains renewed until that deferred cleanup completes.
- Deferred cleanup runs off the event loop and is idempotent with the outer run
  or request finalizer.
- Release is idempotent.
- Provider release and permit release are sequenced with `try/finally`: once the
  run has stopped using the sandbox, a provider cleanup failure must not retain
  an active-use permit. Provider capacity/reconciliation owns the uncertain
  physical resource.
- The Gateway run task calls `release_execution()` in its outer `finally`, so
  failure or cancellation cannot leave a live-process heartbeat renewing a dead
  run.
- Heartbeat starts tracking only after admit and stops only after release.
- A process crash relies on TTL expiry.
- A Redis restart may lose permits. Live holders re-admit only their own keys;
  during reconstruction the documented failure policy applies.
- Admission never destroys a sandbox when a limit is lowered.
- Provider shutdown releases known permits best-effort; TTL is the final safety
  net.

## 10. Rollout plan

### Phase 1: contract and controller, limits off

- add config, memory/Redis contract suites, controller, renewal, and metrics;
- route every run and non-run acquire/release call through the controller;
- add `finally` release to upload and channel attachment synchronization;
- install the Gateway run-finalizer cleanup path and cancellation tests;
- keep all limits at zero while validating the intentional non-run lifecycle
  correction (completed synchronization moves the sandbox to warm);
- add blocking-IO tests for every Redis call reachable from async code.

### Phase 2: static hierarchical limits

- enable config-level user and deployment active limits;
- add exact-boundary, concurrent-admit, cancellation, TTL, backend-failure, and
  multi-instance Redis tests;
- document that `replicas` and active admission control different quantities.

### Phase 3: per-user overrides

- add migration, repository/model propagation, trusted run-context resolution,
  admin endpoints, and audit logging;
- enable limits only after every Gateway instance runs admission-aware code.

### Phase 4: operator UI and follow-ups

- add the frontend quota-management surface if required;
- consider metrics history and a dedicated authz permission;
- evaluate Local-provider inclusion from actual hosted-local demand. The
  controller can apply to Local, but defaults remain unlimited.

## 11. Compatibility, rollback, and observability

- `SandboxProvider` remains unchanged.
- Existing `replicas`, `idle_timeout`, ownership, and E2B overflow configuration
  retain their meanings.
- Limits default to zero, so the initial rollout adds no admission rejection.
  Non-run `finally` cleanup is an explicit lifecycle correction and is not fully
  behavior-neutral.
- The database column is additive and nullable.
- Disabling limits stops new enforcement; existing permit keys expire naturally.

Minimum metrics:

```text
sandbox_admission_granted_total
sandbox_admission_rejected_total{scope}
sandbox_admission_backend_errors_total{operation,policy}
sandbox_admission_active{scope}
sandbox_admission_renew_lost_total
```

## 12. Acceptance criteria

- N concurrent users cannot exceed the deployment active limit.
- One user cannot exceed their effective limit while other users retain access.
- User and deployment checks are atomic in both backends.
- Warm sandboxes do not consume active permits and still remain governed by
  provider capacity.
- E2B capacity behavior and ledger schema are unchanged.
- A cancelled or failed acquire does not leak a permit.
- A cancelled threaded acquire that completes later releases both the returned
  sandbox and its permit.
- Upload, artifact-update, and channel-attachment operations are charged permits
  and release them in `finally`.
- The existing database constraint or the admission scope index rejects a
  second active run for one thread; it never shares the sandbox.
- BoxLite and Tenki permits remain live without ownership stores.
- Lowering a quota blocks new work without killing active runs.
- Lazy rejection produces structured tool metadata; eager rejection produces a
  stable typed run error.
- Redis failure follows the configured policy and is observable.

## 13. Rejected alternatives

### Put counters in every provider

Rejected because atomic quota policy, TTL recovery, configuration, API behavior,
and metrics would drift across providers.

### Generalize E2B capacity into admission

Rejected because E2B capacity tracks physical resources and creation
reservations, while user admission tracks active logical work. Sharing a ledger
would either undercount warm resources or keep users blocked by idle warm VMs.

### Query the user database from providers

Rejected because it crosses the Gateway/harness boundary, introduces async DB IO
into synchronous provider paths, and makes community providers depend on app
storage.

### Fail open unconditionally

Rejected because an operator-configured deployment limit is commonly a resource
protection boundary. Availability-oriented deployments can opt in explicitly.
