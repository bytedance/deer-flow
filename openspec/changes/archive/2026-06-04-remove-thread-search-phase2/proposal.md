## Why

`POST /api/threads/search` 每次请求都会在 Phase 2 中对 LangGraph checkpointer 执行全量扫描（`checkpointer.alist(None)`），以"懒迁移"那些可能未写入 `thread_meta` Store 的遗留线程。但在当前架构下，所有 thread 创建路径（前端 SDK、IM 渠道、Gateway API）最终都经由 nginx 重写打到同一个 `POST /api/threads` 端点，该端点已同步写入 `thread_meta`。此外，`worker.py` 的 `finally` 块已在每次 run 完成后将 title 从 checkpoint 同步到 `thread_meta.display_name`。Phase 2 的三个职责（懒迁移、title 回填、墓碑过滤）均有其他机制覆盖，其全量扫描完全是空转，却随着 checkpoint 表增长线性变慢，直接导致报告历史"查看全部"等依赖 thread search 的页面响应缓慢。

## What Changes

- 移除 `search_threads` 中的 Phase 2（checkpointer 全量扫描 + 懒迁移 + title 回填 + 墓碑查询）
- 简化结果组装：Phase 1 直接返回 list，移除 Phase 3 中因 Phase 2 存在的 dict 合并去重逻辑
- 保留 Phase 1（Store 查询）和过滤/排序/分页逻辑，作为唯一搜索路径
- **不需要**新增 title 同步机制——`worker.py:467-478` 已在每次 run 完成时完成同步

## Capabilities

### New Capabilities

_无新能力。_

### Modified Capabilities

_无 spec 级需求变更。此改动是纯性能优化，不改变 API 契约或外部行为。_

## Impact

- **后端**: `backend/app/gateway/routers/threads.py` — `search_threads` 函数，删除约 100 行 Phase 2 代码
- **API 兼容性**: `POST /api/threads/search` 请求/响应格式不变，返回结果不变（Phase 1 + worker.py title sync 已覆盖全部需求）
- **性能**: 消除 O(n) checkpoint 全表扫描，搜索耗时从线性增长降为常数级
