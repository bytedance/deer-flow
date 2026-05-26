## ADDED Requirements

### Requirement: Markdown 报告渲染
趋势分析报告 SHALL 通过 `export_report.py` 的 `render_trend_markdown()` 函数将报告 payload 渲染为 Markdown 格式。报告 SHALL 包含标准章节：标题、元信息、执行摘要、逐设备详析、横向对比、劣化预警、预测、维护建议。

#### Scenario: 基本 Markdown 渲染
- **WHEN** `trend_report_features.json` 已生成且 `analysis_type` 为 `trend`
- **THEN** `render_trend_markdown()` 输出包含 `# 趋势分析报告` 标题、分析时间范围、设备列表、各章节内容的完整 Markdown 字符串

#### Scenario: Pro 等级 Markdown 增强
- **WHEN** 报告 payload 的 `capability_tier` 为 `pro`
- **THEN** Markdown 报告额外包含：多模型对比表（模型名称、R²_adj、选择标记）、STL 分解文字描述、变点检测结果表、置信区间说明

#### Scenario: Ultra 等级 Markdown 增强
- **WHEN** 报告 payload 的 `capability_tier` 为 `ultra`
- **THEN** Markdown 报告额外包含：LSTM 预测值表、协变组列表、自适应阈值推荐表、模型置信度标注

### Requirement: PDF 报告导出
趋势分析报告 SHALL 支持 PDF 格式导出（通过 weasyprint 将 HTML 转换为 PDF）。当 weasyprint 不可用时 SHALL 降级为仅 Markdown 导出。

#### Scenario: PDF 导出成功
- **WHEN** weasyprint 已安装且 Markdown 渲染成功
- **THEN** 系统调用 `write_report(payload, "pdf", report_type="trend")` 生成 `/mnt/user-data/outputs/trend_report.pdf`

#### Scenario: PDF 导出降级
- **WHEN** weasyprint 未安装（`ImportError`）
- **THEN** 系统跳过 PDF 生成，报告下载链接中标注"PDF 不可用（weasyprint 未安装）"，仅生成 Markdown 下载链接

### Requirement: 报告类型注册
`export_report.py` SHALL 在 `SUPPORTED_REPORT_TYPES` 中注册 `trend` 类型。`_output_dir()` 函数 SHALL 支持 `trend` 类型的环境变量解析。

#### Scenario: 报告类型识别
- **WHEN** `write_report()` 被调用且 `report_type="trend"`
- **THEN** 系统从 `TREND_REPORT_OUTPUT_DIR` 环境变量（回退到 `DAILY_REPORT_OUTPUT_DIR`）解析输出路径，写入 `trend_report.{md,pdf}`

#### Scenario: 输出文件名
- **WHEN** 趋势报告导出完成
- **THEN** 输出文件为 `/mnt/user-data/outputs/trend_report.md` 和 `/mnt/user-data/outputs/trend_report.pdf`（如 PDF 可用）

### Requirement: 下载链接生成
趋势分析报告 SHALL 在报告末尾渲染下载链接，包含 Markdown 链接和 PDF 链接（如可用）。链接 SHALL 使用当前线程 ID 构建 artifact 路径。

#### Scenario: 完整下载链接
- **WHEN** Markdown 和 PDF 均生成成功
- **THEN** 报告末尾包含：`- [下载 Markdown](/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/trend_report.md)` 和 `- [下载 PDF](/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/trend_report.pdf)`

#### Scenario: 仅 Markdown 下载链接
- **WHEN** PDF 不可用
- **THEN** 报告末尾仅包含 Markdown 下载链接，追加 `- PDF 不可用（weasyprint 未安装）`

### Requirement: present_files 暴露
趋势分析报告 SHALL 仅对最终报告文件（`trend_report.md` / `trend_report.pdf`）调用 `present_files`。中间 JSON 文件（`trend_data.json` / `trend_analysis.json` / `trend_report_features.json` 等）SHALL NOT 暴露给用户。

#### Scenario: 仅暴露最终文件
- **WHEN** 报告导出完成
- **THEN** 系统调用 `present_files(["/mnt/user-data/outputs/trend_report.md", "/mnt/user-data/outputs/trend_report.pdf"])`（PDF 不可用时仅传 `.md`）

#### Scenario: 不暴露中间文件
- **WHEN** 分析过程中生成了 `trend_data.json`、`pro_trend_analysis.json` 等中间文件
- **THEN** 系统不调用 `present_files` 暴露这些文件

### Requirement: DSL 脚本声明
`report_scripts.yaml` SHALL 注册 `trend_report_transform` 脚本声明，包含 `input`（多设备趋势分析结果路径列表）和 `output`（报告渲染 payload 路径）参数。

#### Scenario: 脚本声明可发现
- **WHEN** DSL 模板平台加载 `report_scripts.yaml`
- **THEN** 平台可发现 `data-analyst/trend_report_transform` 脚本，获取其 `args_schema` 和 `output_files` 声明

#### Scenario: 脚本输出声明
- **WHEN** `trend_report_transform` 脚本被 DSL 模板引用
- **THEN** 运行时将 `{run_output_dir}` 解析为 ReportRun 的作用域输出目录，脚本输出 `trend_report_features.json` 到该目录
