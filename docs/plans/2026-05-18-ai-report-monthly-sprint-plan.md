# AI 月报智能体 Sprint 实施计划

> **来源设计文档**：[AI 月报智能体功能设计文档](./2026-05-18-ai-report-monthly-design.md)
> **对标计划**：与 [AI 周报智能体 Sprint 实施计划](./2026-05-18-ai-report-weekly-sprint-plan.md) 结构对齐，仅在月维度差异点（自然月/闰年、周聚合、月环比 + 同比双基准、MTBF/MTTR、重大事件、改进跟踪、对日报/周报脚本的向后兼容）上做调整。
> **范围**：基于设计文档拆分出的执行计划，覆盖 Sprint 目标、故事拆分、依赖、验收标准、风险与排期。

---

## 1. Sprint Goal

在不新增后端路由、不新增前端组件、不破坏日报/周报现有行为的前提下，完成 `ai-report--monthly` 的月报生成 MVP：用户可通过 4 轮 GenUI 表单选择报告月份、设备类型、对比基准（环比 + 同比可多选）、设备列表与 KPI 指标（含 MTBF/MTTR/达标率），基于演示/Skill 数据生成月 KPI、周维度趋势图、异常 TopN、重大事件回顾、改进措施跟踪、月度复盘与下月计划，并完成 Markdown 自动导出闭环（PDF 沿用日报/周报 weasyprint 路径，不可用时优雅降级）。

## 2. Sprint 假设

| 项 | 假设 |
| ---- | ------ |
| Sprint 周期 | 1 周 |
| 团队配置 | 1 名全栈/Agent 工程师（与周报同人为佳，便于复用脚本约定） |
| 可用容量 | 5 人天 |
| 缓冲 | 25%（约 1.25 人天，比周报略高，应对闰年/双基准复杂度） |
| 可承诺容量 | 3.75 人天 |
| Must 承诺范围 | Stories M1-M5：query_monthly + monthly_kpi + export_report 扩展 + SOUL.md 4 轮表单 + 端到端联调 |
| Should / Stretch 范围 | Story M6 DSL 脚本注册联调 + Story M7 单元测试与最小回归 |
| 本 Sprint 目标 | 月报 MVP 端到端跑通 Markdown 导出；不强行接真实数据源；不重做 PDF 路径，沿用日报/周报已验证降级方案 |
| 前置依赖 | 周报 MVP（Story W1-W5）已合入主干，`export_report.py` 已具备 `report_type` 调度与 `daily`/`weekly` 双类型支持 |

> 真实数据接入与 PDF 依赖问题已在日报/周报 Sprint 验证过结论，本 Sprint **不再重复验证**；月报直接复用 weasyprint try/except 降级模式。
> "同比（去年同月）" 对比基准依赖历史数据可用性，本 Sprint 仅完成接口与降级路径，不承诺生产数据可用性。
> "改进措施跟踪" 真实数据源（维修工单 / Improvement Plan API）未定，本 Sprint 仅完成演示数据回退与渲染契约。

---

## 3. Stories

> **承诺口径**：Must Stories（M1-M5，共 15 SP）是本 Sprint 的交付承诺；Should Stories（M6-M7，共 4 SP）在 Must 完成后推进，不阻塞 MVP 验收。

### Story M1（Must）：新增 `query_monthly.py` 月度数据查询脚本（4 SP）

**目标**：提供稳定的月度演示数据源，让月报流程在真实数据 API 未确定前可端到端跑通，且与日报/周报演示数据脚本风格一致。**关键复杂度**：自然月边界 + 闰年 + 月内截断 7 日桶拆分 + 双对比基准 + 跨年同期。

**范围**：

- 新增 `skills/custom/data-analyst/scripts/query_monthly.py`
- 支持 `--report-month`、`--type`、`--equipment`、`--scope`、`--scope-filter`、`--kpis`、`--compare`（CSV 多基准）、`--aggregate`、`--include-daily`（MVP 默认 false，保留 V2 趋势分析）
- 使用 `calendar.monthrange(year, month)` 计算 `day_count`，正确处理 2 月闰年/平年
- "月内截断 7 日桶"拆分策略（**非 ISO 周**，禁止使用 `datetime.isocalendar()`）：W1 从 `month_start` 起每 7 天一桶，W5 至 `month_end` 止，每桶含 `label` / `date_range` / `day_count`
- 输出 `/mnt/user-data/outputs/monthly_data.json`
- 返回 `report_period`（含 `week_buckets[]`） / `current.weekly[]` / `current.aggregated` / `current.maintenance`（含 `total_uptime_hours`，由脚本直接计算 `day_count × 24 − total_downtime_minutes / 60`） / `current.alarms` / `current.critical_events` / `current.improvement_tracking` / `compare`（dict by basis）/ `compare_periods`
- 演示数据在 JSON 中标注 `data_source: "demo_fallback"`
- `compare=previous_year_month` 同期数据为空时返回 `compare.previous_year_month: null` 并附带 `compare_warning`
- `improvement_tracking` 演示数据回退时返回 2-3 条样例（含 `done` / `in_progress` / `delayed` 三种状态）

**验收标准**：

- 命令可在 sandbox 中执行
- 无真实 API 时返回演示数据（4-5 周聚合 + 月聚合 + 维修指标 + 告警流水 + 重大事件 + 改进措施）
- 支持 `previous_month` / `previous_year_month` / `none` 任意组合（CSV 形式传入）
- `compare` 字段始终以基准名为 key 的 dict，单基准时其余 key 缺失或 `null`
- 2020-02 / 2024-02（闰年） / 2025-02（平年） / 2026-04（30 天） / 2026-12（含 5 桶） / **2026-01（跨年同期 → `previous_year_month=2025-01`）** 等边界月份 `day_count` 与 `compare_periods` 正确
- "月内截断 7 日桶"边界：W1 / W5 不足 7 天时 `day_count` 正确标注；脚本未使用 ISO 周相关 API（grep 校验：无 `isocalendar` / `IsoYear`）
- 输出 JSON 符合设计文档 §6.1
- 设备 > 50 时 `--aggregate` 路径自动启用，不下钻每台设备周序列
- 演示数据在不同 `--report-month` 输入下输出可复现（同输入同输出）

**依赖**：`/mnt/user-data/outputs/` 可写；`skills/custom/data-analyst/scripts/` 路径存在；周报 Story W1 已落地（参考其 demo 数据 + week_buckets 风格）。

### Story M2（Must）：新增 `monthly_kpi.py` 月 KPI 计算脚本（4 SP）

**目标**：将月度原始数据转换成 GenUI 可直接消费的数据结构，**字段命名严格区分月/周/日口径**，避免用户在日报/周报/月报之间混淆，并支持 MTBF/MTTR 月度专属指标与双对比基准 delta。

**范围**：

- 新增 `skills/custom/data-analyst/scripts/monthly_kpi.py`
- 读取 `/mnt/user-data/outputs/monthly_data.json`
- 输出 `/mnt/user-data/outputs/monthly_kpi.json`
- 生成 `overall_status` / `kpi_summary[]`（每项含 `current_mean` / `current_peak` / `current_trough` / `current_volatility` / `current_in_target_ratio` / `previous_month_mean` / `delta_mom` / `delta_mom_pct` / `direction_mom` / `previous_year_month_mean` / `delta_yoy` / `delta_yoy_pct` / `direction_yoy` / `better_when_higher`）
- 特殊 KPI：`mtbf` 由 `total_uptime_hours / max(total_failures, 1)` 派生（`total_failures == 0` 时输出 `null`）；`mttr` 由 `total_repair_minutes / max(total_failures, 1) / 60` 派生（同保护）；`target_rate`（整月聚合 KPI）由所有具备 `current_in_target_ratio` 的 KPI 简单平均得出
- `weekly_trend_chart`（完整 ECharts option，4-5 周 x 轴，xAxis.data 取自 `report_period.week_buckets[].label`）
- `anomaly_top_n[]`（按设备×级别聚合 Top10）
- `critical_events[]`（透传 + 限制 50 条）
- `improvement_tracking[]`（透传 + 派生 `completion_rate`）
- `monthly_review: string`（多段月度复盘正文，机械生成：异常 TopN 设备 + 持续下行 KPI + 改进项遗留） / `next_month_plan: string[]`（bullet 列表）
- **不输出** `summary_markdown` 字段——完整 Markdown 全文渲染统一由 `export_report.render_monthly_markdown` 在 export 时承担，与日报/周报模式一致

**验收标准**：

- 月均值（按周 `day_count` 加权）/ 峰值 / 低谷 / 波动率计算正确（与设计文档 §4.2 计算口径一致）
- 月环比 `delta_mom_pct` 在 `previous_month_mean=0` 或 `compare.previous_month=null` 时输出 `null`，不抛 ZeroDivisionError
- 月同比 `delta_yoy_pct` 在 `previous_year_month_mean=0` 或 `compare.previous_year_month=null` 时输出 `null`
- 字段命名严格使用 `previous_year_month_mean`（含 `month`），不使用 `previous_year_mean`
- MTBF 公式为 `total_uptime_hours / max(total_failures, 1)`；`total_failures=0` 时输出 `null` 并在 `monthly_review` 中标注"本月零故障，MTBF/MTTR 不适用"
- MTTR 公式为 `total_repair_minutes / max(total_failures, 1) / 60`；同保护逻辑
- 单 KPI `current_in_target_ratio`（"达标天数 / 当月天数"）与整月聚合 KPI `key == "target_rate"`（所有单 KPI 比率的简单平均）字段独立、不混用；KPI 未配置目标值时 `current_in_target_ratio` 输出 `null`
- `weekly_trend_chart.xAxis.data` 为 4-5 个桶 label（如 `"W1: 04-01~04-07"`）
- `anomaly_top_n` 按 `count desc` 排序且限制 Top10
- `critical_events` / `improvement_tracking` 数组形态保留（即使为空），便于 SOUL 判空跳过渲染
- `improvement_tracking[].completion_rate` 派生规则：`done=100`、`closed=100`、`in_progress=60`（演示阶段固定值）、`delayed=30`
- `next_month_plan` 从异常 TopN 设备 + 持续下行 KPI + 未完成改进项中机械生成（不调用 LLM）
- 脚本输出 JSON **不包含** `summary_markdown` 顶层字段（如出现则视为回归失败）
- 输出 JSON 符合设计文档 §6.2
- 与周报 `weekly_kpi.alarm_table` 中 `critical_events` schema 字段兼容（`time` / `equipment` / `level` / `message` + 月报专属 `duration_minutes` / `resolved`）

**依赖**：Story M1 输出 schema 稳定。

### Story M3（Must）：扩展 `export_report.py` 支持月报渲染（2 SP）

**目标**：在不破坏日报/周报现有行为的前提下，给 `export_report.py` 增加月报渲染分支。**关键约束：日报 + 周报现网调用必须零回归**。

**范围**：

- 修改 `skills/custom/data-analyst/scripts/export_report.py`
- `SUPPORTED_REPORT_TYPES` 扩展为 `{"daily", "weekly", "monthly"}`
- 新增常量 `MONTHLY_INPUT_FILENAME = "monthly_kpi.json"`
- `_output_dir(report_type)` 增加 `monthly` 分支：环境变量回退链 `MONTHLY_REPORT_OUTPUT_DIR` → `DAILY_REPORT_OUTPUT_DIR` → `DEFAULT_OUTPUT_DIR`
- `load_payload(path, report_type)` 增加 monthly 分支：默认文件名 `monthly_kpi.json`
- `write_report(payload, fmt, ..., report_type)` 增加 monthly 分支：文件名 `monthly_report.{md,pdf}`
- 新增函数 `render_monthly_markdown(payload, thread_id)` 为 **唯一渲染入口**：按 `monthly_kpi.json` 结构化字段拼装 8 节 Markdown（月度总览 / 月 KPI 表含 MTBF/MTTR/达标率 / 周趋势 SVG / 异常 TopN / 重大事件回顾 / 月环比+同比 / 改进措施跟踪 / 下月计划）。**不再设计"优先用 summary_markdown / 缺失时兜底拼装"双轨**——脚本不输出 summary_markdown，渲染逻辑集中在 export 层。
- PDF 路径沿用日报/周报 weasyprint 模板，仅替换 Markdown 渲染源
- 周趋势图 SVG 嵌入复用现有 `trend_chart_to_svg(payload.weekly_trend_chart)`
- CLI 入口扩展 `--report-type {daily,weekly,monthly}`（默认 `daily`）

**验收标准**：

- 日报现有调用方（不传 `report_type`）行为 100% 不变（回归测试通过）
- 周报现有调用方（`report_type="weekly"`）行为 100% 不变（回归测试通过）
- 月报路径：`write_report(payload, "md", report_type="monthly")` 生成 `monthly_report.md`
- `render_monthly_markdown` 是唯一渲染入口，输出包含 8 节标题（月度总览 / 月 KPI / 周趋势 / 异常 TopN / 重大事件 / 月环比+同比 / 改进措施跟踪 / 下月计划），各小节内容与 `monthly_kpi.json` 字段一致
- `render_monthly_markdown` 行为对 `payload.summary_markdown` 字段不敏感（即使该字段存在也忽略；用 fixture 注入 `summary_markdown="STALE"` 验证输出不含该字符串）
- PDF 路径：weasyprint 不可用时抛 `ImportError`（由 SOUL.md 捕获降级），不静默 fallback 到 Markdown
- 月报 Markdown 中"月 KPI"小节尾部包含"口径说明"引用块（`>` Markdown 引用块），明确"月均值按周 day_count 加权平均"定义，避免与周报"7 日简单平均"和日报"单日值"字段混淆（不另起独立章节，保持 8 节结构）
- `improvement_tracking` 为空数组时 Markdown 跳过该小节（不渲染空表）
- `critical_events` 为空数组时同上

**依赖**：Story M2 输出结构稳定；周报 Story W3 已合入主干（避免合并冲突）。

### Story M4（Must）：改写 `ai-report--monthly` SOUL.md 实现 4 轮表单（3 SP）

**目标**：让月报智能体遵循周报已验证的 "render_ui 表单 → ui_interaction → 校验 → 下一轮 / 生成" 模式，结构同构但 callback_id 与字段集不同，并处理 `compare_with` multi-select 的互斥语义。

**范围**：

- 重写 `agents/builtin/ai-report--monthly/SOUL.md`
- 加入 MCP / Skill / http_connector / 演示回退优先级链
- 加入 4 个 callback：`monthly-report-scope` / `monthly-report-equipment` / `monthly-report-confirm` / `monthly-report-export`（备用）
- 输入白名单校验：
  - `report_month` 正则 `^\d{4}-\d{2}$` + `strptime` 解析 + 年份/月份范围
  - `equipment_type` 枚举
  - `compare_with[i]` 枚举 + **互斥规则**：含 `none` 时长度必须为 1，否则渲染 markdown 提示并重新渲染 Round 1
  - `equipment_ids[i]` 正则
  - `kpi_keys[i]` 必须在 `available_kpis ∪ {mtbf, mttr, target_rate}` 集合内
- KPI 选择表单固定项：始终追加 `kpi_mtbf` / `kpi_mttr` / `kpi_target_rate` 并在 `default_values` 中标记为已勾选；同时把 `list_equipment.available_kpis[].is_primary == true` 的 KPI 也加入 `default_values`（如该元数据缺失，则默认勾选回退为只勾上述 3 项固定项）。三个固定项是 checkbox 而非只读，用户有权取消。
- 设备数 ≤ 10 走 `--equipment`，> 10 同区域走 `--type/--scope area`，> 10 跨区域走 `--equipment --aggregate`（与日报/周报策略一致）
- `--compare` 拼装为 CSV（如 `previous_month,previous_year_month`），`none` 时传空串
- Round 3 自动写 `.md` + 尝试写 `.pdf`，调用 `present_files` 仅暴露 `monthly_report.md` / `monthly_report.pdf`
- **严禁** 对 `monthly_data.json` / `monthly_kpi.json` 调用 `present_files`
- 渲染契约：多 `card`（trend.value 显示环比，subtitle 显示同比）+ 1 `echart`（周趋势）+ 1 `table`（anomaly_top_n）+ 条件渲染 1 `table`（critical_events 非空）+ 条件渲染 1 `table`（improvement_tracking 非空）+ 1 `markdown`（content 由 SOUL 用 `overall_status.summary` + `monthly_review` + `next_month_plan[]` 三个结构化字段拼装，**不读取 `summary_markdown`**；完整 8 节长文在 artifact 文件中）
- 演示数据回退场景下 Markdown 顶部插入红色 banner 提示
- 历史回溯规则：只用"当前消息之前最近一次"匹配回调，不复用更早轮次参数

**验收标准**：

- 用户进入月报智能体后，先看到 Round 1 月报参数表单
- 表单包含 `report_month`（text + pattern）/ `equipment_type`（select）/ `compare_with`（multi-select：previous_month / previous_year_month / none）
- 提交 Round 1 后渲染 Round 1.5 设备多选，按 `area` 分组，默认全选
- 提交 Round 1.5 后渲染 Round 2 KPI 多选，Round 2 表单 `default_values` 顶层 dict 注入：`kpi_mtbf` / `kpi_mttr` / `kpi_target_rate` 已勾选，同时勾选 `available_kpis` 中标注为"主指标"的 KPI（如 `kpi_runtime_rate` / `kpi_alarm_count`）；三个固定项是 checkbox 不是只读，用户可取消
- `compare_with == []`（用户清空 multi-select）视同 `["none"]`（不对比），并在 markdown 中提示"未选择对比基准，本次报告无环比/同比数据"
- 提交 Round 2 后调用 `query_monthly.py` + `monthly_kpi.py` 并按 §3.2 渲染契约渲染多个 Block
- SOUL.md 中 `ui_interaction` 处理段落明确引用 `payload.<field>`（不是 `values`）
- callback_id 严格使用 `monthly-report-*` 前缀，不与日报 `daily-report-*` / 周报 `weekly-report-*` 冲突
- `compare_with` 含 `none` 但长度 > 1 时渲染 markdown 提示并重新渲染 Round 1（不执行脚本）
- 任一输入校验失败渲染 markdown 提示并停止，不执行脚本
- 同一线程多次生成时回溯历史只取最近一次 `monthly-report-*` 回调
- 无后端/前端代码变更

**依赖**：Story M1、M2、M3 已落地；GenUI `form` / `card` / `echart` / `table` / `markdown` 已注册；`data-analyst` skill 启用。

### Story M5（Must）：GenUI 月报渲染联调 + Markdown 导出闭环（2 SP）

**目标**：验证 SOUL.md 能基于脚本输出渲染完整月报页面并完成下载链路；覆盖关键边界场景。

**范围**：

- 端到端联调：参数表单 → 设备表单 → KPI 表单 → query_monthly → monthly_kpi → GenUI Block → export_report → present_files
- 验证 weasyprint 可用 / 不可用两种路径下载链接显示正确
- 验证设备 ≤ 10 / 跨区域 > 10 / 单区域全量 > 10 三种设备选择路径
- 验证 `compare_with` 单基准（`previous_month`） / 双基准（`previous_month + previous_year_month`）/ `none` 三种对比路径
- 验证 `compare=previous_year_month` 数据缺失场景：`card.subtitle` 显示 `同比 —`，不显示 `+NaN%`
- 验证 `critical_events` 为空 / 非空两种渲染路径（空时跳过 table）
- 验证 `improvement_tracking` 为空 / 非空两种渲染路径（空时跳过 table）
- 验证 `total_failures=0` 场景：MTBF/MTTR card 显示 `—` 且 markdown 标注"本月零故障"
- 验证闰年 2 月（`report_month=2024-02`）/ 平年 2 月（`2025-02`）/ 31 天月（`2026-12`）/ **跨年同期（`report_month=2026-01` → `compare_periods.previous_year_month = {start: 2025-01-01, end: 2025-01-31}`）** 边界
- 验证用户在 Round 2 取消默认勾选的 `kpi_mtbf` 后，生成报告时 `kpi_summary` 不含 mtbf 项、MTBF card 不渲染、Markdown "MTBF/MTTR" 小节自动跳过
- 验证 `compare_with == []` 视同 `none` 路径（card.trend / subtitle 都隐藏，markdown 含提示）
- 验证演示数据 banner 在回退场景下出现
- 验证 artifact URL `/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/monthly_report.md` 可下载

**验收标准**：

- 完整链路可在 sandbox 内跑通，无 GenUI schema 错误
- 多个 `card` 渲染独立卡片，`trend.value` 显示环比百分比（`+3.2%` 格式），`subtitle` 显示同比（`同比 +1.1%`）
- `echart` 渲染 4-5 周趋势曲线（双 Y 轴，运行率折线 + 告警柱状），W1/W5 不足 7 天时 label 含日期范围
- 三张 `table`（anomaly_top_n / critical_events / improvement_tracking）按数据非空状态条件渲染
- `markdown` Block 内容由 SOUL 用 `overall_status.summary` + `monthly_review` + `next_month_plan[]` 三个结构化字段拼装；完整 8 节月报正文位于 artifact 文件 `monthly_report.md`（由 `render_monthly_markdown` 渲染），SOUL 不在对话流中重复渲染长文
- Markdown 文件位于 `/mnt/user-data/outputs/monthly_report.md`，前端可下载
- weasyprint 不可用时显示"PDF 不可用（weasyprint 未安装）"，不报错
- 多次生成场景下，回溯历史只取最近一次回调参数（用 2 次连续运行验证）
- `compare_with=[none]` 时 `card.trend` 与 `card.subtitle` 都隐藏（不渲染 `—`）

**依赖**：Story M1-M4 全部完成。

### Story M6（Should）：与 DSL 自定义模板平台脚本注册联调（2 SP）

**目标**：确保本 Sprint 新增的脚本能被未来 `monthly-equipment` DSL builtin 模板直接复用，避免脚本契约在 DSL 接入时返工。

**范围**：

- 在 `skills/custom/data-analyst/report_scripts.yaml` 中注册 `query_monthly` 与 `monthly_kpi`（追加到周报已建立的 registry 文件）
- 声明 `args_schema`、`output_files`、`timeout_seconds`、`max_output_bytes`
- 与自定义模板设计 [§13.4](./2026-05-14-ai-report-custom-template-design.md) 的 schema 格式严格对齐
- 校验脚本 CLI 参数命名与 args_schema 字段名一一对应
- **alias 映射**：在 args_schema 中声明 `compare_with` 支持 `mom`/`yoy` 短名作为 DSL 别名，脚本侧统一接收长名 `previous_month`/`previous_year_month`（由 DSL 平台在加载时映射；脚本本身仍只识别长名）
- 与自定义模板 Phase 5（weekly/monthly DSL builtin）方负责人对齐：当 registry 加载实现就位时，本 Sprint 产物可零修改被消费

**验收标准**：

- `report_scripts.yaml` 通过 YAML 解析
- 字段命名与 `monthly-equipment` DSL 草案 §13.4 一致（`report_month` / `equipment_type` / `compare_with` / `equipment_ids` / `kpi_keys`）
- `compare_with` 枚举值定义为长名（`previous_month`/`previous_year_month`/`none`），alias 注释明确说明 `mom`/`yoy` 短名由 DSL 平台映射
- `query_monthly.output_files` 与 `monthly_kpi.output_files` 路径占位符使用 `{run_output_dir}` 而非硬编码 `/mnt/user-data/outputs/`（脚本本身需要在收到该参数时优先使用，否则回退到默认目录）
- 周报既有 registry 项零回归（YAML 解析通过 + 字段未被覆盖）
- **W6 未完成时的回退**：如周报 Story W6 尚未交付（`report_scripts.yaml` 不存在），M6 范围自动扩大为创建初始 registry 文件，并在 PR 描述中标注此扩大范围；如此扩大导致 M6 SP 超出预算，将 M6 整体降级为下个 Sprint 跟进
- 与自定义模板 Phase 5 owner 完成一次脚本契约 review，记录在 PR 描述中

**依赖**：周报 Story W6 已完成（registry 文件已建立）；自定义模板平台 Phase 5 设计稳定。

### Story M7（Should）：单元测试与最小回归验证（2 SP）

**目标**：确保新增 Skill 脚本稳定，且日报 + 周报回归测试不破。

**范围**：

- 为 `query_monthly.py` 增加测试：
  - 参数解析（含 `--compare` CSV 多基准）
  - 闰年/平年 2 月 `day_count` 正确（2024-02=29，2025-02=28）
  - **跨年同期**：`report_month=2026-01` 时 `compare_periods.previous_year_month` 正确回退到 `2025-01`；闰年跨越场景 `report_month=2024-03` 时 `previous_month` 为 `2024-02-29`，不报错
  - "月内截断 7 日桶" W1/W5 不足 7 天时 `day_count` 正确；脚本未使用 `isocalendar()`（静态检查）
  - `compare` 字段为 dict 形态（含 `previous_month` / `previous_year_month` 任意子集）
  - `previous_year_month` 缺失分支返回 `null` + `compare_warning`
  - `maintenance.total_uptime_hours` 等于 `day_count × 24 − total_downtime_minutes / 60`
  - `improvement_tracking` 演示数据回退含 3 种状态
- 为 `monthly_kpi.py` 增加测试：
  - 月均值按周 `day_count` 加权计算正确
  - `delta_mom_pct` / `delta_yoy_pct` 在零分母下输出 `null`
  - 字段命名 `previous_year_month_mean`（不是 `previous_year_mean`）
  - MTBF 公式 `total_uptime_hours / max(total_failures, 1)`；`total_failures=0` 时输出 `null` 并 `monthly_review` 含"本月零故障"
  - MTTR 公式 `total_repair_minutes / max(total_failures, 1) / 60`；同保护
  - 单 KPI `current_in_target_ratio` 与整月聚合 KPI `target_rate` 字段独立、不混用
  - `weekly_trend_chart.xAxis.data` 长度等于 `week_buckets` 长度（4 或 5）
  - `anomaly_top_n` 排序与限长（Top10）
  - `critical_events` 限长（50 条）
  - `improvement_tracking[].completion_rate` 派生规则正确
  - 输出 JSON **不包含** `summary_markdown` 顶层字段（断言 `"summary_markdown" not in payload`）
- 为 `export_report.py` 增加测试：
  - `report_type` 未传（默认 `daily`） / `report_type="weekly"` / `report_type="monthly"` 三路径文件名正确
  - `render_monthly_markdown` 输出包含 8 节标题
  - `render_monthly_markdown` 对 `payload["summary_markdown"] = "STALE"` 注入不敏感（输出不含该字符串，证明渲染只读结构化字段）
  - 日报 + 周报回归 fixture 不变
- 数据契约测试：`query_monthly.py` 输出可被 `monthly_kpi.py` 直接消费
- 路径校验：所有输出在 `/mnt/user-data/outputs/`（或 `MONTHLY_REPORT_OUTPUT_DIR` 注入时使用该路径）
- 日报 + 周报回归：`query_daily.py` / `daily_kpi.py` / `query_weekly.py` / `weekly_kpi.py` / `export_report.py` 既有行为不变

**验收标准**：

- Python 测试通过（`pytest skills/custom/data-analyst/`）
- 关键脚本可单独执行（不依赖 SOUL.md）
- `query_monthly.py` 输出 JSON 符合设计文档 §6.1
- `monthly_kpi.py` 输出 JSON 符合设计文档 §6.2
- 契约测试覆盖 query_monthly → monthly_kpi → export_report 最小链路
- 日报 + 周报回归测试 0 失败
- 无硬编码真实凭据，错误输出为结构化 JSON 或明确 stderr

**依赖**：Story M1、M2、M3 完成。

---

## 4. 不建议本 Sprint 承诺的内容

### 真实月度数据接入

**原因**：与日报/周报相同，`data_catalog` MCP 未注册，`http_connector` 月聚合接口形态未定，且月维修工单与改进措施跟踪通常跨多个业务系统（CMMS / EAM / 工单），集成成本高。

**建议**：本 Sprint 仅保留接口形状和演示回退；下个 Sprint 与日报/周报真实数据接入并轨推进；改进措施跟踪需独立立项与 CMMS 对接。

### PDF 渲染样式调优（含周趋势 SVG 嵌入）

**原因**：日报/周报 Sprint 已确认 weasyprint 在当前 sandbox 不可用，月报沿用相同结论；月报增加周趋势 + 3 张 table + 改进跟踪后 PDF 排版可能需要额外样式调优。

**建议**：本 Sprint 仅完成代码路径接入（与日报/周报一致的 try/except 降级），不承诺 PDF 完整样式；待 sandbox 镜像决策落地后统一处理。

### 月报/周报/日报抽公共 renderer

**原因**：三种报告章节差异（小时 vs 日 vs 周维度、单值 KPI vs 周聚合 vs 月聚合+MTBF/MTTR、单告警表 vs TopN+流水 vs TopN+重大事件+改进跟踪）较大，过早抽象会放大返工成本。

**建议**：等月报 MVP 稳定后再与 DSL 平台 `render_markdown_generic` 合流（自定义模板平台 §12.2）；本 Sprint 优先保证三种报告独立可用。

### 改进措施跟踪闭环（创建 / 更新 / 完成）

**原因**：超出 SOUL + skill 脚本能力边界，需要新增前端编辑组件 + 后端持久化路由，违反"零前端/后端改动"原则。

**建议**：放到独立"改进措施管理"立项；本 Sprint 仅展示上月遗留改进项的跟踪结果（只读视图）。

### 月报历史归档与跨月对比 UI

**原因**：超出 SOUL + skill 脚本能力边界，需要新增前端列表组件。

**建议**：放到自定义模板平台 Phase 5（报告历史 UI）统一交付。

### 趋势分析报告（季度/年度长期趋势）

**原因**：趋势分析报告（[ai-report--trend](../../agents/builtin/ai-report--trend/SOUL.md)）是独立产品形态，时间维度与聚合粒度均不同；月报的 `--include-daily` 标志已为未来趋势分析预留下钻能力。

**建议**：趋势分析报告独立立项；月报 MVP 不承诺。

---

## 5. Sprint Sequencing

```text
Day 1
- 新增 query_monthly.py 演示数据脚本（含闰年处理 + 月内截断 7 日桶拆分 + 跨年同期 + 双对比基准 CSV 解析）
- 写脚本级单元测试：闰年/平年 2 月 / 跨年同期 2026-01 / W1/W5 截断 / compare dict 形态（Story M1 + M7 第一部分）

Day 2
- 新增 monthly_kpi.py 周加权月均值 + MTBF/MTTR + 双 delta + weekly_trend_chart
- 实现 improvement_tracking completion_rate 派生 + monthly_review/next_month_plan 机械生成；**不输出 summary_markdown**
- 写脚本级单元测试（Story M2 + M7 第二部分）

Day 3
- 扩展 export_report.py（SUPPORTED_REPORT_TYPES + render_monthly_markdown 唯一渲染入口 + monthly 文件路径）
- 日报 + 周报回归测试（Story M3 + M7 回归部分）
- 改写 ai-report--monthly/SOUL.md 4 轮表单骨架（Story M4 上半）

Day 4
- 完成 SOUL.md 输入校验（含 compare_with multi-select 互斥规则 + 空数组视同 none）、设备数阈值分支、Round 2 default_values 默认勾选、present_files 闭环（Story M4 下半）
- GenUI 联调：跑通完整链路（Story M5 主体）

Day 5
- 边界场景验证：闰年 2 月 / 跨年同期 2026-01 / total_failures=0 / compare=previous_year_month 缺失 / 用户取消默认勾选 MTBF / critical_events 与 improvement_tracking 空数组跳过 / weasyprint 不可用 / 多次生成回溯（Story M5 收尾）
- 注册 report_scripts.yaml 含 mom/yoy alias 注释（Story M6；W6 未交付时扩大范围创建初始文件）
- 整理交付说明 + 与自定义模板 Phase 5 owner 对齐脚本契约
```

---

## 6. Sprint Summary

```text
Sprint Goal:
完成 AI 月报智能体 MVP，使其通过 4 轮 GenUI 表单收集参数（含环比 + 同比 multi-select 双基准），
基于 Skill 脚本生成月报含 MTBF/MTTR/达标率/重大事件/改进跟踪/下月计划，
支持 Markdown 自动导出，并为未来 monthly-equipment DSL builtin 模板保留无缝接入路径。

Duration:
1 周

Team Capacity:
5 人天，预留 25% 缓冲后约可承诺 3.75 人天 / 15 SP（Must）

Must Stories（承诺，共 15 SP）:
M1. 新增 query_monthly.py 月度数据查询脚本（含闰年 + 月内截断 7 日桶 + 跨年同期 + 双基准） — 4 SP
M2. 新增 monthly_kpi.py 月 KPI + MTBF/MTTR + 周趋势 + 改进跟踪 + monthly_review/next_month_plan（不输出 summary_markdown） — 4 SP
M3. 扩展 export_report.py 支持月报渲染（日报 + 周报零回归） — 2 SP
M4. 改写 ai-report--monthly SOUL.md 实现 4 轮表单（含 compare_with 互斥校验） — 3 SP
M5. GenUI 月报渲染联调 + Markdown 导出闭环 — 2 SP

Should / Stretch Stories（容量允许时推进，共 4 SP）:
M6. 与 DSL 自定义模板平台脚本注册联调（含 mom/yoy alias） — 2 SP
M7. 单元测试与最小回归验证（日报 + 周报零回归） — 2 SP

不承诺范围:
- 真实月度数据接入（依赖 MCP / HTTP / CMMS API 定稿）
- PDF 渲染样式调优（依赖 sandbox 镜像决策）
- 日/周/月报抽公共 renderer（待 DSL generic renderer 合流）
- 改进措施跟踪闭环（独立"改进措施管理"立项）
- 月报历史归档与跨月对比 UI（自定义模板 Phase 5 范围）
- 趋势分析报告（独立 ai-report--trend 立项）
```
