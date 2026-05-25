## ADDED Requirements

### Requirement: Fetch 8K machine drop events for rotating machinery

When `eq_type` is `rotating_machinery`, the InS provider SHALL fetch device events from the 8K `getMachineDrops` endpoint (`/ins-os-view/sg8kData/getMachineDrops`) for each equipment in the report scope and for the report's time window. The fetch SHALL include all event types (1-18). A failure in the event fetch SHALL NOT cause the overall report to fail; it SHALL degrade gracefully by returning an empty alarms list.

#### Scenario: Successful 8K event fetch

- **WHEN** `_async_fetch_payload` is called with `eq_type="rotating_machinery"`, valid `equipment_ids`, `start_ms`, and `end_ms`
- **THEN** the result's `alarms` field contains a list of event dicts, each with keys `time`, `equipment`, `level`, `message` populated from the `getMachineDrops` response

#### Scenario: 8K event fetch failure degrades gracefully

- **WHEN** the `getMachineDrops` API call raises an exception (network error, auth failure, etc.)
- **THEN** `alarms` is returned as `[]` and the KPI data fetch is unaffected

#### Scenario: Non-rotating machinery skips event fetch

- **WHEN** `_async_fetch_payload` is called with `eq_type="pump"` or `eq_type="static_equipment"`
- **THEN** `alarms` is returned as `[]` without calling `getMachineDrops`

### Requirement: Fetch 9K machine drop events for reciprocating machinery

When `eq_type` is `reciprocating_machinery`, the InS provider SHALL fetch device events from the 9K `getMachineDrops` endpoint (`/ins-os-view/sg9kData/getMachineDrops`) for each equipment in the report scope and for the report's time window. Only event types 1 (主报警), 2 (预报警), 3 (启停机), 14 (预警), and 15 (偏差报警) SHALL be requested, as these are the only types supported by the 9K endpoint.

#### Scenario: Successful 9K event fetch

- **WHEN** `_async_fetch_payload` is called with `eq_type="reciprocating_machinery"`, valid `equipment_ids`, `start_ms`, and `end_ms`
- **THEN** the result's `alarms` field contains event dicts from the `getMachineDrops` response

#### Scenario: 9K event fetch failure degrades gracefully

- **WHEN** the 9K `getMachineDrops` API call raises an exception
- **THEN** `alarms` is returned as `[]` and the KPI data fetch is unaffected

### Requirement: Event type to level mapping

The provider SHALL map `getMachineDrops` event types to alarm severity levels as follows:

| type | label | level |
|------|-------|-------|
| 1 | 主报警 | high |
| 2 | 预报警 | warning |
| 3 | 启停机 | info |
| 4 | 黑匣子 | info |
| 5 | 正反进动 | info |
| 6 | 通频值/过程量偏差 | warning |
| 7 | 1X偏差 | warning |
| 8 | 2X偏差 | warning |
| 9 | 0.5X偏差 | warning |
| 10 | 可选偏差 | warning |
| 11 | 残余量偏差 | warning |
| 12 | 振动波动 | warning |
| 13 | 诊断事件 | info |
| 14 | 预警 | warning |
| 15 | 偏差报警 | high |
| 16 | 诊断事件-D | info |
| 17 | 诊断事件-C | info |
| 18 | 诊断事件-B | info |

#### Scenario: Main alarm maps to high level

- **WHEN** a `getMachineDrops` response contains `types: [1]`
- **THEN** the resulting alarm entry has `level: "high"`

#### Scenario: Warning and pre-alarm map to warning level

- **WHEN** a `getMachineDrops` response contains `types: [2]` (预报警) or `types: [14]` (预警)
- **THEN** the resulting alarm entry has `level: "warning"`

### Requirement: Daily series payload includes per-day events

`_async_fetch_daily_series_payload` (used by weekly reports for daily trend data) SHALL include events in each day's entry when `eq_type` is `rotating_machinery` or `reciprocating_machinery`. Each day's events SHALL be fetched for that day's time window, NOT the full week range.

#### Scenario: Weekly report daily entries have day-scoped events

- **WHEN** `_async_fetch_daily_series_payload` is called with `day_count=7`, `eq_type="rotating_machinery"`
- **THEN** each of the 7 returned daily entries contains `alarms` with events only from that specific day's time window
