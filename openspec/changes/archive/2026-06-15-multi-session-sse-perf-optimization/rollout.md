# Rollout Plan: Multi-Session SSE Performance Optimization

## User-Facing Changelog

### 多会话性能优化 — 后台标签页智能管理

**改进内容:**

- **后台标签页优化**: 切换到其他标签页时，系统自动降低 SSE 连接频率，减少内存和 CPU 占用。切回时自动同步最新状态。
- **流式响应分层**: 普通对话页面使用精简的流模式 (不包含全量 state dump)，报告生成页面保留完整流模式。显著降低长对话的网络负载。
- **增量 UI 提取**: GenUI 组件提取改为增量模式，仅在有新消息时调用 API，而非每次消息变化都全量重新提取。
- **智能背压**: 服务端对长时间生成的 token 事件自动合并，丢弃中间 token 只保留首尾，防止内存溢出。
- **序列号断线恢复**: 客户端通过序列号检测丢失事件，自动触发状态恢复，无需用户手动刷新。
- **共情错误处理**: 后台标签页的错误不再弹出 toast 干扰，切回时以友好方式内联展示。

**用户无需任何操作。**

**已知行为变化:**

- 后台标签页的 AI 回复可能在切回后短暂延迟才完整显示 (正在同步最新数据)。
- 报告模板/报告运行页面行为不变，仍使用完整流模式。

---

## Rollback Plan

每个 Phase 可独立回滚，不影响其他 Phase。

### Phase 1 回滚 — 前端连接生命周期

**影响**: 恢复后台标签页的全量 SSE 连接。

**操作**:
1. `hooks.ts`: 将 `reconnectOnMount: isVisible && hasActiveRun` 改回 `reconnectOnMount: true`
2. `hooks.ts`: 移除 `backgroundPaused` / `backgroundError` 相关代码
3. `use-stream-tier.ts`: 将 `useStreamModes()` 改回固定的全量 stream modes
4. `stream-mode.ts`: `STREAM_MODE_TIERS` 可保留 (不影响功能)

**风险**: 低。纯前端变更，无数据影响。

### Phase 2 回滚 — GenUI 增量提取

**影响**: 恢复每次消息变化时的全量 UI block 提取。

**操作**:
1. `use-ui-block-extractor.ts`: 移除增量提取逻辑，恢复为纯全量提取
2. `message-list.tsx`: 将 `extendMessageGroups` 调用改回 `getMessageGroups` 全量重算
3. `store.ts`: `upsertBlock` 可保留 (向下兼容)

**风险**: 低。纯性能优化，功能不受影响。

### Phase 3 回滚 — 后端流事件压缩

**影响**: 恢复全量 state 推送，不再发送 `state_patch`。

**操作**:
1. `factory.py`: 移除 `chain.append(StatePatchEmitMiddleware())` (line 283)
2. `hooks.ts`: 移除 `onCustomEvent` 中的 `state_patch` 处理分支
3. `hooks.ts`: 移除 `trackSequence` 和 `lastSequenceRef`

**风险**: 低。`state_patch` 是对现有 `updates` 事件的补充，移除后 `updates` 仍然正常工作。

### Phase 4 回滚 — Stream Bridge 多实例

**影响**: 恢复默认 256 队列大小，禁用 merge-drop 背压。

**操作**:
1. `stream_bridge_config.py`: 将 `queue_maxsize` 默认值改回 `256`
2. `memory.py`: 将 `_apply_backpressure` 改为纯 FIFO (移除 messages 事件特殊处理)

**风险**: 中。如果已经在高负载下运行，回滚后可能重新出现内存压力。建议先确认当前负载。

### Phase 5 回滚 — 共情错误处理

**影响**: 后台错误恢复 toast 弹窗。

**操作**:
1. `hooks.ts`: 移除 `backgroundPaused` / `backgroundError` 状态及相关 effect

**风险**: 极低。纯 UX 改进。

---

## 部署顺序建议

1. **先部署 Phase 1 + 2 + 5** (纯前端，无后端变更，可灰度)
2. **再部署 Phase 3** (后端中间件，需要重启 gateway)
3. **最后部署 Phase 4** (stream bridge 配置，与 Phase 3 同步)

每个阶段部署后观察 24 小时，确认无异常后进入下一阶段。

---

## 监控指标

部署后通过以下指标验证:

- **前端**: `perfMetrics.snapshot()` — 活跃 SSE 连接数应 ≤ 可见标签页数
- **后端**: `stream_bridge_metrics.snapshot()` — 平均 payload size 应 < 2KB (standard tier)
- **背压**: `backpressure_count` — 非零正常，突增需关注
- **队列深度**: `total_queue_depth` — 应 < `queue_maxsize * active_runs`
