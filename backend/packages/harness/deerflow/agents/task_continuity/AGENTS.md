# Task continuity

`history_search` accepts optional `role=user|assistant|tool`, mapped at the tool
boundary to stored roles `human|ai|tool`; omission/null keeps all roles. Filter
archived JSON payloads before SQLite FTS `LIMIT 8`, and active messages before
the merged result limit. Preserve ranking, source IDs, returned roles, checkpoint
reachability, and user/thread isolation. Do not add a role parameter to `history_read`.
Sync and async entry points share the implementation; async uses `run_file_io`.
Regression coverage lives in `backend/tests/test_task_continuity.py`.
For usage and trust boundaries, read `docs/task-continuity.md` at the repository root.
