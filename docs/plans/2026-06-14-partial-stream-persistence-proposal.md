# 流式响应中断时的部分状态持久化方案（强化版方案一）

**问题简述**：用户发送消息后，在 AI 流式回答过程中点击「停止」。前端会保留已渲染出来的半截回答（图一），但后端没有持久化这部分内容。一旦刷新或重新进入会话，按后端数据重新水合后，半截回答消失（图二），造成「我的数据怎么没了？」的体验落差。

**目标**：消除中断态下前后端数据不一致，让 partial 回答在刷新后仍可见、且不被上下文压缩丢失、tool_call 全部正确闭合。本文不做编码，只提供方案。

**本期不做**：UI 上不区分「已中断」徽标，partial 消息以普通消息形态渲染。

---

## 1. 根因分析

### 1.1 前端：仅 React 内存，无本地持久化

- stop 链路：`handleStop` ([page.tsx:121-123](frontend/src/app/workspace/chats/[thread_id]/page.tsx#L121)) → `thread.stop()` → SDK 调 `POST /api/threads/{id}/runs/{rid}/cancel`
- `thread.messages` 是纯 React state；刷新前不落地
- 重载从后端 history 接口拉，本地 partial 直接丢失

### 1.2 后端：双层持久化，各自的写入时机都错过了 partial

DeerFlow 实际上有**两个独立的持久化层**：

| 持久化层 | 写入时机 | 服务对象 | 中断时状态 |
|---------|---------|---------|-----------|
| **LangGraph Checkpoint** | 图节点执行完成后 | `POST /history`（前端 `useStream` 首屏快照）、下一轮 agent 上下文、`POST /wait` | 不含 partial（节点未完成）|
| **`run_events` 表**（RunEventStore）| `RunJournal` 在 `on_llm_end` / `on_tool_end` 时 | `GET /messages` 系列端点（前端 `useThreadHistory` 按 run 分页加载完整历史）| 不含 partial（`on_llm_end` 未触发）|

调用链：`worker.py:309-337` 的 stream 循环只做 SSE 转发，**两层都不写**；abort 分支（worker.py:340-385）也只设状态、不补 partial。

### 1.3 关键事实：前端是**双数据源 + 客户端合并**，checkpoint 与 run_events 都是 UI 数据源

经调研确认：

| 调用方 | 端点 | 后端数据源 | 触发时机 |
|--------|------|----------|---------|
| `useStream` SDK（`fetchStateHistory: { limit: 1 }`, [hooks.ts:498-503](frontend/src/core/threads/hooks.ts#L498)） | `POST /api/threads/{id}/history`（[threads.py:599-670](backend/app/gateway/routers/threads.py#L599)，内部 `checkpointer.alist(..., limit=1)` 取最近 1 个 checkpoint 的 `channel_values.messages`） | **checkpoint** | 进入会话页、reconnect、刷新 |
| `useThreadHistory`（[hooks.ts:1033-1206](frontend/src/core/threads/hooks.ts#L1033)） | `GET /api/threads/{id}/runs/{rid}/messages` ([thread_runs.py:384](backend/app/gateway/routers/thread_runs.py#L384))、`GET /api/runs/{rid}/messages` ([runs.py:106](backend/app/gateway/routers/runs.py#L106)) | **`run_events` 表**（`event_store.list_messages_by_run()`） | 按 run 维度分页加载完整历史 |

两路结果在 [hooks.ts:199-237](frontend/src/core/threads/hooks.ts#L199) 的 `mergeMessages(historyMessages, threadMessages, optimisticMessages)` 中按 message identity 去重合并：

- `threadMessages`（来自 checkpoint via `useStream`）→ 决定**首屏快照**（用户打开页面看到的第一眼）
- `historyMessages`（来自 run_events via `useThreadHistory`）→ 决定**完整历史回溯**（向上滚动、跨 run 翻阅）

**推论**：partial 的「首屏可见性」依赖 checkpoint；「长期可回溯性 + 压缩后仍可查」依赖 run_events。**两者都要写**，承担不同职责（详见 §3.3 / §3.4）。

### 1.4 关键事实：summarization 只清 checkpoint，不动 run_events

`SummarizationMiddleware` 通过 `RemoveMessage(REMOVE_ALL_MESSAGES)` 清的是 checkpoint 里的 `ThreadState.messages`，**`run_events` 是 append-only，不会被清**。两者寿命由此发散：

- partial 在 checkpoint：随上下文压缩可能被替换为摘要后消失
- partial 在 run_events：永久存活，跨多轮会话仍可回溯
- 用户的合并视图始终保留 partial — checkpoint 失去后由 run_events 通过 `mergeMessages` 补足

### 1.5 关键事实：`DanglingToolCallMiddleware` 不持久化任何东西

调研确认 [dangling_tool_call_middleware.py:186-205](backend/packages/harness/deerflow/agents/middlewares/dangling_tool_call_middleware.py#L186)：

- 它在 `wrap_model_call` 钩子里 patch **模型输入** (`request.override(messages=patched)`)
- 修补出的 `ToolMessage(status="error")` 是临时的，**既不写 checkpoint 也不写 run_events**，每轮模型调用重新计算一次
- 这意味着：如果只持久化带 tool_call 的 partial AIMessage 而**不主动闭合** ToolMessage，会出现：
  - run_events 视角：UI 看到一个"光秃秃"的带 tool_call 的 AIMessage，没有任何结果，渲染异常
  - checkpoint 视角：每一轮 DanglingToolCallMiddleware 都重复注入 ephemeral ToolMessage，浪费 token

→ tool_call 的闭合必须**由 partial 持久化逻辑主动完成并写入两层**，不能依赖现有中间件。

---

## 2. 强化版方案概览

```
                  cancel 触发 (action != "rollback")
                                │
                                ▼
                ┌──────────────────────────────────┐
                │  worker 累加器                    │
                │  partial: dict[msg_id, Chunk]    │  ← 在 stream 循环里持续累加
                └──────────────────────────────────┘
                                │
                                ▼
                ┌──────────────────────────────────┐
                │  tool_call 闭合处理                │
                │  完整 tool_calls + invalid 都生成   │
                │  对应 ToolMessage(status=error)   │
                └──────────────────────────────────┘
                                │
                  ┌─────────────┴─────────────┐
                  ▼                           ▼
        ┌─────────────────┐         ┌─────────────────┐
        │  写 run_events   │         │  写 checkpoint  │
        │  长期历史/抗压缩  │         │  首屏快照/Agent │
        │  append-only    │         │  uuid6 INSERT   │
        │  喂 history 接口 │         │  喂 /history    │
        └─────────────────┘         └─────────────────┘
```

两边各自服务一条前端数据通路 — checkpoint 喂 `useStream` 的首屏快照，run_events 喂 `useThreadHistory` 的分页历史 — 缺一不可（详见 §1.3、§3.3、§3.4）。

---

## 3. 详细设计

### 3.1 子任务 A：累加 partial AIMessage

#### 累加位置
- 文件：[worker.py:309-337](backend/packages/harness/deerflow/runtime/runs/worker.py#L309)
- 在 `bridge.publish(...)` 之前对 `messages-tuple` chunk 做本地聚合
- 数据结构：`partial_messages: dict[str, AIMessageChunk] = {}`，按 message id 累加（同一 `id` 的 chunk 用 `+` 合并）

#### chunk 合并语义
LangChain `AIMessageChunk + AIMessageChunk` 已实现增量合并：
- `content`：字符串拼接 / list 按 block index 合并（涵盖 Anthropic `thinking` block 增量）
- `additional_kwargs`：深度 merge（涵盖 `reasoning_content`）
- `tool_call_chunks`：按 `index` 合并
- `usage_metadata`：累加

合并完成后调用 LangChain 自带的 `message_chunk_to_message(chunk)` 转为 AIMessage。

#### 流转保留
聚合**只是旁路**，不改变 `bridge.publish(...)` 行为，确保现有前端 SSE 体验完全不变。

---

### 3.2 子任务 B：tool_call 闭合（核心约束）

中断时可能存在 N 个完整 tool_call + 0 或 1 个不完整 tool_call。**全部都要闭合，不允许丢弃**。

#### B1 完整 tool_call（args JSON 已闭合）
- chunk 合并后落在 AIMessage 的 `tool_calls` 数组
- 每个元素都有 `id` / `name` / `args`(dict)
- 原样保留

#### B2 不完整 tool_call（args JSON 残缺）
- chunk 合并后落在 `invalid_tool_calls` 数组，带 `id` / `name` / `args`(原始字符串) / `error`
- **保留** `invalid_tool_calls`
- **同时保留** `additional_kwargs["tool_calls"]` 中的原始 provider payload（与 `DanglingToolCallMiddleware` 现有对残缺 tool_call 的兜底路径一致，方便诊断）

#### B3 闭合 ToolMessage 注入
对 `tool_calls + invalid_tool_calls` 中的**每个** tool_call，生成一条：

```python
ToolMessage(
    content="[Tool call was interrupted before it could be executed.]",
    tool_call_id=tc.id,
    name=tc.name or "unknown",
    status="error",
)
```

闭合措辞复用 [dangling_tool_call_middleware.py:104-126](backend/packages/harness/deerflow/agents/middlewares/dangling_tool_call_middleware.py#L104)（建议把闭合模板抽到公共常量供两边复用，避免文案漂移）。

#### B4 invalid tool_call 的 id 一定要有
LangChain chunk 合并即使 args 残缺，也会基于 `tool_call_chunks[i].index` 生成稳定 id；如果遇到极端情况没有 id，则在 worker 兜底生成 `f"tc_interrupted_{uuid7()}"`。**没有 id 就没法关联 ToolMessage，必须兜底**。

---

### 3.3 子任务 C：写入 `run_events`（长期历史 + 抗压缩，必选）

#### 推荐方式：扩展 `RunJournal`
- 文件：[journal.py](backend/packages/harness/deerflow/runtime/journal.py)
- 新增方法 `record_partial_response(ai_message, tool_messages, *, interrupted: bool = True)`
- 内部：与现有 `on_llm_end` / `on_tool_end` 走同一管道，复用 seq、user_id 注入、JSON 序列化等抽象
- 写入：
  - AIMessage → `event_type="llm.ai.response"`, `category="message"`, `event_metadata={"interrupted": true, "partial": true}`
  - 每条闭合 ToolMessage → `event_type="llm.tool.result"`, `category="message"`, `event_metadata={"interrupted": true, "synthetic": true, "reason": "tool_call_interrupted"}`

`event_metadata` 字段本期**只埋点不消费**——前端按普通消息渲染，但后续若要做"已中断"徽标，标识通道已就位。

#### 调用时机
- 在 `worker.py` 的 abort 分支（line 340-357）调用，**早于** finally 块里的 `journal.flush()`
- 仅在 `action != "rollback"` 时执行
- 同样应在 `asyncio.CancelledError` 分支（line 367-385）的 `interrupt` 路径调用

#### 不走的方式
- 直接 `event_store.put_batch(...)` 绕过 journal —— 失去 seq 分配、user_id 注入等抽象，**不推荐**
- 伪造 `on_llm_end` / `on_tool_end` 回调 —— 触发别的 callback handler 副作用，**不推荐**

---

### 3.4 子任务 D：写入 Checkpoint（首屏快照 + Agent 上下文，必选）

#### 为什么 run_events 之外仍要写 checkpoint

| 目的 | 不写的后果 |
|------|----------|
| 刷新后**首屏渲染**就带 partial（`useStream` 通过 `fetchStateHistory` 调 `/history` 读最近 1 个 checkpoint 作为初始 `threadMessages`）| 首屏先闪空白，等 `useThreadHistory` 异步加载完才补 partial — 体验回到原问题 |
| 用户中断后立即继续问下一个问题，agent 看到的 messages 来自 checkpoint，需要包含 partial 才能语义连贯 | "失忆"，agent 不知道刚才说了什么 |
| 让 `DanglingToolCallMiddleware` 看到闭合 ToolMessage 已存在，下一轮不重复注入 ephemeral 版本 | 每轮重复注入 → token 浪费 + 模型困惑 |
| `POST /wait` 等基于 checkpoint 的端点状态一致 | 状态错位 |

#### 写入方式
- 沿用 [threads.py:540-596](backend/app/gateway/routers/threads.py#L540) 的 uuid6 **INSERT** 模式
- 由 worker 直接 `checkpointer.aput(...)`，不走 HTTP
- 新 uuid6 **不覆盖**最后一次完整 checkpoint，作为历史的一个新增节点

#### 与 Summarization 的关系
- 下一轮 `before_model` 时，SummarizationMiddleware 可能把 partial 一并压缩掉
- 这**符合预期**：partial 在 checkpoint 可能失效，但 `run_events` 永久保留；前端 `mergeMessages` 把 run_events 的 historyMessages 补回来，用户视图仍完整
- agent 上下文里有摘要，语义连贯
- 不需要给 partial 加"防压缩"标记

---

### 3.5 子任务 E：UI（本期不动）

- 不在 [message-group.tsx](frontend/src/components/workspace/messages/message-group.tsx) 加"已中断"徽标
- partial AIMessage 按普通 AIMessage 渲染；闭合 ToolMessage 按普通 status=error 的 ToolMessage 渲染
- 用户体感：刷新后内容与中断前一致 —— 已经隐式做到「所见即所得」
- 后期需要区分中断态时，读 `event_metadata.interrupted` 即可，已埋点

### 3.6 跨存储的 ID 一致性（关键不变量）

前端 `mergeMessages` 按 message identity 去重，所以 **partial 在 checkpoint 与 run_events 两层必须使用同一个 message id**：

- partial AIMessage：直接用 chunk 合并后的 `id`（LangChain `AIMessageChunk` 合并过程会保持稳定 id）
- 闭合 ToolMessage：必须为每条派生稳定 id，建议格式 `f"tm_interrupted_{tool_call_id}"`
- worker 在两层写入时**复用同一份**消息对象，禁止分别构造

否则会出现同一条 partial 在 UI 上重复显示的 bug（一份来自 checkpoint，一份来自 run_events，id 不同 → 去重失败）。

---

## 4. 改动文件清单

### 后端

| 文件 | 改动 | 关联子任务 |
|------|------|----------|
| [worker.py](backend/packages/harness/deerflow/runtime/runs/worker.py) | stream 循环加累加器；abort 分支调用持久化 | A、C、D |
| [journal.py](backend/packages/harness/deerflow/runtime/journal.py) | 新增 `record_partial_response()` 方法 | C |
| 新增 `runtime/runs/partial_persist.py`（建议）| 累加器辅助函数、tool_call 闭合工具、checkpoint 写入封装 | A、B、D |
| [dangling_tool_call_middleware.py](backend/packages/harness/deerflow/agents/middlewares/dangling_tool_call_middleware.py) | 把闭合消息模板（"[Tool call was interrupted...]"）抽到公共常量供 worker 复用 | B |

### 前端

**无改动**。partial 消息以普通消息形态自然渲染。

### Sub-agent（独立增量，建议第二阶段）

- [subagents/executor.py](backend/packages/harness/deerflow/subagents/executor.py) 的 cancel 分支同样接入累加 + 双写
- 需要处理 `custom event: task_running` 的状态聚合
- 第二阶段单独 PR，不阻塞本期上线

---

## 5. 测试与验证

| 场景 | 期望 |
|------|------|
| 纯文本回答中断后刷新 | partial 文本完整可见 |
| 含完整 tool_call（args 已闭合）回答中断 | AIMessage + 对应 ToolMessage(status=error) 都写入 run_events 与 checkpoint |
| 含残缺 tool_call（args JSON 未闭合）回答中断 | `invalid_tool_calls` 保留 + 对应 ToolMessage(status=error) 写入 |
| 中断后继续发新消息 | 模型上下文连贯，DanglingToolCallMiddleware 不重复注入（断言 model input 里 ToolMessage 数量 == tool_call 数量）|
| 中断 → 触发 summarization → 刷新 | checkpoint 中 partial 可能被压缩，但 `GET /messages` 仍返回 partial（来自 run_events）|
| `multitask_strategy="rollback"` | partial **不**写入（避免与 rollback 语义冲突），checkpoint 回滚到 pre-run |
| `POST /state` 端点并发写 | uuid6 INSERT 保证不互相覆盖 |
| 极长回复中断 | 累加器内存可控（按 msg_id 维度有界）|

建议在 `backend/tests/` 增加：
- `test_worker_partial_persist.py` — 模拟 abort，断言 `run_events` 与 checkpoint 双写
- `test_partial_message_after_summarization.py` — 触发 summarization 后断言 `GET /messages` 仍返回 partial
- `test_partial_tool_call_closure.py` — 完整 / invalid tool_call 都得到闭合 ToolMessage
- `test_dangling_tool_call_no_double_inject.py` — 中断 + 闭合 + 下一轮，断言不重复注入

---

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| chunk 合并异常 | try/except 包裹整段持久化，失败 fallback 到原有行为，加 ERROR 日志 + 计数指标 |
| 累加器内存占用（极长回复）| message id 维度天然有界；同一 run 内 message id 数量受 LLM 行为约束，无需主动 cap |
| `run_events` 写失败（DB 故障）| 现有 `journal.flush()` 已 try/except，沿用；至少 SSE 已经发到前端，体感与现状一致 |
| checkpoint 写失败 | 同上 try/except；run_events 已写入是更重要的保证 |
| invalid tool_call 在前端反序列化 | LangChain JS SDK 支持 `invalid_tool_calls`；若有 UI bug 独立修复 |
| Token 计费遗漏 | partial AIMessage 携带 `usage_metadata`；在 `record_partial_response()` 内同步通知 `TokenUsageMiddleware`/`journal` 计入完成数据（与 `update_run_completion` 同口径）|
| 与 ACP 子 agent 交互 | 第二阶段处理，本期不阻塞 |
| `seq` 顺序与并发的活动 run 冲突 | RunEventStore 的 seq 是 `(thread_id)` 单调，落库前 worker 已经持有 abort 后的同步上下文；保留现有锁/串行写假设 |

---

## 7. 开放问题

1. partial 消息携带的 `usage_metadata` 是否计入用户配额？**建议**：计入。
2. `event_metadata.interrupted` 标记是否在 API 响应里透出？**建议**：透出。前端 JSON 反序列化即可见，不影响现有渲染，为后续 UI 提供通道。
3. 中断后**立即**继续发新消息，前端从新 SSE 流拿到的 messages 与本地通过 history 接口拿到的 partial 是否存在顺序冲突？**待验证**：依赖 `seq` 单调，理论上无冲突，但需要回归测试。
4. sub-agent 中断的 partial 持久化纳入第二阶段，主线先稳定后再做。
5. 是否在 `event_metadata` 里加 `cancelled_at` 时间戳？**建议**：加，便于后续做"未完成会话恢复"等功能。

---

## 8. 实施顺序建议

1. 抽闭合消息模板到公共常量（小步重构，可独立合并）
2. 给 `RunJournal` 加 `record_partial_response()` 并单测
3. 加 worker 累加器（不开启持久化，先验证累加正确性，加单测）
4. 接通 abort 分支双写逻辑（run_events + checkpoint）
5. 端到端测试矩阵跑通
6. （第二阶段）sub-agent 同步增量
