## Context

当前 `search_threads`（[threads.py:369-536](backend/app/gateway/routers/threads.py#L369-L536)）分三个阶段：

1. **Phase 1 — Store 查询**: 从 `thread_meta` 表获取最多 10,000 条记录，构建 `merged` dict
2. **Phase 2 — Checkpointer 补充**: `checkpointer.alist(None)` 全量扫描，做三件事：
   - **懒迁移**：将 Store 中缺失的线程补写
   - **Title 回填**：从 checkpoint `channel_values.title` 同步到 `thread_meta.display_name`
   - **墓碑过滤**：跳过已删除线程
3. **Phase 3 — 过滤排序分页**: metadata 过滤、status 过滤、排序、分页

### Phase 2 三个职责的现有覆盖

| Phase 2 职责 | 已被谁覆盖 | 位置 |
|-------------|-----------|------|
| 懒迁移 | `POST /api/threads` 同步写 `thread_meta`；`services.py:375-386` 在 run 启动时 upsert | [threads.py:330](backend/app/gateway/routers/threads.py#L330), [services.py:375-386](backend/app/gateway/services.py#L375-L386) |
| Title 回填 | `worker.py:467-478` 在每次 run 完成后从 checkpoint 同步 title 到 `thread_meta.display_name` | [worker.py:467-478](backend/packages/harness/deerflow/runtime/runs/worker.py#L467-L478) |
| 墓碑过滤 | `DELETE /api/threads/{id}` 同步删除 `thread_meta` 行 + 写入墓碑到 Store | [threads.py:290-296](backend/app/gateway/routers/threads.py#L290-L296) |

三个职责均有其他路径覆盖，Phase 2 完全是冗余扫描。

## Goals / Non-Goals

**Goals:**
- 移除 Phase 2 的 checkpointer 全量扫描，消除 thread search 的性能瓶颈
- 简化 `search_threads` 为单阶段查询：Store → 过滤 → 排序 → 分页
- 保持 API 请求/响应格式完全不变

**Non-Goals:**
- 不修改 `thread_meta` 表结构或索引
- 不修改前端任何代码
- 不新增 title 同步机制——worker.py 已覆盖
- 不添加新的 API 参数或过滤能力

## Decisions

### Decision 1: 删除整个 Phase 2 + Phase 3 的合并逻辑

删减范围（[第418-521行](backend/app/gateway/routers/threads.py#L418-L521)）：

- **删除**: Phase 2 全量 `checkpointer.alist(None)` 扫描及懒迁移
- **删除**: `deleted_thread_ids` 墓碑查询（仅 Phase 2 使用）
- **删除**: `current_tenant` / `current_user` 局部变量（仅 Phase 2 使用）
- **删除**: `checkpointer` / `store` 变量声明（仅 Phase 2 使用）
- **删除**: Phase 3 中从 `merged` dict 转为 list 的中间步骤
- **保留**: Phase 1 Store 查询
- **保留**: metadata 过滤 + status 过滤 + 排序 + 分页（直接应用于 Phase 1 结果）

**理由**: Phase 2 的所有职责已被其他路径覆盖。`merged: dict` 的唯一存在理由就是 Phase 2 的去重需求，移除后 Phase 1 直接返回 list 即可。

### Decision 2: Title 生命周期保证

当前 title 的完整生命周期：

```
TitleMiddleware._agenerate_title_result()
  → state["title"]
  → checkpoint channel_values["title"]

worker.py finally 块
  → checkpoint.aget_tuple() → channel_values["title"]
  → thread_store.update_display_name(thread_id, title)    ← 每次 run 完成时执行

search_threads Phase 1
  → thread_meta.display_name → values.title
  → 前端 titleOfThread() 读取
```

Phase 2 在这个链路中不承担任何不可替代的角色。移除后 title 同步链路保持完整。

### Decision 3: 不加入 feature flag

不添加配置开关来控制是否启用 Phase 2。

**理由**: 没有需要回退的场景。如将来需要从 checkpointer 恢复数据，应写独立的管理脚本，而非在每次 search 时全量扫描。

## Risks / Trade-offs

- **Risk**: 若有第三方工具绕过 Gateway 直接写 checkpointer → **Mitigation**: 当前架构不存在此路径；若将来引入，应在该入口补写 `thread_meta`
- **Risk**: 若 worker.py 的 title sync 失败且 Phase 2 也被移除 → **Mitigation**: Phase 2 的 title 回填同样是 best-effort（有 `except` 兜底），且 worker.py 在 finally 中执行，与 Phase 2 的可靠性相当；前端 `titleOfThread()` 对 null title 降级为 `"Untitled"`
- **Trade-off**: 删除 ~100 行"防御性"代码 → 每次 search 从 O(checkpoint 总量) 降为 O(thread_meta 行数)
