# Capability Keys 与 Canonical Models 清单

> 版本: v1.0  
> 日期: 2026-05-27  
> 状态: Draft  
> 相关文档:
> - [多系统租户级集成与共享数据接入层设计](./2026-05-27-multi-system-tenant-integration-architecture.md)
> - [InS Adapter 平台化改造实施方案](./2026-05-27-ins-adapter-implementation-plan.md)

---

## 1. 概述

为了让 InS、Sms、CRM、ERP 等系统都能通过统一方式被 agent、report、skill 使用，平台必须先固定两件事情:

1. 对上暴露哪些稳定的 capability keys
2. 这些 capability 返回什么 canonical models

这份文档用于定义首批长期稳定契约。

---

## 2. 设计原则

### 2.1 Capability key 面向能力，不面向系统

正确:

- `monitoring.trend`
- `health.assessment`
- `maintenance.work_order`

错误:

- `ins.get_trend`
- `sms.get_health_score`
- `erp.get_ticket`

系统名只能存在于 routing/config 层，不能成为上层长期契约。

### 2.2 Canonical model 面向平台，不面向源系统

正确:

- `Asset`
- `TrendSeries`
- `WaveformPayload`
- `HealthAssessment`

错误:

- `InSPointConfig`
- `SmsScoreRaw`
- `ErpTicketVo`

### 2.3 外部系统字段不直接上浮

外部系统的原始字段、路径、枚举值可以保存在:

- `source_metadata`
- `provenance`
- `adapter_debug`

但不能直接成为上层 contract 核心字段。

---

## 3. Capability Key 命名规则

统一规则:

```text
<domain>.<capability>
```

推荐 domain:

- `asset`
- `monitoring`
- `health`
- `customer`
- `maintenance`
- `inventory`

命名要求:

- 全小写
- 用 `.` 分隔域和能力
- 避免系统名
- 避免 UI 词汇，如 `page`、`widget`
- 避免实现细节词汇，如 `rpc`、`shell`

---

## 4. 第一批 Capability Keys

### 4.1 Asset 域

| capability key | 说明 | 典型提供方 |
|---|---|---|
| `asset.catalog` | 设备目录、层级、筛选能力 | InS |
| `asset.context` | 单设备上下文，含测点、类型、区域、子设备 | InS |
| `asset.overview` | 单设备综合视图，支持多系统 enrich | InS + Sms + ERP |
| `asset.entity_links` | 统一实体与各系统实体映射关系 | 平台 |

### 4.2 Monitoring 域

| capability key | 说明 | 典型提供方 |
|---|---|---|
| `monitoring.trend` | 趋势时序 | InS |
| `monitoring.waveform` | 原始波形和频谱 | InS |
| `monitoring.orbit` | 轴心轨迹 | InS |
| `monitoring.alarm_history` | 报警/事件历史 | InS |
| `monitoring.point_catalog` | 测点目录 | InS |

### 4.3 Health 域

| capability key | 说明 | 典型提供方 |
|---|---|---|
| `health.assessment` | 健康评估结果 | Sms |
| `health.risk_ranking` | 风险排名 | Sms |
| `health.anomaly_statistics` | 异常统计 | Sms |

### 4.4 Customer 域

| capability key | 说明 | 典型提供方 |
|---|---|---|
| `customer.profile` | 客户主档 | CRM |
| `customer.contracts` | 合同与服务关系 | CRM |
| `customer.asset_ownership` | 客户与设备归属关系 | CRM |

### 4.5 Maintenance 域

| capability key | 说明 | 典型提供方 |
|---|---|---|
| `maintenance.work_order` | 工单详情 | ERP |
| `maintenance.work_order_history` | 工单历史 | ERP |
| `maintenance.repair_record` | 维修记录 | ERP |

### 4.6 Inventory 域

| capability key | 说明 | 典型提供方 |
|---|---|---|
| `inventory.stock` | 库存查询 | ERP |
| `inventory.spare_parts` | 备件明细 | ERP |

---

## 5. 第一批 Agent Tool 建议名

上面的 capability keys 是平台内部契约。  
对 agent 暴露的 built-in tool 名，建议更贴近自然语言使用，但一一映射 capability。

| Agent tool | capability key |
|---|---|
| `asset_get_catalog` | `asset.catalog` |
| `equipment_get_context` | `asset.context` |
| `equipment_get_overview` | `asset.overview` |
| `monitoring_get_trend` | `monitoring.trend` |
| `monitoring_get_waveform` | `monitoring.waveform` |
| `monitoring_get_orbit` | `monitoring.orbit` |
| `monitoring_get_alarm_history` | `monitoring.alarm_history` |
| `health_get_assessment` | `health.assessment` |
| `health_get_anomaly_statistics` | `health.anomaly_statistics` |
| `crm_get_customer_profile` | `customer.profile` |
| `erp_get_work_orders` | `maintenance.work_order` |

---

## 6. Canonical Models 总览

首批建议落以下模型:

- `Asset`
- `MeasurementPoint`
- `AssetContext`
- `TrendSeries`
- `WaveformPayload`
- `OrbitPayload`
- `AlarmEvent`
- `HealthAssessment`
- `CustomerProfile`
- `WorkOrder`
- `InventoryItem`
- `EntityLink`
- `Provenance`

---

## 7. Asset 相关模型

### 7.1 Asset

```yaml
id: asset:241212010001718
name: P-101A
display_name: P-101A 原料泵
kind: pump
subtype: centrifugal_pump
area: 常减压装置
location: 2#泵区
status: active
tags: [rotating, critical]
source_metadata: {}
provenance: {}
```

说明:

- `id` 必须是平台统一 ID
- `kind` 用平台统一枚举，如 `pump` / `rotating_machine` / `static_equipment`
- `source_metadata` 存系统专属字段

### 7.2 MeasurementPoint

```yaml
id: point:703030976116162560
asset_id: asset:241212010001718
name: 驱动端水平振动
point_type: vibration
unit: mm/s
endpoint_series: 2k
position_type: 23
alarm_thresholds:
  B: 3.0
  C: 4.5
  D: 6.0
source_metadata: {}
provenance: {}
```

### 7.3 AssetContext

```yaml
asset: <Asset>
children: [<Asset>]
points: [<MeasurementPoint>]
related_assets: [<Asset>]
source_metadata: {}
provenance: {}
```

---

## 8. Monitoring 相关模型

### 8.1 TrendSeries

```yaml
series_id: trend:asset:241212010001718:pp_value
asset_id: asset:241212010001718
point_id: point:703030976116162560
metric_key: vibration_level
display_name: 振动水平
unit: mm/s
aggregation: hourly
time_range:
  start: 2026-05-20T00:00:00Z
  end: 2026-05-27T00:00:00Z
samples:
  - ts: 2026-05-20T01:00:00Z
    value: 3.21
  - ts: 2026-05-20T02:00:00Z
    value: 3.34
statistics:
  min: 2.98
  max: 5.12
  avg: 3.67
  stddev: 0.43
anomalies: []
source_metadata: {}
provenance: {}
```

### 8.2 WaveformPayload

```yaml
asset_id: asset:241212010001718
point_id: point:703030976116162560
sample_rate: 25600
captured_at: 2026-05-27T10:00:00Z
wave_x: [0.0, 0.039, 0.078]
wave_y: [0.12, 0.18, 0.10]
spec_x: [10.0, 20.0, 30.0]
spec_y: [1.2, 0.9, 0.3]
speed_rpm: 2980
unit: mm/s
source_metadata: {}
provenance: {}
```

### 8.3 OrbitPayload

```yaml
asset_id: asset:241212010001718
bearing_id: bearing:DE
captured_at: 2026-05-27T10:00:00Z
probe_ids: [point:x, point:y]
points:
  - [0.12, -0.08]
  - [0.14, -0.06]
points_1x: []
points_2x: []
speed_rpm: 2980
source_metadata: {}
provenance: {}
```

### 8.4 AlarmEvent

```yaml
id: alarm:ins_prod:10001
asset_id: asset:241212010001718
point_id: point:703030976116162560
event_type: alarm
severity: high
title: 主报警
message: 驱动端振动超阈值
started_at: 2026-05-27T09:55:00Z
ended_at: null
duration_seconds: null
source_metadata:
  raw_event_type: 1
provenance: {}
```

---

## 9. Health 相关模型

### 9.1 HealthAssessment

```yaml
asset_id: asset:241212010001718
assessment_time: 2026-05-27T10:00:00Z
overall_score: 82.5
level: medium_risk
summary: 设备存在中等风险，建议重点关注驱动端振动与轴承温度
dimensions:
  vibration: 74.0
  temperature: 88.0
  process_stability: 83.0
risk_items:
  - code: vibration_uptrend
    severity: medium
    message: 驱动端振动近 7 日持续升高
recommendations:
  - 检查联轴器对中
  - 复核轴承润滑状态
source_metadata: {}
provenance: {}
```

---

## 10. Customer 相关模型

### 10.1 CustomerProfile

```yaml
id: customer:acme-001
name: 某炼化集团
industry: petrochemical
region: 华北
service_tier: enterprise
contacts:
  - name: 张三
    role: 运维经理
    phone: null
    email: null
contracts:
  - contract_id: C-2026-001
    status: active
source_metadata: {}
provenance: {}
```

---

## 11. Maintenance / Inventory 相关模型

### 11.1 WorkOrder

```yaml
id: wo:ERP:2026-001
asset_id: asset:241212010001718
title: P-101A 轴承检查
status: in_progress
priority: high
created_at: 2026-05-26T08:00:00Z
planned_start_at: 2026-05-27T08:00:00Z
planned_end_at: 2026-05-27T12:00:00Z
assignee_team: 机修一班
summary: 针对振动升高进行检查
source_metadata: {}
provenance: {}
```

### 11.2 InventoryItem

```yaml
id: inv:ERP:BRG-6205
name: 6205 轴承
category: spare_part
stock_qty: 12
unit: pcs
warehouse: 一库
min_stock_qty: 4
source_metadata: {}
provenance: {}
```

---

## 12. Cross-System 模型

### 12.1 EntityLink

```yaml
tenant_id: acme
entity_type: asset
canonical_id: asset:241212010001718
links:
  - system_key: ins_prod
    remote_id: "241212010001718"
    confidence: 1.0
  - system_key: sms_prod
    remote_id: "P-101A"
    confidence: 0.92
source_metadata: {}
```

### 12.2 Provenance

```yaml
source_system: ins_prod
capability_key: monitoring.waveform
fetched_at: 2026-05-27T10:00:00Z
partial_failures: []
```

聚合场景:

```yaml
primary_system: ins_prod
enrich_systems: [sms_prod, erp_prod]
partial_failures:
  - system: sms_prod
    reason: timeout
```

---

## 13. Query Object 建议

为了让 service 层稳定，建议配套定义统一 query object。

### 13.1 TrendQuery

```yaml
asset_id: asset:241212010001718
point_id: point:703030976116162560
metric_key: vibration_level
time_range:
  start: 2026-05-20T00:00:00Z
  end: 2026-05-27T00:00:00Z
aggregation: hourly
```

### 13.2 WaveformQuery

```yaml
asset_id: asset:241212010001718
point_id: point:703030976116162560
captured_at: 2026-05-27T10:00:00Z
```

### 13.3 AlarmHistoryQuery

```yaml
asset_id: asset:241212010001718
limit: 20
time_range: null
severity_min: warning
```

### 13.4 HealthAssessmentQuery

```yaml
asset_id: asset:241212010001718
window: 7d
```

---

## 14. 系统映射建议

### 14.1 InS -> Canonical

InS 的主要映射:

- 设备树 -> `Asset` / `AssetContext`
- 测点 -> `MeasurementPoint`
- 趋势 -> `TrendSeries`
- 波形 -> `WaveformPayload`
- 轨迹 -> `OrbitPayload`
- machine drops / alarms -> `AlarmEvent`

### 14.2 Sms -> Canonical

Sms 的主要映射:

- 评估结果 -> `HealthAssessment`
- 评分维度 -> `HealthAssessment.dimensions`
- 风险项 -> `HealthAssessment.risk_items`

### 14.3 CRM / ERP -> Canonical

CRM -> `CustomerProfile`  
ERP -> `WorkOrder` / `InventoryItem`

---

## 15. 版本化与兼容原则

### 15.1 Capability key 一经发布尽量不改名

例如:

- `monitoring.trend`
- `health.assessment`

这些一旦对上层开放，就应该视为长期契约。

### 15.2 Canonical model 以“增量字段”为主

允许:

- 新增 optional 字段
- 新增 `source_metadata`
- 新增 `provenance`

避免:

- 改字段含义
- 改类型
- 删除已有字段

---

## 16. 首批落地建议

Phase 1 建议先冻结以下能力与模型:

### Capabilities

- `asset.catalog`
- `asset.context`
- `monitoring.trend`
- `monitoring.waveform`
- `monitoring.orbit`
- `monitoring.alarm_history`
- `health.assessment`

### Models

- `Asset`
- `MeasurementPoint`
- `AssetContext`
- `TrendSeries`
- `WaveformPayload`
- `OrbitPayload`
- `AlarmEvent`
- `HealthAssessment`
- `EntityLink`
- `Provenance`

这是最小可用集，足够支撑 InS 平台化和 Sms 接入第一阶段。

---

## 17. 最终目标

最终应达到:

- agent 记住的是统一 tool 名
- service 记住的是 capability key
- adapter 记住的是外部系统协议
- 外部系统变化只影响 adapter，不影响 agent

一句话总结:

**Capability keys 决定平台“提供什么能力”，canonical models 决定平台“如何稳定返回这些能力的数据”。这两层一旦定住，多系统接入才能真正可持续。**
