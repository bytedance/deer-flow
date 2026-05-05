# RunJournal 替换 History Messages — 方案评估与对比

**日期**：2026-04-11
**分支**：`rayhpeng/fix-persistence-new`
**相关 plan**：[`docs/superpowers/plans/2026-04-10-event-store-history.md`](../plans/2026-04-10-event-store-history.md)（尚未落地）

---

## 1. 问题与数据核对

**症状**：SummarizationMiddleware 触发后，前端历史中无法展示 summarize 之前的真实用户消息。

**复现数据**（thread `6d30913e-dcd4-41c8-8941-f66c716cf359`）：

| 数据源 | seq=1 的 message | 总 message 数 | 是否保留原始 human |
|---|---|---:|---|
| `run_events`（SQLite） | human `"最新伊美局势"` | 9（1 human + 7 ai_tool_call + 9 tool_result + 1 ai_message） | ✅ |
| `/history` 响应（`docs/resp.json`） | type=human，content=`"Here is a summary of the conversation to date:…"` | 不定 | ❌（已被 summary 替换）|

**根因**：`backend/app/gateway/routers/threads.py:587-589` 的 `get_thread_history` 从 `checkpoint.channel_values["messages"]` 读取，而 LangGraph 的 SummarizationMiddleware 会原地改写这个列表。

---

## 2. 候选方案

| 方案 | 描述 | 本次是否推荐 |
|---|---|---|
| **A. event_store 覆盖 messages**（已有 plan） | `/history`、`/state` 改读 `RunEventStore.list_messages()`，覆盖 `channel_values["messages"]`；其它字段保持 checkpoint 来源 | ✅ 主方案 |
| B. 修 SummarizationMiddleware | 让 summarize 不原地替换 messages（作为附加 system message） | ❌ 违背 summarize 的 token 预算初衷 |
| C. 双读合并（checkpoint + event_store diff） | 合并 summarize 切点前后的两段 | ❌ 合并逻辑复杂无额外收益 |
| D. 切到现有 `/api/threads/{id}/messages` 端点 | 前端直接消费已经存在的 event-store 消息端点（`thread_runs.py:285-323`）| ⚠️ 更干净但需要前端改动 |

---

## 3. Claude 自评 vs Codex 独立评估

两方独立分析了同一份 plan。重合点基本一致，但 **Codex 发现了一个我遗漏的关键 bug**。

### 3.1 一致结论

| 维度 | 结论 |
|---|---|
| 正确性方向 | event_store 是 append-only + 不受 summarize 影响，方向正确 |
| ID 补齐 | `uuid5(NAMESPACE_URL, f"{thread_id}:{seq}")` 稳定且确定性，安全 |
| 前端 schema | 零改动 |
| Non-message 字段（artifacts/todos/title/thread_data） | summarize 只影响 messages，不需要覆盖其它字段 |
| 多 checkpoint 语义 | 前端 `useStream` 只取 `limit: 1`（`frontend/src/core/threads/hooks.ts:203-210`），不做时间旅行；latest-only 可接受但应在注释/文档写清楚 |
| 作用域 | 仅 Gateway mode；Standard mode 直连 LangGraph Server，bug 在默认部署路径仍然存在 |

### 3.2 Claude 的独立观察

1. 已验证数据对齐：plan 文档第 15-28 行的真实数据对齐表与本次 `run_events` 导出一致（9 条消息 id 分布：AI 来自 LLM `lc_run--*`、human/tool 为 None）。
2. 担心 `run_end` / `run_error` / `cancel` 路径未必都 flush —— 这一点 Codex 实际核查了代码并给出确定结论（见下）。
3. 方案 A 的单文件改动约 60 行，复杂度小。

### 3.3 Codex 的关键补充（Claude 遗漏）

> **Bug #1 — Plan 用 `limit=1000` 并非全量**
> `RunEventStore.list_messages()` 的语义是"返回最新 limit 条"（`base.py:51-65`、`db.py:151-181`）。对于消息数超过 1000 的长对话，plan 当前写法会**丢掉最早的消息**，再次引入"消息丢失"bug（只是换了丢失的段）。

> **Bug #2 — helper 就地修改了 store 的 dict**
> plan 的 helper 里对 `content` 原地写 `id`；`MemoryRunEventStore` 返回的是**活引用**，会污染 store 中的对象。应 deep-copy 或 dict 推导出新对象。

> **Flush 路径已核查**：
> `RunJournal` 在 threshold (`journal.py:360-373`)、`run_end` (`91-96`)、`run_error` (`97-106`)、worker `finally` (`worker.py:280-286`) 都会 flush；`CancelledError` 也走 finally。**正常 end/error/cancel 都 flush，仅硬 kill / 进程崩溃会丢缓冲区**。
> 因此 `flush_threshold 20 → 5` 的意义**仅在于硬崩溃窗口**与 mid-run reload 可见性，**不是正确性修复**，属于可选 tuning。代价是更多 put_batch / SQLite churn；且 `_flush_sync()` (`383-398`) 已防止并发 flush，所以"每 5 条一 flush"是 best-effort 非严格保证。

### 3.4 Codex 未否决但提示的次要点

- 方案 D（消费现有 `/api/threads/{id}/messages` 端点）更干净但需前端改动。
- `/history` 一旦被方案 A 改过，就不再是严格意义上的"按 checkpoint 快照"API（对 messages 字段），应写进注释和 API 文档。
- Standard mode 的 summarize bug 应建立独立 follow-up issue。

---

## 4. 最终合并判决

**Codex**：APPROVE-WITH-CHANGES
**Claude**：同意 Codex 的判决

### 合并前必须修改（Top 3）

1. **修复分页 bug**：不能用固定 `limit=1000`。必须用以下之一：
   - `count = await event_store.count_messages(thread_id)`，再 `list_messages(thread_id, limit=count)`
   - 或循环 cursor 分页（`after_seq`）直到耗尽
2. **不要原地修改 store dict**：helper 对 `content` 的 id 补齐需要 copy（`dict(content)` 浅拷贝足够，因为只写 top-level `id`）
3. **Standard mode 显式 follow-up**：在 plan 文末加 "Standard-mode follow-up: TODO #xxx"，或在合并 PR 描述中明确这是 Gateway-only 止血

### 可选（非阻塞）

4. `flush_threshold 20 → 5` 降级为"可选 tuning"，不是修复的一部分；或独立一条 commit 并说明只对硬崩溃窗口有用
5. `get_thread_history` 新增注释，说明 messages 字段脱离了 checkpoint 快照语义
6. 测试覆盖：模拟 summarize 后的 checkpoint + 真实 event_store，端到端验证 `/history` 返回包含原始 human 消息

---

## 5. 推荐执行顺序

1. 按本文档 §4 修订 `docs/superpowers/plans/2026-04-10-event-store-history.md`（主要是 Task 1 的 helper 实现 + 分页）
2. 按修订后的 plan 执行（走 `superpowers:executing-plans`）
3. 合并后立即建 Standard mode follow-up issue

## 6. Feedback 影响分析（2026-04-11 补充）

### 6.1 数据模型

`feedback` 表（`persistence/feedback/model.py`）：

| 字段 | 说明 |
|---|---|
| `feedback_id` PK | - |
| `run_id` NOT NULL | 反馈目标 run |
| `thread_id` NOT NULL | - |
| `user_id` | - |
| `message_id` nullable | 注释明确写：`optional RunEventStore event identifier` — 已经面向 event_store 设计 |
| UNIQUE(thread_id, run_id, user_id) | 每 run 每用户至多一条 |

**结论**：feedback **不按 message uuid 存**，按 `run_id` 存，所以 summarize 导致的 checkpoint messages 丢失**不会影响 feedback 存储**。schema 天生与 event_store 兼容，**无需数据迁移**。

### 6.2 前端的 runId 映射：发现隐藏 bug

前端 feedback 目前走两条并行的数据链：

| 用途 | 数据源 | 位置 |
|---|---|---|
| 渲染消息体 | `POST /history`（checkpoint） | `useStream` → `thread.messages` |
| 拿 `runId` 映射 | `GET /api/threads/{id}/messages?limit=200`（**event_store**） | `useThreadFeedback` (`hooks.ts:669-709`) |

两者通过 **"AI 消息的序号"** 对齐：

```ts
// hooks.ts:691-698
for (const msg of messages) {
  if (msg.event_type === "ai_message") {
    runIdByAiIndex.push(msg.run_id);  // 只按 AI 顺序 push
  }
}
// message-list.tsx:70-71
runId = feedbackData.runIdByAiIndex[aiMessageIndex]
```

**Bug**：summarize 过的 thread 里，两条数据链的 AI 消息数量和顺序**不一致**：

| 数据源 | 本 thread 的 AI 消息序列 | 数量 |
|---|---|---:|
| `/history`（checkpoint，summarize 后） | seq=19,31,37,45,53 | 5 |
| `/messages`（event_store，完整） | seq=5,13,19,31,37,45,53 | 7 |

结果：前端渲染的"第 0 条 AI 消息"是 seq=19，但 `runIdByAiIndex[0]` 指向 seq=5 的 run（本例同一 run 里没事，**跨多 run 的 thread 点赞就会打到错的 run 上**）。

**这个 bug 和本次 plan 无关，已经存在了**。只是用户未必注意到。

### 6.3 方案 A 对 feedback 的影响

**负面**：无。feedback 存储不受影响。

**正面（意外收益）**：`/history` 切换到 event_store 后，**两条数据链的 AI 消息序列自动对齐**，§6.2 的隐藏 bug 被顺带修好。

**前提条件**（加入 Top 3 改动之一同等重要）：

- 新 helper 必须和 `/messages` 端点用**同样的消息获取逻辑**（same store, same filter）。否则两条链仍然可能在边界条件下漂移
- 具体说：**两边都要做完整分页**。目前 `/messages?limit=200` 在前端硬编码 200，如果 thread 有 >200 条消息就会截断；plan 的 `limit=1000` 也一样有上限。两个上限不一致 → 两边顺序不再对齐 → feedback 映射错位
- **必须修**：`useThreadFeedback` 的 `limit=200` 需要改成分页获取全部，或者 `/messages` 后端改为默认全量

### 6.4 对前端改造顺序的影响

原 plan 声明"零前端改动"，但加入 feedback 考虑后应修正为：

| 改动 | 必须 | 可选 |
|---|---|---|
| 后端 `/history` 改读 event_store | ✅ | - |
| 后端 helper 用分页而非 `limit=1000` | ✅ | - |
| 前端 `useThreadFeedback` 改用分页或提升 limit | ✅ | - |
| `runIdByAiIndex` 增加防御：索引越界 fallback `undefined`（已有）| - | ✅ 已经是 |
| 前端改用 `/messages` 直接做渲染（方案 D） | - | ✅ 长期更干净 |

### 6.5 feedback 相关的新 Top 3 补充

在原来的 Top 3 之外，再加：

4. **前端 `useThreadFeedback` 必须分页或拉全**（`frontend/src/core/threads/hooks.ts:679`），否则和 `/history` 的新全量行为仍然错位
5. **端到端测试**：一个 thread 跨 >1 个 run + 触发 summarize + 给历史 AI 消息点赞，确认 feedback 打到正确的 run_id
6. **TanStack Query 缓存协调**：`thread-feedback` 与 history 查询的 `staleTime` / invalidation 需要在新 run 结束时同步刷新，否则新消息写入后 `runIdByAiIndex` 没更新，点赞会打到上一个 run

---

## 8. 未决问题

- `RunEventStore.count_messages()` 与 `list_messages(after_seq=...)` 的实际性能（SQLite 上对于数千消息级别应无问题，但未压测）
- `MemoryRunEventStore` 与 `DbRunEventStore` 分页语义是否一致（Codex 只核查了 `db.py`，`memory.py` 需确认）
- 是否应把 `/api/threads/{id}/messages` 提升为前端主用 endpoint，把 `/history` 保留为纯 checkpoint API —— 架构层面更干净但成本更高
