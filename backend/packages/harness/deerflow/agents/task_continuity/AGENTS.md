# 当前任务连续性

**当前任务历史检索** (`task_continuity/`)：`history_search` 的可选 `role`
为 `user|assistant|tool`，工具层映射为存储角色 `human|ai|tool`；省略/null
保持全部角色。archive 必须在 SQLite FTS 的 `LIMIT 8` 前按已有 JSON payload
过滤，active 必须在合并截断前过滤。保持既有排序、source ID、返回角色、
checkpoint 可达性和用户/线程隔离；`history_read` 不增加角色参数。
同步和异步入口共享实现，异步通过 `run_file_io` 执行。回归见
`backend/tests/test_task_continuity.py`；使用及信任边界见 `docs/task-continuity.md`。

