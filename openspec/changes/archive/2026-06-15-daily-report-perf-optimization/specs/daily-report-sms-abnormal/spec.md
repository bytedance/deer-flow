## MODIFIED Requirements

### Requirement: SMS abnormal events section in daily report

The daily report SHALL include an SMS abnormal events section when the equipment type is `rotating_machinery` or `all`. The section SHALL display abnormal events tracked by the SMS (Safety Management System) as a table with columns: rank, equipment name, component name, latest health score, severity level, event count, process status, and run status. The SMS fetch SHALL be executed as a post-processing step after the main report is generated, not as part of the main generation pipeline.

#### Scenario: Rotating machinery report includes SMS abnormal section

- **WHEN** a daily report is generated with `equipment_type=rotating_machinery` and SMS data is available
- **THEN** the report contains an "SMS 异常事件" table section sourced from the `sms_abnormal` data step
- **AND** each row shows equipment name, component name, health score, severity, event count, and process status

#### Scenario: Non-rotating report shows empty SMS section

- **WHEN** a daily report is generated with `equipment_type=static_equipment` or `pump` or `reciprocating_machinery`
- **THEN** the SMS abnormal events table is empty (no rows)
- **AND** the report generation does not fail

#### Scenario: SMS API unavailable

- **WHEN** the SMS API is unreachable or returns an error
- **THEN** the report generation still succeeds with InS data intact
- **AND** the SMS section displays "SMS 数据不可用" or is omitted
- **AND** the overall report status is not affected

#### Scenario: SMS executed after main report

- **WHEN** the direct executor generates a daily report
- **THEN** the main report (query → kpi → export) SHALL complete first
- **AND** SMS fetch SHALL be initiated only after the main report artifacts are written
- **AND** SMS fetch timing SHALL be recorded as a separate instrumentation segment
