# AI 报告平台 P2 + P3 Sprint 实施计划

> **范围**：基于自定义模板平台已就位的 DSL runtime + 14 工具 + 路由 + 5 个 builtin DSL 模板框架 + 12 个 stub 脚本，把剩余 5 个报告类型（trend / diagnosis / failure-analysis / closure / inspection）从"骨架可跑通但 demo 数据浅"提升到"端到端可用 + 符合 §13.2 解释性报告契约"。
> **依赖前置（已完成）**：
> - 自定义模板平台 Phase 1-4 已 ship（[backend/packages/harness/deerflow/report_templates/](../../backend/packages/harness/deerflow/report_templates/) 完整 + 14 builtin tools + `/api/report-templates` + `/api/report-runs`）
> - 日报 / 周报 / 月报 Sprint 全部 DoD 达成（含 [skills/custom/data-analyst/scripts/](../../skills/custom/data-analyst/scripts/) 模式样板）
> - 5 个 DSL builtin 模板框架已建（[agents/builtin/report-templates/](../../agents/builtin/report-templates/)：trend-equipment / diagnosis-fault / failure-analysis / closure-summary / inspection）
> - 12 个 stub 脚本骨架已建（55-122 行，已注册到 [report_scripts.yaml](../../skills/custom/data-analyst/report_scripts.yaml)）
> **不做**：原生 `ai-report--{trend,diagnosis,failure-analysis,closure}` 的 SOUL.md 重写（保持 25 行占位作为兜底入口）；真实数据接入（依赖 MCP/CMMS API 定稿）；PDF 渲染样式调优。
> **战略对齐**：[2026-05-14 自定义模板设计 §13.2](./2026-05-14-ai-report-custom-template-design.md) 解释性报告 5 字段契约（findings / evidence / confidence / data_coverage / human_review_required）；[2026-05-18 月报 Sprint](./2026-05-18-ai-report-monthly-sprint-plan.md) 的"演示数据深度 + DSL 注册对齐"模式作为复用样板。

---

## 1. Sprint Goal

在不动原生 SOUL.md 路径、不破坏日/周/月报现有行为的前提下，让 `ai-report--custom` 智能体可通过 builtin DSL 模板生成 5 种新报告（trend / diagnosis / failure-analysis / closure / inspection），且：

1. **stub 脚本满足 §13.2 解释性报告契约**：trend / diagnosis / failure-analysis 三类必须输出 `findings[] / evidence[] / confidence / data_coverage / human_review_required` 五字段并通过 validator。
2. **DSL 模板 `validate` 通过**：5 个 `default.yaml` 全部通过 platform 的 `report_template_validate` 工具，发布为 v1。
3. **端到端联调可跑通**：5 种报告各完成至少一次 prepare → render_step → submit → run_data_steps → assemble_payload → render_report → export 全链路 smoke。
4. **测试覆盖到位**：每类报告至少 4 个测试文件（query / transform / DSL validate / pipeline），日报+周报+月报零回归。

## 2. Sprint 假设

| 项 | 假设 |
| ---- | ------ |
| Sprint 周期 | **2 周**（10 人天） |
| 团队配置 | 1 名全栈/Agent 工程师（与月报同人，便于复用脚本约定 + 自定义模板平台知识） |
| 可用容量 | 10 人天 |
| 缓冲 | 25%（约 2.5 人天，应对解释性报告 §13.2 5 字段契约 + 5 类报告并行验证）|
| 可承诺容量 | 7.5 人天 |
| Must 承诺 | Stories S1-S6：trend / diagnosis / failure-analysis / closure / inspection 五类 stub 深度强化 + DSL 模板 validate 通过 + 端到端联调 |
| Should / Stretch | Story S7（generic_renderer 配适）+ Story S8（自定义模板平台联调 review）|
| 不承诺 | 真实数据接入 / 原生 SOUL 重写 / PDF 样式调优 / 跨报告抽公共 renderer |
| 前置依赖 | 自定义模板平台 Phase 1-4 已 ship；月报 Sprint 全 DoD 达成；`ai-report--custom` SOUL.md 已存在 |

> **战略基调**：DSL 模板路径作为剩余 5 类报告的主交付路径；原生 SOUL.md 25 行占位保持不动作为兜底（用户从 `ai-report` 父 group 进入子 agent 时仍可看到占位说明，引导改用 `ai-report--custom`）。

> §13.2 P2 (trend / diagnosis) 与 P3 (failure-analysis / closure / inspection) 在本 Sprint 用相同节奏推进，差异仅在解释性 vs 事实性契约。

---

## 3. Stories

> **承诺口径**：Must Stories（S1-S6，共 22 SP）是本 Sprint 的交付承诺；Should Stories（S7-S8，共 4 SP）在 Must 完成后推进，不阻塞 MVP 验收。

### Story S1（Must）：trend / trend-equipment 端到端强化（5 SP）

**目标**：把 `query_trend.py`（84 行 stub）+ `trend_analysis.py`（118 行 stub）升级到与日/周/月报同等的演示数据深度，满足 §13.2 解释性报告契约，并让 `trend-equipment` DSL 模板通过 validator 并端到端跑通。

**范围**：

- 强化 [skills/custom/data-analyst/scripts/query_trend.py](../../skills/custom/data-analyst/scripts/query_trend.py)：
  - 输入参数全：`metric_keys`（CSV）/ `date_range`（`YYYY-MM-DD..YYYY-MM-DD`）/ `aggregation`（hourly/daily/weekly）/ `forecast_horizon`（0-90 天）
  - 输出 `time_series[]`：每个 metric 一条序列，含 `metric_key` / `unit` / `timestamps[]` / `values[]` / `point_count`
  - 输出 `metadata`：`date_range` / `aggregation` / `forecast_horizon` / `data_source: demo_fallback`
  - 演示数据使用确定性 sine + 噪声（同输入同输出），点数随 aggregation 自适应（hourly 24 点/天、daily 1 点/天、weekly 1 点/周）
- 强化 [skills/custom/data-analyst/scripts/trend_analysis.py](../../skills/custom/data-analyst/scripts/trend_analysis.py)：
  - 输入 `--input trend_data.json`，输出 `trend_analysis.json`
  - 输出 §13.2 完整契约：
    - `findings[]`：发现项（趋势上升/下降/突变/异常聚集 4 类）
    - `evidence[]`：每条 finding 至少 1 条 evidence，含 `source_type: timeseries` / `source_id: {metric_key}` / `snapshot_path` / `checksum` / `time_range` / `retrieved_at`
    - `confidence: low | medium | high`
    - `assumptions[]`：分析假设（如"演示数据为合成正弦波"）
    - `data_coverage`：`{covered_metrics, missing_metrics, time_coverage_pct}`
    - `human_review_required: true`（解释性报告默认强制）
    - `trend_chart`：完整 ECharts option（每 metric 一条 line + 预测段虚线）
    - `forecast[]`：每 metric 一条预测序列
    - `recommendations[]`：基于 findings 机械派生
- 校准 [agents/builtin/report-templates/trend-equipment/default.yaml](../../agents/builtin/report-templates/trend-equipment/default.yaml)：
  - 通过 `report_template_validate` 工具
  - 章节用 `sections.source` 引用 `trend_analysis.findings` / `trend_analysis.trend_chart` 等
  - `human_review_required` 渲染为顶部 warning banner

**验收标准**：

- `query_trend.py` 在 sandbox 中可执行，输出 JSON 含 `time_series[]` 与所有 metric 的完整序列
- `trend_analysis.py` 输出 5 字段 §13.2 契约（findings / evidence / confidence / data_coverage / human_review_required）
- 所有 finding 至少关联 1 条 evidence；evidence 字段完整（含 snapshot_path 与 checksum）
- `human_review_required` 始终为 `true`（解释性报告契约）
- `trend-equipment/default.yaml` 通过 `report_template_validate` 无报错
- 端到端跑通：用户在 `ai-report--custom` 中选择 `trend-equipment` 模板 → 提交表单 → runtime 调脚本 → 渲染含 evidence 链的报告 → 导出 Markdown
- 月报 / 周报 / 日报回归 0 失败

**依赖**：自定义模板平台 Phase 4 已 ship；月报 Sprint 已落地的 `data-analyst` skill 注册机制。

### Story S2（Must）：diagnosis / diagnosis-fault 端到端强化（5 SP）

**目标**：把 `query_fault_context.py`（69 行 stub）+ `build_fault_timeline.py`（55 行）+ `diagnosis_analysis.py`（122 行 stub）升级到 §13.2 契约深度。

**范围**：

- 强化 [skills/custom/data-analyst/scripts/query_fault_context.py](../../skills/custom/data-analyst/scripts/query_fault_context.py)：
  - 输入：`--fault-time YYYY-MM-DD` / `--equipment-id` / `--symptom` / `--include-related-equipment` flag
  - 输出 `operations[]`（故障前 24h 运行数据） / `alarms[]`（前后 6h 告警） / `work_orders[]`（最近 3 个工单） / `maintenance_records[]`（最近 30 天维护记录）
  - 演示数据确定性（seed = `fault_time + equipment_id`）
- `build_fault_timeline.py` 已经足够，但需补 `--input fault_context.json` 时 events 含 `source_type` / `source_id`，为 evidence 链做准备
- 强化 [skills/custom/data-analyst/scripts/diagnosis_analysis.py](../../skills/custom/data-analyst/scripts/diagnosis_analysis.py)：
  - 输入 `--input fault_context.json` + `--timeline fault_timeline.json`
  - 输出 §13.2 完整契约 + 诊断专属字段：
    - `findings[]`：候选根因（至少 2-3 条，含"主要根因 / 次要根因"标记）
    - `evidence[]`：每条 finding 至少 2 条 evidence，覆盖 timeseries / alarm / work_order 三种 source_type
    - `confidence` / `assumptions[]` / `data_coverage` / `human_review_required: true`
    - `impact_assessment`：`{affected_equipment[], downtime_minutes, business_impact: string}`
    - `recommendations[]`：处理建议，机械生成
- 校准 [agents/builtin/report-templates/diagnosis-fault/default.yaml](../../agents/builtin/report-templates/diagnosis-fault/default.yaml)：通过 validator + 章节含 timeline / impact / findings-with-evidence

**验收标准**：

- 3 脚本均通过 §13.2 5 字段契约
- diagnosis 每条 finding 至少有 2 条 evidence；evidence source_type 覆盖 timeseries + alarm + work_order
- `human_review_required: true` 不可被关闭（即使 confidence=high）
- `diagnosis-fault/default.yaml` 通过 validator
- 端到端跑通 + 月报/周报/日报回归 0 失败

**依赖**：S1 出齐 §13.2 输出范本（evidence 字段格式）后开工。

### Story S3（Must）：failure-analysis 端到端强化（4 SP）

**目标**：升级 `query_failure_data.py`（60 行）+ `failure_analysis.py`（98 行 stub）到 §13.2 契约 + 三种分析方法切换。

**范围**：

- 强化 [skills/custom/data-analyst/scripts/query_failure_data.py](../../skills/custom/data-analyst/scripts/query_failure_data.py)：
  - 输入：`--asset-id` / `--failure-mode` / `--analysis-method`（5why / fishbone / fmea）/ `--evidence-range`（如 `2026-01-01..2026-05-18`）
  - 输出按 method 分支：
    - 5why：`why_chain[]`（5 层因果链，每层带 evidence）
    - fishbone：`branches[]`（人/机/料/法/环/测 六类），每类 finding
    - fmea：`fmea_rows[]`（mode / effect / severity / occurrence / detection / RPN）
  - 公共字段：`operations_samples[]` / `maintenance_history[]` / `inspection_records[]` / `spares_used[]` / `environment_data[]`
- 强化 [skills/custom/data-analyst/scripts/failure_analysis.py](../../skills/custom/data-analyst/scripts/failure_analysis.py)：
  - 按 method 路由到不同 finding 生成逻辑
  - 输出 §13.2 5 字段契约 + 失效专属：
    - `root_causes[]`：含 `severity: critical | major | minor`
    - `corrective_actions[]`：含 `owner / due_date / verification_plan`
    - `validation_plan`：复测计划
  - `human_review_required: true`
- 校准 [agents/builtin/report-templates/failure-analysis/default.yaml](../../agents/builtin/report-templates/failure-analysis/default.yaml)：method 切换走 `select` field + sections 按 method 条件渲染

**验收标准**：

- 5why / fishbone / fmea 三个 method 输出 schema 都通过 §13.2 契约
- 5why 必须 5 层（占位允许 `evidence: null` 但层级数固定）
- fishbone 必须 6 类分支
- fmea RPN = severity × occurrence × detection（数值化校验）
- `failure-analysis/default.yaml` 通过 validator
- 端到端跑通 + 月/周/日报回归 0 失败

**依赖**：S1 + S2 出齐 §13.2 范本后开工。

### Story S4（Must）：closure / closure-summary 端到端强化（3 SP）

**目标**：升级 `query_closure_items.py`（62 行）+ `closure_summary.py`（66 行 stub）。**事实性报告**，不需 §13.2 evidence 契约。

**范围**：

- 强化 [skills/custom/data-analyst/scripts/query_closure_items.py](../../skills/custom/data-analyst/scripts/query_closure_items.py)：
  - 输入：`--issue-ids CSV` / `--owner-department` / `--verification-period`
  - 输出 `closure_items[]`：每项含 `id / title / owner / department / created_at / due_date / status: pending|in_progress|verifying|closed|reopened / actions[] / verification_results[] / notes`
  - 演示数据含 5 种状态分布（至少各 1 条）
- 强化 [skills/custom/data-analyst/scripts/closure_summary.py](../../skills/custom/data-analyst/scripts/closure_summary.py)：
  - 输出 `overall_status: {closed_count, pending_count, completion_rate}`
  - `unclosed_items[]`：未闭项详情（按 status 分组）
  - `risk_items[]`：风险检查（如 due_date 已过仍未闭、reopened 项）
  - `closure_conclusion`：闭环结论（机械生成）
  - 不需 `findings/evidence/confidence` 等 §13.2 字段（事实性报告）
- 校准 [agents/builtin/report-templates/closure-summary/default.yaml](../../agents/builtin/report-templates/closure-summary/default.yaml)：通过 validator

**验收标准**：

- 5 种 issue status 在 demo 中全部覆盖
- `completion_rate` 计算正确（`closed / total`）
- 风险检查能识别 `due_date < today AND status != closed` 与 `reopened` 两类
- 模板通过 validator
- 端到端跑通 + 月/周/日报回归 0 失败

**依赖**：S1 注册脚本契约后开工，无 §13.2 阻塞。

### Story S5（Must）：inspection 端到端强化（3 SP）

**目标**：升级 `query_inspection.py`（51 行）+ `inspection_summary.py`（79 行 stub）+ `inspection_attachment_summary.py`（57 行）。**事实性报告**。

**范围**：

- 强化 [skills/custom/data-analyst/scripts/query_inspection.py](../../skills/custom/data-analyst/scripts/query_inspection.py)：
  - 输入：`--inspection-date YYYY-MM-DD` / `--route` / `--area` / `--severity-min low|medium|high`
  - 输出 `records[]`：每条 `id / time / route / area / equipment / inspector / status: normal|warning|critical / description / attachments[]`
  - 演示数据含三种 severity 分布
- 强化 [skills/custom/data-analyst/scripts/inspection_summary.py](../../skills/custom/data-analyst/scripts/inspection_summary.py)：
  - `overall_status`：`{total_records, normal_count, warning_count, critical_count}`
  - `severity_distribution[]`：按 severity 聚合 + 占比
  - `anomaly_list[]`：异常清单（warning + critical），按 severity desc 排序
  - `corrective_recommendations[]`：整改建议（机械生成）
- 强化 [skills/custom/data-analyst/scripts/inspection_attachment_summary.py](../../skills/custom/data-analyst/scripts/inspection_attachment_summary.py)：
  - 输入：`inspection_data.json`
  - 输出 `attachment_summary[]`：每条 `{record_id, photo_count, note_count, snippet: 前 200 字}`
- 校准 [agents/builtin/report-templates/inspection/default.yaml](../../agents/builtin/report-templates/inspection/default.yaml)：通过 validator

**验收标准**：

- severity_distribution 三种等级都有占比（至少 demo 一条记录每种）
- attachment_summary 长度等于 records 长度
- 模板通过 validator
- 端到端跑通 + 月/周/日报回归 0 失败

**依赖**：与 S4 并行无前置阻塞。

### Story S6（Must）：5 类报告端到端 + 测试（2 SP）

**目标**：跑通 5 类报告的 prepare → render_step → submit → run_data_steps → assemble_payload → render_report → export 全链路，并补全测试。

**范围**：

- 为每类报告增加 `backend/tests/test_ai_report_{trend,diagnosis,failure_analysis,closure,inspection}_{query,kpi,pipeline,registry}.py` 共 5×4=**20 个测试文件**（参照 [test_ai_report_monthly_*.py](../../backend/tests/) 风格）：
  - `*_query.py`：query 层 schema + 校验 + 边界
  - `*_kpi.py` / `*_transform.py`：transform 层 §13.2 契约（仅 trend/diagnosis/failure-analysis）或事实性 schema（closure/inspection）
  - `*_pipeline.py`：query → transform → DSL validate 最小链路
  - `*_registry.py`：报告类型在 `report_scripts.yaml` 注册 + 字段一致 + 模板 validate
- 写 `skills/custom/data-analyst/scripts/_smoke_e2e_p2p3.py`：12 case smoke harness（每类 2-3 个边界）
- 日 / 周 / 月报回归测试 0 失败

**验收标准**：

- 20 个测试文件全部 pass
- smoke harness "ALL CASES PASSED"
- 月报 + 周报 + 日报既有测试 0 失败
- 每类报告都有 1 个 fixture 显示 `human_review_required: true`（trend/diagnosis/failure-analysis）或事实性结构（closure/inspection）

**依赖**：S1-S5 全部完成。

### Story S7（Should）：`generic_renderer` 5 类报告适配（2 SP）

**目标**：让自定义模板平台的 [generic_renderer.py](../../backend/packages/harness/deerflow/report_templates/generic_renderer.py) 能渲染 5 类报告的 sections 输出为 Markdown，处理 §13.2 evidence 链。

**范围**：

- 检查 `generic_renderer.py` 当前是否覆盖：
  - `findings[]` + `evidence[]` 树状渲染（每条 finding 下嵌套 evidence list）
  - `confidence` badge（low/medium/high 三色）
  - `human_review_required: true` → 顶部红色 warning banner
  - `data_coverage` → "数据覆盖：N/M metrics, T% 时间覆盖"
- 补足缺失渲染分支（不改 schema）
- 不影响日 / 周 / 月报的 `render_{daily,weekly,monthly}_markdown` 专用路径

**验收标准**：

- 5 类报告通过 `report_template_export` 工具生成的 Markdown 包含 evidence 链（trend/diagnosis/failure-analysis）或结构化结论（closure/inspection）
- `human_review_required` banner 在 PDF 与 MD 中均显示
- 日 / 周 / 月报 `render_*_markdown` 测试 0 回归

**依赖**：S1-S5 全部完成。

### Story S8（Should）：自定义模板平台 owner 联调 review（2 SP）

**目标**：与自定义模板平台 owner 完成一次 review，确认 5 个 builtin DSL 模板在 `/api/report-templates` 路由下可被正确 list / fetch / validate，且 `report_run_id` → artifact 链路打通。

**范围**：

- 用 `gh api`（或前端）跑：
  - `GET /api/report-templates?visibility=builtin` 返回 5 + 已有的 3 = 8 个 builtin
  - 每个 builtin 模板 `POST /{id}/validate` 通过
  - 至少 1 类报告（trend）走完 `POST /api/report-templates/{id}/start_run` → 等到 status = completed → `GET /api/report-runs/{rid}/payload` 返回 §13.2 evidence 链
- 记录联调结果到 PR 描述
- 与 owner 对齐：哪些字段命名 / DSL 章节配置需要在下个 Sprint 调整

**验收标准**：

- 8 个 builtin 模板 list / validate 全部通过
- trend 报告 1 次完整 ReportRun 完成（含 artifact 写到 thread output dir）
- PR 描述含联调记录与 owner 签字

**依赖**：S1-S6 + 自定义模板平台 Phase 5 owner 可用。

---

## 4. 不建议本 Sprint 承诺的内容

### 真实数据接入（CMMS / EAM / TSDB）

**原因**：5 类报告依赖 5+ 种业务系统（工单 / 维护记录 / 时序数据库 / 巡检 APP / 缺陷库），集成成本高。

**建议**：本 Sprint 仅保留 demo_fallback；下个 Sprint 与日/周/月报真实数据接入并轨。

### 原生 SOUL.md 重写

**原因**：5 个原生 SOUL.md（[ai-report--trend](../../agents/builtin/ai-report--trend/SOUL.md) / [ai-report--diagnosis](../../agents/builtin/ai-report--diagnosis/SOUL.md) / [ai-report--failure-analysis](../../agents/builtin/ai-report--failure-analysis/SOUL.md) / [ai-report--closure](../../agents/builtin/ai-report--closure/SOUL.md)）保持 25 行占位作为兜底入口，引导用户改用 `ai-report--custom` + DSL 模板。

**建议**：等 DSL 路径稳定 + 用户反馈后再决定是否补原生 SOUL；如要补，照搬月报 SOUL.md 模式即可（每个 ~300 行）。

### PDF 渲染样式调优

**原因**：与日/周/月报相同 sandbox 镜像决策未定。

**建议**：本 Sprint 仅完成 try/except 降级，PDF 样式留给 sandbox 决策落地后统一处理。

### 跨报告抽公共 renderer

**原因**：日/周/月报章节差异已大，5 类新报告差异更大（解释性 vs 事实性），过早抽象返工大。

**建议**：等 5 类 MVP 稳定后再评估与 [generic_renderer.py](../../backend/packages/harness/deerflow/report_templates/generic_renderer.py) 合流路径。

### 改进措施跟踪 / 闭环 CRUD UI

**原因**：超 SOUL + skill 脚本边界，需独立前端立项。

**建议**：放到独立"改进措施管理"立项。

---

## 5. Sprint Sequencing

```text
Week 1（P2：解释性报告深度强化）

Day 1
- S1 上半：query_trend.py 强化（time_series + metadata + demo sine 数据）
- 测试：query_trend 边界 + DSL trend-equipment 字段一致性

Day 2
- S1 下半：trend_analysis.py §13.2 5 字段契约（findings/evidence/confidence/data_coverage/human_review_required）
- trend-equipment DSL 模板 validator 通过 + 端到端 smoke
- 月/周/日报回归

Day 3
- S2 上半：query_fault_context.py + build_fault_timeline.py 强化（含 source_type/source_id 为 evidence 做准备）
- diagnosis_analysis.py §13.2 5 字段契约 + impact_assessment + recommendations

Day 4
- S2 下半：diagnosis-fault DSL 模板 validator + 端到端 smoke
- 测试：diagnosis pipeline 含 evidence source_type 三种覆盖

Day 5
- S3 上半：query_failure_data.py 三种 method（5why / fishbone / fmea）分支
- failure_analysis.py 三种 method 路由 + §13.2 5 字段

Week 2（P3：事实性报告 + 联调 + 测试）

Day 6
- S3 下半：failure-analysis DSL 模板 validator + 端到端 smoke
- 测试：5why 5 层 / fishbone 6 类 / fmea RPN 校验

Day 7
- S4 完整：closure_items 5 状态 demo + closure_summary 风险检查 + closure-summary DSL 模板 validator + smoke
- S5 完整：inspection 3 severity demo + inspection_summary 分布 + inspection_attachment_summary + DSL validator + smoke

Day 8
- S6 测试补齐：20 个测试文件 + _smoke_e2e_p2p3.py（12 case）
- 月/周/日报回归 0 失败

Day 9
- S7：generic_renderer 适配 evidence 链 + human_review_required banner
- 验证 5 类报告 Markdown 导出含 evidence

Day 10
- S8：与自定义模板平台 owner 联调 review
- 整理交付说明 + PR 描述
- 缓冲：处理联调暴露的最后问题
```

---

## 6. Sprint Summary

```text
Sprint Goal:
完成 5 类报告（trend/diagnosis/failure-analysis/closure/inspection）的 stub 深度强化
+ DSL builtin 模板 validate 通过 + 端到端 smoke,
让 ai-report--custom 智能体可通过 5 个 builtin DSL 模板生成符合 §13.2 解释性报告契约
（findings/evidence/confidence/data_coverage/human_review_required）或事实性报告契约的产出。
原生 SOUL.md 保持 25 行占位不动,DSL 模板路径作为剩余 5 类报告的主交付。

Duration:
2 周（10 人天，预留 25% 缓冲 → 可承诺 7.5 人天 / 22 SP Must）

Must Stories（承诺,共 22 SP）:
S1. trend / trend-equipment §13.2 + DSL 模板 — 5 SP
S2. diagnosis / diagnosis-fault §13.2 + DSL 模板 — 5 SP
S3. failure-analysis 三种 method §13.2 + DSL 模板 — 4 SP
S4. closure / closure-summary 事实性契约 + DSL 模板 — 3 SP
S5. inspection 事实性契约 + DSL 模板 — 3 SP
S6. 端到端 + 20 个测试文件 + smoke harness + 日/周/月报零回归 — 2 SP

Should / Stretch Stories（容量允许时推进,共 4 SP）:
S7. generic_renderer evidence 链 + human_review banner 适配 — 2 SP
S8. 自定义模板平台 owner 联调 review — 2 SP

不承诺范围:
- 真实数据接入（依赖 MCP/CMMS API 定稿）
- 原生 SOUL.md 重写（5 个保持 25 行占位作为兜底入口）
- PDF 渲染样式调优（依赖 sandbox 镜像决策）
- 跨报告抽公共 renderer（等 5 类 MVP 稳定后评估与 generic_renderer 合流）
- 改进措施跟踪闭环 CRUD UI（独立立项）
```

---

## 7. 与自定义模板平台已完成情况的对齐

| 已就位组件 | 本 Sprint 如何利用 |
|---|---|
| DSL Runtime（schema / validator / source_resolver / script_registry / repository / records / permissions / service / generic_renderer / runtime/*）| **完全复用**，不改 schema/validator/runtime；本 Sprint 只在 stub 脚本与 builtin DSL 模板层做工作 |
| 14 builtin tools（`report_template_*` + `report_template_runtime_*`）| 联调验证（S8）；模板生命周期通过 `report_template_validate` / `report_template_publish` 工具 |
| Gateway `/api/report-templates` + `/api/report-runs` | 联调路径（S8）；不改路由 |
| 5 个 DSL builtin 模板框架（`agents/builtin/report-templates/{trend-equipment,diagnosis-fault,failure-analysis,closure-summary,inspection}/`）| **就地校准** `default.yaml` 让其通过 `report_template_validate`；不重写 metadata.yaml |
| 12 个 stub 脚本骨架 | **就地强化**（55-122 行 → 与 monthly_kpi.py 同等深度的 ~300-500 行）；不改文件名与注册项 |
| `report_scripts.yaml` 19 个脚本注册 | **不动注册项**；如发现 args_schema 与强化后 CLI 不一致，本 Sprint 内同步更新（在对应 Story 范围内） |
| 月报 Sprint 的 monthly_kpi.py / query_monthly.py / render_monthly_markdown / `_smoke_e2e.py` | **作为样板**复用：契约设计 / fixture 风格 / 测试结构 / 边界场景手册全部参考 |

**关键架构决策**：
1. 本 Sprint **不动** DSL runtime 与 14 builtin tools — 自定义模板平台 Phase 1-4 已 ship 且通过审查。
2. **不重写**原生 `ai-report--{trend,diagnosis,failure-analysis,closure}` SOUL.md — 保持 25 行占位作为兜底。
3. **DSL 模板路径** = 5 类报告的主交付路径，用户从 `ai-report--custom` 智能体进入选择 builtin DSL 模板。
4. **stub 脚本深度** 升级到与 monthly 同等水平（§13.2 解释性契约 / 事实性契约二选一），保留 `data_source: demo_fallback` 标记。
5. 与 `generic_renderer.py` 适配（S7）作为 Should 范围，确保 evidence 链 / human_review_required banner / confidence badge 在 5 类报告 Markdown 输出中正确呈现。
