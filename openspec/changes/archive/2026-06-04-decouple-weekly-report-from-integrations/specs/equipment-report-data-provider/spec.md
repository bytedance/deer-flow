## MODIFIED Requirements

### Requirement: Provider registration for daily / weekly / monthly equipment reports

The data-analyst skill SHALL register `daily`, `weekly`, and `monthly` as named provider sources in `_data_providers._PROVIDER_FACTORIES`, each exposing **only** an `ins` mode resolved through `get_provider(source, mode=...)`. The `DEER_FLOW_DATA_PROVIDER` environment variable SHALL no longer gate AI report generation; when set, it MUST be ignored by the daily / weekly / monthly sources (other unrelated sources MAY continue to honor it). The legacy `demo` mode entries for these three sources MUST NOT be registered, and `Demo{Daily,Weekly,Monthly}Provider` classes (and their backing `_demo_*` helpers in the query scripts) MUST be removed. The `Platform{Daily,Weekly,Monthly}Provider` classes that route through the integrations CLI subprocess MUST also be removed.

The `ins` mode providers SHALL call `_ins_provider` functions directly (not through `_platform_bridge` subprocess). Specifically:
- `InsDailyProvider` SHALL call `_ins_provider._async_fetch_payload(period_kind="day", ...)`
- `InsWeeklyProvider` SHALL call `_ins_provider._async_fetch_daily_series_payload(start_date=..., day_count=7, ...)`
- `InsMonthlyProvider` SHALL call `_ins_provider._async_fetch_payload(period_kind="range", ...)`

#### Scenario: InS provider is the only mode

- **WHEN** `get_provider("daily")` (or `"weekly"` / `"monthly"`) is called with `DEER_FLOW_DATA_PROVIDER` unset
- **THEN** the registry returns the `Ins{Daily,Weekly,Monthly}Provider` instance and `list_registered()["daily"]` equals `["ins"]`

#### Scenario: Legacy demo mode raises

- **WHEN** code calls `get_provider("daily", mode="demo")` (or weekly / monthly)
- **THEN** `get_provider` raises `KeyError("no provider registered for source='daily' mode='demo'; registered=['ins']")`

#### Scenario: Legacy platform mode raises

- **WHEN** code calls `get_provider("daily", mode="platform")` (or weekly / monthly)
- **THEN** `get_provider` raises `KeyError` — the `"platform"` mode is no longer registered

#### Scenario: DEER_FLOW_DATA_PROVIDER is ignored

- **WHEN** `DEER_FLOW_DATA_PROVIDER=demo` is set in the environment and `get_provider("daily")` runs
- **THEN** the registry still returns `InsDailyProvider` — the env var has no effect for these three sources

### Requirement: Wire query scripts to direct InS fetch

`query_daily.py:fetch_day`, `query_weekly.py:fetch_week`, and `query_monthly.py:fetch_month` (and their `_with_provenance` siblings) SHALL invoke the registered InS provider directly via `get_provider(source).fetch(...)` rather than `fetch_with_fallback`. Any `HttpProviderError` raised by the InS provider MUST propagate unchanged to the script's `main()`, where it is rendered as `{"error": "<ExceptionType>: <message>"}` on stdout (matching the existing `_error(...)` helper). Scripts MUST NOT silently substitute synthetic data.

The InS provider SHALL NOT spawn subprocesses or invoke `docker exec`. It SHALL call `_ins_provider` functions in-process, using `asyncio.run()` to bridge async InS API calls to the synchronous script context.

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

#### Scenario: No subprocess or docker exec invoked

- **WHEN** `query_weekly.py` runs successfully
- **THEN** no `subprocess.run()` call is made, no `docker exec` is invoked, and no params temp file is written to `/tmp`

### Requirement: data_source field in script output

`query_daily.py`, `query_weekly.py`, and `query_monthly.py` SHALL write a single top-level field `data_source` with the constant value `"ins"` into their output JSON files (`daily_data.json` / `weekly_data.json` / `monthly_data.json`). The `data_notes` top-level field MUST also be present and MUST be an empty list (`[]`) on every successful run; it MUST NOT carry "fell back" / "downgraded" messages. Downstream `daily_kpi.py` / `weekly_kpi.py` / `monthly_kpi.py` transforms SHALL preserve both fields verbatim and SHALL NOT default `data_source` to `"demo_fallback"` when the field is missing — a missing field MUST raise a `KeyError` so an upstream regression cannot quietly produce demo-tagged output.

#### Scenario: Successful run writes ins with empty notes

- **WHEN** the script runs with a working InS path
- **THEN** the output JSON contains `"data_source": "ins"` and `"data_notes": []` at the top level

#### Scenario: KPI transform preserves data_source

- **WHEN** `daily_kpi.py` reads a `daily_data.json` containing `data_source="ins"` and `data_notes=[]`
- **THEN** the resulting `daily_kpi.json` carries the same two values at its top level

#### Scenario: Missing data_source surfaces a regression

- **WHEN** `daily_kpi.py` reads a payload that omits `data_source`
- **THEN** loading raises `KeyError("data_source")` instead of silently substituting `"demo_fallback"`
