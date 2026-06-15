## ADDED Requirements

### Requirement: Seven-segment timing instrumentation

The system SHALL record timing for seven segments of daily report generation: (1) form interaction, (2) organization tree query, (3) current-day InS fetch, (4) compare-day InS fetch, (5) SMS fetch, (6) KPI computation, (7) report export. Each timing record SHALL be a JSON object with fields `trace_id` (string, the `report_run_id`), `step_name` (string, one of the seven segment names), `duration_ms` (integer, elapsed time in milliseconds), `record_count` (integer, number of records processed), and `timestamp` (string, ISO 8601).

#### Scenario: Timing record emitted for each segment

- **WHEN** a daily report is generated via direct execution
- **THEN** seven timing records SHALL be emitted to stderr, one for each segment
- **AND** each record SHALL contain the same `trace_id` value

#### Scenario: Timing records written to JSONL file

- **WHEN** a daily report generation completes
- **THEN** all seven timing records SHALL be appended to `<output_dir>/.perf/<trace_id>.jsonl`
- **AND** each line of the file SHALL be a valid JSON object conforming to the timing record schema

### Requirement: Instrumentation trace_id consistency

The `trace_id` field SHALL be the `report_run_id` generated at the start of direct execution. All timing records emitted during a single report generation SHALL share the same `trace_id`.

#### Scenario: Same trace_id across all segments

- **WHEN** a daily report is generated
- **THEN** the `trace_id` in the form interaction timing record SHALL equal the `trace_id` in the report export timing record

### Requirement: Instrumentation does not block report generation

Timing instrumentation SHALL NOT add more than 5ms of overhead per segment. The instrumentation SHALL write to stderr and the JSONL file asynchronously or with minimal synchronous I/O.

#### Scenario: Instrumentation overhead within budget

- **WHEN** timing instrumentation is enabled
- **THEN** the total time spent on instrumentation across all seven segments SHALL NOT exceed 35ms

#### Scenario: Instrumentation failure does not fail report

- **WHEN** the instrumentation code encounters an error (e.g., disk full, permission denied)
- **THEN** the error SHALL be logged to stderr
- **AND** the report generation SHALL continue without failure

### Requirement: Instrumentation record_count accuracy

The `record_count` field SHALL reflect the number of data records processed in each segment. For InS fetch segments, this is the total number of data points retrieved. For SMS, it is the number of abnormal events. For KPI computation, it is the number of KPI values computed. For export, it is the number of sections rendered.

#### Scenario: record_count reflects actual data volume

- **WHEN** InS fetch retrieves 1500 data points for 3 equipment items
- **THEN** the `record_count` in the current-day InS fetch timing record SHALL be 1500

#### Scenario: record_count is zero when no data

- **WHEN** SMS fetch returns no abnormal events
- **THEN** the `record_count` in the SMS timing record SHALL be 0
