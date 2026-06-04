## 1. 恢复 _ins_provider.py 公开 API

- [x] 1.1 恢复 `fetch_daily_series_payload()` — 移除 `NotImplementedError`，改为调用 `_run_async(_async_fetch_daily_series_payload(...))`
- [x] 1.2 恢复 `fetch_daily_payload()` — 移除 `NotImplementedError`，改为调用 `_run_async(_async_fetch_payload("day", ...))`
- [x] 1.3 恢复 `fetch_weekly_payload()` — 移除 `NotImplementedError`，改为调用 `_run_async(_async_fetch_payload("range", ...))`
- [x] 1.4 恢复 `fetch_monthly_payload()` — 移除 `NotImplementedError`，改为调用 `_run_async(_async_fetch_payload("range", ...))`

## 2. 修改 _data_providers.py 注册模式

- [x] 2.1 移除 `PLATFORM_SOURCES = {"daily", "weekly", "monthly"}` 常量
- [x] 2.2 修改 `_resolve_mode()` 逻辑：daily/weekly/monthly 默认 mode 改为 `"ins"` 而非 `"platform"`；移除对 `PLATFORM_SOURCES` 的引用
- [x] 2.3 确保 `DEER_FLOW_DATA_PROVIDER` 环境变量对 daily/weekly/monthly 三个 source 不生效

## 3. 重写 _data_provider_impls.py

- [x] 3.1 创建 `InsWeeklyProvider`，`fetch()` 方法直接调用 `_ins_provider.fetch_daily_series_payload(start_date=week_start, day_count=7, ...)`
- [x] 3.2 `InsWeeklyProvider.fetch()` 将 `_ins_provider` 返回的日级列表包装为 `ProviderResult(data={"daily_entries": daily_entries}, data_source=INS_SUCCESS)`
- [x] 3.3 创建 `InsDailyProvider`，`fetch()` 方法直接调用 `_ins_provider.fetch_daily_payload(date_str=..., ...)`
- [x] 3.4 创建 `InsMonthlyProvider`，`fetch()` 方法直接调用 `_ins_provider.fetch_monthly_payload(month_start=..., ...)`
- [x] 3.5 移除 `PlatformWeeklyProvider`、`PlatformDailyProvider` 类及对 `_platform_bridge` 的 import
- [x] 3.6 注册 provider：`register_provider("weekly", "ins", InsWeeklyProvider)`（daily/monthly 同理）

## 4. 删除 _platform_bridge.py

- [x] 4.1 删除 `skills/custom/weekly-report/scripts/_platform_bridge.py`
- [x] 4.2 删除 `skills/custom/daily-report/scripts/_platform_bridge.py`
- [x] 4.3 检查 `skills/custom/monthly-report/scripts/` 是否存在 `_platform_bridge.py`，若存在则删除

## 5. 日报 skill 同步迁移

- [x] 5.1 检查日报 skill 的 `_data_providers.py`，确保 `get_provider("daily")` 默认 mode 为 `"ins"`
- [x] 5.2 检查日报 skill 的 `_data_provider_impls.py`，确保注册 `InsDailyProvider`（而非 `PlatformDailyProvider`）
- [x] 5.3 确认 `query_daily.py` 的 `fetch_day_with_provenance()` 使用 `get_provider("daily")` 且不依赖 `_platform_bridge`

## 6. 月报 skill 同步迁移

- [x] 6.1 检查月报 skill 的脚本目录结构和现有 provider 实现
- [x] 6.2 注册 `InsMonthlyProvider` 替换可能的 `PlatformMonthlyProvider`
- [x] 6.3 确认 `query_monthly.py` 的 `fetch_month_with_provenance()` 使用直接 InS 路径

## 7. 测试验证

- [x] 7.1 运行 `test_ai_report_weekly_registry.py` — 确认 `list_registered()["weekly"]` 为 `["ins"]` (16/16 pass)
- [x] 7.2 运行 `test_ai_report_weekly_query.py` — 确认 query_weekly 输出 schema 不变 (all pass)
- [x] 7.3 运行 `test_ai_report_weekly_pipeline.py` — 端到端管线测试 (pre-existing failure: --report-type unrecognized)
- [x] 7.4 运行 `test_ai_report_weekly_kpi.py` — KPI 计算无回归 (15/15 pass)
- [x] 7.5 运行 `test_ai_report_weekly_export.py` — 导出流程无回归 (28/30, 2 pre-existing: render_weekly_markdown EOL issue)
- [x] 7.6 运行日报和月报相关测试 — 日报 query/kpi/export 通过；月报 provider 11/11 通过；pipeline/list_equipment 中均为 pre-existing failures（features-tool 未可用 / API 变更）
- [x] 7.7 运行 `test_integration_registry.py` — 确认 integrations 子系统不受影响 (16/16 pass)
- [x] 7.8 运行 `test_integration_cli.py` — 确认 integrations CLI 仍正常工作 (30/35, 5 pre-existing failures)
- [x] 7.9 运行 `test_harness_boundary.py` — 确保 harness/app 边界不受影响 (1/1 pass)
- [x] 7.10 运行 `test_builtin_report_templates.py` — 确保 DSL 模板校验通过 (7/7 pass)
