## MODIFIED Requirements

### Requirement: Basic interaction — step-by-step forms
At Basic tier, the user SHALL interact with the monitoring agent through a fixed form sequence: device selection → analysis scope → wait for results.

**工业优先约束**：Basic tier 的默认设备选择列表 SHALL 优先展示已关联的工业设备。如无已关联设备，SHALL 提供示例工业设备供体验。

#### Scenario: Parameters pre-filled for industrial equipment
- **WHEN** 用户在 Basic 模式下选择设备
- **THEN** 设备列表 SHALL 按设备类型（泵、风机、压缩机等工业设备优先）排序

### Requirement: Pro interaction — smart defaults + pre-fill
At Pro tier, the system SHALL pre-fill analysis parameters based on equipment type and historical analysis patterns, reducing the number of manual choices.

**工业优先约束**：Pro tier 的智能默认值 SHALL 基于工业设备类型和历史工业分析模式生成，通用分析模式仅作为后备选项。

#### Scenario: Parameters pre-filled for a pump
- **WHEN** a user selects a pump for monitoring and the agent has `monitoring:pro`
- **THEN** the scope form SHALL pre-select metrics relevant to pumps (vibration_level, pressure, flow_rate, temperature) and set date range to the last 30 days

#### Scenario: User can override pre-filled values
- **WHEN** Pro-tier pre-fills metrics but user wants different ones
- **THEN** the user SHALL be able to modify any pre-filled field before submitting

### Requirement: Ultra interaction — natural language conversation
At Ultra tier, the user SHALL be able to initiate monitoring analysis via free-form natural language without navigating forms. The agent SHALL infer analysis type, time range, and metrics from the conversation context.

**工业优先约束**：Ultra tier 的自然语言理解 SHALL 优先识别工业领域意图（设备诊断、振动分析、监测报告），通用意图（数据查询、研究分析）作为次要识别目标。

#### Scenario: NL request for vibration check
- **WHEN** user types "这台泵最近振动有点高，帮我看看怎么回事"
- **THEN** the agent SHALL infer: equipment=current context, analysis_type=anomaly(+spectrum), metrics=[vibration_level, temperature], date_range=last 30 days, and proceed directly to analysis after confirmation

#### Scenario: Ambiguous NL request requires clarification
- **WHEN** user types "帮我看看设备情况" without specifying equipment or what to check
- **THEN** the agent SHALL ask at most 2 clarifying questions before proceeding

#### Scenario: Ultra NL falls back to forms when needed
- **WHEN** Ultra NL interaction cannot determine required parameters after 2 clarification rounds
- **THEN** the agent SHALL fall back to rendering the scope form with whatever parameters were successfully inferred
