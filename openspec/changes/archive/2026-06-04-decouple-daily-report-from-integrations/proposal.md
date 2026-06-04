## Why

The daily report scripts (`query_daily.py`) currently fetch data through a subprocess bridge (`_platform_bridge.py` → `python -m deerflow.integrations.cli` → `CapabilityRouter` → `InsAdapter` → `InsClientBridge` → `features-tool`). This adds a subprocess boundary, JSON serialization overhead, and a hard dependency on the `deerflow.integrations` module for what is fundamentally a direct InS API call. The daily report should own its data retrieval end-to-end.

## What Changes

- **Remove `_platform_bridge.py`** — eliminate the subprocess bridge that calls `deerflow.integrations.cli`
- **Rewrite `PlatformDailyProvider`** in `_data_providers.py` to directly import and use `features-tool`'s `InsApiClient` for trend/alarm data, plus `kpi_aggregator` functions for KPI computation
- **Extract a lightweight InS client wrapper** (`_ins_client.py`) in the daily-report scripts directory — a thin wrapper around `InsApiClient` that handles connection setup, error mapping, and the 2k/6k/8k/9k endpoint series routing needed by the daily report
- **Keep `kpi_aggregator.py` logic but inline the relevant subset** — the aggregation functions (mean, max, runtime_rate, downtime_count, alarm_count, thickness_loss, hourly_runtime_rate) move into the daily-report scripts as `_kpi_aggregator.py`, eliminating the need to call `--action aggregate_kpi` via CLI subprocess
- **`list_equipment.py`** already calls the Gateway Organize API directly via HTTP — no change needed
- **`daily_kpi.py`** and **`export_report.py`** are pure computation/formatting — no change needed
- **BREAKING**: `_platform_bridge.py` is removed; any other callers (if any) must adopt the same direct pattern

## Capabilities

### New Capabilities
- `daily-report-direct-ins`: Direct InS data access from daily report scripts without the integrations CLI subprocess bridge
- `daily-report-kpi-aggregator`: Self-contained KPI aggregation functions within the daily report skill

### Modified Capabilities
- `equipment-report-data-provider`: The InS provider implementation changes from subprocess-based to direct-import-based. The spec's requirement ("Wire query scripts to direct InS fetch") is already stated — this change fulfills it by removing the subprocess indirection.

## Impact

- **Removed**: `skills/custom/daily-report/scripts/_platform_bridge.py` (~386 lines)
- **Modified**: `skills/custom/daily-report/scripts/_data_providers.py` — `PlatformDailyProvider` rewritten
- **Added**: `skills/custom/daily-report/scripts/_ins_client.py` — thin wrapper around features-tool `InsApiClient`
- **Added**: `skills/custom/daily-report/scripts/_kpi_aggregator.py` — self-contained KPI aggregation functions
- **No change**: `query_daily.py`, `daily_kpi.py`, `export_report.py`, `list_equipment.py` (CLI contract unchanged)
- **No change**: `backend/packages/harness/deerflow/integrations/` (integrations module is unaffected; daily report just stops using it)
