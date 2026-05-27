## MODIFIED Requirements

### Requirement: Ultra interaction — natural language conversation
At Ultra tier, the user SHALL be able to initiate monitoring analysis via free-form natural language without navigating forms. The agent SHALL infer analysis type, time range, and metrics from the conversation context. The agent SHALL maintain the assistant persona tone throughout all Ultra-tier interactions, including proactive empathy and follow-up care.

#### Scenario: NL request for vibration check
- **WHEN** user types "这台泵最近振动有点高，帮我看看怎么回事"
- **THEN** the agent SHALL infer: equipment=current context, analysis_type=anomaly(+spectrum), metrics=[vibration_level, temperature], date_range=last 30 days, acknowledge the user's concern empathetically (e.g., "理解您的担心，振动异常确实需要重视"), and proceed directly to analysis after confirmation

#### Scenario: Ambiguous NL request requires clarification
- **WHEN** user types "帮我看看设备情况" without specifying equipment or what to check
- **THEN** the agent SHALL ask at most 2 clarifying questions in a warm conversational tone (not a dry form list), referencing the user's recent work context when available from memory

#### Scenario: Ultra NL falls back to forms when needed
- **WHEN** Ultra NL interaction cannot determine required parameters after 2 clarification rounds
- **THEN** the agent SHALL fall back to rendering the scope form with whatever parameters were successfully inferred, explaining the fallback in a helpful tone (e.g., "为了给您更准确的分析结果，我还需要确认几个参数")

#### Scenario: Ultra interaction includes post-analysis follow-up
- **WHEN** an Ultra-tier NL analysis completes
- **THEN** the agent SHALL append a follow-up prompt offering related next actions per the care-loop-followup capability
