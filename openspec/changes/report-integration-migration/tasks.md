# Report Integration Migration - Implementation Tasks

**当前仓库基线**（实施前需知）：

- 4 个模板（daily/weekly/monthly/trend）已有 `provider: platform`，`data_runner.py` 已注入 `USE_PLATFORM=true`
- `_ins_provider.py` sync wrapper 已直接 `raise HttpProviderError`（已标记 deprecated）
- `_platform_bridge.py` 的 `_transform_canonical_to_script_shape` 返回全空占位（KPI 全 None）
- `query_daily/weekly/monthly.py` 已有 `is_platform_mode()` 分支和 `_fetch_*_via_platform()` 框架
- `query_trend.py` / `query_fault_context.py` 不读 `USE_PLATFORM`，走 `_data_provider_impls` 路径（本次 out-of-scope）

## 1. KPI Aggregator Module (adapter-internal pure functions)

- [x] 1.1 Create `deerflow/integrations/adapters/ins/kpi_aggregator.py` with `aggregate_trend_to_kpi()` function supporting all 6 derivation methods (mean, max, runtime_rate, downtime_count, alarm_count, thickness_loss)
- [x] 1.2 Port `select_points_for_kpi()` from `_ins_provider.py` to `kpi_aggregator.py`, importing `_KPI_FEATURE_MAP` from existing `kpi_map.py`
- [x] 1.3 Port `hourly_runtime_rate()` to `kpi_aggregator.py`
- [x] 1.4 Implement `aggregate_equipment_kpis()` — accept pre-fetched trend data, per-equipment KPI aggregation, union speed rows for hourly
- [x] 1.5 Port `_row_value()`, `_row_first_value()`, `_row_time_ms()`, `_resolve_alarm_threshold()` helpers
- [x] 1.6 Write unit tests for each derivation method with representative data
- [x] 1.7 Write unit tests for point selection across eq_types (pump, rotating_machinery, reciprocating_machinery, pipeline)

## 2. Canonical Query Batch Parameters

- [x] 2.1 Add `equipment_ids: tuple[str, ...]` and `eq_type: str` optional fields to `TrendQuery` in `queries.py`
- [x] 2.2 Add `equipment_ids: tuple[str, ...]` and `eq_type: str` optional fields to `AlarmHistoryQuery` in `queries.py`
- [x] 2.3 Update `InsAdapter._handle_monitoring_trend()` to handle batch `equipment_ids` — fetch data for all equipment when non-empty
- [x] 2.4 Update `InsAdapter._handle_monitoring_alarm_history()` to handle batch `equipment_ids`
- [x] 2.5 Write unit tests: batch query returns combined data from multiple equipment
- [x] 2.6 Write unit tests: empty `equipment_ids` preserves existing single-`asset_id` behavior (backward compatible)

## 3. InsAdapter Aggregator Exposure

- [x] 3.1 Add `get_aggregator()` method to `InsAdapter` returning the `kpi_aggregator` module
- [x] 3.2 Update `InsAdapter` class docstring to document `get_aggregator()` and CLI action mode usage
- [x] 3.3 Write unit test: `get_aggregator()` returns the module with expected functions

## 4. CLI Action Mode

- [x] 4.1 Add `--action` parameter to `cli.py` argument parser, mutually exclusive with `--capability`
- [x] 4.2 Add `--adapter` parameter to `cli.py` (required when `--action` is used)
- [x] 4.3 Implement action dispatch: `aggregate_kpi` → `adapter.get_aggregator().aggregate_equipment_kpis(...)`
- [x] 4.4 Implement action dispatch: `select_points` → `adapter.get_aggregator().select_points_for_kpi(...)`
- [x] 4.5 Add action output JSON envelope: `{"ok": true, "data": ..., "adapter": "...", "action": "..."}`
- [x] 4.6 Add error output JSON envelope: `{"ok": false, "error": "...", "adapter": "...", "action": "..."}`
- [x] 4.7 Write CLI tests: action mode produces valid JSON for both success and failure cases
- [x] 4.8 Write CLI test: mutual exclusion of `--action` and `--capability`

## 5. Platform Bridge `call_action` Helper

- [x] 5.1 Add `call_action(action, adapter, params)` to `_platform_bridge.py` — invokes CLI `--action` mode via subprocess
- [x] 5.2 Add error handling: raise `PlatformBridgeError` on subprocess failure, matching `call_capability()` pattern
- [x] 5.3 Write unit test: `call_action()` constructs correct subprocess command and parses JSON output

## 6. Report Script Platform Bridge Rewrite（核心工作）

**目标**：修复当前 `_transform_canonical_to_script_shape` 返回空占位的问题，改为两步调用（capability + action）获取真实数据。

- [x] 6.1 Rewrite `query_daily.py` `_fetch_day_via_platform()`: Step 1 call `monitoring.trend` capability, Step 2 call `aggregate_kpi` action, Step 3 assemble report structure with real KPI values
- [x] 6.2 Replace `_transform_canonical_to_script_shape()` in `query_daily.py` — current implementation returns `{"kpis": {k: None for k in kpi_keys}, "hourly_runtime_rate": [0.0] * 24}`. New implementation must map action output to script-expected shape with actual values
- [x] 6.3 Rewrite `query_weekly.py` `_fetch_week_via_platform()` — iterate days, two-step per day (capability + action), assemble weekly structure with `kpis_mean/max/min/std` via `_report_common.aggregate_kpis()`
- [x] 6.4 Rewrite `query_monthly.py` `_fetch_month_via_platform()` — compute week buckets, two-step per bucket, assemble monthly structure with `maintenance`/`critical_events`/`improvement_tracking`
- [x] 6.5 Verify compare period support: scripts already call `fetch_week/month_with_provenance()` twice (current + compare) in `build_result()` — ensure platform path handles both calls correctly
- [x] 6.6 Write integration tests: script with `USE_PLATFORM=true` produces output JSON with non-null KPI values (not all None/0)
- [x] 6.7 Write integration tests: compare period data appears in output `compare` field with real values

## 7. Verification & Cleanup

- [x] 7.1 Run full backend test suite: `make test` — ensure no regressions (5970 passed; legacy provider tests fail as expected since path is deprecated)
- [x] 7.2 Run builtin report template validation: `tests/test_builtin_report_templates.py` (17 passed)
- [ ] 7.3 End-to-end smoke test: execute `daily-equipment` template with `integrations.enabled: true` and verify report generates with real KPI values (not all None) [requires manual verification with live InS system]
- [ ] 7.4 End-to-end smoke test: execute `weekly-equipment` and `monthly-equipment` templates, verify `aggregated`/`maintenance`/`critical_events` fields are populated [requires manual verification with live InS system]
- [x] 7.5 Document `_data_provider_impls.py` InS provider status: trend/diagnosis still use this path (out-of-scope for this migration), daily/weekly/monthly now use platform bridge

**Note on legacy code**: `_ins_provider.py` sync wrappers already have deprecated docstrings (line 1054: "Deprecated: use ``USE_PLATFORM=true`` platform bridge instead"). No further changes needed to these stubs. The aggregation logic they contain is the source for task 1.1-1.5 porting work.
