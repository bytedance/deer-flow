## ADDED Requirements

### Requirement: Report history page has tab-based navigation
报告历史页面 SHALL 提供 Tab 导航，包含"运行记录"和"对话"两个视图。

#### Scenario: User switches between run records and conversations
- **WHEN** 用户在报告历史页面点击"运行记录" Tab
- **THEN** 页面展示报告运行记录列表（当前已有行为）
- **WHEN** 用户点击"对话" Tab
- **THEN** 页面展示报告相关的对话线程列表

#### Scenario: Default tab is run records
- **WHEN** 用户首次进入报告历史页面（URL 无 tab 参数）
- **THEN** 默认展示"运行记录" Tab

### Requirement: Report conversations tab shows threads from report agents
报告对话 Tab SHALL 展示所有由报告智能体（`tags` 包含 `"report"` 的 agent）产生的对话线程，按更新时间倒序排列。

#### Scenario: Threads are filtered by report agent tags
- **WHEN** 存在 `ai-report--custom` 产生的 thread（metadata.agent_name = "ai-report--custom"）且其 tags 包含 "report"
- **THEN** 该 thread 出现在"对话"列表中

#### Scenario: Non-report threads are excluded
- **WHEN** 存在一个由非报告智能体产生的 thread（metadata.agent_name 对应的 agent 不含 "report" tag）
- **THEN** 该 thread 不出现在报告历史"对话"列表中

#### Scenario: Threads are sorted by last update time
- **WHEN** 存在多条报告相关对话
- **THEN** 对话按 `updated_at` 降序排列

### Requirement: Clicking a report conversation navigates to the chat thread
报告对话列表中的每一条对话 SHALL 可点击跳转到对应的对话页面。

#### Scenario: Click thread navigates to chat view
- **WHEN** 用户点击某条报告对话
- **THEN** 页面跳转到 `/workspace/agents/{agent_name}/chats/{thread_id}` 或 `/workspace/chats/{thread_id}`（根据路由约定）

### Requirement: Empty state for report conversations
当没有报告相关的对话时，"对话" Tab SHALL 展示空状态提示。

#### Scenario: No report conversations
- **WHEN** 用户当前没有任何报告相关的对话线程
- **THEN** 展示"暂无报告对话"提示文字（类似运行记录的空状态）
