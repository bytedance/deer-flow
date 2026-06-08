## 1. Create daily-report skill

- [ ] 1.1 Create `skills/custom/daily-report/` directory structure with `scripts/` subdirectory
- [ ] 1.2 Copy `_data_providers.py` from `data-analyst/scripts/` to `daily-report/scripts/` (full copy, unchanged)
- [ ] 1.3 Create `daily-report/scripts/_data_provider_impls.py` — register only `PlatformDailyProvider`, remove all other Provider classes
- [ ] 1.4 Copy `_platform_bridge.py` from `data-analyst/scripts/` to `daily-report/scripts/` (full copy, unchanged)
- [ ] 1.5 Copy `_ins_provider.py` from `data-analyst/scripts/` to `daily-report/scripts/` (full copy, unchanged)
- [ ] 1.6 Create `daily-report/scripts/_report_common.py` — keep only daily constants/functions: `KPI_DISPLAY_NAMES` (no monthly extension), `KPI_BETTER_WHEN_HIGHER`, `KPI_THRESHOLDS`, `validate_equipment_ids`, `parse_csv`, `error_output`, `load_sibling_module`, `detect_equipment_type`, `resolve_equipment_by_scope`, `direction`, `safe_pct`
- [ ] 1.7 Copy `query_daily.py` from `data-analyst/scripts/` to `daily-report/scripts/` (unchanged API/CLI, update sibling imports only if needed)
- [ ] 1.8 Copy `daily_kpi.py` from `data-analyst/scripts/` to `daily-report/scripts/` (unchanged API/CLI)
- [ ] 1.9 Copy `list_equipment.py` from `data-analyst/scripts/` to `daily-report/scripts/` (full copy, unchanged)
- [ ] 1.10 Create `daily-report/scripts/export_report.py` — keep only `daily` report type in `render_markdown()` and `write_report()`, remove weekly/monthly/diagnosis/monitoring/trend logic
- [ ] 1.11 Create `daily-report/report_scripts.yaml` — declare only `query_daily`, `daily_kpi`, `list_equipment`, `export_report` with existing args_schema/output_files/timeout/dependencies
- [ ] 1.12 Create `daily-report/SKILL.md` — document daily report skill scripts and usage

## 2. Create weekly-report skill

- [ ] 2.1 Create `skills/custom/weekly-report/` directory structure with `scripts/` subdirectory
- [ ] 2.2 Copy `_data_providers.py` from `data-analyst/scripts/` to `weekly-report/scripts/` (full copy, unchanged)
- [ ] 2.3 Create `weekly-report/scripts/_data_provider_impls.py` — register only `PlatformWeeklyProvider`, remove all other Provider classes
- [ ] 2.4 Copy `_platform_bridge.py` from `data-analyst/scripts/` to `weekly-report/scripts/` (full copy, unchanged)
- [ ] 2.5 Copy `_ins_provider.py` from `data-analyst/scripts/` to `weekly-report/scripts/` (full copy, unchanged)
- [ ] 2.6 Create `weekly-report/scripts/_report_common.py` — keep daily subset plus `has_previous_year_data_weekly` and `aggregate_kpis`, no monthly constants/functions
- [ ] 2.7 Copy `query_weekly.py` from `data-analyst/scripts/` to `weekly-report/scripts/` (unchanged API/CLI)
- [ ] 2.8 Copy `weekly_kpi.py` from `data-analyst/scripts/` to `weekly-report/scripts/` (unchanged API/CLI)
- [ ] 2.9 Copy `list_equipment.py` from `data-analyst/scripts/` to `weekly-report/scripts/` (full copy, unchanged)
- [ ] 2.10 Create `weekly-report/scripts/export_report.py` — keep only `weekly` report type in `render_markdown()` and `write_report()`, remove daily/monthly/diagnosis/monitoring/trend logic
- [ ] 2.11 Create `weekly-report/report_scripts.yaml` — declare only `query_weekly`, `weekly_kpi`, `list_equipment`, `export_report`
- [ ] 2.12 Create `weekly-report/SKILL.md` — document weekly report skill scripts and usage

## 3. Create monthly-report skill

- [ ] 3.1 Create `skills/custom/monthly-report/` directory structure with `scripts/` subdirectory
- [ ] 3.2 Copy `_data_providers.py` from `data-analyst/scripts/` to `monthly-report/scripts/` (full copy, unchanged)
- [ ] 3.3 Create `monthly-report/scripts/_data_provider_impls.py` — register only `PlatformMonthlyProvider`, remove all other Provider classes
- [ ] 3.4 Copy `_platform_bridge.py` from `data-analyst/scripts/` to `monthly-report/scripts/` (full copy, unchanged)
- [ ] 3.5 Copy `_ins_provider.py` from `data-analyst/scripts/` to `monthly-report/scripts/` (full copy, unchanged)
- [ ] 3.6 Create `monthly-report/scripts/_report_common.py` — keep daily subset plus `KPI_DISPLAY_NAMES_MONTHLY`, `KPI_BETTER_WHEN_HIGHER_MONTHLY`, `parse_report_month`, `month_bounds`, `has_previous_year_data_monthly`, `aggregate_kpis`, no weekly-specific functions
- [ ] 3.7 Copy `query_monthly.py` from `data-analyst/scripts/` to `monthly-report/scripts/` (unchanged API/CLI)
- [ ] 3.8 Copy `monthly_kpi.py` from `data-analyst/scripts/` to `monthly-report/scripts/` (unchanged API/CLI)
- [ ] 3.9 Copy `list_equipment.py` from `data-analyst/scripts/` to `monthly-report/scripts/` (full copy, unchanged)
- [ ] 3.10 Create `monthly-report/scripts/export_report.py` — keep only `monthly` report type in `render_markdown()` and `write_report()`, remove daily/weekly/diagnosis/monitoring/trend logic
- [ ] 3.11 Create `monthly-report/report_scripts.yaml` — declare only `query_monthly`, `monthly_kpi`, `list_equipment`, `export_report`
- [ ] 3.12 Create `monthly-report/SKILL.md` — document monthly report skill scripts and usage

## 4. Update DSL templates (BREAKING)

- [ ] 4.1 Update `agents/builtin/report-templates/daily-equipment/default.yaml` — change all `name:` fields from `data-analyst/` to `daily-report/` prefix
- [ ] 4.2 Update `agents/builtin/report-templates/weekly-equipment/default.yaml` — change all `name:` fields from `data-analyst/` to `weekly-report/` prefix
- [ ] 4.3 Update `agents/builtin/report-templates/monthly-equipment/default.yaml` — change all `name:` fields from `data-analyst/` to `monthly-report/` prefix
- [ ] 4.4 Update `agents/builtin/report-templates/diagnosis-fault/default.yaml` if it references `data-analyst/` scripts (check and update if needed)
- [ ] 4.5 Update `agents/builtin/report-templates/trend-equipment/default.yaml` if it references `data-analyst/` scripts (check and update if needed)

## 5. Update Agent SOUL.md files (BREAKING)

- [ ] 5.1 Update `agents/builtin/ai-report--daily/SOUL.md` — change all `/mnt/skills/custom/data-analyst/scripts/` paths to `/mnt/skills/custom/daily-report/scripts/`
- [ ] 5.2 Update `agents/builtin/ai-report--weekly/SOUL.md` — change all `/mnt/skills/custom/data-analyst/scripts/` paths to `/mnt/skills/custom/weekly-report/scripts/`
- [ ] 5.3 Update `agents/builtin/ai-report--monthly/SOUL.md` — change all `/mnt/skills/custom/data-analyst/scripts/` paths to `/mnt/skills/custom/monthly-report/scripts/`

## 6. Clean up data-analyst skill

- [ ] 6.1 Remove `query_daily.py` and `daily_kpi.py` from `data-analyst/scripts/` (migrated to `daily-report/`)
- [ ] 6.2 Remove `query_weekly.py` and `weekly_kpi.py` from `data-analyst/scripts/` (migrated to `weekly-report/`)
- [ ] 6.3 Remove `query_monthly.py` and `monthly_kpi.py` from `data-analyst/scripts/` (migrated to `monthly-report/`)
- [ ] 6.4 Remove `list_equipment.py` from `data-analyst/scripts/` (copied to all three new skills)
- [ ] 6.5 Remove `export_report.py` from `data-analyst/scripts/` (split into three per-type copies)
- [ ] 6.6 Update `data-analyst/scripts/_data_provider_impls.py` — remove `PlatformDailyProvider`, `PlatformWeeklyProvider`, `PlatformMonthlyProvider` classes
- [ ] 6.7 Update `data-analyst/report_scripts.yaml` — remove `query_daily`, `daily_kpi`, `query_weekly`, `weekly_kpi`, `query_monthly`, `monthly_kpi`, `list_equipment`, `export_report` entries
- [ ] 6.8 Update `data-analyst/SKILL.md` — remove daily/weekly/monthly report documentation, keep trend/diagnosis/failure/closure/inspection docs

## 7. Verify and test

- [ ] 7.1 Verify each new skill's scripts can be imported without errors (`python -c "import <module>"` for each script)
- [ ] 7.2 Run existing backend tests: `pytest backend/tests/test_data_providers.py -v`
- [ ] 7.3 Run existing backend tests: `pytest backend/tests/test_ins_provider_unit.py -v`
- [ ] 7.4 Run existing backend tests: `pytest backend/tests/test_regression_platform_mode.py -v`
- [ ] 7.5 Verify DSL template YAML is valid and passes template validation
- [ ] 7.6 Verify no cross-skill imports exist (grep for `data-analyst` in new skill dirs, grep for `daily-report`/`weekly-report`/`monthly-report` in data-analyst dir)
- [ ] 7.7 Trigger a daily report DSL run end-to-end and verify it completes successfully
- [ ] 7.8 Trigger a weekly report DSL run end-to-end and verify it completes successfully
- [ ] 7.9 Trigger a monthly report DSL run end-to-end and verify it completes successfully
