## ADDED Requirements

### Requirement: 诊断 Skill SOUL.md 声明 INS 数据获取流程

设备诊断 Skill（`device-diagnosis`）的 SOUL.md SHALL 声明标准的 INS 数据获取工作流，引导 Agent 按步骤调用 INS 工具完成诊断。

#### Scenario: 标准诊断流程

- **WHEN** Agent 接收到设备诊断任务
- **THEN** Agent SHALL 按 SOUL.md 声明的顺序执行：(1) 确认设备 ID（通过 GenUI DeviceSelectorBlock 或用户输入），(2) 调用 `ins_get_device_detail` 获取设备基础信息，(3) 调用 `ins_get_alarm_history` 获取历史报警，(4) 调用 `ins_get_vibration_spectrum` 获取振动频谱，(5) 综合分析并输出诊断结论

#### Scenario: 设备 ID 缺失时引导用户

- **WHEN** Agent 接收到诊断任务但未提供设备 ID
- **THEN** Agent SHALL 渲染 GenUI `DeviceSelectorBlock` 组件，引导用户从 INS 设备树中选择目标设备

#### Scenario: INS 工具不可用时降级

- **WHEN** INS 工具调用失败（超时/不可达）
- **THEN** Agent SHALL 告知用户 INS 数据暂时不可用，并请求用户手动提供关键数据（振动值、温度、报警信息），基于用户提供的数据继续诊断

### Requirement: 监测分析 Skill 声明 INS 数据获取流程

监测分析 Skill（`monitoring-analysis`）的 SOUL.md SHALL 声明 INS 数据获取步骤，支持 Agent 在监测场景中查询设备实时状态和历史趋势。

#### Scenario: 设备状态查询

- **WHEN** 用户要求查询某台设备的运行状态
- **THEN** Agent SHALL 调用 `ins_get_device_detail` 获取设备信息，调用 `ins_get_measurement_trend` 获取关键测点的 24 小时趋势，综合判断设备当前状态

#### Scenario: 多设备批量监测

- **WHEN** 用户要求监测多台设备
- **THEN** Agent SHALL 对每台设备分别调用 `ins_get_device_detail` 和 `ins_get_measurement_trend`，汇总输出各设备状态对比表

#### Scenario: 同类对标分析

- **WHEN** 用户要求评估某台设备在同类中的表现
- **THEN** Agent SHALL 调用 `ins_get_peer_comparison` 获取同类对标数据，输出该设备在同类中的排名和关键指标偏差

### Requirement: 趋势报告 Skill 声明 INS 数据获取流程

趋势报告 Skill（`trend-report`）的 SOUL.md SHALL 声明 INS 数据获取步骤，支持 Agent 在生成报告时自动获取设备趋势数据。

#### Scenario: 日报生成

- **WHEN** 用户要求生成某设备的日报
- **THEN** Agent SHALL 调用 `ins_get_measurement_trend(time_range="24h")` 获取过去 24 小时的趋势数据，调用 `ins_get_alarm_history(limit=50)` 获取当日报警记录，综合生成日报内容

#### Scenario: 月报生成

- **WHEN** 用户要求生成某设备的月报
- **THEN** Agent SHALL 调用 `ins_get_measurement_trend(time_range="30d")` 获取月度趋势，调用 `ins_get_alarm_history(limit=100)` 获取月度报警统计，调用 `ins_get_peer_comparison` 获取同类对标，综合生成月报内容

#### Scenario: 报告模板集成

- **WHEN** 趋势报告通过报告模板生成（模板声明了 `ins_data_requirements`）
- **THEN** Agent SHALL 使用模板自动注入的 INS 数据，不重复调用 INS 工具

### Requirement: Skill 工具引用规范

所有工业 Skill 的 SOUL.md SHALL 使用标准化的工具引用格式声明 INS 工具依赖，便于 Agent 解析和执行。

#### Scenario: 工具引用格式

- **WHEN** SOUL.md 中引用 INS 工具
- **THEN** SHALL 使用以下格式：`<tool>ins_get_device_detail</tool>`，并在引用后说明参数来源和预期输出

#### Scenario: 工具可用性检查

- **WHEN** Agent 加载 Skill 时检查工具可用性
- **THEN** 若 INS 工具未注册（INS 连接器未配置），Agent SHALL 在 SOUL.md 引导下跳过 INS 数据获取步骤，使用降级策略

### Requirement: 自定义 Skill 的 INS 工具引用

用户创建的自定义 Skill SHALL 能够引用 INS 工具，与内置工业 Skill 享有相同的工具访问权限。

#### Scenario: 自定义 Skill 使用 INS 工具

- **WHEN** 用户在自定义 Skill 的 SOUL.md 中引用 `ins_get_device_detail` 工具
- **THEN** Agent SHALL 正常调用该工具，无需额外配置

#### Scenario: 自定义 Skill 组合 INS 与通用工具

- **WHEN** 自定义 Skill 的 SOUL.md 同时引用 INS 工具（如 `ins_get_alarm_history`）和通用工具（如 `web_search`）
- **THEN** Agent SHALL 在单次对话中交替使用两类工具，互不干扰
