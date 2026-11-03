# Phase 4 implementation contract

- Opt-in PostgreSQL workflow store; default SQLite/exclusive flock remains unchanged.
- Shared workflow rows/artifacts/definitions, durable control inbox, database-clock execution leases and epoch fencing.
- Generic host ExecutionFence checked in same RunStore transaction as child admission. A preflight-only lease check is insufficient.
- Lease loss stops local worker; stale owner cannot save, dispatch, approve, capture artifacts or cancel a successor's children.
- Remote browser actions revalidate current permission/config, commit exact-version decisions, and owner consumes durable controls. Duplicates are idempotent.
- Lease expiry exposes recoverable/reconciliation state. Takeover requires fresh authenticated browser capability; no credentials serialized and no autonomous execution under a reconstructed user ID.
- Cluster quotas are transactionally reserved; uncertain child effects retain capacity until reconciled, never automatically redispatched.
- Runtime/config incompatibility blocks takeover; old compatible replicas may continue their own live runs during rolling upgrade.
- Tests: opt-in deployed two-Gateway HTTP/auth/PostgreSQL/Redis/nginx acceptance, real process faults, and complementary PostgreSQL transaction/fencing regressions.


## Validation boundaries

`backend/tests/test_workflow_gateway_acceptance.py` starts two real Gateways with
normal login/CSRF, shared PostgreSQL 17, Redis 7, and nginx round-robin routing.
The deterministic model replaces provider answers, not AgentRuns, admission,
LangGraph/checkpoints, storage or authorization. Test-only barriers pause real
operations before SIGKILL/SIGSTOP; no production fault hook or auth bypass exists.

| Scenario | Deployed assertion |
| --- | --- |
| A launch; B inspection/resume/approval/cancel | Same session, real workflow reads through both proxy upstreams without affinity |
| Duplicate launch and approval | Concurrent HTTP requests to A/B produce one workflow, one decision, one child per step |
| Admission receipt lost | Actual child committed, Gateway killed before workflow receipt; recovery retains uncertain slot and never redispatches |
| Completed child, result not yet persisted | Kill before result write; survivor reads the known completed child without starting another |
| Result persisted, response not delivered | Kill after result commit; replay reuses retained output |
| Approval persisted, downstream not dispatched | Kill after decision commit; survivor preserves approval and dispatches the next step once |
| SIGSTOP old owner and restore after takeover | Actual stale host admission rejected; old workflow/artifact writes cannot change successor state |
| File approval after owner death | Modify original after capture; B reviews/approves and downstream receives original immutable bytes |
| Shared quotas | Per-owner workflow limit and cluster child reservations constrain real HTTP launches/host admissions |
| Revocation/config drift | Revoked cookie is rejected; fresh login still cannot bypass changed configuration; rejected takeover does not advance epoch |
| Rolling runtime change | Separate source trees with different worker IPC limits execute; old owner drains, incompatible survivor rejects takeover |
| Active-child cancellation | Peer request reaches actual child owner; delayed observation remains an explicit reconciliation outcome |

The database-level suite additionally tests stale cancellation and admission while
waiting for a real PostgreSQL row lock. It complements the process faults; it is
not a claim that every transaction boundary has been exercised over HTTP.
The local deployment uses OrbStack containers and native Gateway processes with
shared local storage. This does not certify Kubernetes, arbitrary network partitions,
all published-version upgrade pairs, external business-effect rollback, or model
quality. The alternate runtime is a test source revision, not a historical release.

### Authorization and reconciliation delivery boundary

Lease expiry alone grants no user authority. Takeover is an explicit action using a
fresh valid browser-session capability; current permissions, configuration and exact
runtime compatibility are rechecked. No serialized credentials or reconstructed user
ID substitutes for that capability. Unattended automatic takeover needs a separate
durable delegation/authorization design and is not delivered here.

Unknown effects retain the workflow/step evidence and child reservation. Manual
inspection can establish the business outcome, but the product currently has no
supported API/UI that records an operator attestation, audits it, and atomically
releases that reservation. That closure remains open; do not equate direct SQL,
workflow deletion, or a new request ID with a supported safe retry. Cancellation is
not rollback. Host cancellation may be observed after the extension's bounded wait,
leaving `needs_reconciliation` even when the child later becomes interrupted.

### Defect found by deployed acceptance

Pydantic JSON dumps converted `tool_progress.exempt_tools` from a set into a
process-dependent list order. Identical configuration on A and B could therefore
produce different durable HMACs and reject peer controls. Revision encoding now
retains Python set identity and canonicalizes sets while preserving ordered lists.
A focused regression and Gateways with different `PYTHONHASHSEED` values exercise
this fix. Existing pre-fix fingerprints may fail compatibility checks; drain them
on their original compatible runtime rather than rewriting stored fingerprints.

## Earlier validation (before deployed acceptance)

- Full offline backend suite with PostgreSQL enabled: 34,527 passed, 686 skipped.
- Final extension/recovery/API subset: 144 passed, including 14 cluster cases.
- Host fencing, AgentRuns, run ownership and SQL repository subset: 213 passed.
- Blocking-I/O suite: 262 passed, 1 skipped.
- Backend and extension lint/format, frontend lint/typecheck, browser fixture and
  guidance checks passed. PostgreSQL 17 ran on loopback with disposable schemas.
- The final targeted runs include the owner predicate on fenced cancellation and
  file-integrity validation for remote approval added during the full-suite run.

## Deployed acceptance follow-up (2026-10-19)

- OrbStack PostgreSQL 17 / Redis 7 / nginx, native Python 3.12 Gateways:
  **14 deployed acceptance cases passed** (157 seconds).
- Final strengthened proxy/readiness and active-successor stale-artifact checks:
  **1 passed each**, after the full deployed run.
- Full backend offline target with PostgreSQL regressions enabled:
  **34,573 passed, 656 skipped** across four shards. The deployed suite is explicitly
  opt-in and skipped in that target; its result is reported separately above.
- Blocking-I/O target: **262 passed, 1 skipped**.
- PostgreSQL coordination/fencing and AgentRuns subset: **48 passed**.
- AgentRuns and guidance checks: **38 passed**. Changed Python files passed Ruff
  lint/format checks; `git diff --check` passed.
- Acceptance teardown removed its Gateway processes and disposable containers;
  pytest temporary directories retain diagnostic logs. No production/user stack
  was reused or modified. The standalone PostgreSQL regression server was stopped.

## Review follow-up (2026-10-20)

Expired `cancelling` records now project as recoverable so authenticated cancellation
can reclaim the lease and finish cleanup. Ordinary replay rejects stored cancelling,
even without a cancel inbox entry; cancel claims themselves persist cancelling so a
second crash cannot lose the cancellation intent. Cancel takeover bypasses workflow
admission caps while retaining fencing and current permission/configuration checks.
Uncertain child reservations still require reconciliation before deletion.

Workflow get/list and database-identity reads use read-only transactions without
the global budget advisory lock. Listing joins workflow records and lease visibility
in one query/connection. Writes retain conservative global serialization; pooling
and finer write-lock granularity remain deferred for this bounded mode.

Regressions reproduce expired cancellation with and without saturated limits and
inspection while another connection holds the budget lock. Deployed acceptance adds
SIGKILL during cancellation takeover, then cleanup and deletion through a survivor.

Review validation: 17 PostgreSQL cluster cases passed (the three new regressions
failed before the fix); 15 real deployed acceptance cases passed. Full backend
regression: 34,576 passed, 657 skipped; blocking-I/O: 262 passed, 1 skipped.
Backend format/lint, frontend lint/typecheck, extension browser checks and diff
whitespace checks passed. The acceptance processes/containers and the dedicated
PostgreSQL regression server were cleaned up after validation.
