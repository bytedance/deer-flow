## ADDED Requirements

### Requirement: Sidebar report history group has a collapsible conversation sub-list
侧边栏"报告历史"导航项下 SHALL 包含一个可折叠的子列表，展示最近 5 条报告相关对话线程。

#### Scenario: Sub-list is shown under report history nav item
- **WHEN** 侧边栏渲染且 `ai-report--custom` agent 的 `nav_items` 包含"报告历史"（`/workspace/report-runs`）
- **THEN** "报告历史"导航项下方显示一个可展开/折叠的子列表，标题为"报告对话"

#### Scenario: Sub-list shows up to 5 recent report conversations
- **WHEN** 存在 8 条报告相关对话线程
- **THEN** 子列表仅显示最近更新的 5 条

#### Scenario: Sub-list is collapsible
- **WHEN** 用户点击"报告历史"旁的折叠箭头
- **THEN** "报告对话"子列表折叠或展开

#### Scenario: Click sub-list item navigates to corresponding thread
- **WHEN** 用户点击子列表中的某条对话
- **THEN** 页面跳转到该对话的 thread 页面

#### Scenario: Empty sub-list when no report conversations exist
- **WHEN** 不存在任何报告相关的对话
- **THEN** "报告对话"子列表不展示，或展示"无"的空状态

### Requirement: Report conversations are excluded from the general recent chat list
报告相关对话 SHALL NOT 出现在侧边栏"最近的对话"列表中，仅出现在"报告历史"下的"报告对话"子列表中。

#### Scenario: Report thread excluded from recent chats
- **WHEN** 存在一条由 `ai-report--custom` 产生的对话线程
- **THEN** 该线程出现在"报告历史"下的"报告对话"子列表中
- **AND** 该线程不出现在"最近的对话"列表中

### Requirement: Report conversation sub-list filters by agent tags
报告对话子列表 SHALL 通过 agent 的 `tags` 字段识别报告智能体，过滤出对应的对话线程。

#### Scenario: Agent without report tag is excluded
- **WHEN** 一个 thread 的 `metadata.agent_name` 对应的 agent 的 `tags` 不包含 `"report"`
- **THEN** 该 thread 不出现在"报告对话"子列表中
