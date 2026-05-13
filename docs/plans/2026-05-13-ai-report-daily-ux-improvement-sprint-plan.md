# AI 日报交互优化 Sprint 实施计划

> **来源设计文档**：[AI 日报交互优化设计文档](./2026-05-13-ai-report-daily-ux-improvement-design.md)
> **前置交付**：[AI 日报 MVP Sprint](./2026-05-13-ai-report-daily-sprint-plan.md)（已完成）
> **范围**：基于设计文档拆分出的执行计划，覆盖两轮表单、设备目录脚本、KPI 扩展、聚合策略的实现。

---

## 1. Sprint Goal

在不新增后端路由、不新增前端组件的前提下，将日报参数表单从"手动输入 CSV"升级为"两轮交互式表单"，支持按设备类型/区域筛选设备、动态推荐 KPI、大量设备自动聚合展示，使日报功能对管理 2200+ 台设备的工业用户可用。

## 2. Sprint 假设

| 项 | 假设 |
| ---- | ------ |
| Sprint 周期 | 1 周 |
| 团队配置 | 1 名全栈/Agent 工程师 |
| 可用容量 | 5 人天 |
| 缓冲 | 20%（约 1 人天） |
| 可承诺容量 | 4 人天 |
| Must 承诺范围 | Stories 1-5：设备目录脚本、KPI 扩展、范围查询、两轮表单 SOUL、聚合策略、导出适配、测试 |
| Should / Stretch 范围 | Story 6 聚合趋势图增强 |
| 前置依赖 | AI 日报 MVP 已完成（SOUL.md + query_daily.py + daily_kpi.py + export_report.py 全部就绪） |

---

## 3. Stories

> **承诺口径**：Must Stories（1-5，共 14 SP）是本 Sprint 的交付承诺；Should Story（6，2 SP）在 Must 完成后推进。

### Story 1（Must）：新增 `list_equipment.py` 设备目录查询脚本（3 SP）

**目标**：提供设备目录查询能力，支持按类型/区域/指定 ID 筛选，返回匹配设备列表和可用 KPI。

**范围**：

- 新增 `skills/custom/data-analyst/scripts/list_equipment.py`
- 支持 `--type`、`--scope`、`--filter`、`--limit` 参数
- 无真实 API 时返回演示数据（4 类设备，4 个区域，合计 2200 台）
- 输出包含 `equipment`、`total_matched`、`areas`、`available_kpis`
- 输入校验：`--type` 和 `--scope` 枚举白名单，`--filter` 字符集校验

**验收标准**：

- 命令可在 sandbox 中执行
- `--type static_equipment --scope area --filter A区` 返回约 250 条静设备
- `--type all --scope all` 返回 total_matched=2200
- `available_kpis` 根据设备类型正确返回（静设备含腐蚀/壁厚，旋转机组含振动/轴温）
- 前 3 个 KPI 的 `default` 为 `true`
- 输入校验拒绝注入攻击（如 `$(touch pwned)`）
- 输出 JSON 符合设计文档 §4.1

**依赖**：`skills/custom/data-analyst/scripts/` 路径存在。

### Story 2（Must）：扩展 `query_daily.py` 支持设备类型、范围查询和新 KPI（3 SP）

**目标**：让数据查询脚本感知设备类型，支持按区域/全部的大批量设备查询（避免 SOUL.md 拼接 CSV），支持 7 个新增 KPI 的演示数据生成。

**范围**：

- `query_daily.py` 新增 `--type` 可选参数（默认 `all`）
- `query_daily.py` 新增 `--scope`（`all`/`area`/`specific`）和 `--scope-filter` 可选参数
- `--scope` 与 `--equipment` 互斥：传了 `--scope` 时忽略 `--equipment`；脚本内部调用设备查询逻辑获取完整设备列表
- 当设备数 > 20 时（通过 `--scope` 触发），`current` 新增 `per_equipment` 字段（逐设备 KPI + hourly），供 `daily_kpi.py` 计算 min/max 和识别异常设备
- `KPI_UNITS` 扩展 7 个新 KPI（corrosion_rate, thickness_loss, vibration_level, bearing_temp, flow_rate, outlet_pressure, valve_temp）
- `_demo_kpis()` 为每个新 KPI 配置合理的演示值范围
- `_demo_alarms()` 根据设备类型生成对应告警消息
- 现有 `--equipment` 参数和行为不变，向后兼容

**验收标准**：

- `--type static_equipment --scope area --scope-filter A区 --kpis corrosion_rate,thickness_loss` 返回合理演示数据
- `--scope area` 模式下输出包含 `per_equipment` 字段，含每台设备的 KPI
- `--scope all --type pump` 返回 total 1000 台机泵的聚合 + 逐设备数据
- 不传 `--type`/`--scope` 时行为与现有完全一致（向后兼容）
- 所有现有测试继续通过
- 新增 KPI 的 `kpi_units` 正确返回

**依赖**：Story 1（复用设备查询逻辑）。

### Story 3（Must）：扩展 `daily_kpi.py` 和 `export_report.py` 支持新 KPI 和聚合策略（3 SP）

**目标**：让 KPI 计算脚本支持新增 KPI 的显示名和方向判断，基于 `per_equipment` 数据在设备数 > 20 时自动启用聚合模式。同步更新 Markdown 导出以正确渲染聚合输出。

**范围**：

- `daily_kpi.py`：
  - `KPI_DISPLAY_NAMES` 新增 7 个 KPI 中文名
  - `KPI_BETTER_WHEN_HIGHER` 新增 `flow_rate`、`outlet_pressure`
  - 新增聚合逻辑：当输入含 `per_equipment` 且设备数 > 20 时：
    - `kpi_summary` 中 `current` 为均值，新增 `min`/`max`/`current_note`
    - `trend_chart` 标题标注"均值"
    - 基于 `per_equipment` 数据计算 `top_anomalies` 列表（Top-10 异常设备，按严重性排序）
    - 新增 `aggregation_mode` 字段（`detail` / `grouped`）
  - 无 `per_equipment` 或设备数 ≤ 20 时走现有逐台逻辑，输出不变
- `export_report.py`：
  - 聚合模式下设备列表改为计数显示（"共 N 台"而非逐个列出）
  - 报告标题含设备类型信息（如"静设备运行日报"）
  - 新增 `top_anomalies` Markdown 表格段落（排名/设备ID/名称/区域/异常描述/严重性）
  - 无 `top_anomalies` 或为空时不渲染该段落，现有结构不变

**验收标准**：

- 传入含 `per_equipment`（50 台设备）的输入时 `aggregation_mode` 为 `grouped`
- 传入无 `per_equipment`（5 台设备）的输入时 `aggregation_mode` 为 `detail`
- `top_anomalies` 按严重性排序，最多 10 条
- 新 KPI 的 display name 和 direction 正确
- `export_report.py` 聚合模式 Markdown 含"共 N 台"和"异常设备排行"表格
- `export_report.py` 逐台模式 Markdown 保持不变
- 现有测试继续通过

**依赖**：Story 2 输出结构（`per_equipment`）稳定。

### Story 4（Must）：改写 SOUL.md 为两轮表单流程（3 SP）

**目标**：将 SOUL.md 从单轮 `daily-report-params` 改为两轮 `daily-report-scope` + `daily-report-confirm`。

**范围**：

- Round 1 表单（`daily-report-scope`）：日期、设备类型、设备范围、区域/设备筛选、对比基准
- Round 1 回调：校验输入 → 调用 `list_equipment.py` → 渲染 Round 2 表单
- Round 2 表单（`daily-report-confirm`）：动态 checkbox KPI 列表，description 显示匹配设备数
- Round 2 回调：收集选中 KPI → 从对话历史提取 Round 1 参数 → 根据设备范围选择 `--equipment` 或 `--scope` 模式调用脚本 → 渲染日报
- 聚合模式下的渲染指令（aggregation_mode=grouped 时 card 展示均值/范围，table 展示 top_anomalies）
- 导出表单不变（`daily-report-export`）
- 输入校验规则更新（设备类型/范围枚举、区域名字符集）

**验收标准**：

- 进入日报 Agent 后先看到 Round 1 表单（含设备类型 select）
- 提交 Round 1 后看到设备匹配数量和 KPI checkbox 列表
- 提交 Round 2 后生成日报（card/echart/table/markdown）
- 选择"静设备"时 KPI checkbox 包含腐蚀/壁厚
- 选择"旋转机组"时 KPI checkbox 包含振动/轴温
- **提交 Round 2 时若无任何 KPI 被选中，Agent 渲染 markdown 提示"请至少选择一个 KPI 指标"并停止，不调用脚本**
- **Round 2 回调处理时 SOUL.md 显式指导 Agent 从对话历史中的 `daily-report-scope` 回调 payload 提取 Round 1 参数**
- **按区域或全部场景使用 `--type/--scope/--scope-filter` 调用 `query_daily.py`，不拼接设备 ID CSV**
- 导出链路不受影响
- 无后端/前端代码变更

**依赖**：Story 1、2、3。

### Story 5（Must）：测试覆盖（2 SP）

**目标**：确保新增和修改的脚本有充分测试覆盖。

**范围**：

- 新增 `backend/tests/test_ai_report_daily_list_equipment.py`：参数解析、演示数据生成、输入校验、KPI 推荐
- 修改 `test_ai_report_daily_query.py`：新增 `--type`/`--scope`/`--scope-filter` 参数测试、`per_equipment` 输出测试、新 KPI 演示数据测试
- 修改 `test_ai_report_daily_kpi.py`：新增聚合模式测试（含 `per_equipment` 输入）、top_anomalies 测试、新 KPI display name 测试
- 修改 `test_ai_report_daily_export.py`：新增聚合模式 Markdown 渲染测试（设备计数、top_anomalies 表格、设备类型标题）
- 修改 `test_ai_report_daily_pipeline.py`：扩展 pipeline 测试覆盖新 KPI、`--scope` 模式和聚合场景

**验收标准**：

- 所有测试通过
- `list_equipment.py` 测试覆盖：全部类型查询、区域筛选、指定设备、输入校验拒绝
- `query_daily.py` 测试覆盖：`--scope area` 输出含 `per_equipment`、`--equipment` 向后兼容
- 聚合模式测试：含 `per_equipment` 输入返回 `aggregation_mode=grouped` + `top_anomalies`
- `export_report.py` 测试覆盖：聚合模式 Markdown 含"共 N 台"和异常排行表
- 现有 23 个测试不受影响
- 契约测试覆盖 list_equipment → query_daily(scope) → daily_kpi(aggregation) → export 链路

**依赖**：Story 1、2、3。

### Story 6（Should）：聚合趋势图增强（2 SP）

**目标**：在聚合模式下，ECharts 趋势图展示均值曲线 + 范围阴影区域。

**范围**：

- `daily_kpi.py` 在聚合模式下计算每小时的 min/max/avg
- `trend_chart` 新增 areaStyle series 表示范围区域
- 按区域分组时每组一条曲线

**验收标准**：

- 聚合模式趋势图有均值线 + 范围阴影
- 按区域分组时图例展示区域名
- 逐台模式趋势图不变

**依赖**：Story 3。

---

## 4. 不建议本 Sprint 承诺的内容

### 真实设备 API 对接

**原因**：设备数据从后台其它系统获取，具体 API 接口、认证方式、数据 schema 未确定。

**建议**：本 Sprint 使用演示数据验证交互流程和聚合策略，下个 Sprint 接真实 API。

### 设备搜索/模糊匹配

**原因**：GenUI form 的 text 字段不支持 async autocomplete，实现搜索需要新增前端组件。

**建议**：当前通过"类型 + 区域 + 指定 ID"三级筛选满足需求，搜索功能等 GenUI 组件增强后再做。

### 按子类型细分

**原因**：每个设备大类下还有子类型（如静设备下有换热器、塔器、容器等），细分维度过多会增加交互复杂度。

**建议**：MVP 先按大类筛选，子类型信息在 `list_equipment.py` 返回中携带，后续可加第三级筛选。

---

## 5. Sprint Sequencing

```text
Day 1
- 新增 list_equipment.py（演示数据、输入校验、KPI 推荐）
- 新增 list_equipment 测试

Day 2
- 扩展 query_daily.py（--type/--scope/--scope-filter 参数、per_equipment 输出、7 个新 KPI）
- 扩展 daily_kpi.py（新 KPI、基于 per_equipment 的聚合逻辑、top_anomalies）
- 扩展 export_report.py（设备计数、设备类型标题、top_anomalies 表格）
- 更新相关测试

Day 3
- 改写 SOUL.md（两轮表单流程、Round 1→2 状态传递、--scope 模式调用）
- 联调 Round 1 → list_equipment → Round 2

Day 4
- 联调 Round 2 → query_daily(scope) → daily_kpi(aggregation) → GenUI 渲染
- 验证聚合模式下的日报展示（top_anomalies 表格、均值卡片）
- 验证导出链路（聚合模式 Markdown）

Day 5
- 完善测试覆盖（聚合 pipeline、export 聚合模式）
- 回归测试（确保 23 个现有测试通过）
- 修复问题
- 更新设计文档数据契约
```

---

## 6. Sprint Summary

```text
Sprint Goal:
将日报参数表单升级为两轮交互式表单，支持设备分类筛选、动态 KPI 推荐和大量设备聚合展示。

Duration:
1 周

Team Capacity:
5 人天，预留 20% 缓冲后约可承诺 4 人天 / 14 SP

Must Stories（承诺，共 14 SP）:
1. 新增 list_equipment.py 设备目录脚本 — 3 SP
2. 扩展 query_daily.py 支持设备类型、范围查询和新 KPI — 3 SP
3. 扩展 daily_kpi.py 和 export_report.py 支持新 KPI 和聚合策略 — 3 SP
4. 改写 SOUL.md 为两轮表单流程 — 3 SP
5. 测试覆盖 — 2 SP

Should / Stretch Stories（容量允许时推进，共 2 SP）:
6. 聚合趋势图增强 — 2 SP

不承诺范围:
- 真实设备 API 对接（依赖接口定稿）
- 设备搜索/模糊匹配（依赖 GenUI 组件增强）
- 按子类型细分（待大类筛选稳定后再加）

前置依赖（已完成）:
- AI 日报 MVP（SOUL.md + 3 个 Skill 脚本 + 23 个测试）
```
