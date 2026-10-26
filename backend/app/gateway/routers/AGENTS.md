# Router contracts

Branch metadata inherits valid `assistant_id` values verbatim. Validate with
`custom_agent_name` and clear invalid legacy values to null in the new row;
leave the source record unchanged.

Console usage attributes legacy rows without a per-model usage map to
`model_name`, including their recorded `total_input_tokens`. Accumulate those
inputs with newer usage buckets for the same model; do not infer cache hits.
Regression coverage lives in `tests/test_console_router.py`.

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

Skill archive upload copies (`_copy_uploaded_skill_archive`) report the original
size-limit or read error when temporary cleanup or its warning log fails.
Successful copies still return the uploaded bytes unchanged. The upload route's
`finally` discards that archive through the same helper before closing the
multipart form. Form close is suppressed, so a close, cleanup, or warning
failure cannot turn a successful install into a 500, replace an install
error, or skip the discard. Coverage: `tests/test_skill_archive_upload_cleanup.py`.

State updates synchronize titles into thread metadata only for the root checkpoint
namespace. Nonroot writes preserve the conversation title, branch-title sequence
and activity timestamp. `tests/test_threads_router.py` checks metadata/search
isolation and root title synchronization in full and delta modes.

Unauthenticated auth routes (`/register`, `/setup-status`, `/providers`,
`/oauth/{provider}`, `/callback/{provider}`, the `/login/local` throttle) read
`get_app_config()` through `asyncio.to_thread`: each read stats and hashes the
config files. Coverage: `tests/blocking_io/test_auth_router_config_reads.py`.
