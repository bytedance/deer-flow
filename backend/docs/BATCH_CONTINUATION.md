# Native batch dependencies and follow-up

Optional fields extend the existing SQL-backed batch service. Omitting them keeps
independent batch execution. Items remain read-only or idempotent under the existing
retry/recovery policy.

## Conservative recovery (opt-in)

Set `subagent_batches.recovery_policy: conservative` and restart the Gateway to
apply conservative recovery to new batches. The default is `retry`. Admission
persists the host-selected policy with the batch; changing the configuration
later does not change existing batches, including after restart. This first
slice is verified on a single Gateway with SQLite.

Each claim persists a new `attempt_id` bound to its existing item, parent batch,
thread/run and owner. Before launching the native child, the worker commits
`dispatch_started_at` under that claim's lease. Recovery distinguishes:

- No dispatch intent: the child was not launched through this path; expired
  claims may retry within the existing limit.
- Dispatch intent with no recorded outcome: the item becomes `outcome_unknown`,
  retains its attempt identity, and cannot be automatically or manually retried.
  The external operation may already have succeeded. Even a crash immediately
  after intent commits, before launch, is conservatively unknown.
- Recorded completion: retain the result and attempt; do not execute it again.

An execution timeout or lost execution/result acknowledgement after dispatch
also becomes unknown. A recorded failed execution is terminal under this policy,
without an automatic retry; the existing explicit retry remains available for
known failures. Proven admission rejection may requeue because execution did
not start. The default retry policy keeps its existing behavior.

Unknown items use no execution slot. Independent items may finish, but dependent
items remain waiting and the batch cannot trigger its requested follow-up.
The browser labels unknown outcomes and retains report inspection and export.
Pause/resume never clears uncertainty. Cancelling the batch stops pending work
and follow-up while retaining attempt evidence; cancellation does not undo or
disprove an external write. This slice provides no reconciliation or unknown
retry operation. Inspect the external system before arranging further work.

Migration `0053_batch_recovery` adds nullable policy, attempt and dispatch fields;
legacy batches retain `retry`. Upgrade all batch workers before enabling this
policy. Downgrade is refused while conservative work or unknown outcomes remain
outstanding. There is no guarantee of exactly-once external effects: the
regression establishes that this crash recovery path does not repeat the write.

`tests/test_batch_gateway_crash_recovery.py` runs an offline scripted model and
fixed local tool through actual Gateway subprocesses and native batch execution.
It commits a record to a separate SQLite database, kills the Gateway before the
batch result commits, and reopens the same storage. It asserts one external
write, an unknown item, waiting dependents and no follow-up, including across a
second restart and a changed deployment policy. A committed-result control
verifies normal completion and one follow-up.

## Dependencies

Use `depends_on` to name prerequisite item keys in the same batch. Unknown keys,
self-references and cycles are rejected before saving. Dependent items consume no
worker slot until every prerequisite succeeds without a guardrail stop reason.
Retryable attempts keep dependents waiting; exhausted failures, cancellation or
terminal capped results fail unstarted descendants. Independent items continue.
Retrying a failed prerequisite by hand does not requeue the descendants it already
failed; retry each blocked item as well.

Item prompts must name their input/output paths. Ordering does not certify factual
accuracy or make advisory acceptance mandatory. Use existing result readers; full
reports are not copied into every dependent's context.

## Requested follow-up

`continuation` describes remaining work the user already requested. After terminal
batch results are saved, the lead performs that work in the original conversation
through ordinary Run admission. Preserve the originating model selection, reasoning,
limits and admitted retrieval scope. Busy conversations wait. While a question is
unanswered the claim is kept until its lease expires, so the conversation is not
reread on every poll.

A stable idempotency key reconciles lost admission replies without another Run.
Pending claims rotate so busy conversations do not starve others. Manual item retries
hold an unadmitted follow-up but do not re-arm one already dispatched. Without a Goal,
a follow-up cannot request another automatic follow-up.

An active Goal wakes only from its own `external_wait`, consuming one existing
continuation allowance, once even after recovery. Other blockers, no-progress limits
and hard stops remain effective. Goal replacement, clearing and thread deletion
suppress pending work; a failed, cancelled or hard-stopped source Run cannot restart.

## Authority, cancellation and recovery

Follow-up needs a session-authorized Gateway AgentRuns capability or local auth-disabled
mode. Internal/PAT callers and unsupported embedded runtimes retain ordinary batches.
Persist only the original permission ceiling, account token version and auth source;
no cookie, API key or Python capability. Restore checks current account/permissions,
conversation ownership and incarnation. Private continuation data is not returned.

Batch cancellation revokes the existing SQL execution fence and stops an admitted
follow-up, including after a lost launch reply. HTTP and tool cancellation of a batch
with a follow-up also require `runs:cancel`. Trusted internal cleanup retains its existing
path. Claim ownership/expiry lives only in the existing execution-lease table.
Completed item results remain available. The Web panel discovers follow-up Runs
through existing observers; refresh never launches work. Chat Stop remains available.

## Upgrade and verification

Migration `0052_batch_continuation` adds dependency edges and nullable follow-up data,
status and Run ID. Existing rows need no backfill. Upgrade all batch workers before
using dependencies. Do not downgrade with opted-in work outstanding; downgrade drops
new metadata while retaining items and reports.

Focused regressions cover dependency/retry ordering, SQL claims and recovery,
permission revocation, admission races, Goal limits and page reconnection. PostgreSQL
coverage uses `TEST_POSTGRES_URI`; browser backend timing is simulated.
