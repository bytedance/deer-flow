# Native batch dependencies and follow-up

These optional fields extend the existing SQL-backed `batch_task` service. Keep
items read-only or idempotent under its existing retry and recovery policy.
Omitting the new fields retains independent batch execution.

## Dependencies

An item may name other item keys in `depends_on`. Keys must exist in the same
submission; self references and cycles are rejected before a batch is saved.
For example, a comparison item can depend on `sales` and `risks`, while an
independent appendix continues running.

The existing scheduler promotes an item only after every prerequisite succeeds
without a guardrail stop reason. Waiting items remain pending and consume no
worker slot. Exhausted failed, cancelled or capped prerequisites make their
unstarted dependents fail with an explanatory error. Independent items continue.

Dependencies order execution. They do not certify factual accuracy or turn an
advisory acceptance verdict into a mandatory gate. Item prompts must still name
their input/output paths; full reports are not copied into every dependent's
context. Existing result inspection and acceptance evidence remain available.

## Requested follow-up

`continuation` is a short description of remaining work the user has already
requested, such as combining item results and presenting two files. The lead
Agent performs it once after terminal batch results are persisted. It is not a
progress-polling instruction or a new batch item. It may inspect the existing
owner-scoped results with `read_batch_result` or read the supplied output paths.

The originating turn can end while the batch works. The follow-up uses ordinary
Gateway Run admission in the same conversation, preserving model/reasoning
context, recursion limit and admitted knowledge scope. An occupied conversation
defers admission. A stable idempotency key reconciles an uncertain launch after
restart; it does not start the follow-up twice. Without a Goal, a follow-up cannot
register a second automatic follow-up. Explicit item retries do not re-arm a
dispatched follow-up; a follow-up not yet admitted waits for the retried item.

For an active Goal, completion can wake that same Goal after its evaluator records
`external_wait`. This consumes one of the existing Goal continuations, once per
admitted Run even after recovery. Continuation and no-progress limits still apply;
other blockers and hard stops stay stopped. A Goal-owned follow-up may submit more
work within those limits. Changing or clearing the Goal suppresses pending batch
follow-ups. A cancelled, failed or hard-stopped originating Run cannot restart
through this feature.

## Authorization and cancellation

Automatic follow-up requires a session-authorized Gateway AgentRuns capability
(or the existing local auth-disabled mode). Internal/PAT callers and embedded
runtimes without this host support cannot request it. Ordinary batch execution
remains available on its existing paths.

Only the original host-granted permission ceiling, account token version and
auth source are persisted. No session cookie, API key or Python capability is
serialized. Recovery rechecks the account, current permissions, conversation
ownership and incarnation. These records are excluded from public batch views.

Cancel the batch to suppress its follow-up. Cancellation and Goal/deletion
operations revoke the existing SQL execution fence checked inside Run admission.
If admission already committed, cancellation locates and stops that Run, including
when its reply was lost before the batch stored the Run ID. Completed item results
remain inspectable. Existing native execution cleanup and timeout semantics apply.

The Web batch panel keeps observing a pending follow-up and refreshes the existing
chat Run/history observers when its Run appears. Browser refresh does not dispatch
work. Stopping an already running follow-up uses the normal chat Stop control.

## Storage and validation

Migration `0052_batch_continuation` adds same-batch dependency edges and nullable
follow-up fields. Existing batch rows require no backfill. Rolling back drops
dependency/follow-up metadata while retaining items and their reports; do not
roll back while opted-in work is outstanding.
Finish upgrading all batch workers before using dependency fields: older workers
do not understand prerequisite ordering.

Focused offline regressions are in `test_batch_dependencies.py`,
`test_batch_continuation.py` and `test_batch_followup_host.py`. They exercise
real SQL claims, reopen, normal AgentRuns/worker admission, lost launch replies,
authorization revocation and cancellation/Goal changes racing admission.
