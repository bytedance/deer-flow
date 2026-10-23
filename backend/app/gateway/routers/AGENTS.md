# Router contracts

Shared scheduled-task update validation preserves an unchanged future `once`
instant on a live task inside `scheduler.min_once_delay_seconds`; new/changed
instants and terminal reactivation still enforce the minimum delay.

Scheduled-task admission rejects nonexistent naive `run_at` and `end_at`
wall times through the shared Gateway datetime resolver. Keep this check out
of runtime `next_run_at`: legacy tasks retain their accepted execution time,
including unchanged live once definitions. Explicit offsets retain their instant;
ambiguous naive times keep the existing fold choice.

The MCP task list accepts optional `TaskStatus` and `active_only` query filters.
Pass both to the repository before its limit; preserve `threads:read`, owner
checks, current-thread incarnation scoping, and the unfiltered array response.

Custom Agent packages are strict, versioned definition-only JSON documents.
Export explicitly projects the caller's portable `AgentConfig` fields and SOUL;
exclude `github` installation bindings, memory contents, conversations and
credentials. Import may rename locally but must remain owner-scoped and
create-only: collisions return 409, never overwrite or upsert. Ordinary creation
and import share `_persist_new_agent`, which uses `run_drained_write` so a
cancelled request still drains the owned persistence worker.

`GET /api/skills`, `/api/skills/custom` and `/api/skills/{name}` serve every
signed-in user, so their unexpected-failure 500s return a fixed detail. Load
errors (e.g. a malformed `extensions_config.json`) carry host paths and stay in
the server log.

Thread upload, upload delete and shelf attach-to-thread 500s name the file but
not the cause: staging and unlink `OSError`s carry host paths and stay in the
server log.

Skill mutation operation lists return `next_cursor: null` when `has_more` is false, including empty pages after a supplied `after_id`. The next cursor is the final returned operation only when a further page exists.

`GET /api/agent-tool-groups` projects only configured group names for the
custom-Agent settings allowlist. Never expose tool provider paths, credentials,
or raw tool configuration through this catalog.

Custom Agent update guards apply legacy shared-file checks only when the
resolved store is `FileAgentStore`, including the `update_agent` tool. DB
imports retain source files for rollback; those files cannot veto SQL updates.
Keep store resolution and filesystem checks off-loop in the HTTP route.
Agent PUT uses `preserve_non_managed_fields(..., new_tool_groups=...)` to clear
an inherited knowledge default when changed groups remove knowledge access.
Explicit scope/null updates still win; unchanged groups are not a migration.

Agent/profile and deployment/personal MCP mutation 500s plus the
scheduled-task `invalid_assistant` 422 use fixed text. Log exceptions
server-side; they can carry host paths.

Committed MCP reconciliation failures are logged once by
`fail_mcp_reconciliation`, with only the underlying exception type.
`_run_drained_mcp_apply` passes `_McpCommittedReconciliationError` as an expected
error to `run_drained_write` to avoid a duplicate diagnostic. It still drains
retired-pool cleanup outside the config locks and reports the fixed-detail 500.

Custom-skill edit, delete and rollback hold the owning root's process mutex and
`.custom.mutation.lock` sidecar across predecessor read, storage mutation and
history append. Peer Gateway processes sharing that root must use this same
critical section to preserve history ordering. Keep the sidecar distinct from
the nested projection lock, retain it across requests, and acquire/release both
off-loop inside the drained worker. Unrelated users retain independent locks;
external filesystem writers do not participate in this history guarantee.

Plugin actions stamp `ActionContext.interaction=session` only from authenticated
session provenance. Never accept it from payloads or propagate it to model tools;
extensions use it to distinguish owner review from model/tool output.

Skill export request cleanup drains archive-close workers before releasing the
process slot. Ordinary close or diagnostic errors are best-effort and preserve
the completed transfer, disconnect, or cancellation; interruption signals remain
outside exception suppression. Cover both unclaimed worker results and ASGI
response teardown in `tests/test_skill_export_cleanup_outcomes.py`. Pass the skill
name to cleanup diagnostics for downloads and unclaimed worker results; guard
non-I/O close bugs too, since they can replace the same caller outcome.
