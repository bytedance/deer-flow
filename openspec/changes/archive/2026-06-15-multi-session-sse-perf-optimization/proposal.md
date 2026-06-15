## Why

多会话并发场景下，浏览器同时维持多个完整 SSE 流式会话时前后端均被拖垮。前端默认对所有会话开启 `reconnectOnMount`、`streamSubgraphs`、`streamResumable`，即使页面不可见也持续消费全量事件；每个流订阅 `values + messages + updates + custom` 全档 stream mode，其中 `values` 为整份 state 快照序列化，长会话下每帧体积大；GenUI 每次消息变化都全量调用 `/ui-blocks/extract` 重解析整批消息，消息列表也对全量 messages 重做分组计算。三者乘在一起，复杂度为 O(会话数 x 消息数 x 每帧 state 大小)。此外，stream bridge 默认为内存实现（单进程限制），多 worker/多实例部署下重连会丢失流状态；`GenUISSEManager` 独立于 `useStream` 维护第二条 SSE 连接用于 block 恢复，同样缺乏 visibility 感知。需要先止血前端连接层，再逐步瘦身协议和渲染层。

## What Changes

- **前端智能重连策略**：`reconnectOnMount` 仅对当前可见页面且存在未完成 run 时开启；`streamSubgraphs` 仅在提交消息时根据 agent mode（ultra 启用子代理）决定是否开启（per-run 配置，非 per-subscription）；失焦标签页主动暂停 SSE 消费，切回时通过 `fetchStateHistory` 补齐状态并检测是否需要手动触发 `onFinish` 兜底逻辑。
- **渲染节流升级**：`useStream` 的 `throttle` 从 100ms 改为自适应：单流 100ms（保持当前响应感），多流并发 300ms（降低主线程压力）。消息列表分组和 block 归属计算从全量重算改为增量追加。`GenUISSEManager` 的 block 恢复和重连同样适配 visibility 感知。
- **流事件分档订阅**：普通聊天页订阅 `messages-tuple + updates + custom`（保留 `updates` 以确保 SummarizationMiddleware 消息迁移和 title 更新正常工作）；报告/模板场景追加 `values`。移除无效的 `onLangChainEvent` 依赖前先验证后端是否确实跳过 events mode。
- **小事件替代全量 values 快照**：创建统一的 `StatePatchEmitMiddleware`（而非在每个 middleware 中分别添加 emit 逻辑），在中间件链 `after_model` 位置检测 state diff 中的 `title`/`todos`/`artifacts` 变化并自动 emit `state_patch` custom 事件（只推 diff），前端局部更新缓存。
- **GenUI 增量解析**：流过程中只对新增消息做增量 `/ui-blocks/extract`（500ms 防抖），流结束后做一次全量校验兜底。消除流过程中随每条消息持续触发的全量解析。同步整合 `GenUISSEManager` 的 block 恢复逻辑与增量 extract，避免两套同步机制并行。
- **tool_end 自定义事件补全**：后端工具执行完成后 emit `tool_end` custom 事件（只推摘要），替代前端无法收到的 `onLangChainEvent`。
- **Stream Bridge 多实例兜底**：短期 Nginx 配置 sticky session 保证同一 thread 打到同一 worker；中期实现 Redis stream bridge 替代内存实现。`queue_maxsize` 从 256 提升到 1024，增加 backpressure 合并丢弃策略（同一消息的连续 token 事件只丢中间保留首尾），防止慢消费者阻塞 agent worker。

## Capabilities

### New Capabilities

- `sse-connection-lifecycle`: SSE 连接生命周期管理能力。基于 Page Visibility API 的智能重连策略、失焦暂停/切回恢复（含 `onFinish` 兜底）、stream mode 分档订阅（`standard` 保留 `updates`）、throttle 参数调优、`streamSubgraphs` per-run 条件控制、`GenUISSEManager` visibility 感知。
- `stream-event-compaction`: 流事件瘦身能力。统一 `StatePatchEmitMiddleware` 发射 `state_patch` 增量事件、`tool_end` 自定义事件、stream mode 按场景分档选择（`standard` 不含 `values`，`full` 含 `values`）。替代当前全量 values 快照推送。
- `genui-incremental-extract`: GenUI 增量解析能力。流过程中增量 extract（500ms 防抖、仅新增消息），流结束后全量校验兜底。消息列表分组/block 归属从全量重算改为增量追加。`GenUISSEManager` block 恢复与增量 extract 整合、visibility 感知。`useBlockStore` (Zustand) 操作节奏适配。
- `stream-bridge-multi-instance`: Stream Bridge 多实例部署能力。Nginx sticky session 短期方案、Redis stream bridge 中期方案、backpressure 合并丢弃策略（`queue_maxsize` 提升到 1024、同消息连续 token 事件合并丢弃 + sequence number 校验）。

### Modified Capabilities

- `empathetic-error-handling`: 错误分类和重试逻辑需适配流暂停/恢复场景，后台暂停期间的错误不应以 toast 形式弹出；`onFinish` 在 pause/resume 场景需定义兜底行为。

## Impact

- **范围排除说明**：报告生成场景（daily/weekly/monthly report）不在本次优化范围内。报告页面使用 `full` 档 stream mode（含 `values`），且报告执行流程（executor + report_direct_tools）有独立的 SSE 消费链路。本次优化仅影响普通聊天和子代理场景的连接层和渲染层。报告页面的性能优化将在后续专项中处理。
- **代码（前端）**：
  - `frontend/src/core/threads/hooks.ts`：`useStream` 参数改为动态（自适应 throttle、reconnectOnMount、streamMode）；`streamSubgraphs` 改为在 `sendMessage` 中按 agent mode 条件开启；`onLangChainEvent` 验证后迁移到 `onCustomEvent`；`onFinish` 增加 pause/resume 兜底
  - `frontend/src/core/api/stream-mode.ts`：stream mode 分档选择逻辑（`standard` 含 `updates`，不含 `values`）
  - `frontend/src/core/genui/history.ts`：全量 extract 改为增量 + 全量校验兜底
  - `frontend/src/core/genui/sse-recovery.ts`：`GenUISSEManager` 增加 visibility 感知，与增量 extract 整合
  - `frontend/src/core/genui/store.ts`：新增 `upsertBlock` 方法，`useBlockStore` 操作节奏适配增量 extract
  - 消息列表组件：分组计算从全量 `useMemo` 改为增量追加
- **代码（后端）**：
  - 新建 `StatePatchEmitMiddleware`：统一在中间件链中检测 state diff 并 emit `state_patch` custom event（替代在各 middleware 中分别添加 emit）
  - `backend/packages/harness/deerflow/config/stream_bridge_config.py`：`queue_maxsize` 默认值从 256 提升到 1024，增加合并丢弃策略配置
  - Stream bridge 内存实现：`put_with_backpressure` 合并丢弃 + sequence number
  - 工具执行层：工具完成后 emit `tool_end` custom 事件
- **部署**：
  - Nginx：确认 HTTP/2、配置 sticky session（`ip_hash` 或基于 `thread_id` 一致性哈希）
  - Redis（中期）：实现 stream bridge Redis 后端
- **API / 依赖**：无新增外部依赖。Redis stream bridge 需要 Redis 实例（已在项目其他模块使用）。
- **风险**：
  - 阶段一 `pause()` 导致用户切回时消息不完整 → `fetchStateHistory` 补齐 + `onFinish` 兜底检测
  - `streamSubgraphs` 为 per-run 配置，提交后无法动态切换 → 按 agent mode 在提交时决定，不支持运行时切换
  - 阶段三 `state_patch` 丢失 → sequence number gap 检测后触发 state fetch（无 periodic polling）+ `full` 档 fallback
  - 前后端协议变更需同步发版 → 后端保留 `values` 全量推送作为 fallback，灰度切换
  - Backpressure 合并丢弃 → `queue_maxsize` 提升到 1024 降低触发频率，UI 降级表现需产品确认
