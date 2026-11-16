# Native batch dependencies and follow-up

Optional fields extend the existing SQL-backed batch service. Omitting them keeps
independent batch execution. Items remain read-only or idempotent under the existing
retry/recovery policy.

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
