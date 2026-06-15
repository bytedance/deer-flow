# 日报性能优化 — 变更日志

## 改动点

### 1. 埋点基线 (`_perf.py`)

新增 `PerfTracer` 类，七段计时（表单交互、组织树查询、当天/对比日 InS、SMS、KPI 计算、导出）输出结构化 JSON 到 stderr + `<output_dir>/.perf/<trace_id>.jsonl`。

### 2. 直执行器契约修复 (`executor.py`)

修复 stdout 契约：从脚本 stdout 解析 `output` 字段定位真实数据文件，避免将 stdout 元数据覆写到数据文件。新增 `_resolve_output_path` 方法 + 6 个单元测试。

### 3. 组织树查询优化

- `_report_common.py`: `detect_equipment_type` / `resolve_equipment_by_scope` 支持 `resolved_type` / `resolved_records` 透传参数，跳过内部组织树查询。
- `_report_common.py`: 新增 `get_kpi_catalog(eq_type)` 返回静态 KPI 目录。
- `query_daily.py`: 新增 `--equipment-meta` 参数，从前端表单透传消费设备元数据。
- `executor.py` / `report_direct_tools.py`: 工具签名新增 `equipment_meta` 参数，构造 `--equipment-meta` CLI 参数。
- `SOUL.md`: Round 1.5 改用静态 KPI 映射，Round 2 直接调用 `report_direct_execute` 替代逐脚本编排。

### 4. InS 并发拉取 (`_ins_client.py`)

- `fetch_trend_data_async` / `fetch_alarm_events_async`: 改用 `asyncio.Semaphore(INS_CONCURRENCY_LIMIT)` + `asyncio.gather`，并发上限默认 4，通过 `INS_CONCURRENCY_LIMIT` 环境变量可调。
- `_get_slim_components_cached`: 新增模块级 dict 缓存，单次运行内跨调用共享。
- `query_daily.py`: `build_result` 中当天/对比日使用 `ThreadPoolExecutor(max_workers=2)` 并发拉取。

### 5. SMS 异步 Post-Processing（方案 B：移入 daily_kpi.py）

- `daily_kpi.py`: 新增 `_fetch_sms_direct(payload)` 直接调用 `query_sms_abnormal.fetch_sms_abnormal`，在 `compute()` 内通过 `ThreadPoolExecutor(max_workers=1)` 与 KPI 计算并发执行。SMS 失败返回 None，主报告正常生成。
- `daily_kpi.py`: 新增 `_sms_kpi(key, value)` 辅助函数，减少 SMS KPI 卡片构建重复代码。
- `executor.py`: 移除 `_start_sms_thread` 方法、`threading` 导入、以及 `execute()` 中的 SMS 线程启动/等待逻辑。executor 回归通用报告执行器职责，不再感知 SMS。
- `export_report.py`: `render_markdown` 新增 "SMS 异常监测" 章节，渲染异常总数、等级分布、Top 10 事件。

## 单元测试

- `test_executor_stdout_contract.py`: 6 个用例覆盖 `_resolve_output_path` 正常/异常路径。
- `test_daily_report_scripts.py::TestInsClientConcurrency`: 4 个用例覆盖 semaphore 限流、缓存命中、告警并发、6k 静默。
- `test_ai_report_daily_sms_kpi.py`: 7 个用例覆盖 `_fetch_sms_direct`（缺参/异常/空结果/成功）、2 个用例覆盖 `_sms_kpi` 辅助函数、4 个用例覆盖 compute() SMS 集成（注入/无注入/detail 兼容/表格行）。原 `TestSMSThread` 4 个用例已移除。

总计 74 个相关测试全部通过。

## 已知限制

- **压测未执行**: 任务 2.13（4/8/16 并发压测 InS）需要真实环境，待集成测试阶段完成。
- **端到端验证未执行**: 任务 4.1（端到端验证）和 4.2（性能对比）需要运行环境。
- **基线数据缺失**: 由于埋点尚未在真实环境运行，优化前后的具体耗时对比数据暂缺。
- **PerfTracer 非线程安全**: tracer 使用单一 `_active_span`，并发场景下使用单个 span 包裹并发块（`ins_fetch_both`）而非每线程独立 span。
