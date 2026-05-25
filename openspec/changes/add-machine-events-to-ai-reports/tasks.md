## 1. Provider: Add getMachineDrops call & event mapping

- [x] 1.1 Add `_EVENT_TYPE_MAP` constant in `_ins_provider.py` with type→(label, level) mapping for all 18 event types
- [x] 1.2 Add `_MACHINE_DROP_EVENT_TYPES` constant: 8K = all types 1-18, 9K = [1,2,3,14,15]
- [x] 1.3 Implement `_fetch_machine_drops(client, equipment_id, start_ms, end_ms, endpoint_series)` async function that calls `client.get_machine_drops()` and maps response to unified alarm dicts `{time, equipment, level, message}`
- [x] 1.4 Implement `_fetch_equipment_events(client, equipment_ids, start_ms, end_ms, eq_type)` async function that dispatches to 8K or 9K endpoint based on eq_type, with try/except graceful degradation on failure
- [x] 1.5 Modify `_async_fetch_payload` to call `_fetch_equipment_events` concurrently with KPI data when `eq_type` is `rotating_machinery` or `reciprocating_machinery`, and merge results into the `alarms` field
- [x] 1.6 Modify `_async_fetch_daily_series_payload` to call `_fetch_equipment_events` per day when applicable, scoping events to each day's time window

## 2. Tests

- [x] 2.1 Add unit tests for `_EVENT_TYPE_MAP` completeness and correctness (all 18 types mapped, level values in {high, warning, info})
- [x] 2.2 Add unit tests for `_fetch_equipment_events` graceful degradation when `getMachineDrops` raises
- [x] 2.3 Add integration test verifying that rotating machinery report payload includes non-empty alarms when InS returns events
- [x] 2.4 Add integration test verifying that pump/static_equipment reports still have `alarms: []`
- [x] 2.5 Add integration test verifying that weekly report daily series entries have per-day event scoping

## 3. Validation

- [x] 3.1 Run existing report pipeline tests (`test_ai_report_daily_pipeline.py`, `test_ai_report_weekly_pipeline.py`, `test_ai_report_monthly_export.py`) to verify no regressions (19/19 passed)
- [x] 3.2 Run `test_builtin_report_templates.py` to verify DSL templates pass validation (15/17 passed, 2 pre-existing failures: diagnosis-fault, failure-analysis)
- [ ] 3.3 Manual end-to-end test: generate a daily report for rotating_machinery, verify alarm_table section is populated

## 4. SOUL.md Fix: Missing `--type` in specific-equipment command variants

- [x] 4.1 Add `--type "{validated.equipment_type}"` to the "指定设备场景" query command in `ai-report--daily/SOUL.md`
- [x] 4.2 Add `--type "{validated.equipment_type}"` to the "指定设备场景" query command in `ai-report--weekly/SOUL.md`
- [x] 4.3 Add `--type "{validated.equipment_type}"` to the "指定设备场景" query command in `ai-report--monthly/SOUL.md`
