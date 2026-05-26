## ADDED Requirements

### Requirement: Basic recommendations — none
At Basic tier, the system SHALL present findings without automatically generating actionable recommendations.

### Requirement: Pro recommendations — rule-based maintenance suggestions
At Pro tier, the system SHALL generate recommendations by matching finding patterns against a rule table, producing specific maintenance suggestions.

#### Scenario: High vibration triggers inspection recommendation
- **WHEN** Pro anomaly detection finds vibration_level exceeding threshold with `pattern: "持续恶化"`
- **THEN** the system SHALL recommend "建议安排振动分析仪现场检测，排查不平衡/不对中/轴承磨损"

#### Scenario: Multiple anomalies trigger priority review
- **WHEN** Pro analysis finds anomalies in 3+ KPIs for the same equipment
- **THEN** the system SHALL recommend "多项指标同时异常，建议启动综合故障诊断流程"

### Requirement: Ultra recommendations — AI-generated action plan with priority
At Ultra tier, the system SHALL generate prioritized action recommendations using LLM reasoning over the full analysis context, including estimated impact and urgency classification.

#### Scenario: AI action plan with priorities
- **WHEN** Ultra analysis finds critical vibration anomaly + degraded health score + BPFO fault match
- **THEN** the system SHALL generate an action plan like:
  1. [24h 紧急] 安排停机检查轴承外圈，振动烈度超标 45% 且包络谱确认 BPFO
  2. [1周内] 复查润滑油质，温度同步升高可能指示润滑失效
  3. [1月内] 评估该设备整体健康趋势，当前预测 30 天内评分将降至 72

#### Scenario: Recommendation confidence included
- **WHEN** Ultra recommendations are generated
- **THEN** each recommendation SHALL include a `confidence` score and the evidence linking it to specific findings

#### Scenario: No critical findings — light-touch recommendations
- **WHEN** Ultra analysis finds no critical or warning-level findings
- **THEN** the recommendations SHALL be limited to "保持当前监测节奏，下个周期继续观察" without generating unnecessary actions
