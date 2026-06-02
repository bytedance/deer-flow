## ADDED Requirements

### Requirement: 日报 deep-link 参数直达报告

当日报 deep-link 传入的 `<deep_link_params>` 块中包含 `template_id` 和 `date` 且均校验通过时，Agent SHALL 跳过全部 GenUI 交互表单，直接执行 DSL 完整链路（`prepare_run` → `form_steps` 填入参数 → `data_pipeline` → `render` → `export`）直到报告生成完成。

#### Scenario: 参数齐全直达报告

- **WHEN** 日报 deep-link 传入 `template_id=daily-equipment` 且 `date=2026-06-01`，且 `template_id` 匹配已安装模板
- **THEN** Agent 直接调用 `prepare_run`，跳过设备选择器和日期表单，填入参数，执行完整 DSL 链路并导出报告

#### Scenario: 参数缺失回退表单

- **WHEN** 日报 deep-link 只传入 `template_id=daily-equipment` 但缺少 `date`
- **THEN** Agent 回退到正常的表单交互流程，将 `template_id` 作为预填值

#### Scenario: 模板不存在回退表单

- **WHEN** 日报 deep-link 传入 `template_id=nonexistent` 且 `date=2026-06-01`
- **THEN** Agent 回退到模板选择表单

---

### Requirement: 周报 deep-link 参数直达报告

周报 Agent SHALL 支持从 `<deep_link_params>` 块读取 `template_id`、`date_start`、`date_end` 参数。三个参数齐全且校验通过时，Agent SHALL 跳过全部 GenUI 交互表单，直接执行报告生成链路直到完成。

#### Scenario: 参数齐全直达周报

- **WHEN** 周报 deep-link 传入 `template_id=weekly-equipment`、`date_start=2026-05-25`、`date_end=2026-06-01`，且模板匹配
- **THEN** Agent 跳过表单，直接生成周报

#### Scenario: 参数缺失回退表单

- **WHEN** 周报 deep-link 只传入 `template_id` 但缺少 `date_start` 或 `date_end`
- **THEN** Agent 回退到正常的表单交互流程

---

### Requirement: 月报 deep-link 参数直达报告

月报 Agent SHALL 支持从 `<deep_link_params>` 块读取 `template_id` 和 `month` 参数。两个参数齐全且校验通过时，Agent SHALL 跳过全部 GenUI 交互表单，直接执行报告生成链路直到完成。

#### Scenario: 参数齐全直达月报

- **WHEN** 月报 deep-link 传入 `template_id=monthly-equipment`、`month=2026-06`，且模板匹配
- **THEN** Agent 跳过表单，直接生成月报

#### Scenario: 参数缺失回退表单

- **WHEN** 月报 deep-link 只传入 `template_id` 但缺少 `month`
- **THEN** Agent 回退到正常的表单交互流程
