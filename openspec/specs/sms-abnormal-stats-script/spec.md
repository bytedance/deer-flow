## ADDED Requirements

### Requirement: Query SMS abnormal list by date range

The `query_sms_abnormal.py` script SHALL query the SMS `/api/abnormal/list` endpoint with `startTime` and `endTime` parameters derived from the report date. The script SHALL accept `--date`, `--equipment`, `--equipment-names`, and `--type` arguments following the same CLI conventions as `query_daily.py`.

#### Scenario: Successful SMS query for a single day

- **WHEN** the script is invoked with `--date 2026-06-04 --type rotating_machinery --equipment P-203A,K-101`
- **THEN** it calls `GET /api/abnormal/list` with `startTime` = 2026-06-04T00:00:00 ms and `endTime` = 2026-06-04T23:59:59 ms
- **AND** writes a JSON file containing `sms_abnormal` with `total_count`, `by_severity`, `by_status`, `by_type`, and `top_events` fields
- **AND** exits with code 0

#### Scenario: SMS API returns empty results

- **WHEN** the SMS API returns an empty `rows` array for the given date range
- **THEN** the script writes a JSON file with `sms_abnormal.total_count=0` and empty `top_events`
- **AND** exits with code 0

#### Scenario: SMS API unavailable

- **WHEN** the SMS API is unreachable (connection timeout, DNS failure, or HTTP error)
- **THEN** the script writes a JSON file with `sms_abnormal.error` describing the failure
- **AND** exits with code 0 (non-fatal — caller handles the error field)

### Requirement: Client-side equipment filtering

The script SHALL filter SMS abnormal events by equipment IDs on the client side, since the SMS API does not support equipment ID filtering. The script SHALL normalize equipment IDs (remove hyphens, lowercase) before comparing with SMS `mac_id` values.

#### Scenario: Filter SMS results to requested equipment

- **WHEN** the script is invoked with `--equipment P-203A`
- **AND** SMS returns 10 abnormal events across 5 different `mac_id` values
- **THEN** the output `top_events` only contains events where normalized `mac_id` matches normalized "P-203A"
- **AND** `total_count` and `by_*` aggregations are computed from filtered results only

#### Scenario: No matching equipment in SMS results

- **WHEN** the script is invoked with `--equipment P-203A`
- **AND** SMS returns abnormal events but none with a matching `mac_id`
- **THEN** the output `total_count` is 0
- **AND** `top_events` is an empty array

### Requirement: Output contract

The script SHALL output a JSON file conforming to the following schema. The output path SHALL default to `$DAILY_REPORT_OUTPUT_DIR/sms_abnormal.json` (or `/mnt/user-data/outputs/sms_abnormal.json`).

```json
{
  "report_date": "2026-06-04",
  "equipment_type": "rotating_machinery",
  "sms_abnormal": {
    "total_count": 5,
    "by_severity": {"critical": 1, "high": 2, "medium": 1, "low": 1},
    "by_status": {"pending": 3, "processed": 2},
    "by_type": {"t": 2, "sensor": 1, "w": 1, "k": 1},
    "top_events": [
      {
        "rank": 1,
        "abnormal_id": "ab_001",
        "mac_name": "循环氢压缩机",
        "component_name": "驱动端轴承",
        "mac_id": "P-203A",
        "latest_health": 72.5,
        "latest_level": 60,
        "serious_level": 75,
        "event_count": 3,
        "process_status": "待处理",
        "run_status": "运行",
        "first_event_time": 1717459200000,
        "lastest_event_time": 1717545600000
      }
    ]
  }
}
```

#### Scenario: Output file is written to the correct location

- **WHEN** the script completes successfully
- **THEN** a valid JSON file exists at the `--output` path or the default output directory
- **AND** the file contains all required top-level fields (`report_date`, `equipment_type`, `sms_abnormal`)

#### Scenario: Error output is still valid JSON

- **WHEN** the SMS API returns an error
- **THEN** the script writes `{"report_date": "...", "sms_abnormal": {"error": "..."}}` to the output path
- **AND** the JSON is still parseable by downstream consumers

### Requirement: Authentication via environment token

The script SHALL authenticate to the SMS API using the `INS_ACCESS_TOKEN` environment variable as a Bearer token. The SMS base URL SHALL be read from `INS_BASE_URL` environment variable, defaulting to `http://182.92.187.198`.

#### Scenario: Token available

- **WHEN** `INS_ACCESS_TOKEN` is set in the environment
- **THEN** requests to SMS API include `Authorization: Bearer <token>` header

#### Scenario: Token missing

- **WHEN** `INS_ACCESS_TOKEN` is not set
- **THEN** requests are sent without Authorization header
- **AND** if SMS returns 401, the script writes an error to output (non-fatal)

### Requirement: Severity level mapping

The script SHALL map SMS `latest_level` values to severity labels using the following thresholds: `>= 60` → `critical`, `41-59` → `high`, `21-40` → `medium`, `<= 20` → `low`.

#### Scenario: Severity classification

- **WHEN** an SMS abnormal event has `latest_level=60`
- **THEN** it is classified as `critical` in the output
- **WHEN** an SMS abnormal event has `latest_level=45`
- **THEN** it is classified as `high` in the output
- **WHEN** an SMS abnormal event has `latest_level=30`
- **THEN** it is classified as `medium` in the output
- **WHEN** an SMS abnormal event has `latest_level=10`
- **THEN** it is classified as `low` in the output
