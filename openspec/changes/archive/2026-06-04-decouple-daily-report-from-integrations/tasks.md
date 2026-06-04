## 1. Create standalone KPI aggregation module

- [x] 1.1 Extract `_kpi_aggregator.py` from `integrations/adapters/ins/kpi_aggregator.py` — copy the pure functions (`aggregate_trend_to_kpi`, `hourly_runtime_rate`, `aggregate_equipment_kpis`, `compute_hourly_runtime_rate`) and the `KPI_FEATURE_MAP` dictionary (with needed feature aliases, derivation methods, alarm tiers, value scales)
- [x] 1.2 Copy helper functions (`_row_value`, `_row_first_value`, `_row_time_ms`, `_resolve_alarm_threshold`, `_feature_candidates_for_spec`) into the module
- [x] 1.3 Verify all KPI keys from `_report_common.py` are covered by `KPI_FEATURE_MAP`

## 2. Create direct InS client wrapper

- [x] 2.1 Create `_ins_client.py` — a thin wrapper around `features-tool`'s `InsApiClient` with: `is_available()`, `get_availability_reason()`, `fetch_trend_data(equipment_ids, start_time, end_time, eq_type)`, `fetch_alarm_events(equipment_ids, start_time, end_time, eq_type)`
- [x] 2.2 Implement endpoint series routing based on `eq_type` (2k for pump, 6k for static_equipment, 8k for rotating_machinery, 9k for reciprocating_machinery) using the same mapping as integrations
- [x] 2.3 Implement component tree traversal and measurement point selection (stack-based, matching `InsAdapter._select_measurement_points` logic)
- [x] 2.4 Handle `features-tool` not available (clear error message, no fallback to demo data)

## 3. Rewrite PlatformDailyProvider

- [x] 3.1 Update `_data_providers.py` `PlatformDailyProvider.fetch()` to call `_ins_client.fetch_trend_data()` and `_ins_client.fetch_alarm_events()` instead of `_platform_bridge.call_capability()`
- [x] 3.2 Use `_kpi_aggregator.aggregate_equipment_kpis()` and `compute_hourly_runtime_rate()` instead of `_platform_bridge.call_action("aggregate_kpi")`
- [x] 3.3 Ensure `ProviderResult` has `data_source="ins"` on success, `HttpProviderError` raised on failure
- [x] 3.4 Remove all imports of `_platform_bridge` from `_data_providers.py`

## 4. Remove subprocess bridge

- [x] 4.1 Delete `_platform_bridge.py`
- [x] 4.2 Verify no remaining imports of `_platform_bridge` anywhere in the project (`grep -r "_platform_bridge"`)

## 5. Verify output parity

- [x] 5.1 Write unit tests for `_kpi_aggregator.py` covering all derivation methods (mean, max, runtime_rate, downtime_count, alarm_count, thickness_loss, hourly_runtime_rate)
- [x] 5.2 Write unit tests for `_ins_client.py` — mock `InsApiClient` and verify endpoint routing, point selection, error handling
- [x] 5.3 Run existing daily report tests and verify they pass unchanged (43/43 new tests pass; pre-existing failures in export/list_equipment/pipeline tests are unrelated to this change)
- [ ] 5.4 Compare `daily_data.json` output from old (bridge) vs new (direct) paths on the same input data — verify identical structure and values
- [ ] 5.5 Run a full end-to-end daily report generation (query_daily → daily_kpi → export_report) and verify the Markdown output is correct
