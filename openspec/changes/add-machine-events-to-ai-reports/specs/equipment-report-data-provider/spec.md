## MODIFIED Requirements

### Requirement: Wire query scripts to direct InS fetch

`query_daily.py:fetch_day`, `query_weekly.py:fetch_week`, and `query_monthly.py:fetch_month` (and their `_with_provenance` siblings) SHALL invoke the registered InS provider directly via `get_provider(source).fetch(...)` rather than `fetch_with_fallback`. Any `HttpProviderError` raised by the InS provider MUST propagate unchanged to the script's `main()`, where it is rendered as `{"error": "<ExceptionType>: <message>"}` on stdout (matching the existing `_error(...)` helper). Scripts MUST NOT silently substitute synthetic data.

For `eq_type` values `rotating_machinery` and `reciprocating_machinery`, the InS provider SHALL fill the `alarms` field with real machine drop events fetched from the 8K or 9K `getMachineDrops` endpoint respectively. For all other `eq_type` values, `alarms` SHALL remain `[]`.

#### Scenario: InS error propagates to script main

- **WHEN** `InsDailyProvider.fetch(...)` raises `HttpProviderError("device <id> not found in InS")` and `query_daily.py` runs as a CLI
- **THEN** the script writes `{"error": "HttpProviderError: device <id> not found in InS"}` to stdout, exits 0 (existing convention), and does NOT write `daily_data.json`

#### Scenario: Compare period error fails the whole report

- **WHEN** the InS fetch for the `current` period succeeds but the `compare` period (e.g. previous day) raises `HttpProviderError`
- **THEN** the entire report fails with the InS error — no demo data is written and no "downgraded" / "fell back" notes are emitted

#### Scenario: features-tool unavailable surfaces an explicit error

- **WHEN** `_FEATURES_TOOL_AVAILABLE` is `False` (e.g. local sandbox without `/opt/features-tool`) and `query_daily.py` runs
- **THEN** the script returns the error `{"error": "HttpProviderError: features-tool not available: <reason>"}` rather than producing a demo-fallback report

#### Scenario: Rotating machinery reports include real alarms

- **WHEN** `InsDailyProvider.fetch(...)` runs with `eq_type="rotating_machinery"` and InS returns machine drop events
- **THEN** the `current.alarms` field in the output contains a list of non-empty alarm entries with `time`, `equipment`, `level`, `message` fields

#### Scenario: Event fetch failure does not fail the report

- **WHEN** `getMachineDrops` call fails (e.g. network timeout) during a rotating machinery report fetch
- **THEN** `current.alarms` is `[]` and the KPI data fetch proceeds normally — the event fetch failure is logged but does not propagate as an error
