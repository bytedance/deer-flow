## ADDED Requirements

### Requirement: INS Provider 封装

系统 SHALL 提供 `InsProvider` 类，封装 INS REST API 的调用逻辑，包括认证、租户隔离、响应格式化和错误处理。Provider SHALL 基于 `HttpConnectorConfig` 构建，复用 `http_connector_tool` 的基础设施。

#### Scenario: Provider 初始化

- **WHEN** Agent 首次调用任一 INS 工具
- **THEN** 系统从 `http_connectors` 配置中获取当前租户的 INS 连接器配置，创建 `InsProvider` 实例，绑定 `tenant_id` 和认证信息

#### Scenario: INS 连接器未配置

- **WHEN** 当前租户的 `http_connectors` 中未配置 INS 连接器
- **THEN** 工具 SHALL 返回明确的错误信息："INS connector not configured for this tenant. Please contact administrator."

#### Scenario: Provider 认证失败

- **WHEN** INS API 返回 401/403 状态码
- **THEN** Provider SHALL 记录错误日志（包含 tenant_id 和 connector_name），并向 Agent 返回 "INS authentication failed. Check API credentials."

### Requirement: ins_get_device_detail 工具

系统 SHALL 提供 `ins_get_device_detail` 工具，接收 `device_id` 参数，调用 INS REST API 获取设备详情，返回结构化的设备信息（名称、型号、测点列表、各测点阈值）。

#### Scenario: 查询存在的设备

- **WHEN** Agent 调用 `ins_get_device_detail(device_id="P-101")` 且该设备存在于 INS 中
- **THEN** 工具 SHALL 返回格式化的设备信息文本，包含设备名称、型号、所属装置、测点列表（测点名、量程、单位、报警阈值）

#### Scenario: 查询不存在的设备

- **WHEN** Agent 调用 `ins_get_device_detail(device_id="INVALID")` 且该设备不存在
- **THEN** 工具 SHALL 返回 "Device 'INVALID' not found. Use DeviceSelectorBlock to select a valid device."

#### Scenario: 输入参数验证

- **WHEN** Agent 调用 `ins_get_device_detail` 时 `device_id` 为空或格式不合法
- **THEN** 工具 SHALL 返回参数验证错误信息，不发起 INS API 请求

### Requirement: ins_get_measurement_trend 工具

系统 SHALL 提供 `ins_get_measurement_trend` 工具，接收 `point_id` 和 `time_range` 参数，返回测点在指定时间范围内的趋势摘要（非全量时间序列）。

#### Scenario: 查询测点趋势

- **WHEN** Agent 调用 `ins_get_measurement_trend(point_id="P-101-VA", time_range="7d")`
- **THEN** 工具 SHALL 返回趋势摘要：最大值、最小值、平均值、标准差、异常点数量、最近值，以及最多 10 个异常点的时间戳和值

#### Scenario: 支持的时间范围

- **WHEN** Agent 传入 `time_range` 参数
- **THEN** 工具 SHALL 支持以下枚举值：`1h`（1小时）、`24h`（24小时）、`7d`（7天）、`30d`（30天）、`90d`（90天）。其他值 SHALL 返回参数验证错误

#### Scenario: 数据量控制

- **WHEN** INS 返回的趋势数据超过 100 个数据点
- **THEN** Provider SHALL 仅返回统计摘要和异常点，不返回全量时间序列，避免撑爆 Agent 上下文窗口

### Requirement: ins_get_vibration_spectrum 工具

系统 SHALL 提供 `ins_get_vibration_spectrum` 工具，接收 `device_id` 和可选的 `timestamp` 参数，返回设备的振动频谱特征数据。

#### Scenario: 查询最新频谱

- **WHEN** Agent 调用 `ins_get_vibration_spectrum(device_id="P-101")` 不指定 `timestamp`
- **THEN** 工具 SHALL 返回最近一次采集的振动频谱数据：主要频率分量（频率、幅值）、总振值（RMS）、是否超标

#### Scenario: 查询历史频谱

- **WHEN** Agent 调用 `ins_get_vibration_spectrum(device_id="P-101", timestamp="2026-05-25T10:00:00")`
- **THEN** 工具 SHALL 返回指定时间点的频谱数据，若该时间点无数据则返回最近的一次

#### Scenario: 频谱数据格式化

- **WHEN** Provider 从 INS 获取频谱原始数据
- **THEN** Provider SHALL 将数据格式化为 Agent 友好的文本：列出 Top 5 频率分量（频率 Hz + 幅值 mm/s），标注是否超过 ISO 10816 阈值

### Requirement: ins_get_alarm_history 工具

系统 SHALL 提供 `ins_get_alarm_history` 工具，接收 `device_id` 和可选的 `limit` 参数，返回设备的历史报警记录。

#### Scenario: 查询历史报警

- **WHEN** Agent 调用 `ins_get_alarm_history(device_id="P-101", limit=10)`
- **THEN** 工具 SHALL 返回最近 10 条报警记录，每条包含：时间、报警类型、严重等级、描述、持续时长

#### Scenario: 默认 limit

- **WHEN** Agent 调用 `ins_get_alarm_history(device_id="P-101")` 不指定 `limit`
- **THEN** 工具 SHALL 默认返回最近 20 条报警记录

#### Scenario: 无报警记录

- **WHEN** 指定设备在 INS 中无报警记录
- **THEN** 工具 SHALL 返回 "No alarm history found for device 'P-101'."

### Requirement: ins_get_peer_comparison 工具

系统 SHALL 提供 `ins_get_peer_comparison` 工具，接收 `device_id` 参数，返回同型号设备的运行指标对比数据。

#### Scenario: 同类对标查询

- **WHEN** Agent 调用 `ins_get_peer_comparison(device_id="P-101")`
- **THEN** 工具 SHALL 返回：同型号设备总数、当前设备在同类中的排名百分位、关键指标对比（振动值、温度、运行时长）与同类平均值的偏差

#### Scenario: 同类设备不足

- **WHEN** 同型号设备数量少于 3 台
- **THEN** 工具 SHALL 返回 "Insufficient peer devices for comparison (found 2, minimum 3 required)."

### Requirement: 租户隔离

所有 INS 工具 SHALL 强制执行租户隔离。每个工具调用 SHALL 使用 `get_current_tenant_id()` 获取当前租户，仅访问该租户的 INS 数据。

#### Scenario: 跨租户隔离

- **WHEN** 租户 A 的 Agent 调用 `ins_get_device_detail(device_id="P-101")`
- **THEN** 工具 SHALL 仅使用租户 A 的 INS 连接器配置（URL、认证），仅返回租户 A 有权访问的设备数据

#### Scenario: 租户上下文缺失

- **WHEN** 工具调用时 `get_current_tenant_id()` 返回空值
- **THEN** 工具 SHALL 返回 "Tenant context not available. Ensure authentication is configured."

### Requirement: 工具注册与发现

INS 工具 SHALL 通过 `get_available_tools()` 自动注册，所有 Agent 均可使用，无需在 Agent 配置中显式声明。

#### Scenario: 工具自动注册

- **WHEN** 系统启动且 `config.yaml` 中配置了 INS 连接器
- **THEN** `get_available_tools()` 返回的工具列表 SHALL 包含 5 个 INS 工具

#### Scenario: 工具未配置时不注册

- **WHEN** 系统启动但 `config.yaml` 中未配置 INS 连接器
- **THEN** `get_available_tools()` 返回的工具列表 SHALL 不包含 INS 工具，且不影响其他工具的加载

#### Scenario: 与其他工具共存

- **WHEN** INS 工具与 `http_connector_tool`、MCP 工具同时存在
- **THEN** 三类工具 SHALL 在 `get_available_tools()` 返回的列表中正常共存，通过工具名去重

### Requirement: 错误处理与降级

INS 工具 SHALL 在所有异常情况下返回 Agent 可理解的错误信息，不抛出未捕获的异常。

#### Scenario: INS API 超时

- **WHEN** INS API 在配置的 `timeout_seconds` 内未响应
- **THEN** 工具 SHALL 返回 "INS service timeout after {N}s. Please try again later or provide data manually."

#### Scenario: INS API 返回非 JSON

- **WHEN** INS API 返回的响应不是合法 JSON
- **THEN** Provider SHALL 记录警告日志，工具返回 "INS returned unexpected response format. Contact administrator."

#### Scenario: 网络不可达

- **WHEN** INS API 因网络原因不可达
- **THEN** 工具 SHALL 返回 "INS service unreachable. Check network connectivity."，不重试超过配置的 `max_retries`
