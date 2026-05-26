## ADDED Requirements

### Requirement: Basic closure — manual ticket creation
At Basic tier, the system SHALL describe how to manually create a closure ticket from the monitoring report, but SHALL NOT automatically create tickets.

#### Scenario: Report footer suggests manual ticket
- **WHEN** a Basic-tier analysis finds critical anomalies
- **THEN** the report SHALL include "未达自动建单阈值，可在工作台手动登记闭环单"

### Requirement: Pro closure — auto-create for critical findings + SLA tracking
At Pro tier, the system SHALL automatically create closure tickets via `create_closure_ticket` when findings meet the severity threshold (critical, or high with confidence ≥0.7), and SHALL include SLA tracking information.

#### Scenario: Critical anomaly auto-creates ticket
- **WHEN** Pro-tier anomaly detection finds a `severity: "critical"` anomaly
- **THEN** the system SHALL call `create_closure_ticket` with the anomaly details and the report SHALL include the ticket ID and SLA deadline

#### Scenario: Warning-level anomaly does not auto-create
- **WHEN** all anomalies are `severity: "warning"` or lower
- **THEN** the system SHALL NOT create tickets automatically, but SHALL note the findings in the report with a manual creation prompt

### Requirement: Ultra closure — predictive ticketing + re-inspection scheduling + full-chain tracking
At Ultra tier, the system SHALL additionally create tickets based on predictive degradation (health score projected to enter warning zone within 30 days), schedule automatic re-inspection after ticket closure, and track the full "detection → ticket → repair → re-check" lifecycle.

#### Scenario: Predictive degradation triggers preemptive ticket
- **WHEN** Ultra health assessment predicts equipment health score will drop to ≤70 within 30 days
- **THEN** the system SHALL create a `priority: "important"` ticket with title "预判性维护：{设备名} 健康评分预计 30 天内进入警戒区"

#### Scenario: Auto re-inspection scheduled after closure
- **WHEN** a closure ticket created from Ultra monitoring is marked resolved
- **THEN** the system SHALL schedule a follow-up monitoring analysis for 7 days after closure to verify the fix

### Requirement: Closure tracking section in report
At Pro and Ultra tiers, the report SHALL include a "闭环跟踪" section listing all created tickets, their status, and next actions.

#### Scenario: Ultra report closure section
- **WHEN** Ultra analysis creates 2 tickets
- **THEN** the report SHALL include a table with ticket IDs, priorities, SLA deadlines, and current status
