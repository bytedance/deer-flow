## Context

当前 DeerFlow 前端侧边栏中，所有对话线程（thread）通过 `RecentChatList` 统一展示，不分智能体来源。"报告历史"页面（`report-runs-page.tsx`）仅展示报告运行记录（report runs），不包含对话线程。用户查看报告历史时无法同时看到生成该报告的对话，造成信息分裂。

后端已支持按 metadata 过滤 threads（`/api/threads/search` 接受 `metadata` 参数，在 Phase 3 做精确匹配过滤）。前端创建 thread 时已在 metadata 中写入 `agent_name`（见 `useThreadStream` 的 `onCreated` 回调）。

## Goals / Non-Goals

**Goals:**
- 报告历史页面支持同时查看"运行记录"和"对话"两个视图
- 报告相关对话从报告历史入口可直达，点击跳转到对应 thread
- 侧边栏的报告历史导航分组下可展开显示最近几次报告对话
- 不影响非报告智能体的对话在侧边栏的展示

**Non-Goals:**
- 不改变 thread 的存储模型或后端 API 契约
- 不修改报告运行记录本身的数据结构
- 不涉及跨页面上下文传递（由 `connect-chat-report-artifact-navigation` 覆盖）

## Decisions

### 决策 1：通过 agent `tags` 识别报告相关对话

- **选择**：前端遍历已加载的 agents 列表，找出所有 `tags` 包含 `"report"` 的 agent，将其 name 列表作为 thread 过滤条件
- **替代方案**：硬编码 agent name 列表 → 脆弱，新增报告子智能体时需要改代码
- **理由**：agent 的 `tags` 已在 config.yaml 中定义（如 `ai-report--custom` 的 `tags: [report, custom]`），与 agent 系统天然集成，无需额外配置

### 决策 2：报告历史页使用 Tab 分栏而非合并列表

- **选择**：报告历史页增加 Tab 切换（"运行记录" / "对话"），各 Tab 独立加载和展示
- **替代方案**：将运行记录和对话合并到同一时间线列表 → UI 混乱，两者结构和字段完全不同
- **理由**：运行记录和对话是两种不同的数据类型，Tab 切换更符合用户心智模型，且实现简单

### 决策 3：侧边栏报告对话归属——二级折叠列表

- **选择**：在 `WorkspaceNavChatList` 的"报告历史"导航项下增加一个可折叠的"报告对话"子列表，展示最近 5 条报告相关 thread
- **替代方案**：
  - a) 在 `RecentChatList` 中过滤掉报告线程 → 用户可能在"对话"入口找不到历史对话，体验倒退
  - b) 在 `RecentChatList` 中同时保留 → 用户可能困惑为什么同一对话出现在两个位置
- **理由**：报告对话只出现在"报告历史"导航分组下，从"最近的对话"列表中移除。这样用户只从报告入口找到报告对话，避免同一对话出现在两个位置造成困惑。子列表使用 `Collapsible` 保持侧边栏整洁

### 决策 4：复用 `useThreads` 现有 metadata 过滤

- **选择**：使用 `useThreads({ metadata: { agent_name: reportAgentNames.join(',') } })` 来获取报告对话
- **替代方案**：新增专用 API 端点 → 不必要，后端已支持
- **注意**：当前 metadata 过滤是精确匹配，需确认后端支持 `agent_name` 的多值匹配或前段分多次查询

## Risks / Trade-offs

- [风险] `tags` 包含 `"report"` 的 agent 较多时，需要后端支持 IN 查询 → 当前后端 metadata 过滤是精确匹配（`r.metadata.get(k) == v`），多值匹配需要前段分多次查询或后端微调。**优先方案**：利用 `parent: ai-report` 层级关系，查询父 agent 为 `ai-report` 的所有子 agent name，逐个发起 thread 查询后合并
- [风险] 侧边栏"报告对话"子列表和 `RecentChatList` 数据互补（互斥展示），需确保过滤逻辑一致 → `collectReportAgentNames` 是唯一过滤来源，两边共享同一纯函数

## Migration Plan

无需数据迁移。所有改动为纯前端展示层变化：
1. 部署新前端代码
2. 不需要后端变更
3. 回滚：恢复前端旧版本即可

## Open Questions

- 后端 metadata 过滤是否应支持多值（IN 语义）以支持一次查询多个 agent_name？（当前可先用分次查询 + 客户端合并兜底）
