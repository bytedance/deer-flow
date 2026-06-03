# Equipment Report Data Provider (Delta)

## MODIFIED Requirements

### Requirement: Provider registration for daily / weekly / monthly equipment reports

The data-analyst skill SHALL register `daily`, `weekly`, and `monthly` as named provider sources in `_data_providers._PROVIDER_FACTORIES`, each exposing **only** a `platform` mode resolved through `get_provider(source, mode=...)`. The `DEER_FLOW_DATA_PROVIDER` environment variable SHALL NOT be read for these sources. The legacy `ins` and `demo` mode entries for these three sources MUST NOT be registered. `Ins{Daily,Weekly,Monthly}Provider` classes and their backing `_ins_provider.py` aggregation code SHALL be removed — data for these sources flows exclusively through the integrations CLI bridge (`_platform_bridge.py` → `call_capability` + `call_action`).

#### Scenario: Platform bridge is the only mode

- **WHEN** `get_provider("daily")` (or `"weekly"` / `"monthly"`) is called
- **THEN** the registry returns a `PlatformDailyProvider` instance that routes through `_platform_bridge.call_capability` + `call_action`, and `list_registered()["daily"]` equals `["platform"]`

#### Scenario: Legacy ins mode raises

- **WHEN** code calls `get_provider("daily", mode="ins")` (or weekly / monthly)
- **THEN** `get_provider` raises `KeyError("no provider registered for source='daily' mode='ins'; registered=['platform']")`

#### Scenario: Legacy demo mode raises

- **WHEN** code calls `get_provider("daily", mode="demo")` (or weekly / monthly)
- **THEN** `get_provider` raises `KeyError`

### Requirement: Wire query scripts to platform bridge

`query_daily.py:fetch_day`, `query_weekly.py:fetch_week`, and `query_monthly.py:fetch_month` (and their `_with_provenance` siblings) SHALL invoke the registered platform provider via `get_provider(source).fetch(...)` which internally calls `_platform_bridge.call_capability("monitoring.trend", ...)` + `call_action("aggregate_kpi", adapter="ins_prod", ...)`. Any `PlatformBridgeError` raised by the bridge SHALL propagate to the script's `main()`, rendered as `{"error": "<ExceptionType>: <message>"}` on stdout. Scripts MUST NOT fall back to any other path.

#### Scenario: Platform bridge error propagates to script main

- **WHEN** the platform bridge subprocess fails (e.g., CLI timeout, InS connection error)
- **THEN** the script writes `{"error": "PlatformBridgeError: ..."}` to stdout and does NOT write output data files

#### Scenario: Successful platform bridge call produces real data

- **WHEN** `query_daily.py` runs with `USE_PLATFORM=true` and the integrations CLI returns valid trend + KPI data
- **THEN** the output JSON contains non-null KPI values in `current.kpis` and non-zero `current.hourly_runtime_rate`

### Requirement: _ins_provider.py aggregation code removed

The file `skills/custom/data-analyst/scripts/_ins_provider.py` SHALL have its aggregation function bodies (`_aggregate_trend_to_kpi`, `_hourly_runtime_rate`, `_fetch_kpi_for_equipment`, `fetch_daily_payload`, `fetch_weekly_payload`, `fetch_monthly_payload`, and all `_build_*_payload` helpers) replaced with stubs that raise `NotImplementedError("This path has been removed. Use integrations layer with provider: platform")`. The `_KPI_FEATURE_MAP` import from `kpi_map.py` SHALL remain (it is shared with `kpi_aggregator.py`).

#### Scenario: Direct _ins_provider call raises NotImplementedError

- **WHEN** any code calls `_ins_provider.fetch_daily_payload(...)` (or weekly/monthly variants)
- **THEN** a `NotImplementedError` is raised with a message directing to integrations layer

## REMOVED Requirements

### Requirement: data_source field ends demo_fallback support

**Reason**: With all paths going through integrations layer, `data_source` is always `"ins"`. The `demo_fallback` value no longer has any code path that produces it.

**Migration**: Remove `DEMO_FALLBACK` constant from `_data_providers.py`. Remove `fetch_with_fallback()` function. `data_source` field is still written as `"ins"` on every successful run for backward compatibility with downstream consumers.

### Requirement: fetch_with_fallback function

**Reason**: The fallback helper that catches `HttpProviderError` and retries with demo provider is removed. All sources that previously used fallback now raise errors directly.

**Migration**: Callers use `get_provider(source).fetch(...)` directly. Errors propagate as structured JSON `{"error": ...}` on stdout.
