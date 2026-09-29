# Task continuity

When changing `task_note` capacity or batch receipts, follow the
[continuity contract](../../../../../../docs/task-continuity.md) and run the real
graph regressions in `backend/tests/test_task_note_capacity.py`; locking one
snapshot cannot coordinate parallel Commands. With handle resolution enabled,
reservations use the same resolver as execution through the call-local argument
view supplied by `ArtifactResolutionMiddleware`. Both modules import
`RESOLVED_TOOL_CALL_ARGS_KEY` from `state.py`. This view stays in the current
`ToolRuntime.state`, outside messages and checkpoints. Disabled resolution and
direct tool graphs retain raw arguments. Skip non-dict sibling arguments before
reading note fields so malformed calls cannot break valid sibling receipts.

`history_search` accepts optional `role=user|assistant|tool`, mapped at the tool
boundary to stored roles `human|ai|tool`; omission/null keeps all roles. Filter
archived JSON payloads before SQLite FTS `LIMIT 8`, and active messages before
the merged result limit. Preserve ranking, source IDs, returned roles, checkpoint
reachability, and user/thread isolation. Do not add a role parameter to `history_read`.
Sync and async entry points share the implementation; async uses `run_file_io`.
Regression coverage lives in `backend/tests/test_task_continuity.py`.
For usage and trust boundaries, read `docs/task-continuity.md` at the repository root.
