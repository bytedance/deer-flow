# GenUI / A2UI Sprint Plan

> DeerFlow 项目 — 基于 Agent 的动态 UI 渲染方案实施计划

## Sprint 概览

| 项目 | 内容 |
|------|------|
| **Sprint Goal** | 实现 Agent 动态生成结构化 UI 的完整闭环，使 DeerFlow 支持图表、表格、表单等富交互组件 |
| **Duration** | 4 周（4 个 Sprint，每 Sprint 1 周） |
| **预估总工作量** | ~138 Story Points |
| **技术栈** | Python (LangGraph) + TypeScript (React/Next.js) + Zustand + Zod + Recharts |

---

## Sprint 1: 基础设施（Week 1）

**Sprint Goal**: 打通 UIBlock 从 Agent 到前端的完整数据通路，实现最小可用的端到端渲染。

**容量**: ~34 SP

### Stories

| # | Story | SP | Owner | 依赖 | 优先级 |
|---|-------|----|-------|------|--------|
| 1.1 | 定义 UIBlock JSON Schema（含 schema_version、action、parent_id） | 3 | 后端 | 无 | P0 |
| 1.2 | 实现 `render_ui` Tool（使用 `get_stream_writer()`） | 5 | 后端 | 1.1 | P0 |
| 1.3 | 将 `render_ui` 注册到 Agent Graph 工具列表 | 3 | 后端 | 1.2 | P0 |
| 1.4 | Agent system prompt 注入 GenUI Guidance | 3 | 后端 | 1.2 | P0 |
| 1.5 | SSE custom event 解析（前端识别 `ui_block` 类型） | 5 | 前端 | 1.2 | P0 |
| 1.6 | 前端 Component Registry 骨架（lazy loading） | 3 | 前端 | 无 | P0 |
| 1.7 | BlockStore (Zustand) 实现（create/update/delete） | 5 | 前端 | 无 | P0 |
| 1.8 | Props Sanitizer（白名单 + DOMPurify） | 3 | 前端 | 1.6 | P0 |
| 1.9 | Zod Props Validator（chart、form schema） | 3 | 前端 | 1.8 | P1 |
| 1.10 | schema_version 检测与降级路由逻辑 | 2 | 前端 | 1.6 | P1 |
| 1.11 | 端到端冒烟测试（Agent → SSE → 前端渲染占位符） | 5 | 全栈 | 1.5, 1.7 | P0 |

### 验收标准 (Definition of Done)

- [ ] Agent 调用 `render_ui` 后，前端 SSE 能接收到 UIBlock JSON
- [ ] BlockStore 正确管理 block 生命周期（create/update/delete）
- [ ] Props Sanitizer 能过滤 XSS payload（单元测试覆盖）
- [ ] 未知 component 类型降级显示 fallback UI
- [ ] 未知 schema_version 降级为 markdown 渲染

### 依赖关系图

```
1.1 → 1.2 → 1.3
         ↘ 1.4
         ↘ 1.5 → 1.11
1.6 → 1.8 → 1.9
  ↘ 1.10
1.7 ──────→ 1.11
```

---

## Sprint 2: 核心组件（Week 2）

**Sprint Goal**: 实现 5 个核心展示组件并集成到消息流，Agent 能输出可视化图表、数据表格和统计卡片。

**容量**: ~37 SP

### Stories

| # | Story | SP | Owner | 依赖 | 优先级 |
|---|-------|----|-------|------|--------|
| 2.1 | `chart` 组件（bar/line/pie/scatter，基于 Recharts）+ Zod schema | 8 | 前端 | Sprint 1 | P0 |
| 2.2 | `table` 组件（排序、分页，基于 TanStack Table）+ Zod schema（预留可选交互字段） | 5 | 前端 | Sprint 1 | P0 |
| 2.3 | `card` 组件（KPI 卡片、趋势指标）+ Zod schema | 3 | 前端 | Sprint 1 | P0 |
| 2.4 | `layout` 容器组件（grid/flex 布局 + children 渲染）+ Zod schema | 5 | 前端 | 2.1, 2.3 | P0 |
| 2.5 | `markdown` 降级组件（未知版本 fallback）+ Zod schema | 2 | 前端 | Sprint 1 | P1 |
| 2.6 | BlockErrorBoundary 包裹所有组件 | 3 | 前端 | 2.1-2.5 | P0 |
| 2.7 | GenUIRenderer 主渲染器集成 | 5 | 前端 | 2.1-2.6 | P0 |
| 2.8 | 消息流 UIBlock 渲染集成（在对话流中识别并插入 GenUIRenderer） | 5 | 前端 | 2.7 | P0 |
| 2.9 | Agent 输出 dashboard 场景 E2E 测试 | 5 | 全栈 | 2.4, 2.8 | P0 |
| 2.10 | RAG 检索结果通过 table/card 展示 E2E 验证 | 3 | 全栈 | 2.2, 2.3, 2.8 | P1 |

### 验收标准

- [ ] Agent 输出 chart UIBlock 后，前端正确渲染 Recharts 图表
- [ ] layout 组件能正确嵌套 card + chart 形成 dashboard
- [ ] 组件渲染失败时 ErrorBoundary 捕获并显示友好错误
- [ ] 所有组件支持 React.lazy 按需加载
- [ ] UIBlock 在聊天消息流中正确定位和渲染（与 markdown 消息混排）
- [ ] 每个组件都有对应的 Zod schema 校验
- [ ] table 组件 Zod schema 预留可选交互字段（onRowSelect），待 Sprint 3 交互基础设施就绪后启用
- [ ] RAG 场景下 Agent 能通过 table/card 展示检索结果

### 依赖关系图

```
Sprint 1 (全部完成)
    ↓
2.1 ─┐
2.2  ├→ 2.6 → 2.7 → 2.8 → 2.9
2.3 ─┤       ↗                ↘
2.4 ─┘      /                 2.10
2.5 ───────/
```

---

## Sprint 3: 交互闭环（Week 3）

**Sprint Goal**: 实现用户与 UI 组件的双向交互，表单提交和确认操作能回流至 Agent 继续处理。

**容量**: ~40 SP

### Stories

| # | Story | SP | Owner | 依赖 | 优先级 |
|---|-------|----|-------|------|--------|
| 3.1 | `form` 组件（React Hook Form + 动态字段渲染）+ Zod schema | 8 | 前端 | Sprint 2 | P0 |
| 3.2 | `confirm` 组件（确认/取消对话框）+ Zod schema | 3 | 前端 | Sprint 2 | P0 |
| 3.3 | InteractionStore 后端实现（幂等、超时、checkpoint） | 5 | 后端 | Sprint 1 | P0 |
| 3.4 | GenUIMiddleware 实现（回调转 HumanMessage） | 5 | 后端 | 3.3 | P0 |
| 3.5 | 交互回调 API `/api/threads/{id}/ui-interaction`（含 resume_graph 实现） | 5 | 后端 | 3.4 | P0 |
| 3.6 | 前端 `submitInteraction`（乐观更新 + 重试） | 5 | 前端 | 3.5 | P0 |
| 3.7 | 前端 loading/error/submitted/expired 状态展示（含 timeout 主动过期） | 4 | 前端 | 3.6 | P0 |
| 3.8 | 后端 UIBlock 持久化层（按 thread_id 存储已发射 blocks） | 3 | 后端 | 3.5 | P1 |
| 3.9 | SSE 断线重连 + Block 恢复机制 | 5 | 前端 | 3.8 | P1 |
| 3.10 | 交互闭环 E2E 测试（form 提交 → Agent 响应） | 5 | 全栈 | 3.6, 3.7 | P0 |

### 验收标准

- [ ] 用户填写 form 并提交后，Agent 能接收到表单数据并继续处理
- [ ] 交互回调 API 能通过 `resume_graph` 从指定 checkpoint 恢复 graph 执行并注入 HumanMessage
- [ ] 重复提交同一 callback_id 时幂等处理（不重复执行）
- [ ] 回调超时后前端显示过期提示，交互组件自动禁用
- [ ] 前端根据 `callback_timeout_ms` 主动检测并禁用已过期的交互组件
- [ ] SSE 断线后自动重连并从服务端恢复已有 blocks
- [ ] confirm 组件的确认/取消操作正确回流
- [ ] 后端持久化层正确存储每个 thread 的 UIBlock 历史

### 依赖关系图

```
Sprint 2 → 3.1, 3.2
Sprint 1 → 3.3 → 3.4 → 3.5 → 3.6 → 3.7
                         ↘ 3.8 → 3.9
3.1 + 3.6 + 3.7 → 3.10
```

---

## Sprint 4: 高级功能与可观测性（Week 4）

**Sprint Goal**: 补全剩余组件，建立可观测性体系，配置安全加固，确保系统生产就绪。

**容量**: ~32 SP

### Stories

| # | Story | SP | Owner | 依赖 | 优先级 |
|---|-------|----|-------|------|--------|
| 4.1 | `code` 组件（Shiki 高亮 + iframe sandbox 执行）+ Zod schema | 8 | 前端 | Sprint 2 | P0 |
| 4.2 | `timeline` 组件 + Zod schema | 3 | 前端 | Sprint 2 | P1 |
| 4.3 | UIBlock update/delete 操作验证（进度条场景） | 3 | 全栈 | Sprint 3 | P0 |
| 4.4 | 前端 Telemetry 埋点（render/error/interaction，含 UIBlock metadata 上报） | 3 | 前端 | Sprint 3 | P1 |
| 4.5 | 后端 Prometheus Metrics（render_ui 调用/错误/延迟） | 3 | 后端 | Sprint 3 | P1 |
| 4.6 | 后端 Telemetry 接收 API `/api/telemetry/genui` | 2 | 后端 | 4.4 | P1 |
| 4.7 | 告警规则配置（错误率、延迟、超时） | 2 | 后端 | 4.5 | P2 |
| 4.8 | CSP Header 配置（限制 inline script、iframe 来源） | 2 | 后端 | 4.1 | P1 |
| 4.9 | Block 恢复 API `/api/threads/{id}/ui-blocks` | 3 | 后端 | 3.8 | P1 |
| 4.10 | 全量回归测试 + 性能基准测试 | 5 | 全栈 | 4.1-4.9 | P0 |

### 验收标准

- [ ] code 组件能安全执行 JS 代码（iframe sandbox 隔离）
- [ ] update action 能实时更新进度条/状态卡片
- [ ] Prometheus 能采集 render_ui 调用量和错误率
- [ ] 前端 telemetry 正确上报渲染耗时和交互延迟，包含 UIBlock metadata（agent_node、created_at）
- [ ] 后端 telemetry API 正确接收并存储前端上报数据
- [ ] CSP header 正确配置，阻止非法 inline script
- [ ] Block 恢复 API 能返回指定 thread 的完整 UIBlock 历史
- [ ] 全量 E2E 测试通过，无 P0 回归

### 依赖关系图

```
Sprint 2 → 4.1, 4.2
Sprint 3 → 4.3, 4.4, 4.5, 4.9
3.8 → 4.9
4.4 → 4.6
4.5 → 4.7
4.1 → 4.8
4.1-4.9 → 4.10
```

### 延期至 Phase 5（后续迭代）

| Story | SP | 原因 |
|-------|----|------|
| 后端代码沙箱 Docker 执行器（Python/JS） | 5 | 复杂度高，需独立安全评审；Phase 4 先用 iframe sandbox 覆盖 JS 执行 |
| 协议双版本并行支持（MAJOR 升级过渡期） | 3 | 当前仅 v1.0，无实际升级需求；待首次 MAJOR 升级时实现 |

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| LangGraph `get_stream_writer()` API 变更 | 低 | 高 | Sprint 1 第一天验证 API 兼容性，锁定版本 |
| Agent 频繁生成无效 UIBlock | 中 | 中 | Prompt Guidance 迭代优化 + 后端白名单兜底 |
| Recharts 包体积影响首屏 | 中 | 低 | React.lazy 按需加载，监控 bundle size |
| 交互回调与 checkpoint 状态不一致 | 中 | 高 | InteractionStore 强绑定 checkpoint_id，增加集成测试 |
| iframe sandbox 浏览器兼容性 | 低 | 中 | Phase 4 实现，有充足时间测试；降级为只读代码块 |
| 团队对 LangGraph StreamWriter 不熟悉 | 中 | 中 | Sprint 1 安排 spike 任务，产出示例代码 |
| 消息流集成影响现有聊天功能 | 中 | 高 | 2.8 需充分回归测试，确保纯文本消息不受影响 |
| UIBlock 持久化层性能瓶颈 | 低 | 中 | 初期使用内存缓存 + TTL，后续按需迁移到 Redis |
| CSP 配置过严导致正常功能受阻 | 低 | 中 | 先 report-only 模式观察，确认无误后切换为 enforce |

---

## 技术 Spike（Sprint 1 前置）

在 Sprint 1 正式开始前，建议用 0.5 天完成以下验证：

1. **StreamWriter 验证**: 确认当前 LangGraph 版本的 `get_stream_writer()` + `stream_mode=custom` 能正确推送自定义 JSON
2. **SSE 通道验证**: 确认前端现有 SSE 连接能接收 custom event 并解析
3. **DOMPurify 集成**: 确认 DOMPurify 在 Next.js SSR 环境下正常工作
4. **消息流扩展点**: 确认现有 Message 组件架构支持插入自定义渲染器的扩展方式

---

## Definition of Ready（Story 准入标准）

- [ ] 有明确的验收标准（AC）
- [ ] 已估点（Story Points）
- [ ] 依赖项已识别且无阻塞
- [ ] 设计方案已在技术设计文档中明确
- [ ] 涉及安全的 Story 已通过安全评审
- [ ] 组件类 Story 包含对应 Zod schema 定义

## Definition of Done（Story 完成标准）

- [ ] 代码已提交并通过 Code Review
- [ ] 单元测试覆盖率 ≥ 80%
- [ ] 无 P0/P1 Bug
- [ ] 安全校验通过（Props Sanitizer + Zod schema 测试）
- [ ] 文档已更新（API 文档、组件文档）
- [ ] 在开发环境端到端验证通过
- [ ] 组件类 Story 的 Zod schema 覆盖所有 props 字段

---

## 里程碑

| 时间 | 里程碑 | 交付物 |
|------|--------|--------|
| Week 1 末 | M1: 数据通路打通 | Agent → SSE → 前端占位符渲染 |
| Week 2 末 | M2: 可视化 Demo | Agent 输出 dashboard（chart + card + table），集成到消息流 |
| Week 3 末 | M3: 交互闭环 | 用户通过 form 与 Agent 双向交互，含持久化和恢复 |
| Week 4 末 | M4: 生产就绪 | 全组件 + 可观测性 + CSP 安全加固 + 回归测试通过 |

---

## 设计文档覆盖度检查清单

以下确认技术设计文档（2026-05-10-genui-a2ui-technical-design.md）各章节在本 Sprint Plan 中的覆盖情况：

| 设计文档章节 | Sprint 覆盖 | 状态 |
|-------------|-------------|------|
| §4.1 UIBlock 基础结构 | 1.1 | ✅ |
| §4.2 操作语义 (create/update/delete) | 1.7, 4.3 | ✅ |
| §4.3 交互式 UIBlock (callback_id, timeout) | 3.3-3.7 | ✅ |
| §4.4 布局与分组 (layout, parent_id) | 2.4 | ✅ |
| §4.5 全部 9 种组件类型 | 2.1-2.5, 3.1-3.2, 4.1-4.2 | ✅ |
| §4.6 协议版本演进策略 | 1.10 (降级路由) + Phase 5 (双版本) | ✅ |
| §5.1 render_ui Tool | 1.2 | ✅ |
| §5.2 GenUIMiddleware + InteractionStore | 3.3, 3.4 | ✅ |
| §5.3 Agent Prompt Guidance | 1.4 | ✅ |
| §5.4 SSE 传输 | 1.5 | ✅ |
| §5.5 交互回调 API | 3.5 | ✅ |
| §6.1 Component Registry | 1.6 | ✅ |
| §6.2 Props Sanitizer | 1.8 | ✅ |
| §6.3 BlockStore | 1.7 | ✅ |
| §6.4 GenUIRenderer + ErrorBoundary | 2.6, 2.7 | ✅ |
| §6.5 交互回调 (submitInteraction) | 3.6 | ✅ |
| §6.6 SSE 重连与 Block 恢复 | 3.9, 4.9 | ✅ |
| §7.1 Props 安全校验 (白名单+DOMPurify+Zod+CSP) | 1.8, 1.9, 4.8 | ✅ |
| §7.2 代码沙箱 (iframe) | 4.1 | ✅ |
| §7.2 代码沙箱 (Docker) | Phase 5 延期 | ✅ (已标注) |
| §8.1 前端埋点 | 4.4 | ✅ |
| §8.2 后端监控 (Prometheus) | 4.5 | ✅ |
| §8.3 告警规则 | 4.7 | ✅ |
| §11 前端 Message 组件集成 | 2.8 | ✅ |
| §11 知识库 RAG 集成 | 2.10 | ✅ |
| §11 监控系统集成 | 4.5, 4.6 | ✅ |
| §12 全部技术选型 | 各 Story 对应 | ✅ |
