# Weekly & Monthly Report Performance Optimization

## 概述

基于日报性能优化的经验，将周报和月报也切换到直执行模式，复用日报的优化成果（埋点基线、stdout契约修复、组织树透传、InS并发拉取、SMS异步化、TodoMiddleware进度跟踪）。

## 改动点

### 1. 基础设施

- **`_perf.py` 复制**：将 `daily-report/scripts/_perf.py` 复制到 `weekly-report/scripts/_perf.py` 和 `monthly-report/scripts/_perf.py`，确保三个 Skill 各自独立、无跨 Skill 导入。

### 2. 周报脚本优化

- **`_ins_provider.py` 并发改造**：
  - 实现 `asyncio.Semaphore(INS_CONCURRENCY_LIMIT)` + `asyncio.gather` 并发模式
  - 环境变量 `INS_CONCURRENCY_LIMIT` 控制并发数（默认 4）
  - 提取 `_fetch_trend_device` / `_fetch_alarm_device` 单设备函数

- **`_ins_provider.py` 缓存**：
  - 实现 `_get_slim_components_cached` 模块级 dict 缓存
  - 避免重复查询 slim_components API

- **`_report_common.py` 增强**：
  - 新增 `get_kpi_catalog(eq_type)` 静态 KPI 目录函数
  - 覆盖 `all` / `static_equipment` / `rotating_machinery` / `pump` / `reciprocating_machinery` 五种设备类型
  - `detect_equipment_type` 新增 `resolved_type` 关键字参数
  - `resolve_equipment_by_scope` 新增 `resolved_records` 关键字参数

- **`query_weekly.py` CLI 增强**：
  - 新增 `--equipment-meta` CLI 参数（JSON 字符串或 @file 路径）
  - 解析后透传给内部函数，避免重复查询组织树
  - 接入 `PerfTracer` 埋点（`org_tree`、`ins_fetch`、`ins_fetch_compare` 段计时）

- **`weekly_kpi.py` SMS 异步化**：
  - 新增 `_fetch_sms_direct(payload)` 和 `_sms_kpi(key, value)` 辅助函数
  - 在 `compute()` 内通过 `ThreadPoolExecutor(max_workers=1)` 并发获取 SMS 数据
  - 接入 `PerfTracer` 埋点（`kpi_compute` 段计时）

- **`export_report.py` 埋点**：
  - 接入 `PerfTracer` 埋点（`export` 段计时）

### 3. 月报脚本优化

- **`_ins_provider.py` 并发改造**：
  - 实现 `asyncio.Semaphore(INS_CONCURRENCY_LIMIT)` + `asyncio.gather` 并发模式
  - Semaphore 跨日期共享，适配月报批量拉取场景

- **`_ins_provider.py` 缓存**：
  - 实现 `_get_slim_components_cached` 模块级 dict 缓存

- **`_report_common.py` 增强**：
  - 新增 `get_kpi_catalog(eq_type)` 静态 KPI 目录函数
  - 覆盖五种设备类型，含月报特有 KPI：`mtbf`、`mttr`、`target_rate`
  - `detect_equipment_type` 新增 `resolved_type` 关键字参数
  - `resolve_equipment_by_scope` 新增 `resolved_records` 关键字参数

- **`query_monthly.py` CLI 增强**：
  - 新增 `--equipment-meta` CLI 参数（JSON 字符串或 @file 路径）
  - 实现日期级并发——`ThreadPoolExecutor` 对月内多个工作日并发调用 `fetch_day_with_provenance`
  - 所有日期共享同一个 Semaphore
  - 接入 `PerfTracer` 埋点（`org_tree`、`ins_fetch_batch` 段计时）

- **`monthly_kpi.py` SMS 异步化**：
  - 新增 `_fetch_sms_direct(payload)` 和 `_sms_kpi(key, value)` 辅助函数
  - `_sms_kpi` 使用月报 KPI 格式（含 `current_in_target_ratio`、`previous_month_mean`、`delta_mom`、`delta_yoy`）
  - 在 `compute()` 内并发获取 SMS 数据
  - 接入 `PerfTracer` 埋点（`kpi_compute` 段计时）

- **`export_report.py` 埋点**：
  - 接入 `PerfTracer` 埋点（`export` 段计时）

### 4. Agent SOUL.md 更新

- **周报 Agent (`ai-report--weekly/SOUL.md`)**：
  - Round 1.5 删除 `list_equipment.py --limit 1` 调用
  - Round 1.5 改用 `_report_common.get_kpi_catalog(eq_type)` 静态映射生成 KPI 表单
  - Round 1.5 新增 `equipment_meta` 构建逻辑（从 device-selector-multi payload 构建 `{id: {id, name}}` 字典）
  - Round 2 回调删除逐脚本 bash 编排（query_weekly → weekly_kpi → query_sms_abnormal → export_report）
  - Round 2 改为单次 `report_direct_execute` 调用，透传 `equipment_meta`

- **月报 Agent (`ai-report--monthly/SOUL.md`)**：
  - Round 1.5 删除 `list_equipment.py --limit 1` 调用
  - Round 1.5 改用 `_report_common.get_kpi_catalog(eq_type)` 静态映射生成 KPI 表单
  - Round 1.5 新增 `equipment_meta` 构建逻辑
  - Round 2 回调删除逐脚本 bash 编排
  - Round 2 改为单次 `report_direct_execute` 调用，透传 `equipment_meta`

## 测试覆盖

### 周报测试 (`test_ai_report_weekly_concurrency.py`)

- `test_ins_concurrency_semaphore_limit`：验证 Semaphore 限制并发数
- `test_slim_components_cache_hit`：验证模块级 dict 缓存命中
- `test_weekly_sms_kpi_helper`：验证 `_sms_kpi` 辅助函数格式正确
- `test_weekly_fetch_sms_direct_missing_params`：验证缺参时优雅降级
- `test_weekly_fetch_sms_direct_success`：验证成功获取 SMS 数据
- `test_weekly_compute_sms_integration`：验证 compute() 集成 SMS 数据
- `test_weekly_perf_tracer_export`：验证 PerfTracer 埋点输出

### 月报测试 (`test_ai_report_monthly_concurrency.py`)

- `test_monthly_ins_concurrency_semaphore`：验证跨日期 Semaphore 共享
- `test_monthly_slim_components_cache_hit`：验证模块级 dict 缓存命中
- `test_monthly_sms_kpi_helper`：验证月报 KPI 格式（含同比环比字段）
- `test_monthly_fetch_sms_direct_missing_params`：验证缺参时优雅降级
- `test_monthly_fetch_sms_direct_success`：验证成功获取 SMS 数据
- `test_monthly_compute_sms_integration`：验证 compute() 集成 SMS 数据
- `test_monthly_perf_tracer_export`：验证 PerfTracer 埋点输出

### 执行器测试 (`test_report_direct_executor.py`)

- `test_execute_weekly_with_equipment_meta`：验证周报透传 `equipment_meta`
- `test_execute_monthly_with_equipment_meta`：验证月报透传 `equipment_meta`
- `test_execute_passes_report_run_id_env`：验证 `REPORT_RUN_ID` 环境变量透传

## 已知限制

1. **日期级并发复杂度**：月报日期级并发通过 `ThreadPoolExecutor` 实现，所有日期共享同一个 `asyncio.Semaphore`。由于 asyncio 事件循环在单个线程中运行，真正的跨线程并发需要更复杂的事件循环管理。当前实现已通过设备级并发提供显著性能提升。

2. **SMS 异步化限制**：SMS 数据获取通过 `ThreadPoolExecutor(max_workers=1)` 实现，单线程避免并发冲突。如需进一步提升，可考虑增加 worker 数，但需确保 SMS API 支持并发请求。

3. **组织树透传依赖前端**：`equipment_meta` 由前端表单构建并透传。若前端未实现此逻辑，脚本会回退到查询组织树（性能略差但功能正常）。

4. **PerfTracer 依赖环境变量**：`PerfTracer` 需要 `REPORT_RUN_ID` 环境变量才能输出 trace 文件。若未设置，tracer 静默禁用，不影响功能。

5. **缓存生命周期**：`_slim_components_cache` 是模块级 dict，进程重启后清空。长生命周期进程中若 slim_components 数据变更，需手动清空缓存或重启进程。

## 性能预期

- **InS 数据拉取**：从串行 N 次请求优化为并发（最多 `INS_CONCURRENCY_LIMIT` 次），预期提速 2-4 倍（取决于并发限制和网络延迟）。
- **SMS 数据获取**：从同步阻塞优化为异步并发，预期节省 1-3 秒（取决于 SMS API 响应时间）。
- **组织树查询**：通过 `equipment_meta` 透传，完全避免重复查询，预期节省 0.5-2 秒。
- **整体报告生成**：综合上述优化，预期周报生成时间从 10-15 秒降低到 4-8 秒，月报从 20-30 秒降低到 8-15 秒（具体取决于设备数量和网络条件）。

## 验证清单

- [ ] 端到端验证：通过前端走一遍周报完整流程（表单 → 设备选择 → KPI 确认 → 生成），确认报告正确
- [ ] 端到端验证：通过前端走一遍月报完整流程，确认报告正确且日期级并发生效
- [ ] 检查 `.perf/<trace_id>.jsonl` 包含周报/月报的各段计时记录
- [ ] 验证周报/月报在设备数量 > 10 时的并发限流行为
- [ ] 验证 SMS 数据缺失时报告仍正常生成（SMS 章节置空）
- [ ] 验证 `equipment_meta` 透传后脚本不再查询组织树（通过日志或 tracer 确认）
