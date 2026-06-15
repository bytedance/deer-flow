## Context

DeerFlow 前端通过 LangGraph SDK 的 `useStream` hook 与后端建立 SSE 长连接，实现流式 AI 响应。当前每个 thread 实际维持**两条连接**：`useStream` 的 LangGraph SDK SSE（[hooks.ts:241](frontend/src/core/threads/hooks.ts#L241)）和 `GenUISSEManager` 的 UI block recovery SSE（[sse-recovery.ts:16](frontend/src/core/genui/sse-recovery.ts#L16)）。

当前实现存在以下问题：

1. **连接层无差别全量订阅**：[hooks.ts:246](frontend/src/core/threads/hooks.ts#L246) 中 `reconnectOnMount: true` 导致所有挂载的会话都维持完整 SSE 流，即使页面不可见。`streamSubgraphs: true` 在 [hooks.ts:582](frontend/src/core/threads/hooks.ts#L582) 被设为默认且为 per-run 配置（传给 `client.runs.stream()`，控制 run 的执行模式而非订阅过滤）。`GenUISSEManager` 同样缺乏 visibility 感知。

2. **协议层全档 stream mode**：前端默认订阅 `values + messages-tuple + custom + updates` 全部模式。`values` 事件推送整份 `ThreadState` 快照，长会话下单帧可达数十 KB。`onLangChainEvent` 监听 `on_tool_end`（[hooks.ts:258](frontend/src/core/threads/hooks.ts#L258)），但后端可能跳过 events mode（需验证）。`onUpdateEvent`（[hooks.ts:266-321](frontend/src/core/threads/hooks.ts#L266-L321)）依赖 `updates` mode 处理 SummarizationMiddleware 消息迁移和 title 更新——降级 stream mode 时必须保留 `updates`。

3. **渲染层全量重解析**：[history.ts:46-57](frontend/src/core/genui/history.ts#L46-L57) 每次 messages 变化都 POST 全量消息到 `/ui-blocks/extract`。[message-list.tsx](frontend/src/components/workspace/messages/message-list.tsx) 有 20+ 个 `useMemo` 全量重算。`useBlockStore` (Zustand) 的 `replaceAllBlocks` 操作与 extract 调用节奏耦合。

4. **部署层单进程限制**：[stream_bridge_config.py:13-15](backend/packages/harness/deerflow/config/stream_bridge_config.py#L13-L15) 的 `memory` 模式使用 in-process `asyncio.Queue`，仅支持单进程。`queue_maxsize: 256` 过小，溢出行为未定义。

5. **`TitleMiddleware` 不使用 `StreamWriter`**：[title_middleware.py:174-179](backend/packages/harness/deerflow/agents/middlewares/title_middleware.py#L174-L179) 通过 `after_model` 返回 state diff（`{"title": "..."}`）更新标题，不经过 `custom` 事件通道。不能简单地在每个 middleware 中分别添加 emit 逻辑。

## Goals / Non-Goals

**Goals:**

- 多会话并发（3-5 个）时浏览器主线程不再持续长任务
- 活跃 SSE 数量（含 `GenUISSEManager`）≈ 当前可见会话数 x 2（每个 thread 两条连接）
- 普通聊天场景 SSE 平均包体 < 2KB（去掉 `values` mode 后）
- 流过程中 `/ui-blocks/extract` 调用次数降至 O(1)
- 多 worker 部署下流重连恢复成功率 > 99%
- 后台暂停期间 run 完成时，切回后 2s 内完成状态同步和 `onFinish` 兜底

**Non-Goals:**

- 不改变 LangGraph SDK 的底层 SSE 协议格式
- 不实现 WebSocket 替代方案（SSE 足够，HTTP/2 多路复用解决连接数问题）
- 不修改 agent 执行逻辑或中间件链行为（`StatePatchEmitMiddleware` 是新增中间件，不修改现有中间件）
- 不改变报告生成管线的执行流程
- 不实现跨实例的实时状态同步（仅保证流连续性）
- 不在运行时动态切换 `streamSubgraphs`（per-run 配置，提交时决定）

## Decisions

### 决策 1：连接生命周期基于 Page Visibility API + 活跃 run 检测

**选择**：使用 `document.visibilityState` + `thread.isLoading` 双重条件控制重连和流消费。`GenUISSEManager` 同样接入 visibility 感知。

**替代方案**：
- A) 基于 React 组件 mount/unmount：不可行，React Router 不一定在标签页切换时卸载组件。
- B) 基于 `requestIdleCallback` 降低后台优先级：不够，后台标签页仍会触发 SSE 数据消费和 React 状态更新。
- C) 基于 `BroadcastChannel` 跨标签页协调：过度复杂，且浏览器不保证后台标签页的投递。

**理由**：Page Visibility API 是浏览器标准，语义清晰，与 React 生命周期解耦。`GenUISSEManager` 是独立于 `useStream` 的连接，需要单独接入 visibility 感知，否则优化效果减半。

### 决策 2：Stream mode 分两档，`standard` 保留 `updates`

**选择**：定义两档固定组合。`standard` 包含 `updates`（不含 `values`），`full` 包含全部。

**替代方案**：
- A) 三档（`standard` 不含 `updates`）：会导致 SummarizationMiddleware 消息迁移失效和 title 更新延迟，引入功能回退。
- B) 每个订阅源独立开关：灵活但易出错。

**理由**：`onUpdateEvent`（[hooks.ts:266-321](frontend/src/core/threads/hooks.ts#L266-L321)）依赖 `updates` mode 处理 SummarizationMiddleware 的消息迁移（L267-293）和 title 更新同步到侧边栏（L295-321）。去掉 `updates` 会导致被摘要的消息直接消失、title 更新延迟到 `onFinish`。保留 `updates` 后，`standard` 和 `full` 的唯一差异是 `values` mode——这正是我们要消除的大包体源。

| 档位 | stream mode | 适用场景 | 与当前差异 |
|------|-------------|----------|-----------|
| `standard` | `["messages-tuple", "updates", "custom"]` | 普通聊天 + 子代理 | 去掉 `values`，包体降 80%+ |
| `full` | `["values", "messages-tuple", "updates", "custom"]` | 报告生成/模板预览 | 不变 |

### 决策 3：`streamSubgraphs` 为 per-run 配置，按 agent mode 决定

**选择**：`streamSubgraphs` 在 `sendMessage`（[hooks.ts:582](frontend/src/core/threads/hooks.ts#L582)）中按 agent mode 条件设置：`ultra` mode 为 `true`（启用子代理），其他 mode 为 `false`。不支持运行时动态切换。

**替代方案**：
- A) 根据子代理面板是否展开动态切换：不可行。`streamSubgraphs` 是 per-run 配置，传给 `client.runs.stream()`，控制 run 的执行模式。一旦 run 以 `false` 启动，后续展开面板也没有子图事件可消费。
- B) 始终设为 `true`：浪费带宽，普通聊天不需要子图事件。

**理由**：`streamSubgraphs` 控制的是 run 是否产生子图事件，不是前端的订阅过滤。必须在 run 创建时决定，与 UI 面板状态无关。

### 决策 4：统一 `StatePatchEmitMiddleware` + 实例级 `_last_emitted` 状态比对

**选择**：创建一个新的 `StatePatchEmitMiddleware`，放在中间件链末尾（所有 state-modifying middleware 之后）。在 `after_model`/`aafter_model` 中，从当前 state 读取 `title`/`todos`/`artifacts` 字段值，与实例级 `_last_emitted` 缓存比对。对每个有变化的字段，通过 `get_stream_writer()` emit `state_patch` custom 事件，并更新 `_last_emitted`。中间件返回空 dict（不修改 state）。

**替代方案**：
- A) 在 `TitleMiddleware`、`TodoListMiddleware` 等每个 middleware 中分别添加 `get_stream_writer()` 调用：侵入现有 middleware 内部实现，违反单一职责，新增 state 字段时需要修改多个 middleware。
- B) 从 `updates` 事件中提取 state 变更：`updates` 事件按 node 分组，解析复杂且不稳定。
- C) 读取 state diff 参数比对：LangGraph middleware 的 `after_model` 接收的 state 是 pre-merge state，无法直接拿到前一个 middleware 返回的 diff。diff 在 LangGraph runtime 内部合并后才变为可见的 state。

**理由**：方案 C 不可行的根本原因是 LangGraph 的 middleware 执行模型：每个 middleware 的 `after_model` 在 model 返回后依次执行，各自返回 state diff，但 diff 在所有 middleware 执行完毕后才由 runtime 合并到 state。因此任何单个 middleware 无法在 `after_model` 中直接"看到"其他 middleware 产生的 diff。方案 D 绕过 diff 比对，改为**读取 state 字段的绝对值**并与上次 emit 时的值比对。因为中间件放在链末尾，此时所有 state-modifying middleware 已执行完毕，state 中的字段值是最新的。实例级 `_last_emitted` 缓存跨调用持久化，使中间件能检测跨轮次的变化。

**实现细节**：
```python
class StatePatchEmitMiddleware:
    def __init__(self):
        self._last_emitted: dict[str, Any] = {}

    def after_model(self, state: ThreadState, runtime: MiddlewareRuntime) -> dict:
        writer = get_stream_writer()
        tracked_fields = {"title", "todos", "artifacts"}
        for field in tracked_fields:
            current_value = state.get(field)
            if current_value != self._last_emitted.get(field):
                writer({"type": "state_patch", "patch": {field: current_value}})
                self._last_emitted[field] = current_value
        return {}  # 不修改 state
```

**兼容策略**：state diff 仍由原 middleware（如 `TitleMiddleware`）返回，通过 `values`/`updates` mode 传递。`state_patch` custom event 是额外的增量通道。两套通道并行，前端做幂等处理（last write wins）。

### 决策 5：GenUI 增量解析 + 流结束全量校验 + `GenUISSEManager` 整合

**选择**：流过程中只对新增消息做增量 extract（500ms 防抖），流结束后做一次全量校验兜底。`GenUISSEManager` 的 block 恢复逻辑与增量 extract 整合为单一数据源，避免两套 block 同步机制并行。`useBlockStore` 操作节奏适配增量模式。

**替代方案**：
- A) 纯前端本地解析：需将后端解析逻辑复制到前端，维护成本高。
- B) 保持 `GenUISSEManager` 和增量 extract 并行：两套机制可能冲突，block 状态不一致。

**理由**：当前 `GenUISSEManager`（[sse-recovery.ts](frontend/src/core/genui/sse-recovery.ts)）通过 `/api/threads/{id}/ui-blocks` 恢复 block，增量 extract 通过 `/ui-blocks/extract` 解析 block。两条路径、两个端点、两套状态管理。整合后统一由增量 extract 管理 block 状态，`GenUISSEManager` 仅负责连接健康检查和 visibility 感知。

### 决策 6：`onFinish` pause/resume 兜底

**选择**：在 `useDocumentVisible` 从 `false` 变为 `true` 时，检查 `thread.status`。如果已经是 `completed`/`error` 但 `onFinish` 未触发（后台暂停期间 run 完成），手动执行收尾逻辑：从 `/threads/{id}/state` 拉取完整 state、`appendMessages`、`invalidateQueries`。

**替代方案**：
- A) 依赖 LangGraph SDK 的 `reconnectOnMount` 自动触发 `onFinish`：不可靠。SDK 的 reconnect 行为取决于 run 状态和 checkpoint，后台暂停期间的 run 完成可能不会触发 `onFinish`。
- B) 不做兜底：用户切回后看到的是不完整的消息列表，需要手动刷新。

**理由**：`onFinish`（[hooks.ts:383-392](frontend/src/core/threads/hooks.ts#L383-L392)）做了关键的收尾工作：`appendMessages`、`invalidateQueries`。后台暂停期间 SSE 被暂停，`messagesRef.current` 不完整，`onFinish` 可能不会触发。必须显式兜底。

### 决策 7：Backpressure 合并丢弃 + `queue_maxsize` 提升

**选择**：
- `queue_maxsize` 从 256 提升到 1024（降低触发频率）
- 队列满时执行合并丢弃：同一消息的连续 `messages-tuple` token 事件，只丢弃中间的 token，保留首尾
- 非 `messages-tuple` 事件（`custom`、`updates`）按 FIFO 丢弃最旧
- 每个事件带 sequence number，前端检测 gap 后触发 state fetch

**替代方案**：
- A) 简单 FIFO 丢弃最旧：聊天场景丢弃旧 token 会导致消息开头缺失，用户永远看不到完整的首条消息。
- B) 丢弃最新：丢失最新数据更严重。
- C) 无限队列：内存泄漏风险。

**理由**：聊天和视频流的关键区别是视频丢帧后后续帧能补偿，聊天丢事件后内容不可恢复。合并丢弃保留消息的首尾 token，前端可以通过 state fetch 补齐中间缺失的 token。1024 的队列大小在普通聊天场景下几乎不会触发。

### 决策 8：Stream Bridge 短期 sticky session + 中期 Redis

**选择**：
- 短期：Nginx 配置基于 `thread_id` 的一致性哈希
- 中期：实现 Redis stream bridge（`stream_bridge_config.py` 已预留配置字段）

**决策时机**：先确认当前部署拓扑。如果已经是多 worker/多实例部署，Redis bridge 优先级提升为短期。

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|------|------|------|
| `pause()` 导致切回时消息不完整 | 用户看到缺失的中间输出 | `fetchStateHistory: { limit: 1 }` 补齐 + `onFinish` 兜底检测（决策 6） |
| `streamSubgraphs` 为 per-run 配置无法动态切换 | 提交时 mode 不对，后续无法补救 | 按 agent mode 决定（`ultra` → `true`），文档说明不支持运行时切换 |
| `state_patch` 事件丢失（网络抖动） | title/todos 不更新 | sequence number gap 检测后触发 state fetch（无 periodic polling）；`full` 档仍接收 `values` 作为 fallback |
| 增量 GenUI extract 结果与全量不一致 | UI block 显示错误 | 流结束后全量校验覆盖；snapshot test 确保两种路径产出一致 |
| `StatePatchEmitMiddleware` 与原 middleware 的 state diff 并行 | 前端同时收到 `updates` 和 `state_patch` 的 title 更新 | 前端 `onCustomEvent` 和 `onUpdateEvent` 都做幂等处理，以最后到达的为准 |
| 前后端协议变更需同步发版 | 灰度期间新旧版本共存 | 后端保留 `values` 全量推送，前端通过 stream mode 分档控制 |
| Sticky session 在 worker 重启时失效 | 流中断 | 前端 `reconnectOnMount` 自动重连 + `onFinish` 兜底 |
| Backpressure 合并丢弃后 UI 闪烁 | 短暂的消息内容不连续 | `queue_maxsize` 提升到 1024 降低触发频率；sequence number 检测后 state fetch 补齐 |
| `GenUISSEManager` 与增量 extract 整合引入 bug | block 状态不一致 | 整合期间保留双路径 fallback，验证稳定后移除旧路径 |
| `onLangChainEvent` 可能实际有效（后端未跳过 events mode） | 移除后丢失 tool_end 追踪 | 实施前先验证后端行为；如有效则保留，同时增加 `tool_end` custom event 作为冗余 |
