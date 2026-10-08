# Native reuse implementation audit notes

## B: durable tracking before execution

Native McpTaskService submits remotely, then SQL repository create commits the tracking row. The poller claims rows in a separate session and commits its lease before calling get_status. Therefore the first normal native poll cannot precede tracking commit, although it may precede submission refresh/return.

The executor can persist submit as staged and activate only on a signed background status call. Workers consume queued rows only. Activation, cancellation and staging expiry must serialize in one transaction; terminal rows never reactivate. Require HTTP plus native user_auth so the background caller installs the persisted owner. A signed status is Gateway-origin evidence under this configured chain, not a general database commit certificate.

Lost submit responses leave staged jobs which expire without execution. Cancellation compensation can arrive before tracking exists and must never activate work. If commit succeeded but refresh failed, a poll may already have activated the job, so cancellation requires actual STOP evidence. Submission idempotency and uncertain acknowledgements still require explicit implementation; do not import old Fleet tracking-ID reuse blindly.

## C: native admission and cleanup

Use native app.gateway.services.start_run exactly once, with a stable dispatch idempotency key and immutable envelope. Outbound worker delivery resolves server-owned owner/thread binding before creating an internal local request. An extension service currently lacks public run admission/app/cancel capabilities; a trusted local route or a minimal host capability is needed. Custom HTTP admission also needs runs:create permission enforcement.

Native terminal status, extension task-stop, and SSE end occur before journal/sandbox/reference cleanup. Resource release cannot use those events as physical STOP receipts. Await attached native task completion and account separately for external sandbox/process cleanup; restart-safe receipts require an owner-fenced durable acknowledgment. Keep resident Gateway resources reserved even after a run ends.

## Goal continuation

Native thread checkpoint GoalState remains goal authority. Native MCP notifications already re-enter start_run with durable delivery idempotency and busy-thread retries. Extend dependency membership and admission validation around that path; do not add another goal evaluator or competing Agent loop.

These are verified integration findings, not acceptance evidence for complete B/C/BC. Cloud deployment remains deferred.
