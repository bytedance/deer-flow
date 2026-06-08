# report-deep-link-direct Specification

## Purpose
TBD - created by archiving change add-report-deep-link-direct-execution. Update Purpose after archive.
## Requirements
### Requirement: 日报 deep-link 参数直达报告

当日报 deep-link 传入的 `<deep_link_params>` 块中包含 `template_id` 和 `report_date` 且均校验通过时，Agent SHALL 跳过全部 GenUI 交互表单，直接调用 `report_direct_execute` 工具，传入解析后的参数。工具内部自动完成数据获取、KPI 计算、报告生成和导出。

#### Scenario: 参数齐全直达报告

- **WHEN** 日报 deep-link 传入 `template_id=daily-equipment` 且 `report_date=2026-06-01`，且 `template_id` 匹配 builtin 模板
- **THEN** Agent 直接调用 `report_direct_execute(report_type="daily", scope={report_date: "2026-06-01"}, ...)`，跳过所有表单交互，工具内部完成完整报告生成链路并导出 Markdown

#### Scenario: 参数缺失回退表单

- **WHEN** 日报 deep-link 只传入 `template_id=daily-equipment` 但缺少 `report_date`
- **THEN** Agent 回退到正常的表单交互流程，将 `template_id` 作为预填值

#### Scenario: 模板不存在回退表单

- **WHEN** 日报 deep-link 传入 `template_id=nonexistent` 且 `report_date=2026-06-01`
- **THEN** Agent 回退到模板选择表单

---

### Requirement: 周报 deep-link 参数直达报告

周报 Agent SHALL 支持从 `<deep_link_params>` 块读取 `template_id`、`week_start`、`date_end` 参数。三个参数齐全且校验通过时，Agent SHALL 跳过全部 GenUI 交互表单，直接调用 `report_direct_execute` 工具完成报告生成。

#### Scenario: 参数齐全直达周报

- **WHEN** 周报 deep-link 传入 `template_id=weekly-equipment`、`week_start=2026-05-25`、`date_end=2026-06-01`，且模板匹配
- **THEN** Agent 直接调用 `report_direct_execute(report_type="weekly", scope={week_start: "2026-05-25", date_end: "2026-06-01"}, ...)`，跳过表单，直接生成周报

#### Scenario: 参数缺失回退表单

- **WHEN** 周报 deep-link 只传入 `template_id` 但缺少 `week_start` 或 `date_end`
- **THEN** Agent 回退到正常的表单交互流程

---

### Requirement: 月报 deep-link 参数直达报告

月报 Agent SHALL 支持从 `<deep_link_params>` 块读取 `template_id` 和 `report_month` 参数。两个参数齐全且校验通过时，Agent SHALL 跳过全部 GenUI 交互表单，直接调用 `report_direct_execute` 工具完成报告生成。

#### Scenario: 参数齐全直达月报

- **WHEN** 月报 deep-link 传入 `template_id=monthly-equipment`、`report_month=2026-06`，且模板匹配
- **THEN** Agent 直接调用 `report_direct_execute(report_type="monthly", scope={report_month: "2026-06"}, ...)`，跳过表单，直接生成月报

#### Scenario: 参数缺失回退表单

- **WHEN** 月报 deep-link 只传入 `template_id` 但缺少 `report_month`
- **THEN** Agent 回退到正常的表单交互流程
