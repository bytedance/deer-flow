## MODIFIED Requirements

### Requirement: Direct executor artifact output

The tool SHALL write all output artifacts to the thread-scoped output directory and return their paths. The executor SHALL parse the `output` field from each script's stdout to locate the actual data file, rather than writing the stdout metadata to the data file path.

#### Scenario: Artifacts written to output directory

- **WHEN** `report_direct_execute` completes successfully
- **THEN** the tool SHALL write `daily_report.md` (or `weekly_report.md` / `monthly_report.md`) to `/mnt/user-data/outputs/` and include the path in the returned `artifacts` array

#### Scenario: Executor parses script stdout correctly

- **WHEN** `query_daily.py` outputs `{"output": "/mnt/user-data/outputs/daily_data.json", "report_date": "2026-06-08"}`
- **THEN** the executor SHALL read the actual data from `/mnt/user-data/outputs/daily_data.json`
- **AND** the executor SHALL NOT overwrite that file with the stdout metadata
- **AND** the downstream `daily_kpi.py` SHALL receive the actual data file as input

#### Scenario: Contract applies to all report types

- **WHEN** `report_direct_execute` is called for weekly or monthly reports
- **THEN** the executor SHALL apply the same stdout parsing logic for `query_weekly.py` and `query_monthly.py`

### Requirement: Direct executor SMS post-processing

After generating the main report artifacts, the executor SHALL optionally invoke `query_sms_abnormal.py` as a post-processing step. The SMS result SHALL be appended to the report or stored as a supplementary artifact. SMS failure SHALL NOT block the main report generation.

#### Scenario: SMS executed as post-processing

- **WHEN** `report_direct_execute` completes the main report generation (query → kpi → export)
- **THEN** the executor SHALL invoke `query_sms_abnormal.py` if the equipment type is `rotating_machinery` or `all`
- **AND** the SMS result SHALL be appended to the report or stored as a separate artifact

#### Scenario: SMS failure does not block main report

- **WHEN** `query_sms_abnormal.py` fails or returns an error
- **THEN** the main report artifacts SHALL remain valid
- **AND** the executor SHALL log the SMS failure but SHALL NOT raise an exception
