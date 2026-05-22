## 1. Core Implementation

- [x] 1.1 Add `_load_ins_provider()` helper to `query_monthly.py` (mirrors `query_weekly.py`'s pattern)
- [x] 1.2 Refactor `fetch_month_with_provenance()` to call `_ins_provider.fetch_daily_series_payload(start_date=month_start, day_count=day_count, ...)` instead of per-day `query_daily.fetch_day_with_provenance()` loop
- [x] 1.3 Verify batch return format `[{date, kpis, kpi_units, alarms}, ...]` is field-to-field identical with existing `daily_entries` construction (no mapping code needed — confirmed in design §Decision 3)
- [x] 1.4 Remove `_load_query_daily()` function (no longer needed after refactor)
- [x] 1.5 Run existing monthly tests to verify output contract unchanged

## 2. Test Updates

- [x] 2.1 Update `test_ai_report_monthly_pipeline.py` mock strategy: mock `_ins_provider.fetch_daily_series_payload` instead of `fetch_month_with_provenance` (or keep the existing stub approach which already works at `build_result` level)
- [x] 2.2 Add test case for `fetch_month_with_provenance()` calling batch path with correct `start_date` and `day_count` for a 30-day month
- [x] 2.3 Add test case for February leap year (2024-02 → day_count=29)
- [x] 2.4 Verify `test_ai_report_monthly_registry.py` still passes (no changes expected)
- [x] 2.5 Run full monthly test suite: `pytest backend/tests/test_ai_report_monthly_*.py -v`

## 3. Verification

- [x] 3.1 Run `python skills/custom/data-analyst/scripts/query_monthly.py --report-month 2026-04 --equipment "RM-001" --kpis "runtime_rate,downtime_count,alarm_count,mtbf,mttr,target_rate" --compare "previous_month,previous_year_month"` and verify valid JSON output on stdout
- [x] 3.2 Run `python skills/custom/data-analyst/scripts/monthly_kpi.py` and verify `monthly_kpi.json` output contains all expected sections
- [x] 3.3 Run `python skills/custom/data-analyst/scripts/export_report.py --report-type monthly --format md` and verify 8-section markdown output
