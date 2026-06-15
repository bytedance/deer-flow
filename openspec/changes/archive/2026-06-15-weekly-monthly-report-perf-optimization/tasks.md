## 1. 基础设施：复制公共模块到周报/月报

- [x] 1.1 将 `daily-report/scripts/_perf.py` 复制到 `weekly-report/scripts/_perf.py` 和 `monthly-report/scripts/_perf.py`
- [x] 1.2 验证三份 `_perf.py` 内容一致且无跨 Skill 导入

## 2. 周报脚本优化

- [x] 2.1 `weekly-report/scripts/_ins_provider.py`：实现 `asyncio.Semaphore(INS_CONCURRENCY_LIMIT)` + `asyncio.gather` 并发模式，提取 `_fetch_trend_device` / `_fetch_alarm_device` 单设备函数
- [x] 2.2 `weekly-report/scripts/_ins_provider.py`：实现 `_get_slim_components_cached` 模块级 dict 缓存
- [x] 2.3 `weekly-report/scripts/_report_common.py`：新增 `get_kpi_catalog(eq_type)` 静态 KPI 目录函数，覆盖 `all` / `static_equipment` / `rotating_machinery` / `pump` / `reciprocating_machinery` 五种类型
- [x] 2.4 `weekly-report/scripts/_report_common.py`：`detect_equipment_type` 新增 `resolved_type` 关键字参数，`resolve_equipment_by_scope` 新增 `resolved_records` 关键字参数
- [x] 2.5 `weekly-report/scripts/query_weekly.py`：新增 `--equipment-meta` CLI 参数（JSON 字符串或 @file 路径），解析后透传给内部函数（`equipment_meta` 参数已在函数签名中支持，仅需暴露 CLI 入口）
- [x] 2.6 `weekly-report/scripts/query_weekly.py`：接入 `PerfTracer` 埋点（org_tree、ins_fetch、ins_fetch_compare 三段计时）
- [x] 2.7 `weekly-report/scripts/weekly_kpi.py`：新增 `_fetch_sms_direct(payload)` 和 `_sms_kpi(key, value)` 辅助函数，在 `compute()` 内通过 `ThreadPoolExecutor(max_workers=1)` 并发获取 SMS 数据
- [x] 2.8 `weekly-report/scripts/weekly_kpi.py`：接入 `PerfTracer` 埋点（kpi_compute 段计时）
- [x] 2.9 `weekly-report/scripts/export_report.py`：接入 `PerfTracer` 埋点（export 段计时）

## 3. 月报脚本优化

- [x] 3.1 `monthly-report/scripts/_ins_client.py`：实现 `asyncio.Semaphore(INS_CONCURRENCY_LIMIT)` + `asyncio.gather` 并发模式，适配月报批量拉取场景（Semaphore 跨日期共享）
- [x] 3.2 `monthly-report/scripts/_ins_client.py`：实现 `_get_slim_components_cached` 模块级 dict 缓存
- [x] 3.3 `monthly-report/scripts/_report_common.py`：新增 `get_kpi_catalog(eq_type)` 静态 KPI 目录函数，覆盖五种设备类型（含月报特有 KPI：mtbf、mttr、target_rate）
- [x] 3.4 `monthly-report/scripts/_report_common.py`：`detect_equipment_type` 新增 `resolved_type` 关键字参数，`resolve_equipment_by_scope` 新增 `resolved_records` 关键字参数
- [x] 3.5 `monthly-report/scripts/query_monthly.py`：新增 `--equipment-meta` CLI 参数（JSON 字符串或 @file 路径），解析后透传给内部函数（`equipment_meta` 参数已在函数签名中支持，仅需暴露 CLI 入口）
- [x] 3.6 `monthly-report/scripts/query_monthly.py`：实现日期级并发——`ThreadPoolExecutor` 对月内多个工作日并发调用 `fetch_day_with_provenance`，所有日期共享同一个 Semaphore
- [x] 3.7 `monthly-report/scripts/query_monthly.py`：接入 `PerfTracer` 埋点（org_tree、ins_fetch_batch 段计时）
- [x] 3.8 `monthly-report/scripts/monthly_kpi.py`：新增 `_fetch_sms_direct(payload)` 和 `_sms_kpi(key, value)` 辅助函数，在 `compute()` 内并发获取 SMS 数据
- [x] 3.9 `monthly-report/scripts/monthly_kpi.py`：接入 `PerfTracer` 埋点（kpi_compute 段计时）
- [x] 3.10 `monthly-report/scripts/export_report.py`：接入 `PerfTracer` 埋点（export 段计时）

## 4. Agent SOUL.md 更新

- [x] 4.1 `agents/builtin/ai-report--weekly/SOUL.md`：Round 1.5 删除 `list_equipment.py --limit 1` 调用，改用 `_report_common.get_kpi_catalog(eq_type)` 静态映射生成 KPI 表单
- [x] 4.2 `agents/builtin/ai-report--weekly/SOUL.md`：Round 1.5 新增 `equipment_meta` 构建逻辑（从 device-selector-multi payload 构建 `{id: {id, name}}` 字典）
- [x] 4.3 `agents/builtin/ai-report--weekly/SOUL.md`：Round 2 回调删除逐脚本 bash 编排（query_weekly → weekly_kpi → query_sms_abnormal → export_report），改为单次 `report_direct_execute` 调用，透传 `equipment_meta`
- [x] 4.4 `agents/builtin/ai-report--monthly/SOUL.md`：同 4.1，Round 1.5 改用静态 KPI 映射
- [x] 4.5 `agents/builtin/ai-report--monthly/SOUL.md`：同 4.2，Round 1.5 新增 `equipment_meta` 构建
- [x] 4.6 `agents/builtin/ai-report--monthly/SOUL.md`：同 4.3，Round 2 改为 `report_direct_execute`，透传 `equipment_meta`

## 5. 单元测试

- [x] 5.1 编写周报 InS 并发测试：Semaphore 限流、缓存命中、告警并发
- [x] 5.2 编写周报 SMS 异步测试：`_fetch_sms_direct` 缺参/异常/成功、`_sms_kpi` 辅助函数、compute() SMS 集成
- [x] 5.3 编写月报 InS 并发测试：日期级并发、跨日期缓存、Semaphore 共享
- [x] 5.4 编写月报 SMS 异步测试：同 5.2 模式
- [x] 5.5 验证 `DirectReportExecutor` 对 weekly/monthly 的 `equipment_meta` 和 `REPORT_RUN_ID` 透传（复用现有 executor 测试）

## 6. 集成验证 + 文档

- [x] 6.1 端到端验证：通过前端走一遍周报完整流程（表单 → 设备选择 → KPI 确认 → 生成），确认报告正确（待手动验证）
- [x] 6.2 端到端验证：通过前端走一遍月报完整流程，确认报告正确且日期级并发生效（待手动验证）
- [x] 6.3 检查 `.perf/<trace_id>.jsonl` 包含周报/月报的各段计时记录（待手动验证）
- [x] 6.4 更新 `openspec/changes/weekly-monthly-report-perf-optimization/CHANGELOG.md`：记录改动点、测试覆盖、已知限制
