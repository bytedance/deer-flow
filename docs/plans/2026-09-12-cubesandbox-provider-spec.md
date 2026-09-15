# Spec: CubeSandbox Provider (L1 Integration)

**Status:** Draft for feedback
**Affects:** `backend/packages/harness/deerflow/community/` (new module), `backend/packages/harness/deerflow/sandbox/` (no contract changes), `backend/tests/`, `config.example.yaml`, `backend/packages/harness/deerflow/sandbox/AGENTS.md`
**Tracked branch:** `feat/cubesandbox-provider`

## Problem Statement

DeerFlow gives every agent thread a "virtual computer" through the `SandboxProvider`
abstraction, but operators who need **hardware-grade isolation for untrusted,
LLM-generated code** have no self-hostable option today:

- The default production backend (`AioSandboxProvider`) runs Docker containers that
  **share the host kernel**. Container escape is a real risk class for agentic
  workloads, and our own docs state Local is *not* a security boundary.
- The hardware-isolated providers we do ship (`E2BSandboxProvider`,
  `BoxliteProvider`, `TenkiSandboxProvider`) are either external clouds or specific
  virtualization stacks. An operator who wants "KVM microVMs on my own machines"
  has no provider to select.
- Cold-start latency (seconds) is compensated by warm pools that pin memory. A
  backend with millisecond snapshot-based boot would make that compensation
  unnecessary.

[CubeSandbox](https://github.com/TencentCloud/CubeSandbox) (Tencent Cloud,
open-sourced 2026-04) is a self-hostable microVM sandbox service built on
RustVMM + KVM: hardware isolation per sandbox, <60ms cold start via pre-snapshotted
templates, <5MB per-sandbox overhead, stateless control plane coordinated through
Redis, and **E2B SDK compatibility** as a first-class feature. It is an attractive
execution substrate for DeerFlow — but there is no provider for it.

## Solution

Add an **optional, config-selected `CubeSandboxProvider`** that implements the
existing `SandboxProvider` contract against CubeSandbox's E2B-compatible API,
reusing the E2B provider's client/upload/serialization machinery wherever
semantics align.

The integration is deliberately shallow (L1 of the fusion roadmap):

- Selected via `sandbox.use` class-path config — **one line switches the backend**;
  default deployments are untouched.
- v1 keeps DeerFlow's existing lifecycle semantics: warm pool via the shared
  `WarmPoolLifecycleMixin`, `AcquireSerializer` per `(user_id, thread_id,
  skills_root)`, per-thread skills projection upload. CubeSandbox-native
  capabilities (pause/resume, snapshot clone/rollback, CubeEgress credential
  injection) are **not** wired in v1.
- v1 is **single-instance only**: `supports_cross_process = False` (memory
  ownership). Multi-instance ownership is follow-up work.
- A **Phase-0 API-parity gate** precedes any conformance claim: we verify the
  E2B-compatible surface CubeSandbox actually ships against the contract our E2B
  machinery depends on, and record divergences as explicit provider behavior.

## User Stories

1. As a **platform operator**, I want to select CubeSandbox as the sandbox backend
   with one `sandbox.use` line in `config.yaml`, so that I can adopt it without
   code changes or a fork.
2. As a **platform operator**, I want CubeSandbox to be strictly opt-in, so that
   my existing Local/AIO/E2B deployments are completely unaffected.
3. As a **platform operator**, I want the provider to be lazy-imported with its
   SDK as an optional dependency, so that installations that never select it pay
   no import or dependency cost.
4. As a **security engineer**, I want agent-executed commands to run inside KVM
   microVMs with an independent guest kernel, so that LLM-generated code cannot
   escape through a shared host kernel.
5. As a **security engineer**, I want the existing `sandbox:execute` authorization
   gate to apply unchanged to the new provider, so that role-based deny keeps
   working on first use *and* on sandbox reuse.
6. As a **security engineer**, I want inherited secret-looking environment
   variables (`*KEY*`/`*SECRET*`/`*TOKEN*`/`*PASS*`/`*CREDENTIAL*`) scrubbed before
   any command runs, so platform credentials never leak into skill subprocesses.
7. As a **security engineer**, I want per-call secrets injected through fresh exec
   sessions only, so nothing sensitive persists in long-lived shell sessions.
8. As an **agent skill developer**, I want the `/mnt/user-data/{workspace,uploads,
   outputs}` and `/mnt/skills` virtual-path contract to work identically on
   CubeSandbox, so my skills need no backend-specific code.
9. As an **agent skill developer**, I want the seven sandbox operations
   (`execute_command`, `read_file`, `write_file`, `list_dir`, `glob`, `grep`,
   `update_file`) to behave exactly as they do on other providers, so tool
   prompts and skills stay provider-agnostic.
10. As a **platform operator**, I want each `(user_id, thread_id)` pair to map to a
    deterministic sandbox identity, so consecutive turns reuse the same sandbox
    and mid-turn state survives.
11. As a **platform operator**, I want released sandboxes kept warm with bounded
    replicas and idle timeout, so turn-to-turn latency stays low without
    unbounded resource growth.
12. As a **platform operator**, I want overlapping acquire/release/sync operations
    for the same thread serialized, so concurrent runs cannot interleave a wipe
    with an upload.
13. As an **agent policy administrator**, I want explicit-agent-policy threads to
    receive the four managed skills categories via the same signed projection
    sync as E2B, so skill isolation policies hold on the new backend.
14. As an **SRE**, I want the provider to declare `supports_cross_process = False`
    in v1 and log a clear startup warning under multi-instance deployments, so I
    cannot accidentally run a half-HA configuration.
15. As an **SRE**, I want `get()` to remain a pure in-memory lookup, so the event
    loop is never blocked by sandbox I/O on tool paths (Blockbuster-enforced).
16. As an **SRE**, I want live integration tests against a real CubeSandbox
    deployment to be env-gated and absent from default CI, so the merge gate
    stays offline and deterministic.
17. As a **contributor**, I want a recorded Phase-0 API-parity checklist, so I can
    see exactly which E2B-compatible behaviors were verified and where the
    provider intentionally diverges.
18. As a **maintainer**, I want the provider to fail closed when the backend
    cannot confirm a healthy sandbox, so a half-broken CubeSandbox never hands a
    stale client to an agent.
19. As a **platform operator**, I want rollback to be "revert one config line",
    so abandoning the experiment costs nothing.
20. As a **product stakeholder**, I want the fusion roadmap (pause/resume, egress
    credential injection, VM-snapshot rollback) explicitly parked, so this PR
    stays reviewable and lands independently.

## Implementation Decisions

1. **New module, no contract changes.** The provider lives in a new
   `community/cubesandbox/` module alongside the existing community providers.
   Neither the `Sandbox` ABC nor `SandboxProvider` gains or changes any method;
   if CubeSandbox cannot meet the existing contract, the provider adapts
   internally rather than widening the contract.

2. **Composition over subclassing for E2B reuse.** CubeSandbox's headline
   compatibility is the E2B SDK surface. The provider reuses the E2B machinery
   (client lifecycle, skills projection upload with its size/count/symlink
   safety rails, `AcquireSerializer` hold, ownership publish flow) through
   internal adapters, **not** by subclassing `E2BSandboxProvider`: Phase-0 may
   reveal semantic divergences (pause/resume presence, session model, discovery
   metadata), and a shared base class would couple two backends' futures.
   Genuinely identical helpers are extracted to shared internal functions rather
   than inherited.

3. **Configuration.** Selected via
   `sandbox.use: "deerflow.community.cubesandbox:CubeSandboxProvider"`. Endpoint
   and credentials come from named environment variables (matching how E2B
   compatibility is documented upstream — a base-URL switch), never hardcoded.
   `config.example.yaml` gains a commented sample block.

4. **Deterministic identity.** Sandbox names derive via
   `derive_sandbox_scope_token` — its keyword-only SHA-256/16-hex contract is
   preserved verbatim so containers are never orphaned by an identity-format
   change. Keys are `(user_id, thread_id)`; policy-scoped threads derive a
   distinct identity (same rule as E2B) so a container created with a shared
   skills projection is never reused for a policy-scoped thread.

5. **Acquire serialization.** One `AcquireSerializer` hold keyed
   `(user_id, thread_id, skills_root)` covers acquire, release, reset-plus-upload
   for policy syncs — the same keying as E2B, so overlapping operations for one
   thread cannot interleave.

6. **Warm pool, not pause/resume.** v1 manages reuse through the shared
   `WarmPoolLifecycleMixin` (`DEFAULT_IDLE_TIMEOUT=600`,
   `IDLE_CHECK_INTERVAL=60`, `DEFAULT_REPLICAS=3`, oldest-warm eviction).
   CubeSandbox auto-pause/resume is deliberately unused in v1: mapping our
   turn-scoped warm semantics onto machine-scoped pause semantics is an L2
   design decision with its own trade-offs, not a mechanical wiring.

7. **Single-instance ownership.** The provider reports
   `supports_cross_process = False` and uses the in-process ownership path only.
   A startup warning fires when the deployment shape implies multiple Gateway
   instances (mirroring the existing memory-store warning), so half-HA
   configurations are loud rather than silent. Redis ownership for this provider
   is follow-up work that must run the shared ownership-store contract suite
   before it ships.

8. **Skills projection.** Identical policy model to E2B: unrestricted threads
   get a one-shot upload of the enabled-only shared projection; policy-scoped
   threads skip that upload and instead `sync_agent_skills` clears only the four
   managed category directories plus signature, then uploads the signed thread
   projection. All existing safety rejections apply (non-canonical paths,
   protected mounts/homes, symlinked roots, OS trees). Delegated subagents are
   non-owners of the lead's projection and never rebuild it.

9. **Secrets handling.** `env_policy` scrubbing applies unchanged. Per-call
   `env` secrets go through fresh exec sessions (no persistence in long-lived
   sessions), matching the E2B/AIO behavior. If Phase-0 shows the compatible
   exec API does not support per-call env, the provider must emulate it with
   one-shot sessions — or fail that command shape loudly; silent persistence of
   secrets into a session is not acceptable.

10. **Fail-closed health model.** A sandbox whose health cannot be confirmed is
    treated as not adoptable: the provider drops it from all in-process maps and
    falls through to create, matching the AIO/E2B convention. Backend errors
    surface as ordinary tool errors; the provider never fabricates success.

11. **Phase-0 parity gate (deliverable).** Before claiming conformance, the
    branch records a checklist verifying, against a live single-node
    CubeSandbox: file API (read/write/stat/mkdir, binary safety, streaming),
    exec (exit codes, timeouts, per-call env, output capture), session behavior,
    sandbox lifecycle (create/reuse/kill), metadata/discovery surface, and
    documented vs actual pause/resume availability. Each row ends in one of:
    **parity** / **adapted in provider** / **documented limitation**. The
    checklist lands as an appendix to this spec in the same PR.

12. **Documentation.** `sandbox/AGENTS.md` gains a provider section per the
    repo's documentation-update policy; root `AGENTS.md` and `README.md` are
    touched only if user-facing behavior changes (they should not).

## Testing Decisions

**What makes a good test here:** tests assert *external behavior through the
public `SandboxProvider`/`Sandbox` interface only* — never implementation
details. The CubeSandbox service is mocked at the E2B-compatible SDK/HTTP
boundary, exactly where existing E2B tests cut. Default CI stays offline and
deterministic; anything requiring a real CubeSandbox is an env-gated
integration tier, mirroring `DEER_FLOW_TEST_REDIS_URL` (self-skips when unset).

Five seams, existing ones preferred:

1. **Provider behavioral contract (primary seam).** Isomorphic to
   `tests/test_e2b_sandbox_provider.py`: acquire → `get()` → all seven sandbox
   operations → release; deterministic identity; serializer mutual exclusion;
   upload bounds (oversized file/tree, excess file count, size-change after
   preflight); policy-scoped sync safety rejections; subagent non-ownership.
2. **Config resolution.** `sandbox.use` class path loads the provider through
   the existing reflection mechanism; a one-line config switch selects it.
   Prior art: provider config/mode-detection tests.
3. **Warm-pool lifecycle.** The shared mixin contract from
   `tests/test_warm_pool_lifecycle.py` — replica counting, oldest-warm eviction,
   expiry, disabled-timeout no-op — instantiated against the new provider.
4. **Ownership posture (v1).** Assert `supports_cross_process` is `False` and
   the multi-instance startup warning fires. The shared ownership-store
   contract suite (`tests/test_sandbox_ownership_store.py`) and orphan
   reconciliation scenarios are **deferred** and listed as follow-up.
5. **Platform gates smoke.** One authorization test proving the
   `sandbox:execute` gate denies through the new provider with the standard
   friendly error (prior art `tests/test_sandbox_authorization.py`), and one
   Blockbuster test proving `get()` never leaves the event loop (prior art
   `tests/blocking_io/test_aio_sandbox_get.py`, which injects a deliberately
   blocking probe).

Integration tier: `CUBESANDBOX_TEST_URL`-gated live tests against a throwaway
single-node deployment, excluded from default CI like the Redis tier.

## Out of Scope

- CubeSandbox auto-pause/resume replacing or augmenting the warm pool (L2).
- CubeEgress integration: L7 egress policies, credential injection at the proxy,
  wiring our network-policy events to it (L2).
- VM snapshot × checkpoint dual-capture rollback (machine-level undo for runs,
  edit/regenerate) (L3).
- Per-subagent ephemeral sandboxes (L3).
- RBAC × egress domain allowlists (L3).
- Redis-backed / multi-instance ownership for this provider.
- Provisioner/Kubernetes deployment mode integration.
- Any change to the default provider or to existing providers' behavior.

## Further Notes

- Upstream: <https://github.com/TencentCloud/CubeSandbox> (open-sourced
  2026-04; docs at <https://cubesandbox.com/>). Evaluation here is based on its
  public documentation, not a source read — Phase-0 exists precisely to replace
  documentation claims with verified behavior.
- **Risk:** the project is young and KVM self-hosting is operationally heavy
  (bare metal or nested virtualization). The optional-provider shape keeps our
  blast radius at "one config line" and our coupling behind the existing
  `SandboxProvider` contract — no irreversible commitment.
- **Strategic context:** this spec is L1 of the DeerFlow × CubeSandbox fusion
  roadmap. L2/L3 items are intentionally parked (see Out of Scope) so this PR
  lands independently; each will get its own spec with its own seams.
- **Acceptance:** per repo TDD policy, the PR ships with the offline test suite
  green (`make test`, `make test-blocking-io`), the parity checklist filled in,
  and docs updated in the same change set.
