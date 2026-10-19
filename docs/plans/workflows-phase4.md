# Phase 4 implementation contract

- Opt-in PostgreSQL workflow store; default SQLite/exclusive flock remains unchanged.
- Shared workflow rows/artifacts/definitions, durable control inbox, database-clock execution leases and epoch fencing.
- Generic host ExecutionFence checked in same RunStore transaction as child admission. A preflight-only lease check is insufficient.
- Lease loss stops local worker; stale owner cannot save, dispatch, approve, capture artifacts or cancel a successor's children.
- Remote browser actions revalidate current permission/config, commit exact-version decisions, and owner consumes durable controls. Duplicates are idempotent.
- Lease expiry exposes recoverable/reconciliation state. Takeover requires fresh authenticated browser capability; no credentials serialized and no autonomous execution under a reconstructed user ID.
- Cluster quotas are transactionally reserved; uncertain child effects retain capacity until reconciled, never automatically redispatched.
- Runtime/config incompatibility blocks takeover; old compatible replicas may continue their own live runs during rolling upgrade.
- Tests: real PostgreSQL multi-process coordination and host atomic fencing; two services for end-to-end worker replay/control; stale owner and deterministic persistence boundaries.


## Validation boundaries

The PostgreSQL integration suite uses disposable schemas and real database locks.
Two independent service instances exercise routing-independent controls; a separate
OS process exercises abrupt owner termination during review. Crash-image tests cover
admission, result and approval persistence boundaries without repeating confirmed
steps. Host tests traverse the actual capability/manager/store admission path and
reject stale epochs after a real PostgreSQL lock wait. Agent responses remain
synthetic. These tests do not establish arbitrary business-effect rollback or a
fully deployed Kubernetes/Redis/load-balancer environment.

The supported recovery policy is explicit session-authorized takeover. Lease expiry
alone grants no user authority. Unknown child reservations require manual operational
reconciliation and remain counted until their effects are verified. Automatic user
authority reattachment and automatic reconciliation are outside this release.

## Local validation

- Full offline backend suite with PostgreSQL enabled: 34,527 passed, 686 skipped.
- Final extension/recovery/API subset: 144 passed, including 14 cluster cases.
- Host fencing, AgentRuns, run ownership and SQL repository subset: 213 passed.
- Blocking-I/O suite: 262 passed, 1 skipped.
- Backend and extension lint/format, frontend lint/typecheck, browser fixture and
  guidance checks passed. PostgreSQL 17 ran on loopback with disposable schemas.
- The final targeted runs include the owner predicate on fenced cancellation and
  file-integrity validation for remote approval added during the full-suite run.
