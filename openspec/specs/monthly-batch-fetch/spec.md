# monthly-batch-fetch

## Purpose

月报 (`query_monthly.py`) 通过 `_ins_provider.fetch_daily_series_payload` 单次批量拉取全月每日 KPI 数据，替代原先逐日独立 InS API 调用的模式。与周报 (`query_weekly.py`) 保持一致的批量拉取模式。

## Requirements

### Requirement: Monthly report fetches daily series in single batch call
`query_monthly.fetch_month_with_provenance()` SHALL call `_ins_provider.fetch_daily_series_payload(start_date, day_count, ...)` to retrieve all daily KPI data for the calendar month in one batch invocation, instead of looping per-day through `query_daily.fetch_day_with_provenance()`.

#### Scenario: 30-day month batch fetch
- **WHEN** `fetch_month_with_provenance(report_month="2026-04", equipment_ids=["RM-001"], kpi_keys=["runtime_rate"], ...)` is called
- **THEN** exactly one call to `_ins_provider.fetch_daily_series_payload` is made with `start_date="2026-04-01"` and `day_count=30`
- **AND** the returned `list[dict]` has 30 entries, each containing `kpis`, `kpi_units`, and `alarms` for the corresponding date

#### Scenario: February in leap year (29 days)
- **WHEN** `fetch_month_with_provenance(report_month="2024-02", ...)` is called
- **THEN** `fetch_daily_series_payload` is called with `day_count=29`
- **AND** `calendar.monthrange(2024, 2)` correctly yields `(..., 29)`

#### Scenario: 31-day month batch fetch
- **WHEN** `fetch_month_with_provenance(report_month="2026-05", ...)` is called
- **THEN** `fetch_daily_series_payload` is called with `day_count=31`

### Requirement: Compare periods also use batch fetch
`query_monthly.build_result()` SHALL use the same batch fetch path for comparison periods (`previous_month`, `previous_year_month`) when calling `fetch_month_with_provenance()` for the compare baseline.

#### Scenario: Dual baseline comparison with batch fetch
- **WHEN** `build_result(report_month="2026-04", ..., compare_bases=["previous_month", "previous_year_month"])` is called
- **THEN** the current month, previous month (2026-03), and previous year month (2025-04) each use a single `fetch_daily_series_payload` call
- **AND** total InS API calls for the full monthly report is 3 (one per period) instead of 30 + 31 + 30 = 91

### Requirement: Output contract unchanged
The `monthly_data.json` output SHALL maintain the same JSON shape (report_period, equipment_ids, kpi_keys, compare_types, compare_periods, current with weekly/aggregated/maintenance/alarms/critical_events/improvement_tracking, compare, data_source, data_notes, compare_warning) as before the optimization.

#### Scenario: Pipeline end-to-end output compatibility
- **WHEN** `query_monthly.build_result()` returns a result dict with the batch fetch path
- **AND** `monthly_kpi.compute()` processes that result
- **AND** `export_report.render_monthly_markdown()` renders the KPI output
- **THEN** the markdown output contains all 8 numbered sections (月度总览 through 下月计划)
- **AND** `report_period.day_count` matches the calendar month
- **AND** `kpi_summary` includes `mtbf`, `mttr`, and `target_rate` when requested
