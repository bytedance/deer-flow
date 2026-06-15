# daily-report-ins-provider Specification

## Purpose
TBD - created by syncing change daily-report-perf-optimization. Update Purpose after archive.

## Requirements

### Requirement: Async InS trend data fetching

The `_ins_client.py` module SHALL provide `fetch_trend_data_async` that fetches trend data for multiple equipment items concurrently using `asyncio.Semaphore` and `asyncio.gather`. The concurrency limit SHALL be configurable via the `INS_CONCURRENCY_LIMIT` environment variable, defaulting to 4.

#### Scenario: Concurrent trend data fetch

- **WHEN** `fetch_trend_data_async` is called with 6 equipment IDs
- **THEN** the function SHALL process all 6 equipment items using concurrent requests
- **AND** at most `INS_CONCURRENCY_LIMIT` requests SHALL be in flight simultaneously

#### Scenario: Default concurrency limit

- **WHEN** `INS_CONCURRENCY_LIMIT` is not set
- **THEN** the concurrency limit SHALL default to 4

### Requirement: Async InS alarm event fetching

The `_ins_client.py` module SHALL provide `fetch_alarm_events_async` that fetches alarm events for multiple equipment items concurrently, using the same concurrency control mechanism as `fetch_trend_data_async`.

#### Scenario: Concurrent alarm event fetch

- **WHEN** `fetch_alarm_events_async` is called with 5 equipment IDs
- **THEN** the function SHALL process all 5 equipment items using concurrent requests
- **AND** at most `INS_CONCURRENCY_LIMIT` requests SHALL be in flight simultaneously

### Requirement: get_slim_components caching

The `_ins_client.py` module SHALL cache the result of `get_slim_components` calls within a single report generation run. The cache SHALL be keyed by `equipment_id` and SHALL be shared across `fetch_trend_data_async` and `fetch_alarm_events_async` calls.

#### Scenario: Cache prevents redundant API calls

- **WHEN** `fetch_trend_data_async` calls `get_slim_components("P-203A")`
- **AND** subsequently `fetch_alarm_events_async` needs components for "P-203A"
- **THEN** the second call SHALL use the cached result
- **AND** no additional network request SHALL be made

#### Scenario: Cache invalidation

- **WHEN** a new report generation run starts
- **THEN** the cache from the previous run SHALL NOT be reused

### Requirement: Synchronous API wrapper compatibility

The synchronous functions `fetch_trend_data` and `fetch_alarm_events` SHALL remain available and SHALL internally use the async implementations via `asyncio.run` or equivalent. Callers using the synchronous API SHALL NOT need to modify their code.

#### Scenario: Synchronous wrapper works

- **WHEN** `query_daily.py` calls `fetch_trend_data(equipment_ids, start_time, end_time, eq_type)`
- **THEN** the call SHALL succeed and return the same data structure as before
- **AND** the internal implementation SHALL use concurrent fetching

### Requirement: Dynamic concurrency adjustment on rate limiting

If the upstream InS API returns rate-limit errors (HTTP 429), the system SHALL dynamically reduce the concurrency limit and retry failed requests. The limit SHALL be gradually restored after successful requests.

#### Scenario: Rate limit reduces concurrency

- **WHEN** 3 consecutive requests receive HTTP 429 responses
- **THEN** the concurrency limit SHALL be halved (minimum 1)
- **AND** failed requests SHALL be retried

#### Scenario: Concurrency restored after recovery

- **WHEN** 10 consecutive requests succeed without rate-limit errors
- **THEN** the concurrency limit SHALL be gradually increased toward the configured value
