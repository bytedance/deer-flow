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

## Shared host requirements verified from the native source

The user repository class retains the name SQLiteUserRepository but receives the shared async session factory and supports PostgreSQL. User authentication does not need a second executor user database. Instances require the same JWT secret and native authorization checks; possession of a node credential never grants arbitrary user/thread authority.

Native multi-instance startup requires PostgreSQL, DB run events, ownership heartbeats and Redis stream bridge. Scheduler needs its own multi_instance flag if enabled. Stateful native browser tools are currently rejected by the gate even with a fixed dispatcher affinity. They are commented out in config.example.yaml. For an operator who enables interactive browsing, the supported existing integration seam is authenticated HTTP/SSE browser MCP with explicit persistent session identity or thread-to-node affinity and defined restart behavior. This preserves interactive tool capability but does not automatically expose the native Browser Live UI; that UI would require an additional provider/owner routing integration. Do not claim all browser transports are interchangeable.

AIO Docker is a candidate native shell sandbox for fixed ECS nodes: each worker owns local Docker; Redis coordinates sandbox ownership; shared paths and thread_data_mounts must match on the Gateway and sandbox side. Warm processes and browser state remain node-local and are not migrated by NAS. Local provider with allow_host_bash=false does not satisfy shell execution; do not silently use that setting while claiming full bash support.

DeerMem body/manifest and skill/config projections already use file locks. Keep its derived SQLite FTS5/WAL retrieval index on each instance's local disk using an absolute retrieval_index_path, while sharing only the authoritative memory files. NAS flock, atomic rename and cross-node refresh still need later cross-host acceptance.

## Fork preservation audit

Local refs checked before integration: fork/main is 96bacf4f and Gitee uses gitee/master, not gitee/main. The common ancestor with the official baseline is c35022e1. Both sides have substantial changes; the new branch must not be pushed as a force replacement of the fork. Review fork-only core changes separately from Fleet adapters, retain unrelated fixes, and preserve old migration/data history. Current implementation remains on codex/ecs-native-reuse; no remote update is implied by its local commits.

## Local model preflight (2026-10-08)

Using the new checkout's native PatchedChatDeepSeek with the existing main checkout's private configuration, one request with max_tokens=8 returned READY successfully. Configured model alias: deepseek-chat; returned provider model: deepseek-flash. Secret values were not printed or copied into this repository. This is only provider connectivity evidence; it is not C Agent/model/tool/dispatch acceptance.

## Preserved timeout preference

The previous implementation's FleetConfig.lease_seconds defaults to 120 seconds, and delivery notes retain a cumulative 120-second cleanup/quarantine safety budget. Preserve the user's accepted 120-second lease/cleanup allowance when adding the shared pool; do not shorten physical-stop safety waits merely to make local fault tests faster. This is separate from configurable per-program execution deadlines and fresh per-call signature lifetimes.

## B file delivery implementation boundary

A log JSON artifact alone does not satisfy the original shared-input/output requirement. The B main additionally needs an owner/thread-scoped immutable input snapshot, persistent isolated outputs, bounded regular-file collection and manifest integrity, plus publication through the native user/thread artifact path. Native metadata owner/incarnation remains authoritative during publication; no duplicate thread table or access to native mcp_tasks is needed. Keep private results after stale-thread rejection without replaying computation. A remote service Bearer URL is not a substitute for the native browser/session-authorized file entry.

## Task 2 review and verification (2026-10-09)

Independent SPEC review passed after a combined inline/reference input-count admission fix. Root independently reproduced the focused scope/B suite: 17 passed, 1 explicit Docker opt-in skipped. Actual TCP/PostgreSQL/Docker execution also passed after that guard, including immutable native upload snapshots, restart without replay, native artifact ownership and physical cancellation. Quality review identified a real normal-terminal Docker-object cleanup leak; durable cleanup_pending and an independent terminal cleanup sweep fixed it. The lifecycle regression proves failed removal and SQL/worker restart preserve results without start replay. Independent quality re-review passed. Latest locked-environment focused suite: 18 passed, 1 explicit opt-in skipped; latest actual TCP/PostgreSQL/Docker main: 1 passed in 16.48 seconds, including automatic completed-container removal before fixture cleanup. Task 2 is now verified; local implementation commit ddf85787.

The first repository-wide offline attempt reused the old checkout virtual environment and a temporary uv wrapper. Subprocess tests deliberately changed PYTHONPATH, selecting the old extension-api 0.2.0; the wrapper also rejected uv --version/lock. That run is not valid regression evidence for this branch. A dedicated backend/.venv was then created with uv sync --locked --extra postgres --extra redis. Genuine make test completed with exit 0: all four shards passed (26,761 passed, 411 skipped; slowest shard 303.55 seconds); genuine make test-blocking-io passed 229 tests (20.19 seconds). No application credentials or database URLs are recorded here.
