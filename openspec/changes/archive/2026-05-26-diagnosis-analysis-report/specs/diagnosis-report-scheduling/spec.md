## ADDED Requirements

### Requirement: Pro tier shall support scheduled diagnosis reports
The system SHALL support scheduled (periodic) diagnosis report generation for Pro tier, triggered by cron-like schedule configuration.

#### Scenario: Pro daily embedded diagnosis
- **WHEN** schedule configuration specifies "daily" mode and capability_tier is "pro"
- **THEN** system SHALL generate diagnosis report at configured time each day
- **AND** report SHALL be embedded in daily report as additional section
- **AND** schedule_label SHALL be "定时 · daily · {date}"

#### Scenario: Pro weekly standalone diagnosis
- **WHEN** schedule configuration specifies "weekly" mode and capability_tier is "pro"
- **THEN** system SHALL generate standalone diagnosis report at configured time each week
- **AND** report title SHALL be "周度诊断报告 · {week_range}"
- **AND** schedule_label SHALL be "定时 · weekly · {date}"

#### Scenario: Pro schedule with no anomalies detected
- **WHEN** scheduled diagnosis runs but no anomalies are detected in the time window
- **THEN** system SHALL still generate report with "未发现异常" in section 2
- **AND** system SHALL skip sections 4-6 (no diagnosis, differential, recommendations)

### Requirement: Ultra tier shall support event-driven diagnosis reports
The system SHALL support event-driven diagnosis report generation for Ultra tier, triggered by critical alarms.

#### Scenario: Ultra event-driven trigger on critical alarm
- **WHEN** system receives alarm event with level="critical" and equipment_id matches a monitored device
- **THEN** system SHALL automatically trigger diagnosis report generation
- **AND** system SHALL auto-fill: diagnosis_date = alarm timestamp date, diagnosis_hour = alarm hour, focus_codes = alarm-associated fault family codes
- **AND** schedule_label SHALL be "事件驱动 · critical alarm · {alarm_time}"

#### Scenario: Ultra event-driven with equipment kind auto-detection
- **WHEN** critical alarm is received and equipment_id is known
- **THEN** system SHALL auto-detect equipment kind from equipment registry
- **AND** system SHALL select appropriate rule set based on detected kind

#### Scenario: Ultra event-driven report title format
- **WHEN** event-driven diagnosis report is generated
- **THEN** report title SHALL be "诊断报告 · {equipment_name} · {diagnosis_date} {diagnosis_hour}:00 · {primary_fault_type}"

### Requirement: Diagnosis scheduling shall enforce deduplication
The system SHALL enforce deduplication to prevent redundant diagnosis reports for the same fault event.

#### Scenario: Deduplication within 2-hour window
- **WHEN** event-driven trigger fires for same equipment_id and same focus_codes within 2 hours of previous trigger
- **THEN** system SHALL suppress the duplicate trigger
- **AND** system SHALL log: "去重：{equipment_id} 在 2h 窗口内已生成诊断报告"

#### Scenario: Deduplication across different focus codes
- **WHEN** event-driven trigger fires for same equipment_id but different focus_codes within 2 hours
- **THEN** system SHALL allow the trigger (different fault type)

#### Scenario: Manual trigger bypasses deduplication
- **WHEN** user manually requests diagnosis report via GenUI form
- **THEN** system SHALL NOT apply deduplication (manual requests always execute)

### Requirement: Diagnosis scheduling shall integrate with existing alarm pipeline
The system SHALL integrate event-driven diagnosis with the existing alarm notification pipeline.

#### Scenario: Alarm pipeline triggers diagnosis
- **WHEN** alarm pipeline processes a critical alarm and diagnosis scheduling is enabled for Ultra tier
- **THEN** alarm pipeline SHALL invoke diagnosis report generation after alarm notification is sent
- **AND** diagnosis report SHALL be linked to the same thread as the alarm notification

#### Scenario: Alarm pipeline with diagnosis disabled
- **WHEN** alarm pipeline processes a critical alarm but diagnosis scheduling is disabled
- **THEN** alarm pipeline SHALL send alarm notification only
- **AND** alarm pipeline SHALL NOT trigger diagnosis report generation

### Requirement: Diagnosis scheduling shall support rate limiting
The system SHALL enforce rate limits to prevent excessive diagnosis report generation.

#### Scenario: Rate limit per equipment per day
- **WHEN** more than 3 diagnosis reports are generated for the same equipment_id within 24 hours
- **THEN** system SHALL suppress additional triggers for that equipment_id
- **AND** system SHALL log: "限流：{equipment_id} 今日已生成 3 份诊断报告"

#### Scenario: Rate limit per system per hour
- **WHEN** more than 10 diagnosis reports are generated system-wide within 1 hour
- **THEN** system SHALL queue additional triggers for processing in the next hour
- **AND** system SHALL log: "系统限流：当前小时已生成 10 份诊断报告，后续请求将延迟处理"
