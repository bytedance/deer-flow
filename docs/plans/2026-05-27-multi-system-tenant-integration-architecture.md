# 多系统租户级集成与共享数据接入层设计

> 版本: v1.0  
> 日期: 2026-05-27  
> 状态: Draft  
> 适用范围: DeerFlow 多租户工业场景下的外部系统接入架构  
> 相关文档:
> - [三层产品结构原则](../governance/three-layer-product-structure-principles.md)
> - [行业能力三层分类结论](../governance/industry-capability-layer-classification.md)
> - [平台能力配置模型](../governance/platform-capability-config-model.md)

---

## 1. 概述

当前系统已经接入部分 InS 能力，并计划继续接入 Sms，后续还可能引入 CRM、ERP 等系统。现状的主要问题是:

- 外部系统接入主要以 skill、shell 脚本或 sandbox 私有工具链方式存在
- 不同 agent 复用外部系统数据时，需要知道具体 skill、脚本路径或运行细节
- 数据源接入与业务分析逻辑耦合，难以扩展到 Sms、CRM、ERP 等新系统
- 租户配置、系统连接、能力路由、实体映射没有形成统一抽象

本设计的目标是将外部系统接入重构为三层结构:

1. 租户级连接器配置
2. 所有 agent 共用的数据源接入层
3. 外部系统本身，如 InS、Sms、CRM、ERP

最终效果是:

- agent 只调用平台统一能力
- 租户只配置“接什么系统、哪些能力走哪个系统”
- 外部系统只是能力提供者，而不是 agent 的直接依赖

---

## 2. 设计目标

### 2.1 Goals

- 支持 InS、Sms、CRM、ERP 等多系统按统一模式接入
- 支持租户级系统连接配置、能力路由配置和启停控制
- 建立所有 agent、report、skill 共用的数据访问层
- 将数据获取与分析逻辑解耦
- 支持跨系统实体映射，如设备、客户、工单、库存对象
- 支持后续继续增加新系统，而不改 agent 架构

### 2.2 Non-Goals

- 本设计不要求一次性替换所有现有 skill
- 本设计不要求立即废弃 sandbox 中的 features-tool
- 本设计不要求在 Phase 1 完成所有 CRM/ERP 业务域建模
- 本设计不要求当前所有能力都改为实时聚合，可保留渐进式迁移

---

## 3. 总体架构

```text
Agents / Skills / Reports / UI
        |
        v
Shared Data Access Layer
        |
        v
Tenant Integration Control Plane
        |
        v
External Systems
  - InS
  - Sms
  - CRM
  - ERP
```

统一调用链必须固定为:

```text
agent -> 平台能力 -> 租户路由/连接器 -> 外部系统
```

严禁长期形成如下调用链:

```text
agent -> 某个 skill 的 shell 脚本 -> 某个系统
```

这类链路可以作为兼容层存在，但不能继续作为平台主接入方式。

---

## 4. 三层职责划分

### 4.1 租户级连接器配置

这一层属于 Enterprise Control Plane，负责:

- 管理每个租户接入了哪些系统
- 管理系统连接参数、认证方式、密钥引用
- 管理能力到系统的路由关系
- 管理实体映射规则和人工校正关系
- 管理系统启停、超时、审计、回退策略

这一层回答的问题是:

- 这个租户是否接了 InS / Sms / CRM / ERP
- 这个租户的 `monitoring.trend` 应该走哪个系统
- 这个租户的 `asset.overview` 是否需要多系统聚合
- 这个租户的认证信息从哪里取

### 4.2 所有 agent 共用的数据源接入层

这一层属于 Core Platform 与 Industry Solution Layer 交界处的共享接入层，负责:

- 统一装载租户的系统配置和能力路由
- 调用各系统 adapter
- 将各系统响应映射为平台内部 canonical model
- 提供稳定的 capability service 给 agent、report、skill 复用
- 统一错误模型、审计模型、provenance 模型

这一层回答的问题是:

- 如何稳定地给 agent 提供 `monitoring_get_trend`
- 如何将 InS 和 Sms 的数据统一成一个设备视图
- 如何让新系统接入只补 adapter，而不是重写 agent

### 4.3 外部系统本身

这一层是被接入对象，不属于 DeerFlow 内部逻辑。其职责是提供数据和业务事实。

建议初始权威边界如下:

- InS
  - 设备树
  - 测点与测量通道
  - 趋势数据
  - 波形、频谱、轨迹
  - 报警与机器事件

- Sms
  - 异常统计
  - 健康评估
  - 风险评分
  - 排名与评估历史

- CRM
  - 客户信息
  - 合同
  - 服务对象归属
  - 装置/客户关系

- ERP
  - 工单
  - 备件与库存
  - 采购记录
  - 维修记录
  - 设备台账辅助信息

---

## 5. 租户级连接器配置模型

建议新增三类核心对象。

### 5.1 IntegrationSystem

表示“一个租户接入的一个外部系统实例”。

建议字段:

```yaml
tenant_id: acme
system_key: ins_prod
system_type: ins
display_name: "Acme InS Production"
base_url: https://ins.example.com
auth:
  type: bearer
  secret_ref: tenant://secrets/ins_token
timeout_seconds: 30
max_retries: 2
enabled: true
extra_config:
  factory_id: F1
  api_version: v1
```

说明:

- `system_key` 是租户内唯一标识
- `system_type` 决定由哪个 adapter 处理
- `secret_ref` 只引用密钥，不在配置中存明文
- `extra_config` 用于承接系统专属参数

### 5.2 CapabilityRoute

表示“某项平台能力由哪个系统提供”。

```yaml
tenant_id: acme
capability_key: monitoring.trend
primary_system_key: ins_prod
enrich_system_keys: []
fallback_system_keys: []
enabled: true
```

支持聚合能力:

```yaml
tenant_id: acme
capability_key: asset.overview
primary_system_key: ins_prod
enrich_system_keys:
  - sms_prod
  - erp_prod
fallback_system_keys: []
enabled: true
```

### 5.3 EntityLink

表示“平台统一实体与外部系统实体的映射关系”。

```yaml
tenant_id: acme
entity_type: asset
canonical_id: asset:241212010001718
links:
  - system_key: ins_prod
    remote_id: "241212010001718"
    confidence: 1.0
  - system_key: sms_prod
    remote_id: "P-101"
    confidence: 0.92
  - system_key: erp_prod
    remote_id: "EQ-000873"
    confidence: 0.95
```

没有这层，后续多系统聚合会失控。

### 5.4 建议 API

```text
GET    /api/tenants/{tenant_id}/integration-systems
POST   /api/tenants/{tenant_id}/integration-systems
PUT    /api/tenants/{tenant_id}/integration-systems/{system_key}
DELETE /api/tenants/{tenant_id}/integration-systems/{system_key}

GET    /api/tenants/{tenant_id}/capability-routes
PUT    /api/tenants/{tenant_id}/capability-routes/{capability_key}

GET    /api/tenants/{tenant_id}/entity-links
POST   /api/tenants/{tenant_id}/entity-links
PUT    /api/tenants/{tenant_id}/entity-links/{entity_type}/{canonical_id}
```

现有的 `/api/tenants/{tenant_id}/connectors` 可以保留，但建议定位为低层 HTTP 连接器，不再直接承担长期系统级集成模型。

---

## 6. 共享数据源接入层设计

建议新增以下目录结构:

```text
backend/packages/harness/deerflow/integrations/
  __init__.py
  errors.py
  registry.py
  routing.py
  provenance.py

  models/
    asset.py
    monitoring.py
    assessment.py
    customer.py
    maintenance.py

  adapters/
    base.py
    ins/
      adapter.py
      mapper.py
      models.py
    sms/
      adapter.py
      mapper.py
      models.py
    crm/
      adapter.py
      mapper.py
      models.py
    erp/
      adapter.py
      mapper.py
      models.py

  services/
    asset_service.py
    monitoring_service.py
    assessment_service.py
    customer_service.py
    maintenance_service.py
```

### 6.1 分层职责

- `adapters/`
  - 负责系统协议适配
  - 负责认证、超时、重试、响应校验、字段转换
  - 不向上暴露外部系统原始格式

- `models/`
  - 定义平台统一 canonical model
  - 供 services、agent tools、report 共同消费

- `services/`
  - 以平台能力为单位提供稳定接口
  - 内部按 `tenant_id + capability_key` 查路由
  - 再调用一个或多个 adapter

### 6.2 Canonical Model

建议最早落地以下模型:

- `Asset`
- `MeasurementPoint`
- `TrendSeries`
- `WaveformPayload`
- `AlarmEvent`
- `HealthAssessment`
- `CustomerProfile`
- `WorkOrder`
- `InventoryItem`

其中 `TrendSeries` 和 `WaveformPayload` 对 InS 是关键，`HealthAssessment` 对 Sms 是关键。

### 6.3 Adapter Contract

建议对外定义明确协议，避免每个系统接口随意扩张。

示例:

```python
class MonitoringAdapter(Protocol):
    async def get_trend(self, req: TrendQuery) -> TrendSeries: ...
    async def get_waveform(self, req: WaveformQuery) -> WaveformPayload: ...
    async def get_alarm_history(self, req: AlarmHistoryQuery) -> list[AlarmEvent]: ...
```

```python
class AssessmentAdapter(Protocol):
    async def get_health_assessment(self, req: HealthAssessmentQuery) -> HealthAssessment: ...
```

### 6.4 Service Contract

agent、report、skill 不应该知道系统名，只应该知道能力名。

建议服务层接口:

```python
class MonitoringService:
    async def get_trend(self, tenant_id: str, req: TrendQuery) -> TrendSeries: ...
    async def get_waveform(self, tenant_id: str, req: WaveformQuery) -> WaveformPayload: ...
    async def get_alarm_history(self, tenant_id: str, req: AlarmHistoryQuery) -> list[AlarmEvent]: ...
```

### 6.5 Provenance

每次返回都应带数据来源信息，便于 agent 和报告输出时解释“数据来自哪里”。

建议统一字段:

```yaml
provenance:
  source_system: ins_prod
  capability_key: monitoring.trend
  fetched_at: 2026-05-27T10:00:00Z
  partial_failures: []
```

如果是聚合能力:

```yaml
provenance:
  primary_system: ins_prod
  enrich_systems: [sms_prod]
  partial_failures:
    - system: sms_prod
      reason: timeout
```

### 6.6 错误模型

建议统一错误，而不是把各系统报错原样暴露到 agent。

错误分类建议:

- `IntegrationConfigError`
- `IntegrationAuthError`
- `IntegrationTimeoutError`
- `IntegrationUnavailableError`
- `IntegrationDataShapeError`
- `EntityLinkNotFoundError`
- `CapabilityRouteNotFoundError`

agent 和 report 只消费统一错误模型，不消费外部系统异常栈。

---

## 7. Agent / Skill / Report 的消费方式

### 7.1 Agent

未来 agent 不应该再长期写死:

```text
bash /mnt/skills/custom/ins-get-waveform-data/scripts/run.sh ...
```

建议由平台内建统一工具暴露能力，例如:

- `asset_get_catalog`
- `equipment_get_context`
- `monitoring_get_trend`
- `monitoring_get_waveform`
- `monitoring_get_alarm_history`
- `health_get_assessment`
- `crm_get_customer_profile`
- `erp_get_work_orders`

这些 built-in tools 的内部调用 shared service，而不是直接调 skill 脚本。

### 7.2 Skill

skill 可以继续存在，但定位改变为:

- 负责流程 orchestration
- 负责分析、规则、解释、报告拼装
- 不再承担系统接入的唯一入口

### 7.3 Report

report scripts 同样不应再私有持有 InS 接入逻辑。更合理的方式是:

- report script 调 shared service
- service 再决定走 InS 还是 Sms
- 输出中带 provenance 和 data_source

---

## 8. InS 的重构方向

### 8.1 当前问题

当前 InS 接入链路分散在以下位置:

- `docker/sandbox/features-tool/ins/client.py`
- `docker/sandbox/features-tool/tools/get_waveform_data_tool.py`
- `skills/custom/ins-get-waveform-data/scripts/run.sh`
- `skills/custom/data-analyst/scripts/_ins_provider.py`
- 多个 `ins-*` skill 和 agent SOUL 中的 shell 调用

当前模式的问题:

- 接入能力是 sandbox 私有链路
- 上层需要知道脚本路径和 shell 用法
- InS client 与具体分析 skill 耦合
- 不利于未来给 Sms、CRM、ERP 复用同一架构

### 8.2 目标

将 InS 改造成第一个标准 adapter:

```text
InS -> InSAdapter -> MonitoringService / AssetService -> Agent / Report / Skill
```

### 8.3 迁移建议

Phase 1:

- 抽出 `InSAdapter`
- 保留现有 `features-tool` 作为兼容 wrapper
- 新 built-in tool 走 `MonitoringService`

Phase 2:

- `data-analyst` 的 `_ins_provider.py` 改走 shared service
- `ins-get-*` skills 改成兼容层
- 逐步从 SOUL 中移除 shell 直连路径

Phase 3:

- 仅保留少数算法型 sandbox wrapper
- 外部系统访问统一走 shared service

### 8.4 兼容策略

短期内允许保留:

- `run.sh`
- `ins-get-waveform-data`
- `ins-get-orbit-data`
- `features-tool` 内部专用工具

但这些都应成为 compatibility layer，而不是平台唯一接入面。

---

## 9. Sms、CRM、ERP 的接入约定

### 9.1 Sms

建议优先接入以下能力:

- `health.assessment`
- `health.risk-ranking`
- `monitoring.anomaly-statistics`

Sms 不建议直接定义设备主数据，而是通过 `EntityLink` 关联到平台统一 `Asset`。

### 9.2 CRM

建议优先接入以下能力:

- `customer.profile`
- `customer.contracts`
- `customer.asset-ownership`

CRM 应作为客户关系和服务对象权威源，不应定义实时监测数据。

### 9.3 ERP

建议优先接入以下能力:

- `maintenance.work-order`
- `maintenance.history`
- `inventory.stock`
- `inventory.spare-parts`

ERP 应作为工单与库存权威源，不应承担实时趋势和波形能力。

---

## 10. 能力路由建议

建议将平台能力按域命名，避免以后按系统命名。

推荐第一批 capability keys:

- `asset.catalog`
- `asset.context`
- `asset.overview`
- `monitoring.trend`
- `monitoring.waveform`
- `monitoring.orbit`
- `monitoring.alarm_history`
- `health.assessment`
- `health.risk_ranking`
- `customer.profile`
- `maintenance.work_order`
- `inventory.stock`

这层命名一旦确定，应尽量保持稳定，因为它将成为所有 agent 的长期契约。

---

## 11. 安全与治理要求

### 11.1 安全

- 外部系统密钥只允许通过 `secret_ref` 引用
- adapter 必须在边界校验第三方响应
- 任何外部系统返回都视为不可信输入
- 审计日志记录 `tenant_id`、`system_key`、`capability_key`
- 必须支持超时、重试、限流和错误降级

### 11.2 治理

- 新系统接入必须先定义 adapter contract
- 新 capability key 必须先评审，再开放给 agent
- 任何系统级字段不得直接上浮为公共契约
- capability routing 变更应纳入租户审计

---

## 12. 推荐实施顺序

### Phase 0: 模型与边界定稿

- 定义 `IntegrationSystem`
- 定义 `CapabilityRoute`
- 定义 `EntityLink`
- 定义第一版 capability keys

### Phase 1: InS 标准化

- 创建 `integrations/adapters/ins`
- 创建 `asset_service.py`、`monitoring_service.py`
- 提供统一 built-in tools
- 保留现有 `ins-*` skill 兼容

### Phase 2: Sms 接入

- 创建 `integrations/adapters/sms`
- 创建 `assessment_service.py`
- 打通 `health.assessment`

### Phase 3: CRM / ERP 接入

- 创建 `crm` / `erp` adapters
- 打通 `customer.profile`、`maintenance.work_order`
- 建立更完整的实体映射和聚合视图

### Phase 4: 上层迁移

- agent SOUL 从 shell 直连迁移到统一能力
- report scripts 改为调用 shared service
- skill 保留流程价值，弱化系统接入价值

---

## 13. 最终目标状态

最终应达到以下状态:

- 租户管理员配置系统连接和能力路由
- 所有 agent 共用同一套数据访问能力
- InS、Sms、CRM、ERP 都是 adapter 插件
- 新系统接入不需要重写 agent 架构
- 外部系统变化被限制在 adapter 层

最终的上层体验应是:

```text
agent 只知道:
- 我需要什么能力

平台只知道:
- 这个租户把这个能力路由给哪个系统

adapter 只知道:
- 如何把系统数据转成平台标准模型
```

这才是 DeerFlow 面向多系统、可持续演进的长期接入架构。

---

## 14. 后续建议

建议紧接着补两份文档:

1. `InS adapter 落地设计`
   - 明确如何从现有 `features-tool` 抽出共享 adapter
   - 明确兼容层保留范围

2. `Capability Keys 与 Canonical Models 清单`
   - 明确首批对外开放的能力名
   - 明确统一数据模型字段

这两份文档完成后，就可以进入 InS 第一阶段改造实施。
