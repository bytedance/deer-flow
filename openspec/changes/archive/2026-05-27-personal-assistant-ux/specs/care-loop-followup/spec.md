## ADDED Requirements

### Requirement: Post-completion follow-up prompt
After completing an analysis or report generation task, the assistant SHALL append a follow-up prompt to its response that summarizes key findings and offers related next actions.

#### Scenario: Follow-up after anomaly detection
- **WHEN** the assistant completes an anomaly detection analysis
- **THEN** the response SHALL end with a summary sentence and a follow-up question (e.g., "总体来看设备运行正常，只有振动在上周有一次小幅波动。需要我帮您深入分析那次波动的原因吗？")

#### Scenario: Follow-up after report generation
- **WHEN** the assistant completes generating a report
- **THEN** the response SHALL end with a brief summary of key findings and offer to explain specific sections in detail or schedule the next report

#### Scenario: Follow-up prompt includes at most 2 suggestions
- **WHEN** any follow-up prompt is generated
- **THEN** the prompt SHALL offer no more than 2 specific next-action suggestions to avoid overwhelming the user

### Requirement: Follow-up memory marker
When the assistant generates a follow-up prompt, the system SHALL store a `pendingFollowUp` fact in the user's memory with the context of what needs follow-up.

#### Scenario: Follow-up fact stored after analysis
- **WHEN** the assistant completes an analysis and generates a follow-up prompt about device X
- **THEN** a memory fact SHALL be created with `category: "followup"`, `content` describing the follow-up context, and `createdAt` timestamp

#### Scenario: Follow-up fact consumed in next greeting
- **WHEN** the user starts a new conversation and has a `pendingFollowUp` memory fact
- **THEN** the greeting API SHALL reference the pending follow-up in the personalized greeting (e.g., "上次您分析了2号泵的振动数据，需要我继续跟进吗？")

#### Scenario: Follow-up fact cleared after addressed
- **WHEN** the user addresses a pending follow-up (asks about the same topic)
- **THEN** the `pendingFollowUp` memory fact SHALL be cleared or marked as resolved

### Requirement: Assistant status indicators during processing
While the assistant is processing a request, the frontend SHALL display human-readable status indicators derived from the current tool calls, instead of generic "thinking" spinners.

#### Scenario: Data fetching status
- **WHEN** the assistant is calling a data retrieval tool (e.g., `search_knowledge_base`, `http_connector`)
- **THEN** the frontend SHALL display "正在查询数据…" as the status indicator

#### Scenario: Report generation status
- **WHEN** the assistant is calling a report generation tool (e.g., `report_template_render_report`, `report_template_export`)
- **THEN** the frontend SHALL display "正在生成报告…" as the status indicator

#### Scenario: Thinking status
- **WHEN** the assistant is in extended thinking mode with no active tool calls
- **THEN** the frontend SHALL display "正在思考…" as the status indicator

### Requirement: Assistant avatar and identity in chat messages

The frontend SHALL display the assistant's identity (avatar icon + name label) on assistant messages in the chat interface.

#### Scenario: Avatar displayed on assistant messages

- **WHEN** an assistant message is rendered in the chat
- **THEN** the message SHALL include the agent's icon (from agent config) and the agent's display name as a label

#### Scenario: Default avatar for agents without icon

- **WHEN** an assistant message is rendered but the agent has no custom icon configured
- **THEN** the message SHALL display a default assistant avatar (a friendly robot or AI icon)

### Requirement: Closure ticket status follow-up

The assistant SHALL proactively track and surface the status of closure tickets that were created from the user's previous analyses. The greeting API and follow-up prompts SHALL reference open or recently resolved tickets.

#### Scenario: Greeting surfaces open ticket status change

- **WHEN** the user has an open closure ticket linked to a device they previously analyzed
- **THEN** the greeting SHALL include a status update (e.g., "您之前为2号泵组开的闭环单（#TK-0042），目前已进入处理中状态，需要查看详细进展吗？")

#### Scenario: Follow-up references recently closed ticket

- **WHEN** a closure ticket linked to the user's recent analysis was closed within the last 7 days
- **THEN** the assistant's follow-up prompt SHALL offer to run a re-inspection analysis to verify the fix (e.g., "上次2号泵组的闭环单已经关闭了，需要我帮您做一次复检分析确认修复效果吗？")

#### Scenario: Follow-up does not surface stale tickets

- **WHEN** a closure ticket was closed more than 30 days ago and no re-inspection is pending
- **THEN** the assistant SHALL NOT proactively surface that ticket in greetings or follow-ups

### Requirement: Preventive maintenance cycle reminder

The assistant SHALL surface upcoming scheduled maintenance for the user's monitored equipment when the maintenance date is within 14 days. The greeting API SHALL include maintenance reminders as high-priority suggestions.

#### Scenario: Greeting includes maintenance reminder

- **WHEN** the user has monitored equipment with a scheduled maintenance date within the next 14 days
- **THEN** the greeting SHALL include a maintenance reminder suggestion (e.g., "这台泵距离下次计划检修还有5天，需要我提前准备一份状态评估报告吗？")

#### Scenario: Maintenance reminder offers pre-maintenance report

- **WHEN** a maintenance reminder suggestion is clicked by the user
- **THEN** the assistant SHALL offer to generate a pre-maintenance status assessment report for that equipment

#### Scenario: No maintenance data available

- **WHEN** the equipment metadata does not include scheduled maintenance dates
- **THEN** the assistant SHALL NOT generate maintenance reminder suggestions
