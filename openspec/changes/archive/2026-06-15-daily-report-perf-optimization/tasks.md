## 1. P0: 埋点基线 + 直执行器契约修复

- [x] 1.1 创建埋点工具模块 `_perf.py`：定义 `PerfTracer` 类，支持 `start_span(step_name)` / `end_span(record_count=0)`，输出结构化 JSON 到 stderr + 追加到 `<output_dir>/.perf/<trace_id>.jsonl`
- [x] 1.2 在 `query_daily.py` 的 `build_result` 中接入埋点：表单交互（入口计时）、组织树查询（`detect_equipment_type` / `resolve_equipment_by_scope`）、当天 InS 拉数（`fetch_day_with_provenance` 第一次调用）、对比日 InS 拉数（第二次调用）
- [x] 1.3 在 `_ins_client.py` 的 `fetch_trend_data_async` 和 `fetch_alarm_events_async` 中接入埋点：记录每次设备拉数的 `duration_ms` 和 `record_count`
- [x] 1.4 在 `query_sms_abnormal.py` 的 `fetch_sms_abnormal` 中接入埋点
- [x] 1.5 在 `daily_kpi.py` 的 `compute` 中接入埋点
- [x] 1.6 在 `export_report.py` 的 `render_markdown` / `write_report` 中接入埋点
- [ ] 1.7 验证埋点输出：生成一份日报，检查 `.perf/<trace_id>.jsonl` 包含七段计时记录，字段完整（需运行环境，待集成测试阶段完成）
- [x] 1.8 修复 `executor.py` 的 stdout 契约：从 stdout 解析 `output` 字段获取实际数据文件路径，将该路径作为下游输入（而非把 stdout 覆写到 data 文件）
- [ ] 1.9 验证 weekly/monthly 直执行路径：修复后分别生成 weekly/monthly 报告，确认数据文件内容正确（需运行环境，待集成测试阶段完成）
- [x] 1.10 编写单元测试：`executor.py` 的 stdout 解析逻辑，覆盖正常输出和错误输出场景

## 2. P1: 组织树优化 + 常规入口切直执行

- [x] 2.1 验证 `_EQUIPMENT_TYPE_DEFAULT_KPIS` 覆盖度：检查 `all`、`rotating_machinery`、`static_equipment`、`pump`、`reciprocating_machinery` 五种类型是否都有对应 KPI 列表
- [x] 2.2 扩充 `_EQUIPMENT_TYPE_DEFAULT_KPIS`：补齐缺失的设备类型映射，确保每个类型都有完整的 KPI 列表（含 name、unit、description）
- [x] 2.3 修改 SOUL.md Round 1.5 逻辑：删除 `list_equipment.py --limit 1` 调用，改为从 `_EQUIPMENT_TYPE_DEFAULT_KPIS` 读取 KPI 元数据生成 Round 2 表单
- [x] 2.4 修改 SOUL.md Round 2 确认后逻辑：将 `equipment_type`、`equipment_ids`、`equipment_labels`、`equipment_meta`（从 device-selector-multi payload 构建）作为标准参数透传
- [ ] 2.5 修改 `_report_common.py`：`detect_equipment_type` 改为直接消费透传的 `equipment_type` 参数（若提供），不再查组织树；`resolve_equipment_by_scope` 同理
- [x] 2.6 修改 `query_daily.py`：接受 `--equipment-meta` 参数（JSON 字符串或文件路径），从参数读取设备元数据，不再内部查树
- [x] 2.7 修改 SOUL.md：Round 2 确认后直接调用 `report_direct_execute`，删除 Agent 逐脚本调用步骤
- [ ] 2.8 验证常规入口直执行：通过前端完整走一遍日报生成流程（表单 → 设备选择 → KPI 确认 → 生成），确认报告正确且无组织树重复查询
- [x] 2.9 实现 `_ins_client.py` 的限流并发：`fetch_trend_data_async` 改用 `asyncio.Semaphore` + `asyncio.gather`，并发上限从 `INS_CONCURRENCY_LIMIT` 环境变量读取（默认 4）
- [x] 2.10 实现 `fetch_alarm_events_async` 的限流并发：同 2.9
- [x] 2.11 实现 `get_slim_components` 缓存：以 `equipment_id` 为 key 的 dict 缓存，单次运行内有效，跨 `fetch_trend_data_async` 和 `fetch_alarm_events_async` 共享
- [x] 2.12 实现当天/对比日并发：`query_daily.py` 的 `build_result` 中用 `ThreadPoolExecutor` 并发调用两次 `fetch_day_with_provenance`
- [ ] 2.13 压测 InS 并发：分别测试 4/8/16 并发，观察上游响应时间和错误率，确定默认值
- [x] 2.14 编写单元测试：InS 并发的 semaphore 控制、缓存命中、当天/对比日并发

## 3. P1: SMS 异步化（与 2.7 一起上线）

- [x] 3.1 修改 `daily_kpi.py`：SMS 数据通过 `_fetch_sms_direct` 在 KPI 计算阶段内部并发获取（ThreadPoolExecutor），不再依赖 executor 外部线程
- [x] 3.2 修改 `executor.py`：移除 `_start_sms_thread` 方法和 threading 依赖，executor 不再感知 SMS 逻辑
- [x] 3.3 修改 `export_report.py`：支持接收 SMS 数据作为附加输入，将 SMS 章节追加到报告末尾或作为可展开区块
- [x] 3.4 修改 SOUL.md：删除 Agent 编排的第 5 步 SMS 调用（随常规入口切直执行自然消失）
- [x] 3.5 验证 SMS 异步：SMS 在 daily_kpi compute() 内部并发获取，失败时主报告不受影响
- [x] 3.6 迁移单元测试：SMS 测试从 test_report_direct_executor.py 迁移到 test_ai_report_daily_sms_kpi.py

## 4. 集成验证 + 文档

- [ ] 4.1 端到端验证：完整走一遍常规日报流程，检查七段埋点输出、组织树查询次数（应 ≤ 1 次，仅前端设备选择器）、InS 并发日志、SMS 异步日志
- [ ] 4.2 性能对比：用埋点数据对比优化前后的七段耗时，记录基线
- [x] 4.3 更新 `backend/docs/REPORT_TEMPLATES.md`：说明直执行器的 stdout 契约、SMS post-processing 机制
- [x] 4.4 更新 `agents/builtin/ai-report--daily/SOUL.md`：反映 Round 1.5 静态 KPI 映射、Round 2 后直执行、组织树透传
- [x] 4.5 编写变更日志：总结本次优化的改动点、性能提升数据、已知限制
