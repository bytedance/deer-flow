## ADDED Requirements

### Requirement: 模板 DSL 扩展 ins_data_requirements

报告模板 DSL SHALL 支持可选的 `ins_data_requirements` 字段，声明模板运行时需要从 INS 获取的数据。该字段 SHALL 为数组，每个元素指定一个 INS 工具调用及其参数绑定来源。

#### Scenario: 声明 INS 数据需求

- **WHEN** 模板 DSL 包含 `ins_data_requirements` 字段
- **THEN** 系统 SHALL 解析每个条目的 `tool`（INS 工具名）、`bind_from`（表单字段路径）、`params`（静态参数），在模板运行时按声明调用对应工具

#### Scenario: 未声明时不影响现有模板

- **WHEN** 模板 DSL 不包含 `ins_data_requirements` 字段
- **THEN** 模板 SHALL 按现有逻辑正常运行，不触发任何 INS 工具调用

#### Scenario: bind_from 字段解析

- **WHEN** `ins_data_requirements` 条目的 `bind_from` 为 `form_steps.select_device.device_id`
- **THEN** 系统 SHALL 从表单步骤 `select_device` 的输出中提取 `device_id` 字段的值，作为工具调用的参数

### Requirement: 运行时自动注入 INS 数据

当报告模板执行时，系统 SHALL 根据 `ins_data_requirements` 声明，自动调用 INS 工具并将结果注入到 Agent 上下文中。

#### Scenario: 表单提交后自动获取数据

- **WHEN** 用户在报告模板表单中选择了设备并提交表单
- **THEN** 系统 SHALL 按 `ins_data_requirements` 中的声明顺序，依次调用 INS 工具，将所有结果合并为结构化的上下文文本，注入到 Agent 的后续对话中

#### Scenario: 部分工具调用失败

- **WHEN** `ins_data_requirements` 声明了 3 个工具调用，其中 1 个因 INS 超时失败
- **THEN** 系统 SHALL 将成功获取的 2 个结果注入 Agent 上下文，对失败的工具返回错误信息（"数据获取失败: {工具名}"），不阻断报告生成流程

#### Scenario: 数据注入格式

- **WHEN** INS 工具返回结果
- **THEN** 系统 SHALL 以 `<ins_data tool="{tool_name}">` 标签包裹的方式注入 Agent 上下文，便于 Agent 识别数据来源

### Requirement: 模板编辑器支持 INS 数据字段

报告模板可视化编辑器 SHALL 支持配置 `ins_data_requirements` 字段，允许模板作者通过 UI 添加 INS 数据需求。

#### Scenario: 编辑器添加 INS 数据需求

- **WHEN** 模板作者在编辑器中点击"添加 INS 数据源"按钮
- **THEN** 编辑器 SHALL 显示可用 INS 工具列表，作者选择工具后可配置参数绑定（从表单步骤字段中选择）和静态参数

#### Scenario: 编辑器验证

- **WHEN** 模板作者配置了 `bind_from` 指向不存在的表单步骤
- **THEN** 编辑器 SHALL 显示验证错误："引用的表单步骤不存在"

#### Scenario: YAML 同步

- **WHEN** 模板作者通过编辑器 UI 修改 `ins_data_requirements`
- **THEN** YAML 编辑器 SHALL 同步更新 DSL 的 `ins_data_requirements` 段，保持双向编辑一致性

### Requirement: 数据获取时机控制

系统 SHALL 支持配置 INS 数据的获取时机：表单提交时（`on_submit`）或报告生成前（`before_generation`）。

#### Scenario: on_submit 模式

- **WHEN** `ins_data_requirements` 条目的 `fetch_timing` 为 `on_submit`（默认值）
- **THEN** 系统 SHALL 在用户提交表单后立即调用 INS 工具获取数据

#### Scenario: before_generation 模式

- **WHEN** `ins_data_requirements` 条目的 `fetch_timing` 为 `before_generation`
- **THEN** 系统 SHALL 在报告生成流程启动前调用 INS 工具获取数据（适用于需要最新数据的场景）

### Requirement: 数据缓存与去重

同一报告运行中，系统 SHALL 对相同的 INS 工具调用进行缓存和去重，避免重复请求。

#### Scenario: 相同参数去重

- **WHEN** `ins_data_requirements` 中有 2 个条目调用 `ins_get_device_detail` 且参数相同
- **THEN** 系统 SHALL 仅发起 1 次 INS API 调用，2 个条目共享同一结果

#### Scenario: 运行内缓存

- **WHEN** 同一报告运行中，Agent 在对话中再次调用已获取过的 INS 工具（相同参数）
- **THEN** 系统 SHALL 返回缓存结果（受 `cache_ttl_seconds` 配置控制），不重复请求 INS API
