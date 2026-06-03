## ADDED Requirements

### Requirement: Direct InS monthly data provider

The monthly-report skill SHALL register a `DirectInsMonthlyProvider` as the `ins` mode under the `monthly` source in `_data_providers._PROVIDER_FACTORIES`. This provider SHALL call `_ins_provider._async_fetch_payload` and `_ins_provider._async_fetch_daily_series_payload` directly within the sandbox process, without spawning subprocesses through the integrations CLI bridge.

#### Scenario: DirectInsMonthlyProvider resolves via get_provider

- **WHEN** `get_provider("monthly", mode="ins")` is called
- **THEN** an instance of `DirectInsMonthlyProvider` is returned

#### Scenario: DirectInsMonthlyProvider fetches full month data

- **WHEN** `DirectInsMonthlyProvider.fetch(report_month="2026-06", equipment_ids=["EQ1"], kpi_keys=["runtime_rate", "alarm_count"], eq_type="all")` is called and features-tool is available
- **THEN** the returned `ProviderResult` contains a `daily_entries` list with exactly 30 entries (one per day in June 2026), each entry having `date`, `kpis`, `kpi_units`, and `alarms` fields

#### Scenario: DirectInsMonthlyProvider raises on unavailable features-tool

- **WHEN** `DirectInsMonthlyProvider.fetch(...)` is called and `_FEATURES_TOOL_AVAILABLE` is `False`
- **THEN** an `HttpProviderError` is raised with a message containing "features-tool not available"

#### Scenario: Daily entries include machine drop alarms for rotating machinery

- **WHEN** `DirectInsMonthlyProvider.fetch(...)` is called with `eq_type="rotating_machinery"` and features-tool is available
- **THEN** at least one daily entry's `alarms` field contains non-empty alarm data fetched from the 8K `getMachineDrops` endpoint

### Requirement: Restore fetch_monthly_payload sync wrapper

The sync wrapper `fetch_monthly_payload` in `_ins_provider.py` SHALL be restored to an actual implementation that calls `_run_async(_async_fetch_payload(...))`. It SHALL NOT raise `NotImplementedError`.

#### Scenario: fetch_monthly_payload calls InS directly

- **WHEN** `_ins_provider.fetch_monthly_payload(month_start="2026-06-01", month_end="2026-06-30", equipment_ids=["EQ1"], kpi_keys=["runtime_rate"], eq_type="all")` is called and features-tool is available
- **THEN** a dict with `kpis`, `kpi_units`, `hourly_runtime_rate`, and `alarms` keys is returned

#### Scenario: fetch_monthly_payload raises on unavailable features-tool

- **WHEN** `_ins_provider.fetch_monthly_payload(...)` is called and `_FEATURES_TOOL_AVAILABLE` is `False`
- **THEN** an `HttpProviderError` is raised
