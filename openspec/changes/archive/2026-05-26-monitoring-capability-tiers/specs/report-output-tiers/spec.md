## ADDED Requirements

### Requirement: Basic report — Markdown with core findings
At Basic tier, the system SHALL produce a Markdown report containing: scope header (analysis type, time range, equipment), key findings list, evidence tables appropriate to the analysis type, and a download link.

### Requirement: Pro report — Markdown + PDF + evidence chain
At Pro tier, the system SHALL additionally produce PDF output (via weasyprint), include full evidence chain linking each finding to its source data, and add a "分析方法" section listing algorithms used.

#### Scenario: Pro PDF report with evidence chain
- **WHEN** Pro-tier analysis completes
- **THEN** `monitoring_report.pdf` SHALL be generated alongside `monitoring_report.md`, and both SHALL contain an "证据链" section linking findings to data snapshots

### Requirement: Ultra report — multi-format + model explainability + action plan
At Ultra tier, the system SHALL additionally include a "模型可解释性" section (model name, version, known limitations), an "行动计划" section with prioritized recommendations, and preserve all Pro/Ultra-specific fields in the report.

#### Scenario: Ultra report includes action plan
- **WHEN** Ultra analysis detects critical anomalies with root cause candidates
- **THEN** the report SHALL include "建议行动计划" ranking actions by urgency: immediate (24h), short-term (1 week), medium-term (1 month)

#### Scenario: Model explainability in Ultra report
- **WHEN** any Ultra ONNX model was used
- **THEN** the report SHALL list each model with: model name, version, training data provenance, and a 1-line limitation statement

### Requirement: Report depth reflects tool group
The report's content depth SHALL match the agent's highest available `monitoring:*` tool group, not a user selection.

#### Scenario: Pro agent produces Pro report automatically
- **WHEN** agent has `monitoring:pro` (but not `monitoring:ultra`) in its tool_groups
- **THEN** the report SHALL include all Pro-tier sections automatically without the user selecting a depth level
