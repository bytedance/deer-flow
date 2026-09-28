# Task continuity

`history_search` accepts optional `role=user|assistant|tool`, mapped at the tool
boundary to stored roles `human|ai|tool`; omission/null keeps all roles. Filter
archived JSON payloads before SQLite FTS `LIMIT 8`, and active messages before
the merged result limit. Preserve ranking, source IDs, returned roles, checkpoint
reachability, and user/thread isolation. Do not add a role parameter to `history_read`.
Sync and async entry points share the implementation; async uses `run_file_io`.
Regression coverage lives in `backend/tests/test_task_continuity.py`.
For usage and trust boundaries, read `docs/task-continuity.md` at the repository root.


搜索片段由 `archive.lookup(excerpts=True)` 在检索选中结果后生成；保持原排序和八条上限。
`excerpt_start` / `excerpt_end` 是可回读原文的零基、左闭右开字符区间，必须满足
`source_text[start:end] == excerpt`。按原文字符映射 casefold 扩展，不得使用字节偏移。
active 按子串定位，archive 使用与索引共享的分词位置；FTS 额外归一化无法精确定位时，
回退开头并返回 `excerpt_match=false`。同源 active 优先；重复归档采用与按 ID 回读相同的
首个 rowid 版本，保留该版本的截断标记。不要用不同版本的文本生成偏移。
修改片段时阅读 `docs/task-continuity.md` 中的边界规则，并运行真实工具搜索/回读测试。
