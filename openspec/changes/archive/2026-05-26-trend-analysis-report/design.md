## Context

### 现状分析

**监测分析 Agent (`monitoring-analysis`)**：已实现完整的 5 类分析流水线（趋势/异常/KPI/关联/图谱），支持 Basic/Pro/Ultra 三层能力，通过 GenUI 表单收集参数、调用 Python 脚本执行分析、ECharts 渲染可视化、Markdown/PDF 导出报告。趋势分析流水线最为成熟，包含 `query_trend.py` → `trend_analysis.py`（Basic）/ `pro_trend.py`（Pro）/ `ultra_trend.py`（Ultra）完整链路。

**AI 报告体系**：以 `ai-report` 为父 agent，下辖 daily/weekly/monthly/diagnosis/failure-analysis/closure/trend/custom 共 8 个子 agent。其中 daily/weekly/monthly 已实现完整流水线（query → transform → export），diagnosis 和 closure 也各自完整。**唯独 `ai-report--trend` 只有 SOUL.md 概述（7 条要点）和空 config.yaml，没有执行流水线、脚本集成或报告导出。**

**DSL 模板平台**：`report_scripts.yaml` 已注册 query_weekly/weekly_kpi/query_daily/daily_kpi/query_monthly/monthly_kpi/query_trend/trend_analysis 等脚本。`query_trend` 和 `trend_analysis` 已声明但只服务于 monitoring-analysis agent 的交互式会话，未被 AI 报告体系编排。

**脚本生态**：
- `query_trend.py`：拉取时间序列 + 预测窗口，支持 hourly/daily/weekly 聚合
- `trend_analysis.py`：Basic 趋势分析（线性回归、移动平均、斜率/波动率、预测）
- `pro_trend.py`：Pro 趋势分析（多模型回归、STL 分解、PELT 变点检测、置信区间）
- `ultra_trend.py`：Ultra 趋势分析（LSTM 预测、协变组检测、自适应阈值推荐）
- `data_quality.py`：数据质量评估（Pro/Ultra）
- `export_report.py`：已支持 daily/weekly/monthly/diagnosis/monitoring 五种报告类型，缺少独立的 `trend` 类型

### 约束条件

- 所有分析结论必须来自脚本输出，不凭空编造
- 可下载产物必须写入 `/mnt/user-data/outputs/`
- 仅使用已注册 GenUI 组件（`form` / `card` / `table` / `markdown` / `echart` / `device-selector-multi`）
- Pro/Ultra 脚本依赖（`scikit-learn`, `statsmodels`, `ruptures`, `onnxruntime`）已在 docker sandbox 中声明
- 报告导出格式为 Markdown（必选）+ PDF（可选，依赖 weasyprint）

## Goals / Non-Goals

**Goals:**
- 将 `ai-report--trend` 从薄壳升级为完整的趋势分析报告生成器
- 复用 monitoring-analysis 已验证的趋势分析脚本链（query_trend → trend_analysis / pro_trend / ultra_trend）
- 支持 Pro/Ultra 能力等级门控，与 monitoring-analysis 共享分级体系
- 支持独立触发和嵌入日报/周报的两种调度模式
- 生成结构化报告（执行摘要 → 逐设备详析 → 劣化预警 → 预测 → 建议）
- 支持 Markdown + PDF 双格式导出
- 在 `report_scripts.yaml` 注册趋势报告专属脚本声明，供 DSL 模板平台发现

**Non-Goals:**
- 不实现异常检测/KPI/关联/图谱的报告（这些属于其他 AI 报告子 agent 的职责）
- 不修改 monitoring-analysis agent 的交互式趋势分析流水线
- 不引入新的 Python 依赖（复用 monitoring-analysis 已声明的依赖）
- 不实现前端组件变更（复用现有 GenUI 组件）
- 不设计跨 agent 的报告聚合机制（属于后续 V2 范围）

## Decisions

### 决策 1：复用 vs 重建脚本链

**选择：复用 monitoring-analysis 脚本链**

趋势分析报告调用与 monitoring-analysis 完全相同的脚本（`query_trend.py` → `trend_analysis.py` / `pro_trend.py` / `ultra_trend.py`），不编写新的分析脚本。

**理由**：
- 脚本已验证，覆盖 Basic/Pro/Ultra 三层
- 输出 JSON schema 稳定（`trend_data.json` → `trend_analysis.json` / `pro_trend_analysis.json` / `ultra_trend_result.json`）
- 只需新增一个 transform 脚本 `trend_report_transform.py` 将分析结果转换为报告渲染 payload（多设备聚合 + 报告章节结构）

**替代方案**：为 AI 报告编写独立脚本链 → 代码重复、维护成本翻倍、分析结果不一致

### 决策 2：独立报告类型 vs monitoring 子类型

**选择：在 `export_report.py` 新增独立 `trend` 报告类型**

**理由**：
- monitoring 报告面向交互式会话（包含 GenUI 渲染上下文），trend 报告面向结构化文档（执行摘要 + 章节）
- 两者 Markdown 结构差异大：monitoring 报告以 analysis_type 为维度，trend 报告以设备为维度
- 独立类型使 export_report.py 的 `render_trend_markdown()` 可专注于报告结构，不污染 `render_monitoring_markdown()`

**替代方案**：在 monitoring 类型内增加 `report_mode: "document"` 参数 → 函数复杂度增加、测试矩阵扩大

### 决策 3：SOUL.md 流水线设计

**选择：3 步 GenUI 流水线**

1. **设备选择**：复用 `device-selector-multi` 组件（与 monitoring-analysis 相同）
2. **分析范围**：简化版表单——时间范围 + 指标选择（去掉 analysis_type，因为固定为 trend）+ 对比模式（无/环比/同比）
3. **执行 + 报告导出**：调用脚本链 → 渲染可视化 → 生成报告 → 下载链接

**理由**：
- 趋势报告的分析类型固定为 trend，不需要 5 选 1 的分析类型选择器
- 增加对比模式选项（`compare_period`：none/wow/yoy），这是 monitoring-analysis Pro 智能交互中已设计但未在趋势报告中落地的功能
- 3 步流水线比 monitoring-analysis 的 4 步更简洁（省去了 analysis_type 选择步骤）

### 决策 4：多设备聚合策略

**选择：逐设备分析 + 横向对比摘要**

- 对每台设备独立运行趋势分析脚本，生成 per-device 趋势结果
- 新增 `trend_report_transform.py` transform 脚本，聚合所有设备结果为统一报告 payload
- 报告结构：执行摘要（跨设备概览）→ 逐设备详析（每设备一节）→ 横向对比（同指标跨设备）→ 劣化预警 → 预测 → 建议

**理由**：
- `query_trend.py` 支持 `--equipment` 参数批量查询，但 `trend_analysis.py` 对每个指标独立分析，不区分设备
- 逐设备运行允许每设备独立的能力等级回退（某设备 Ultra 模型缺失不影响其他设备）
- 横向对比需要所有设备的分析结果在同一 JSON 中，transform 脚本负责聚合

**替代方案**：一次查询所有设备 → 脚本不支持按设备分组输出，需要大量后处理

### 决策 5：DSL 脚本声明

**选择：新增 `trend_report_transform` 脚本声明**

在 `report_scripts.yaml` 中注册：
- `trend_report_transform`：将多台设备的 trend_analysis/pro_trend/ultra_trend 输出聚合为报告渲染 payload
- 复用已声明的 `query_trend` 和 `trend_analysis` / `pro_trend` / `ultra_trend`

**理由**：
- DSL 模板平台通过 `report_scripts.yaml` 发现可用脚本
- `trend_report_transform` 是报告专属的聚合逻辑，不属于通用分析脚本
- 保持与 daily_kpi/weekly_kpi/monthly_kpi 相同的声明模式（data_step → transform → export）

## Risks / Trade-offs

**[风险] 多设备串行分析耗时过长** → 缓解：Pro/Ultra 等级支持并行拉取（`query_trend.py` 的 `--equipment` 参数支持 CSV 列表），transform 脚本统一处理。单次报告限制设备数（Basic ≤5, Pro ≤20, Ultra ≤50）。

**[风险] 趋势报告与 monitoring 报告的内容重叠** → 缓解：明确职责分离——monitoring 报告是交互式会话的快照导出，trend 报告是独立生成的结构化文档。报告结构、章节标题、受众不同。

**[权衡] 新增 transform 脚本 vs 在 SOUL.md 内联 Python** → 选择新增脚本。内联 Python 不利于测试和 DSL 注册，但增加了代码文件数。考虑到 monitoring-analysis 的异常检测也用了内联 Python 且未注册脚本，这里保持一致性——趋势报告因为需要多设备聚合所以用独立脚本更合理。

**[风险] PDF 导出依赖 weasyprint 可能不可用** → 缓解：与现有报告一致，PDF 不可用时降级为仅 Markdown。在报告末尾标注 PDF 可用性状态。

## Migration Plan

无需迁移。本变更是新增功能，不修改现有行为。

部署步骤：
1. 升级 `ai-report--trend` agent 的 SOUL.md 和 config.yaml
2. 新增 `trend_report_transform.py` 脚本
3. 在 `export_report.py` 新增 `trend` 报告类型和 `render_trend_markdown()` 函数
4. 在 `report_scripts.yaml` 注册新脚本声明
5. 更新 docker sandbox 的 requirements.txt（如需新增依赖）

回滚：删除新增文件和代码段即可，不影响现有功能。

## Open Questions

1. 趋势报告是否需要支持「对比基准」功能（同类设备均值、行业参考线）？当前设计仅支持环比/同比，同类设备基准留作 V2。
2. 调度器触发趋势报告时，是否需要通知用户（推送消息/邮件），还是静默归档到 `/mnt/user-data/outputs/`？
3. 趋势报告是否需要支持「趋势异常」子分析（在趋势分析中嵌入变点检测的异常解读），还是严格只做趋势？
