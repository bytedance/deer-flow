# Task continuity

修改 `task_note` 容量或批次回执时，遵守 [连续性契约](../../../../../../docs/task-continuity.md)，
并运行 `backend/tests/test_task_note_capacity.py` 的真实图回归；单次快照加锁不能协调并行 Command。
句柄解析启用时，容量预留使用 `ArtifactResolutionMiddleware` 提供的调用局部
`__resolved_tool_call_args` 参数视图，与实际执行使用同一解析器；该视图仅存在于
本次 `ToolRuntime.state`，不写入消息或检查点。关闭解析及直接工具图仍使用原始参数。

`history_search` accepts optional `role=user|assistant|tool`, mapped at the tool
boundary to stored roles `human|ai|tool`; omission/null keeps all roles. Filter
archived JSON payloads before SQLite FTS `LIMIT 8`, and active messages before
the merged result limit. Preserve ranking, source IDs, returned roles, checkpoint
reachability, and user/thread isolation. Do not add a role parameter to `history_read`.
Sync and async entry points share the implementation; async uses `run_file_io`.
Regression coverage lives in `backend/tests/test_task_continuity.py`.
For usage and trust boundaries, read `docs/task-continuity.md` at the repository root.
