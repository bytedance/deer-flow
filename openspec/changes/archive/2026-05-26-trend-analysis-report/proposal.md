## Why

`ai-report--trend` agent 目前只是一个薄壳（仅有 SOUL.md 概述，无执行流水线、无脚本集成、无 GenUI 工作流），而 `monitoring-analysis` agent 已经实现了完整的趋势分析能力（Basic/Pro/Ultra 三层、脚本调用、可视化、报告导出）。这导致两个问题：(1) 用户无法通过 AI 报告入口自动生成周期性趋势分析报告；(2) monitoring-analysis 的趋势分析结果无法被日报/周报/月报等定期报告流水线复用。需要设计一个独立的、可调度的、支持多格式导出的趋势分析报告功能。

## What Changes

- **充实 `ai-report--trend` agent**：从薄壳升级为完整的趋势分析报告生成器，包含 GenUI 参数收集流水线、脚本调度、报告渲染和导出
- **复用 monitoring-analysis 趋势流水线**：趋势分析报告的核心分析逻辑复用 `query_trend.py` → `trend_analysis.py` / `pro_trend.py` / `ultra_trend.py` 脚本链，不重复造轮子
- **新增趋势报告导出类型**：在 `export_report.py` 中新增 `trend` 报告类型（独立于 `monitoring` 类型），支持 Markdown + PDF 导出
- **支持 DSL 模板集成**：在 `report_scripts.yaml` 中注册趋势报告专属的脚本声明，使 Custom Template 平台可发现并编排
- **支持定时调度**：趋势分析报告可被 Pro/Ultra 调度器定期触发（日报内嵌趋势段、独立周/月趋势报告）
- **多设备对比分析**：报告支持跨设备趋势对比（同类型设备横向对比、历史环比/同比）
- **结构化报告章节**：报告包含执行摘要、逐设备趋势详析、劣化预警、预测、维护建议等标准章节

## Capabilities

### New Capabilities
- `trend-report-pipeline`: 趋势分析报告的端到端执行流水线——参数收集、数据拉取、分析调度、可视化渲染、报告导出
- `trend-report-export`: 趋势分析报告的导出能力——Markdown/PDF 渲染、DSL 模板集成、下载链接生成
- `trend-report-scheduling`: 趋势分析报告的调度能力——独立触发、嵌入日报/周报、周期性自动生成

### Modified Capabilities
<!-- 无需修改现有 spec 的需求定义。本变更引入的能力与 monitoring-analysis 的能力正交：monitoring-analysis 负责交互式分析会话，trend-report 负责结构化报告生成。两者共享底层脚本但上层流水线独立。 -->

## Impact

- **Agent 层**：升级 `agents/builtin/ai-report--trend/SOUL.md` 和 `config.yaml`，增加 `monitoring:pro` / `monitoring:ultra` 工具组引用
- **脚本层**：`export_report.py` 新增 `render_trend_markdown()` 函数和 `trend` 报告类型；可能新增 `trend_report_features.py` transform 脚本
- **DSL 层**：`report_scripts.yaml` 新增趋势报告专属脚本声明（`trend_report_transform`）
- **前端**：无变更（复用现有 GenUI 组件 `form` / `card` / `table` / `echart` / `device-selector-multi`）
- **后端**：无变更（复用现有 sandbox 执行环境）
- **依赖**：Pro 等级依赖 `scikit-learn` / `statsmodels` / `ruptures`（已在 monitoring-analysis 中声明）；Ultra 额外依赖 `onnxruntime`（可选）
