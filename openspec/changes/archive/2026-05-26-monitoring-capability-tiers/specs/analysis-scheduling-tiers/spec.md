## ADDED Requirements

### Requirement: Basic scheduling — manual trigger only
At Basic tier, the system SHALL only support on-demand analysis triggered by a user initiating a conversation with the monitoring agent.

### Requirement: Pro scheduling — scheduled recurring analysis
At Pro tier, the system SHALL support time-based scheduled analysis: daily, weekly, or monthly recurring monitoring runs configured via the agent's cron or external scheduler.

#### Scenario: Weekly monitoring report auto-generated
- **WHEN** a monitoring agent with `monitoring:pro` is configured with a weekly Monday 9:00 schedule
- **THEN** the system SHALL automatically execute a full monitoring analysis at the scheduled time and deliver the report

### Requirement: Ultra scheduling — event-driven + scheduled + manual
At Ultra tier, the system SHALL additionally support event-driven analysis: when an external alert or anomaly is detected (e.g., from InS alarm stream), the system SHALL automatically trigger a deep-dive Ultra analysis for the affected equipment.

#### Scenario: Anomaly alert triggers Ultra analysis
- **WHEN** an InS alarm is raised for Equipment X (vibration_level > threshold)
- **THEN** the system SHALL automatically launch an Ultra-tier anomaly detection + spectrum analysis for Equipment X

#### Scenario: Event-driven analysis throttled
- **WHEN** 10 alarms fire for the same equipment within 1 hour
- **THEN** the system SHALL deduplicate and run at most 1 analysis per equipment per hour
