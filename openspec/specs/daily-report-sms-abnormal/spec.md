## ADDED Requirements

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

### Requirement: SMS abnormal count as KPI

The daily report KPI summary SHALL include `sms_abnormal_count` (当日 SMS 新增异常数) and `sms_abnormal_pending` (当日待处理异常数) when SMS data is available and the equipment type is rotating machinery.

#### Scenario: SMS KPIs displayed for rotating machinery

- **WHEN** SMS data is fetched successfully for a rotating machinery report
- **THEN** `sms_abnormal_count` and `sms_abnormal_pending` appear in the KPI summary cards
- **AND** each KPI shows its current value with unit "条"

#### Scenario: SMS KPIs hidden for non-rotating types

- **WHEN** a report is generated for a non-rotating equipment type
- **THEN** `sms_abnormal_count` and `sms_abnormal_pending` KPIs are not displayed

### Requirement: SMS severity affects overall status

The daily report's overall status SHALL consider SMS abnormal severity levels. If any SMS abnormal event has `latest_level >= 60` (critical), the overall status SHALL be at least `warning`. If combined with high InS alarms, the status SHALL escalate to `danger`.

#### Scenario: Critical SMS abnormal elevates status to warning

- **WHEN** the report date has no high InS alarms (overall would be `ok`)
- **AND** SMS returns at least one abnormal event with `latest_level >= 60`
- **THEN** the overall status is `warning`
- **AND** the summary text references the SMS critical abnormal count

#### Scenario: SMS abnormal combined with InS alarms escalates to danger

- **WHEN** the report date has high InS alarms (overall would be `warning`)
- **AND** SMS returns at least one abnormal event with `latest_level >= 60`
- **THEN** the overall status is `danger`

### Requirement: Equipment ID normalization for SMS matching

The system SHALL normalize equipment IDs when matching SMS abnormal events to report equipment. Both the SMS `mac_id` and the Organize Tree equipment ID SHALL be normalized by removing hyphens and converting to lowercase before comparison.

#### Scenario: Equipment ID with hyphen matches SMS data

- **WHEN** the report includes equipment "P-203A" (Organize Tree format)
- **AND** SMS returns abnormal events for `mac_id="P203A"` (without hyphen)
- **THEN** the abnormal event is correctly matched to the report equipment

#### Scenario: Case-insensitive equipment ID matching

- **WHEN** the report includes equipment "k-101"
- **AND** SMS returns abnormal events for `mac_id="K-101"`
- **THEN** the abnormal event is correctly matched to the report equipment
