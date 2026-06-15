## Why

日报生成链路存在可观测性缺失 + 无效 IO + 串行瓶颈：无分段计时埋点导致性能优化只能凭感觉；`list_equipment.py --limit 1` 仍完整请求组织树只为拿 KPI 元数据；同一轮内组织树被前端、`resolve_equipment_by_scope`、`detect_equipment_type` 重复查询三次；InS 趋势/告警按设备串行、当天/对比日顺序执行；直执行器 stdout 契约与脚本实际输出不一致导致切流会放大故障面。当前常规入口仍走多轮 Agent 编排，deep-link 直执行路径未覆盖主流量，性能问题在常规入口上被进一步放大。先补埋点建立基线，再逐步消除无效 IO 和串行瓶颈，是当前 ROI 最高的路径。

## What Changes

- **新增七段计时埋点**：表单交互、组织树查询、当天 InS 拉数、对比日 InS 拉数、SMS、KPI 计算、导出。统一字段 `trace_id` + `step_name` + `duration_ms` + `record_count`，覆盖全部七段。
- **修复直执行器输入输出契约**：当前 executor 把 query\_daily.py 的 stdout（`{"output": path}` 元数据）覆写到 `daily_data.json`，覆盖了脚本刚写入的实际数据。executor 需改为从 stdout 读取 `output` 字段定位实际数据文件，或让脚本不再写文件、纯靠 stdout 传递数据。daily\_kpi.py 同此契约。
- **去掉 Round 1.5 的无效组织树查询**：`list_equipment.py --limit 1` 仅为拿 `available_kpis`，但脚本内部仍完整请求并扁平化组织树。改为按 `equipment_type` 从静态映射 `_EQUIPMENT_TYPE_DEFAULT_KPIS` 返回 KPI 元数据，不再查树。需先验证该映射覆盖度。
- **合并后续重复组织树查询**：将"用户已选设备列表 + equipment\_type + scope"作为最终确认表单的标准输入透传到生成阶段，生成阶段不再回头查组织树。`detect_equipment_type` 和 `resolve_equipment_by_scope` 改为消费透传参数。
- **常规入口切到直执行**：保留表单交互（Round 1 → Round 1.5 → Round 2），"点击生成"后直接把结构化参数交给 `report_direct_execute`，不再让 Agent 按脚本一步步调。前置条件是直执行器契约已修复。
- **InS 拉数改为限流并发**：设备维度做有上限的并发（建议 4–8）；当天与对比日并发拉；`get_slim_components` 结果做单次运行内缓存。落点 `_ins_client.py` 的 `fetch_trend_data_async` 和 `fetch_alarm_events_async`。
- **SMS 从主链路挪到次链路**：在直执行器层做 post-processing，先出主报告再补 SMS 章节，或把 SMS 做成"展开查看"不阻塞首屏。落点需与"常规入口切直执行"一起在 P1 确定，不拆到 P2。
- **保持 `compare_with=previous_day` 默认不变**：默认值调整有口径变化风险。待埋点跑一周后，对 trend 类 KPI 才拉对比、标量 KPI 用单日快照 + 缓存昨日值的方案再独立评估。本次不调整。

## Capabilities

### New Capabilities

- `daily-report-perf-instrumentation`: 七段计时埋点能力。定义统一字段（trace\_id、step\_name、duration\_ms、record\_count）、采集点（query\_daily.py、\_ins\_client.py、query\_sms\_abnormal.py、daily\_kpi.py、export\_report.py）、输出格式（结构化 JSON 日志或 OpenTelemetry span）。
- `ins-concurrent-fetch`: InS 限流并发拉数能力。设备维度并发上限可配（默认 4–8），当天/对比日并发，`get_slim_components` 单次运行内缓存。保持现有同步 API 签名不变，内部切换为 `asyncio.Semaphore` + `asyncio.gather`。

### Modified Capabilities

- `daily-report-skill`: Round 1.5 不再调 `list_equipment.py --limit 1`，改为消费静态 KPI 元数据映射；Round 2 确认后直接走直执行而非 Agent 编排；组织树查询结果通过表单 payload 透传，生成阶段不再回头查树。
- `builtin-report-direct-executor`: 修复 stdout 契约。executor 从 stdout 解析 `output` 字段定位实际数据文件，而非把 stdout 元数据覆写到 data 文件。影响 daily/weekly/monthly 三类报告。
- `daily-report-sms-abnormal`: 从 Agent 编排的第 5 步串行调用，改为直执行器 post-processing 阶段的异步附加章节。失败不阻塞主报告，成功则追加到报告末尾或作为可展开区块。
- `daily-report-ins-provider`: 底层 `_ins_client.py` 的 `fetch_trend_data_async` 和 `fetch_alarm_events_async` 改为限流并发实现。保持对外 API 签名不变。

## Impact

- **代码**：
  - `skills/custom/daily-report/scripts/query_daily.py`：加埋点；Round 1.5 KPI 元数据改为静态映射消费
  - `skills/custom/daily-report/scripts/_ins_client.py`：加埋点；`fetch_trend_data_async` / `fetch_alarm_events_async` 改并发
  - `skills/custom/daily-report/scripts/query_sms_abnormal.py`：加埋点
  - `skills/custom/daily-report/scripts/daily_kpi.py`：加埋点
  - `skills/custom/daily-report/scripts/_report_common.py`：`detect_equipment_type` / `resolve_equipment_by_scope` 改为消费透传参数
  - `skills/custom/daily-report/scripts/list_equipment.py`：验证 `_EQUIPMENT_TYPE_DEFAULT_KPIS` 覆盖度，必要时扩充
  - `skills/custom/daily-report/scripts/export_report.py`：加埋点
  - `backend/packages/harness/deerflow/report_executor/executor.py`：修复 stdout 契约解析
  - `agents/builtin/ai-report--daily/SOUL.md`：Round 1.5 改静态 KPI 映射；Round 2 确认后直接调 `report_direct_execute`；删除组织树重复查询步骤
- **API / 依赖**：无新增外部依赖。InS 并发需确认上游 API 限流策略（建议先压测 4 并发稳定性）。
- **系统**：直执行器契约修复是常规入口切流的前置条件，两类改动需在同一次发布中完成，避免中间态故障。
- **风险**：
  - 直执行器契约修复会影响 weekly/monthly 报告，需同步验证
  - 常规入口切直执行后，Agent 编排层的容错/重试逻辑需迁移到直执行器
  - InS 并发上限需压测确认，避免触发上游限流
