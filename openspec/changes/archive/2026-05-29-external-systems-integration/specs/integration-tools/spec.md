## ADDED Requirements

### Requirement: Integration tools for Agent consumption

The system SHALL define LangChain `@tool` decorated functions in `deerflow/integrations/tools/` that wrap service methods for Agent consumption. Each tool SHALL:

1. Accept Agent-friendly parameters
2. Call the corresponding service method
3. Format the canonical model result as a human-readable Chinese string
4. Handle errors gracefully with user-friendly messages

Tool categories:

**Asset tools** (`deerflow/integrations/tools/asset_tools.py`):

- `asset_get_catalog` — wraps `AssetService.get_catalog()`
- `equipment_get_context` — wraps `AssetService.get_context()`
- `equipment_get_overview` — wraps `AssetService.get_overview()`, returns composite view with asset info, health status, and recent alarms

**Monitoring tools** (`deerflow/integrations/tools/monitoring_tools.py`):

- `monitoring_get_trend` — wraps `MonitoringService.get_trend()`
- `monitoring_get_waveform` — wraps `MonitoringService.get_waveform()`
- `monitoring_get_orbit` — wraps `MonitoringService.get_orbit()`
- `monitoring_get_alarm_history` — wraps `MonitoringService.get_alarm_history()`

**Assessment tools** (`deerflow/integrations/tools/assessment_tools.py`):

- `health_get_assessment` — wraps `AssessmentService.get_health_assessment()`
- `health_get_anomaly_statistics` — wraps `AssessmentService.get_anomaly_statistics()`
- `health_get_risk_ranking` — wraps `AssessmentService.get_risk_ranking()`

#### Scenario: Tool formats TrendSeries as Chinese text

- **WHEN** `monitoring_get_trend` returns a `TrendSeries`
- **THEN** output is formatted as:

  ```
  设备 P-101A 振动水平趋势 [来源: ins_prod]:
  - 时间范围: 2026-05-20 ~ 2026-05-27，聚合: 小时级
  - 最大值: 5.12 mm/s
  - 平均值: 3.67 mm/s
  - 数据点: 168 个
  ```

#### Scenario: Tool formats HealthAssessment

- **WHEN** `health_get_assessment` returns a `HealthAssessment`
- **THEN** output is formatted as:

  ```
  设备 P-101A 健康评估 [来源: sms_prod]:
  - 评分: 82.5/100 (medium_risk)
  - 评估时间: 2026-05-27T10:00:00Z
  - 摘要: 设备存在中等风险，建议重点关注驱动端振动与轴承温度
  - 维度评分: 振动 74.0, 温度 88.0, 工艺稳定性 83.0
  - 风险项: 驱动端振动近 7 日持续升高 (medium)
  - 建议: 检查联轴器对中; 复核轴承润滑状态
  ```

#### Scenario: Tool formats AssetContext

- **WHEN** `equipment_get_context` returns an `AssetContext`
- **THEN** output includes asset info, children, measurement points:

  ```
  设备 P-101A 上下文 [来源: ins_prod]:
  - 类型: centrifugal_pump (原料泵)
  - 区域: 常减压装置 / 2#泵区
  - 状态: active
  - 子设备: 2 个
  - 测点: 8 个 (振动×4, 温度×2, 转速×1, 位移×1)
  ```

#### Scenario: Tool formats AssetOverview

- **WHEN** `equipment_get_overview` returns an `AssetOverview`
- **THEN** output includes combined asset, health, and alarm data:

  ```
  设备 P-101A 综合概览 [主要来源: ins_prod, 补充来源: sms_prod]:
  - 类型: centrifugal_pump (原料泵)
  - 区域: 常减压装置 / 2#泵区
  - 状态: active
  - 健康评分: 82.5/100 (medium_risk)
  - 健康摘要: 设备存在中等风险，建议重点关注驱动端振动与轴承温度
  - 维度评分: 振动 74.0, 温度 88.0, 工艺稳定性 83.0
  - 风险项: 驱动端振动近 7 日持续升高 (medium)
  - 近期报警: 2 条
    - [2026-05-27 08:30] 驱动端振动超阈值 (high)
    - [2026-05-26 14:15] 轴承温度预警 (warning)
  ```

#### Scenario: Tool formats AssetOverview with Sms unavailable

- **WHEN** `equipment_get_overview` returns an `AssetOverview` with `health=None`
- **THEN** the health section shows: `"健康评估: 数据暂不可用"`
- **THEN** the output includes `[⚠️ sms_prod 数据暂不可用]`

#### Scenario: Tool handles errors

- **WHEN** service raises `RouteNotFoundError`
- **THEN** tool returns `"该能力未配置路由，请联系管理员"`
- **WHEN** service raises `IntegrationError`
- **THEN** tool returns `"所有系统均不可用，请稍后重试"`
- **WHEN** service raises `IntegrationAuthError`
- **THEN** tool returns `"外部系统认证失败，请联系管理员"`
- **WHEN** service raises `IntegrationTimeoutError`
- **THEN** tool returns `"外部系统响应超时，请稍后重试"`
- **WHEN** service raises `IntegrationUnavailableError`
- **THEN** tool returns `"外部系统暂不可用，请稍后重试"`
- **WHEN** service raises `AdapterError(..., "equipment_not_found")`
- **THEN** tool returns `"未找到设备 {asset_id}"`

#### Scenario: Tool docstring describes capability

- **WHEN** the Agent receives the tool schema
- **THEN** `monitoring_get_trend`'s description says "查询设备趋势数据（振动、温度、转速等）"
- **THEN** it does NOT say "calls Ins adapter via CapabilityRouter"

### Requirement: Tool output includes provenance

Every tool output SHALL include the source system and fetch timestamp, so the Agent can cite data provenance in its responses.

#### Scenario: Provenance in output

- **WHEN** `asset_get_catalog` returns results from `ins_prod`
- **THEN** the output includes `[来源: ins_prod, 获取时间: 2026-05-27T10:30:00Z]`

#### Scenario: Enrich provenance

- **WHEN** `equipment_get_context` returns primary data from `ins_prod` enriched with `sms_prod`
- **THEN** the output includes `[主要来源: ins_prod, 补充来源: sms_prod]`

#### Scenario: Partial failure provenance

- **WHEN** enrich from `sms_prod` fails
- **THEN** the output includes `[来源: ins_prod, ⚠️ sms_prod 数据暂不可用]`

### Requirement: Capability system integration

The system SHALL extend `CapabilityType` in `app/gateway/routers/capabilities.py` with `INTEGRATION_SYSTEM = "integration_system"`. The `list_capabilities` endpoint SHALL include integration systems.

Each integration system SHALL appear as a `CapabilitySummary` with:

- `name`: system_key (e.g. `"ins_prod"`, `"sms_prod"`)
- `type`: `INTEGRATION_SYSTEM`
- `display_name`: human-readable name
- `description`: system description
- `scope`: `GLOBAL`
- `status`: `enabled` if healthy, `disabled` if unhealthy
- `tags`: list of supported capability keys

#### Scenario: Integration system in capabilities list

- **WHEN** `GET /api/capabilities` is called and `ins_prod` is configured and healthy
- **THEN** response includes `CapabilitySummary(name="ins_prod", type="integration_system", status="enabled", tags=["asset.catalog", "asset.context", "monitoring.trend", "monitoring.waveform", "monitoring.orbit", "monitoring.alarm_history"])`

#### Scenario: Filter by integration_system type

- **WHEN** `GET /api/capabilities?type=integration_system` is called
- **THEN** only integration system entries are returned
