## 1. Pre-deletion audit

- [x] 1.1 Grep the entire repo for `_data_banner`, `format_banner`, `data_source_banner`, `DEMO_BANNER`, `INS_BANNER` and record every call site outside the AI report path
- [x] 1.2 Grep for `DemoDailyProvider`, `DemoWeeklyProvider`, `DemoMonthlyProvider`, `_demo_day`, `_demo_week`, `_demo_month` and confirm no caller outside `_data_provider_impls.py` / `query_*.py` depends on them
- [x] 1.3 Grep frontend code and archived run viewers for `data_source_banner` field reads; if any consumer reads it, file a follow-up to drop the read before this change merges
- [x] 1.4 Grep for `DEER_FLOW_DATA_PROVIDER` in code, docs, configs, and `.env*` files; record which references are AI-report-specific (to be removed) vs unrelated (to keep)

## 2. Provider registry and impls

- [x] 2.1 In `skills/custom/data-analyst/scripts/_data_provider_impls.py`, delete the `DemoDailyProvider`, `DemoWeeklyProvider`, `DemoMonthlyProvider` classes
- [x] 2.2 Delete the three `register_provider("daily", "demo", ...)` / `("weekly", "demo", ...)` / `("monthly", "demo", ...)` calls
- [x] 2.3 Remove any imports of `_demo_day` / `_demo_week` / `_demo_month` from `_data_provider_impls.py`
- [x] 2.4 Update `_data_providers.py` module docstring to remove the "demo / http / ins" wording for daily/weekly/monthly and reflect that those three sources are InS-only

## 3. Query scripts (daily / weekly / monthly)

- [x] 3.1 In `query_daily.py`, replace the `fetch_with_fallback(...)` call inside `fetch_day_with_provenance` with `get_provider("daily").fetch(**fetch_args)`; let `HttpProviderError` propagate
- [x] 3.2 Delete `_demo_day`, `_demo_kpis`, `_demo_kpis_single`, `_demo_hourly`, `_demo_hourly_single`, `_demo_alarms`, `_deterministic_float`, `_deterministic_int`, `KPI_DEMO_RANGES`, `TYPE_ALARM_MESSAGES`, `KPI_INTEGER_KEYS` from `query_daily.py` (and any other helpers used only by the demo path)
- [x] 3.3 In `query_daily.py:build_result`, drop any logic that downgrades to demo when `current_src != "demo_fallback"`; assume `data_source == "ins"`
- [x] 3.4 Repeat 3.1–3.3 in `query_weekly.py` (`fetch_week_with_provenance`, `_demo_week`, downgrade branch around `current_src != "demo_fallback"`)
- [x] 3.5 Repeat 3.1–3.3 in `query_monthly.py` (`fetch_month_with_provenance`, `_demo_month`, downgrade branch and `compare_sources` consistency code)
- [x] 3.6 Confirm `query_*.py main()` still uses the `_error(...)` helper so `HttpProviderError` rendered as `{"error": "HttpProviderError: <msg>"}` reaches stdout
- [x] 3.7 Remove `fetch_with_fallback` imports from the three query scripts if no longer used

## 4. KPI transforms

- [x] 4.1 In `daily_kpi.py`, change `payload.get("data_source", "demo_fallback")` → `payload["data_source"]` so a missing field raises `KeyError`
- [x] 4.2 In `daily_kpi.py`, delete the `result["data_source_banner"] = _load_data_banner().format_banner(...)` assignment and any `_load_data_banner` helper
- [x] 4.3 Repeat 4.1–4.2 in `weekly_kpi.py`
- [x] 4.4 Repeat 4.1–4.2 in `monthly_kpi.py`
- [x] 4.5 Confirm `data_source` and `data_notes` are still propagated verbatim (not stripped) by the three KPI transforms

## 5. Markdown rendering and shared helper

- [x] 5.1 In `export_report.py:render_markdown`, delete the banner-prepending logic and the call to `format_banner` (or `_data_banner.format_banner`)
- [x] 5.2 Remove the idempotency check based on `is_banner_line` from `export_report.py`
- [x] 5.3 If audit 1.1 confirmed no remaining call sites, delete `skills/custom/data-analyst/scripts/_data_banner.py`
- [x] 5.4 If `_data_banner.py` is still needed by an out-of-scope consumer, leave the file but remove the AI report call sites only; note the leftover usage in `design.md` Open Questions

## 6. Builtin DSL templates

- [x] 6.1 Open `agents/builtin/report-templates/daily-equipment/default.yaml` and remove the `data_source_banner` markdown section from the `sections` array
- [x] 6.2 Do the same for `agents/builtin/report-templates/weekly-equipment/default.yaml`
- [x] 6.3 Do the same for `agents/builtin/report-templates/monthly-equipment/default.yaml`

## 7. SOUL prompts

- [x] 7.1 In `agents/builtin/ai-report--daily/SOUL.md`, remove every clause referencing "横幅" / "banner" / "demo" / "fallback" / "演示数据"
- [x] 7.2 Do the same in `agents/builtin/ai-report--weekly/SOUL.md`
- [x] 7.3 Do the same in `agents/builtin/ai-report--monthly/SOUL.md`
- [x] 7.4 Skim the three prompts for any remaining "as a backup" / "if real data is unavailable" wording and remove it

## 8. Documentation

- [x] 8.1 In `backend/docs/HTTP_CONNECTORS.md`, remove the "设备日/周/月报真数据" subsection language that mentions `DEER_FLOW_DATA_PROVIDER` as the AI report switch; replace with a "InS-only" note that lists `INS_USERNAME` / `INS_PASSWORD` / `FEATURES_TOOL_ROOT` / optional `INS_FACTORY_ID` as the required envs
- [x] 8.2 In the same doc, list the supported KPI keys for AI reports (so prompt authors don't request unmapped ones)
- [x] 8.3 Update `backend/CLAUDE.md` to remove the demo-path reference for AI reports and link to the updated `HTTP_CONNECTORS.md` section
- [x] 8.4 If `openspec/specs/equipment-report-data-provider/spec.md` exists in the canonical specs dir, ensure no cross-link still references the removed requirements

## 9. Tests

- [x] 9.1 Rewrite `backend/tests/test_ai_report_daily_ins_provider.py`: delete the "DEER_FLOW_DATA_PROVIDER unset → demo_fallback" case, keep the InS success cases, and add a new case asserting `HttpProviderError` propagates to `{"error": ...}` from `query_daily.main`
- [x] 9.2 Repeat 9.1 for `test_ai_report_weekly_ins_provider.py` and `test_ai_report_monthly_ins_provider.py`
- [x] 9.3 Delete `test_ai_report_daily_export.py::test_*_banner` assertions; if a whole test file is dedicated to banner rendering, delete the file
- [x] 9.4 Repeat 9.3 for weekly and monthly export tests
- [x] 9.5 Update `test_ai_report_daily_query.py` (and weekly / monthly equivalents) to mock `Ins{Daily,Weekly,Monthly}Provider.fetch` and assert the new `data_source="ins"` / `data_notes=[]` contract; delete any assertions that depended on the demo output shape
- [x] 9.6 Update `test_builtin_report_templates.py` to assert that none of the three DSL templates reference `data_source_banner`
- [x] 9.7 Run the full `pytest backend/tests/test_ai_report_*.py backend/tests/test_builtin_report_templates.py` suite and confirm green
- [x] 9.8 Run the broader smoke test (`pytest backend/tests/test_ins_provider_unit.py` and any other touched tests) to catch unintended regressions

## 10. Validation and wrap-up

- [x] 10.1 Run `openspec validate remove-ai-report-demo-section --strict` and address any reported issues
- [x] 10.2 Run `openspec status --change remove-ai-report-demo-section` and confirm all artifacts show `done`
- [ ] 10.3 Manually trigger a daily report against a working InS sandbox and verify the rendered markdown has no banner line and that `daily_data.json` / `daily_kpi.json` carry `data_source="ins"` + `data_notes=[]`
- [ ] 10.4 Manually trigger a daily report against a broken InS path (e.g. wrong credentials) and verify the script exits with `{"error": "HttpProviderError: ..."}` rather than producing demo output
