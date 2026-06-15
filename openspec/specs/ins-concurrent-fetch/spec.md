# ins-concurrent-fetch Specification

## Purpose
TBD - created by syncing change daily-report-perf-optimization. Update Purpose after archive.

## Requirements

### Requirement: Rate-limited concurrent InS fetching

The system SHALL fetch InS trend data and alarm events for multiple equipment items concurrently, with a configurable concurrency limit. The default concurrency limit SHALL be 4. The limit SHALL be overridable via the `INS_CONCURRENCY_LIMIT` environment variable.

#### Scenario: Concurrent fetch for multiple equipment

- **WHEN** `fetch_trend_data_async` is called with 8 equipment IDs and `INS_CONCURRENCY_LIMIT=4`
- **THEN** at most 4 concurrent requests SHALL be in flight at any time
- **AND** all 8 equipment items SHALL be processed

#### Scenario: Concurrency limit respected

- **WHEN** `fetch_alarm_events_async` is called with 10 equipment IDs
- **THEN** the number of concurrent `get_machine_drops` calls SHALL NOT exceed the configured limit

### Requirement: Concurrent current-day and compare-day fetching

The system SHALL fetch current-day and compare-day InS data concurrently using `asyncio.gather`. The two fetch operations SHALL run in parallel, not sequentially.

#### Scenario: Current and compare day fetched concurrently

- **WHEN** `build_result` is called with `compare="previous_day"`
- **THEN** the current-day fetch and compare-day fetch SHALL run concurrently
- **AND** the total elapsed time SHALL be approximately the maximum of the two fetch times, not the sum

### Requirement: get_slim_components result caching

The system SHALL cache the result of `get_slim_components` calls within a single report generation run. The cache key SHALL be the `equipment_id`. Subsequent calls for the same equipment SHALL return the cached result without making a network request.

#### Scenario: Cache hit for repeated equipment

- **WHEN** `fetch_trend_data_async` and `fetch_alarm_events_async` are both called for equipment "P-203A" in the same report generation
- **THEN** `get_slim_components("P-203A")` SHALL be called only once
- **AND** the second call SHALL use the cached result

#### Scenario: Cache scoped to single report generation

- **WHEN** a new report generation starts
- **THEN** the cache from the previous report generation SHALL NOT be used

### Requirement: Backward-compatible API signature

The public API signatures of `fetch_trend_data`, `fetch_trend_data_async`, `fetch_alarm_events`, and `fetch_alarm_events_async` SHALL remain unchanged. Callers SHALL NOT need to modify their code to benefit from concurrent fetching.

#### Scenario: Existing callers work without modification

- **WHEN** `query_daily.py` calls `fetch_trend_data(equipment_ids, start_time, end_time, eq_type)`
- **THEN** the call SHALL succeed and return the same data structure as before
- **AND** the internal implementation SHALL use concurrent fetching

### Requirement: Graceful degradation on upstream rate limiting

If the upstream InS API returns rate-limit errors (HTTP 429 or equivalent), the system SHALL reduce the concurrency limit dynamically and retry failed requests.

#### Scenario: Rate limit triggers concurrency reduction

- **WHEN** the InS API returns HTTP 429 for 3 consecutive requests
- **THEN** the concurrency limit SHALL be reduced by half (minimum 1)
- **AND** failed requests SHALL be retried with the new limit

#### Scenario: Rate limit recovery

- **WHEN** the concurrency limit has been reduced due to rate limiting
- **AND** subsequent requests succeed without rate-limit errors for 10 consecutive requests
- **THEN** the concurrency limit SHALL be gradually increased back to the configured value
