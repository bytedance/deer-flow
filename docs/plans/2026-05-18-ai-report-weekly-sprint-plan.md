# AI 周报智能体 Sprint 实施计划

> **来源设计文档**：[AI 周报智能体功能设计文档](./2026-05-18-ai-report-weekly-design.md)
> **对标计划**：与 [AI 日报智能体 Sprint 实施计划](./2026-05-13-ai-report-daily-sprint-plan.md) 结构对齐，仅在周维度差异点（7 日聚合、周环比、TopN、对日报脚本的向后兼容）上做调整。
> **范围**：基于设计文档拆分出的执行计划,覆盖 Sprint 目标、故事拆分、依赖、验收标准、风险与排期。

---

## 1. Sprint Goal

在不新增后端路由、不新增前端组件、不破坏日报现有行为的前提下，完成 `ai-report--weekly` 的周报生成 MVP：用户可通过 4 轮 GenUI 表单选择周开始日期、设备类型、对比基准、设备列表与 KPI 指标，基于演示/Skill 数据生成周 KPI、日趋势图、异常 TopN、告警流水、周复盘与下周关注，并完成 Markdown 自动导出闭环（PDF 沿用日报 weasyprint 路径，不可用时优雅降级）。

## 2. Sprint 假设

| 项 | 假设 |
| ---- | ------ |
| Sprint 周期 | 1 周 |
| 团队配置 | 1 名全栈/Agent 工程师（与日报同人为佳，便于复用脚本约定） |
| 可用容量 | 5 人天 |
| 缓冲 | 20%（约 1 人天） |
| 可承诺容量 | 4 人天 |
| Must 承诺范围 | Stories W1-W5：query_weekly + weekly_kpi + export_report 扩展 + SOUL.md 4 轮表单 + 端到端联调 |
| Should / Stretch 范围 | Story W6 DSL 脚本注册联调 + Story W7 单元测试与最小回归 |
| 本 Sprint 目标 | 周报 MVP 端到端跑通 Markdown 导出；不强行接真实数据源；不重做 PDF 路径，沿用日报已验证降级方案 |
| 前置依赖 | 日报 MVP（Story 1-5）已合入主干，`export_report.py` 现网可运行 |

> 真实数据接入与 PDF 依赖问题已在日报 Sprint 6 验证过结论，本 Sprint **不再重复验证**；周报直接复用日报的 weasyprint try/except 降级模式。
> "去年同期" 对比基准依赖历史数据可用性，本 Sprint 仅完成接口与降级路径，不承诺生产数据可用性。

---

## 3. Stories

> **承诺口径**：Must Stories（W1-W5，共 14 SP）是本 Sprint 的交付承诺；Should Stories（W6-W7，共 4 SP）在 Must 完成后推进，不阻塞 MVP 验收。

### Story W1（Must）：新增 `query_weekly.py` 7 天数据查询脚本（3 SP）

**目标**：提供稳定的 7 日演示数据源，让周报流程在真实数据 API 未确定前可端到端跑通，且与日报演示数据脚本风格一致。

**范围**：

- 新增 `skills/custom/data-analyst/scripts/query_weekly.py`
- 支持 `--week-start`、`--type`、`--equipment`、`--scope`、`--scope-filter`、`--kpis`、`--compare`、`--aggregate`
- 输出 `/mnt/user-data/outputs/weekly_data.json`
- 返回 `report_period` / `current.daily[7]` / `current.aggregated` / `current.alarms` / `compare` 数据结构
- 演示数据在 JSON 中标注 `data_source: "demo_fallback"`
- `week_start` 非周一时输出 `week_start_warning` 字段
- `compare=previous_year` 同期数据为空时返回 `compare: null` 并附带 `compare_warning`

**验收标准**：

- 命令可在 sandbox 中执行
- 无真实 API 时返回演示数据（7 日日序数据 + 聚合 + 告警流水）
- 支持 `previous_week` / `previous_year` / `none` 三种对比基准路径
- 输出 JSON 符合设计文档 §6.1
- 设备 > 50 时 `--aggregate` 路径自动启用，不下钻每台设备日序列
- 演示数据在不同 `--week-start` 输入下输出可复现（同输入同输出）

**依赖**：`/mnt/user-data/outputs/` 可写；`skills/custom/data-analyst/scripts/` 路径存在；日报 Story 2 已落地（参考其 demo 数据风格）。

### Story W2（Must）：新增 `weekly_kpi.py` 周 KPI 计算脚本（3 SP）

**目标**：将 7 天原始数据转换成 GenUI 可直接消费的数据结构，**字段命名严格区分周/日口径**，避免用户在日报/周报之间混淆。

**范围**：

- 新增 `skills/custom/data-analyst/scripts/weekly_kpi.py`
- 读取 `/mnt/user-data/outputs/weekly_data.json`
- 输出 `/mnt/user-data/outputs/weekly_kpi.json`
- 生成 `overall_status` / `kpi_summary[]`（含 `current_mean` / `current_peak` / `current_trough` / `current_volatility` / `previous_mean` / `delta_mean` / `delta_pct` / `direction`） / `daily_trend_chart`（完整 ECharts option，7 日 x 轴） / `anomaly_top_n[]`（按设备×级别聚合 Top10） / `alarm_table[]` / `next_week_focus[]`

**验收标准**：

- 周均值 / 峰值 / 低谷 / 波动率计算正确（与设计文档 §4.2 计算口径一致）
- 周环比 `delta_pct` 在 `previous_mean=0` 或 `compare=null` 时输出 `null`，不抛 ZeroDivisionError
- `daily_trend_chart.xAxis.data` 为周一-周日 7 个 label（含 `MM-DD 周X` 格式）
- `anomaly_top_n` 按 `count desc` 排序且限制 Top10
- `next_week_focus` 从异常 TopN 设备 + 持续下行 KPI 中机械生成（不调用 LLM）
- 输出 JSON 符合设计文档 §6.2
- 与日报 `daily_kpi.alarm_table` schema 字段一致（`time` / `equipment` / `level` / `message`）

**依赖**：Story W1 输出 schema 稳定。

### Story W3（Must）：扩展 `export_report.py` 支持周报渲染（2 SP）

**目标**：在不破坏日报现有行为的前提下，给 `export_report.py` 增加周报渲染分支。**关键约束：日报现网调用必须零回归**。

**范围**：

- 修改 `skills/custom/data-analyst/scripts/export_report.py`
- 新增函数 `render_weekly_markdown(payload, thread_id)`，输出 7 节 Markdown：本周概览 / 周 KPI 表 / 日趋势图（用 ECharts option 描述/SVG） / 异常 TopN / 告警流水 / 周环比 / 下周关注
- 修改 `write_report(payload, format, report_type="daily")` 增加 `report_type` 关键字参数（默认 `daily`，向后兼容）
- `report_type="weekly"` 时输出文件名 `weekly_report.md` / `weekly_report.pdf`，输出目录仍为 `/mnt/user-data/outputs/`
- PDF 路径沿用日报 weasyprint 模板，仅替换 Markdown 渲染源
- CLI 入口扩展 `--report-type {daily,weekly}`（默认 `daily`）

**验收标准**：

- 日报现有调用方（不传 `report_type`）行为 100% 不变（回归测试通过）
- 周报路径：`write_report(payload, "md", report_type="weekly")` 生成 `weekly_report.md`
- `render_weekly_markdown` 输出包含 7 节标题且内容与 `weekly_kpi.json` 一致
- PDF 路径：weasyprint 不可用时抛 `ImportError`（由 SOUL.md 捕获降级），不静默 fallback 到 Markdown
- 周报 Markdown 中"口径说明"小节明确周均值/周峰值定义，避免与日报字段混淆

**依赖**：Story W2 输出结构稳定；日报 Story 5 已合入主干（避免合并冲突）。

### Story W4（Must）：改写 `ai-report--weekly` SOUL.md 实现 4 轮表单（3 SP)

**目标**：让周报智能体遵循日报已验证的 "render_ui 表单 → ui_interaction → 校验 → 下一轮 / 生成" 模式，结构同构但 callback_id 与字段集不同。

**范围**：

- 重写 `agents/builtin/ai-report--weekly/SOUL.md`
- 加入 MCP / Skill / http_connector / 演示回退优先级链
- 加入 4 个 callback：`weekly-report-scope` / `weekly-report-equipment` / `weekly-report-confirm` / `weekly-report-export`（备用）
- 输入白名单校验：`week_start` 正则 + 日期解析 / `equipment_type` 枚举 / `compare_with` 枚举 / `equipment_ids[i]` 正则 / `kpi_keys[i]` 必须在 `available_kpis` 集合内
- 设备数 ≤ 10 走 `--equipment`，> 10 同区域走 `--type/--scope area`，> 10 跨区域走 `--equipment --aggregate`（与日报策略一致）
- Round 3 自动写 `.md` + 尝试写 `.pdf`，调用 `present_files` 仅暴露 `weekly_report.md` / `weekly_report.pdf`
- **严禁** 对 `weekly_data.json` / `weekly_kpi.json` 调用 `present_files`
- 演示数据回退场景下 Markdown 顶部插入红色 banner 提示
- 历史回溯规则：只用"当前消息之前最近一次"匹配回调，不复用更早轮次参数

**验收标准**：

- 用户进入周报智能体后，先看到 Round 1 周报参数表单
- 表单包含 `week_start`（date）/ `equipment_type`（select）/ `compare_with`（select：previous_week / previous_year / none）
- 提交 Round 1 后渲染 Round 1.5 设备多选，按 `area` 分组，默认全选
- 提交 Round 1.5 后渲染 Round 2 KPI 多选
- 提交 Round 2 后调用 `query_weekly.py` + `weekly_kpi.py` 并渲染多 `card` / 1 `echart` / 2 `table` / 1 `markdown` Block
- SOUL.md 中 `ui_interaction` 处理段落明确引用 `payload.<field>`（不是 `values`）
- callback_id 严格使用 `weekly-report-*` 前缀，不与日报 `daily-report-*` 冲突
- 任一输入校验失败渲染 markdown 提示并停止，不执行脚本
- 无后端/前端代码变更

**依赖**：Story W1、W2、W3 已落地；GenUI `form` / `card` / `echart` / `table` / `markdown` 已注册；`data-analyst` skill 启用。

### Story W5（Must）：GenUI 周报渲染联调 + Markdown 导出闭环（3 SP）

**目标**：验证 SOUL.md 能基于脚本输出渲染完整周报页面并完成下载链路；覆盖关键边界场景。

**范围**：

- 端到端联调：参数表单 → 设备表单 → KPI 表单 → query_weekly → weekly_kpi → GenUI Block → export_report → present_files
- 验证 weasyprint 可用 / 不可用两种路径下载链接显示正确
- 验证设备 ≤ 10 / 跨区域 > 10 / 单区域全量 > 10 三种设备选择路径
- 验证 `compare=previous_week` 数据齐全 / `compare=previous_year` 数据缺失两种对比路径
- 验证演示数据 banner 在回退场景下出现
- 验证 artifact URL `/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/weekly_report.md` 可下载

**验收标准**：

- 完整链路可在 sandbox 内跑通，无 GenUI schema 错误
- 多个 `card` 渲染独立卡片，`trend.value` 显示周环比百分比（`+3.2%` 格式）
- `echart` 渲染 7 日趋势曲线（双 Y 轴，运行率折线 + 告警柱状）
- 两张 `table` 分别渲染异常 TopN 和告警流水
- `markdown` 渲染周复盘 + 下周关注（来自 `next_week_focus`）
- Markdown 文件位于 `/mnt/user-data/outputs/weekly_report.md`，前端可下载
- weasyprint 不可用时显示"PDF 不可用（weasyprint 未安装）"，不报错
- `compare=previous_year` 同期数据缺失时 `card.trend` 显示 `—`，不显示 `+NaN%`
- 多次生成场景下，回溯历史只取最近一次回调参数（用 2 次连续运行验证）

**依赖**：Story W1-W4 全部完成。

### Story W6（Should）：与 DSL 自定义模板平台脚本注册联调（2 SP）

**目标**：确保本 Sprint 新增的脚本能被未来 `weekly-equipment` DSL builtin 模板直接复用，避免脚本契约在 DSL 接入时返工。

**范围**：

- 在 `skills/custom/data-analyst/report_scripts.yaml` 中注册 `query_weekly` 与 `weekly_kpi`（如该文件不存在则创建初始版本）
- 声明 `args_schema`、`output_files`、`timeout_seconds`、`max_output_bytes`
- 与自定义模板设计 [§9.1.1](./2026-05-14-ai-report-custom-template-design.md) 的 schema 格式严格对齐
- 校验脚本 CLI 参数命名与 args_schema 字段名一一对应
- 与自定义模板 Phase 3（Script Registry 加载逻辑）方负责人对齐：当 registry 加载实现就位时，本 Sprint 产物可零修改被消费

**验收标准**：

- `report_scripts.yaml` 通过 YAML 解析
- 字段命名与 `weekly-equipment` DSL 草案 §13.3 一致（`week_start` / `equipment_type` / `compare_with` / `equipment_ids` / `kpi_keys`）
- `query_weekly.output_files` 与 `weekly_kpi.output_files` 路径占位符使用 `{run_output_dir}` 而非硬编码 `/mnt/user-data/outputs/`（脚本本身需要在收到该参数时优先使用，否则回退到默认目录）
- 日报脚本若需要同步补 registry 项，**不在本 Story 范围**（避免扩散）；只保证周报新增脚本可注册
- 与自定义模板 Phase 3 owner 完成一次脚本契约 review，记录在 PR 描述中

**依赖**：自定义模板平台 Phase 3 Script Registry 设计稳定；`skills/custom/data-analyst/` 目录可写。

### Story W7（Should）：单元测试与最小回归验证（2 SP）

**目标**：确保新增 Skill 脚本稳定，且日报回归测试不破。

**范围**：

- 为 `query_weekly.py` 增加测试：参数解析 / 演示数据 7 日完整性 / `previous_year` 缺失分支 / `week_start_warning` 触发条件
- 为 `weekly_kpi.py` 增加测试：周均值/峰值/低谷/波动率计算 / `delta_pct` 在零分母下输出 `null` / `anomaly_top_n` 排序与限长 / `next_week_focus` 非空
- 为 `export_report.py` 增加测试：`report_type="daily"` 默认行为回归 / `report_type="weekly"` 输出文件名 / `render_weekly_markdown` 7 节标题存在
- 数据契约测试：`query_weekly.py` 输出可被 `weekly_kpi.py` 直接消费
- 路径校验：所有输出在 `/mnt/user-data/outputs/`
- 日报回归：`query_daily.py` / `daily_kpi.py` / `export_report.py`（不传 `report_type`）行为不变

**验收标准**：

- Python 测试通过（`pytest skills/custom/data-analyst/`）
- 关键脚本可单独执行（不依赖 SOUL.md）
- `query_weekly.py` 输出 JSON 符合设计文档 §6.1
- `weekly_kpi.py` 输出 JSON 符合设计文档 §6.2
- 契约测试覆盖 query_weekly → weekly_kpi → export_report 最小链路
- 日报回归测试 0 失败
- 无硬编码真实凭据，错误输出为结构化 JSON 或明确 stderr

**依赖**：Story W1、W2、W3 完成。

---

## 4. 不建议本 Sprint 承诺的内容

### 真实周数据接入

**原因**：与日报相同，`data_catalog` MCP 未注册，`http_connector` 周聚合接口形态未定，且周数据通常涉及跨日 join，复杂度高于日报。

**建议**：本 Sprint 仅保留接口形状和演示回退；下个 Sprint 与日报真实数据接入并轨推进。

### PDF 渲染样式调优

**原因**：日报 Sprint 已确认 weasyprint / pandoc 等依赖在当前 sandbox 不可用，周报沿用相同结论；周报增加日趋势图后 PDF 排版可能需要额外样式调优。

**建议**：本 Sprint 仅完成代码路径接入（与日报一致的 try/except 降级），不承诺 PDF 完整样式；待 sandbox 镜像决策落地后统一处理。

### 周报与日报章节结构抽公共 renderer

**原因**：周报与日报章节差异（小时 vs 日维度、单值 KPI vs 周均值/峰值、单告警表 vs TopN+流水）较大，过早抽象会放大返工成本。

**建议**：等周报 MVP 稳定 + 月报立项时再统一抽 `render_report_generic`（与自定义模板平台 §12.2 的 `render_markdown_generic` 合流）。

### 周报历史归档与跨周对比 UI

**原因**：超出 SOUL + skill 脚本能力边界，需要新增前端列表组件，违反"零前端改动"原则。

**建议**：放到自定义模板平台 Phase 5（报告历史 UI）统一交付。

---

## 5. Sprint Sequencing

```text
Day 1
- 新增 query_weekly.py 演示数据脚本（含 previous_week / previous_year / none 三分支）
- 写脚本级单元测试（Story W1 + W7 第一部分）

Day 2
- 新增 weekly_kpi.py
- 完成周均值/峰值/波动率/周环比/TopN/next_week_focus 计算
- 写脚本级单元测试（Story W2 + W7 第二部分）

Day 3
- 扩展 export_report.py（render_weekly_markdown + report_type 参数）
- 日报回归测试（Story W3 + W7 日报回归部分）
- 改写 ai-report--weekly/SOUL.md 4 轮表单骨架（Story W4 上半）

Day 4
- 完成 SOUL.md 输入校验、设备数分支、present_files 闭环（Story W4 下半）
- GenUI 联调：跑通完整链路（Story W5 主体）

Day 5
- 边界场景验证：compare=previous_year 缺失 / weasyprint 不可用 / 多次生成回溯（Story W5 收尾）
- 注册 report_scripts.yaml（Story W6）
- 整理交付说明 + 与自定义模板 Phase 3 owner 对齐脚本契约
```

---

## 6. Sprint Summary

```text
Sprint Goal:
完成 AI 周报智能体 MVP，使其通过 4 轮 GenUI 表单收集参数，基于 Skill 脚本生成周报，支持 Markdown 自动导出，
并为未来 weekly-equipment DSL builtin 模板保留无缝接入路径。

Duration:
1 周

Team Capacity:
5 人天，预留 20% 缓冲后约可承诺 4 人天 / 14 SP

Must Stories（承诺，共 14 SP）:
W1. 新增 query_weekly.py 7 天数据查询脚本 — 3 SP
W2. 新增 weekly_kpi.py 周 KPI 计算脚本 — 3 SP
W3. 扩展 export_report.py 支持周报渲染（日报零回归） — 2 SP
W4. 改写 ai-report--weekly SOUL.md 实现 4 轮表单 — 3 SP
W5. GenUI 周报渲染联调 + Markdown 导出闭环 — 3 SP

Should / Stretch Stories（容量允许时推进，共 4 SP）:
W6. 与 DSL 自定义模板平台脚本注册联调 — 2 SP
W7. 单元测试与最小回归验证 — 2 SP

不承诺范围:
- 真实周数据接入（依赖 MCP / HTTP API 定稿）
- PDF 渲染样式调优（依赖 sandbox 镜像决策）
- 周报与日报抽公共 renderer（待月报立项 / DSL generic renderer 合流）
- 周报历史归档与跨周对比 UI（自定义模板 Phase 5 范围）
```
