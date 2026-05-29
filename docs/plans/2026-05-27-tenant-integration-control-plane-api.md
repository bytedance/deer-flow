# 租户级集成控制面 API 与配置模型

> 版本: v1.0  
> 日期: 2026-05-27  
> 状态: Draft  
> 相关文档:
> - [多系统租户级集成与共享数据接入层设计](./2026-05-27-multi-system-tenant-integration-architecture.md)
> - [InS Adapter 平台化改造实施方案](./2026-05-27-ins-adapter-implementation-plan.md)
> - [Capability Keys 与 Canonical Models 清单](./2026-05-27-capability-keys-and-canonical-models.md)

---

## 1. 概述

本文档聚焦三层架构中的第一层:

- 租户级连接器配置
- 租户级能力路由配置
- 租户级跨系统实体映射

目标不是替代现有的低层 `tenant_connectors` CRUD，而是在其上方增加一层更稳定的业务控制面，让平台可以表达:

- 这个租户接了哪些外部系统
- 这些系统分别是什么类型
- 哪些 capability 由哪个系统提供
- 同一个设备、客户、工单在不同系统中的 ID 如何对齐

这层设计完成后，`Shared Data Access Layer` 可以通过统一方式解析租户配置，而不需要知道某个 agent 当前依赖哪条 shell 或 skill 链路。

---

## 2. 设计目标

### 2.1 Goals

- 保留现有 `/api/tenants/{tenant_id}/connectors` 作为低层 HTTP transport 配置能力
- 新增系统级资源，表达 `InS / Sms / CRM / ERP` 这类长期系统
- 新增 capability routing，解决“哪个能力走哪个系统”的问题
- 新增 entity link，解决跨系统 ID 对齐问题
- 支持后续接入非 HTTP 类型系统，不把抽象锁死在 HTTP connector 上

### 2.2 Non-Goals

- Phase 1 不要求替换所有现有 connector API
- Phase 1 不要求提供自动发现所有跨系统映射关系的能力
- Phase 1 不要求实现全量同步任务平台

---

## 3. 与现有 `tenant_connectors` 的关系

当前已有 API:

- `POST /api/tenants/{tenant_id}/connectors`
- `GET /api/tenants/{tenant_id}/connectors`
- `GET /api/tenants/{tenant_id}/connectors/{connector_name}`
- `PUT /api/tenants/{tenant_id}/connectors/{connector_name}`
- `DELETE /api/tenants/{tenant_id}/connectors/{connector_name}`
- `PUT /api/tenants/{tenant_id}/connectors/{connector_name}/enabled`

这套 API 的定位建议保留为:

- 低层传输配置
- 面向具体 URL / method / auth header
- 为 `http_connector_tool` 和 adapter transport 提供底座

在此基础上新增的控制面定位为:

- 面向系统，而不是面向某个 URL
- 面向 capability routing，而不是面向单次 HTTP 调用
- 面向 canonical entity link，而不是面向脚本内部参数

一句话:

`connector` 解决“怎么连”  
`integration system` 解决“连的是什么系统”  
`capability route` 解决“这个能力该走谁”  
`entity link` 解决“跨系统对象怎么对齐”

---

## 4. 资源模型

### 4.1 IntegrationSystem

表示某个租户下的一个外部业务系统实例。

建议字段:

```json
{
  "system_key": "ins_prod",
  "system_type": "ins",
  "display_name": "InS Production",
  "description": "Primary industrial monitoring system",
  "connector_ref": "ins_http_main",
  "transport_type": "http",
  "base_path": "/openapi",
  "enabled": true,
  "priority": 100,
  "timeout_seconds": 30,
  "retry_policy": {
    "max_retries": 2,
    "retry_on_status": [502, 503, 504]
  },
  "capabilities": [
    "asset.catalog",
    "monitoring.trend",
    "monitoring.waveform",
    "monitoring.alarm_history"
  ],
  "metadata": {
    "vendor": "InS",
    "region": "cn-east"
  }
}
```

字段说明:

- `system_key`: 租户内唯一主键
- `system_type`: `ins | sms | crm | erp | custom`
- `connector_ref`: 指向现有 tenant connector 的名字
- `transport_type`: 初期可支持 `http`，后续可扩为 `rpc | db | file | sdk`
- `capabilities`: 该系统理论上可承载的 capability 列表
- `enabled`: 租户级启停

### 4.2 CapabilityRoute

表示某个 capability 在某个租户中的实际路由。

```json
{
  "capability_key": "equipment.overview",
  "primary_system_key": "ins_prod",
  "enrich_system_keys": ["sms_prod", "erp_prod"],
  "fallback_system_keys": [],
  "enabled": true,
  "timeout_seconds": 20,
  "merge_policy": "primary_plus_enrich",
  "partial_failure_policy": "return_partial"
}
```

字段说明:

- `primary_system_key`: 主数据源
- `enrich_system_keys`: 附加补充系统
- `fallback_system_keys`: 主系统失败时可降级的系统
- `merge_policy`: 多系统聚合策略
- `partial_failure_policy`: 局部失败时是否返回部分结果

### 4.3 EntityLink

表示平台统一实体与外部系统实体之间的映射。

```json
{
  "entity_type": "asset",
  "canonical_id": "asset:tenant-a:pump-001",
  "display_name": "1# 给水泵",
  "links": [
    {
      "system_key": "ins_prod",
      "remote_id": "INS-10001",
      "remote_code": "PUMP-001",
      "is_primary": true
    },
    {
      "system_key": "sms_prod",
      "remote_id": "SMS-90088",
      "remote_code": "DEVICE-001",
      "is_primary": false
    }
  ],
  "confidence": 0.98,
  "status": "active",
  "metadata": {
    "site_code": "SITE-A"
  }
}
```

初期建议先支持:

- `asset`
- `measurement_point`
- `customer`
- `work_order`
- `inventory_item`

---

## 5. API 设计

### 5.1 Integration Systems

#### 5.1.1 创建系统

`POST /api/tenants/{tenant_id}/integration-systems`

请求示例:

```json
{
  "system_key": "ins_prod",
  "system_type": "ins",
  "display_name": "InS Production",
  "description": "Primary industrial monitoring system",
  "connector_ref": "ins_http_main",
  "transport_type": "http",
  "base_path": "/openapi",
  "enabled": true,
  "priority": 100,
  "timeout_seconds": 30,
  "capabilities": [
    "asset.catalog",
    "monitoring.trend",
    "monitoring.waveform",
    "monitoring.alarm_history"
  ],
  "metadata": {
    "vendor": "InS"
  }
}
```

返回示例:

```json
{
  "success": true,
  "data": {
    "tenant_id": "tenant-a",
    "system_key": "ins_prod",
    "system_type": "ins",
    "enabled": true
  }
}
```

#### 5.1.2 查询系统列表

`GET /api/tenants/{tenant_id}/integration-systems`

支持查询参数:

- `system_type`
- `enabled`
- `capability`

#### 5.1.3 查询单个系统

`GET /api/tenants/{tenant_id}/integration-systems/{system_key}`

#### 5.1.4 更新系统

`PUT /api/tenants/{tenant_id}/integration-systems/{system_key}`

#### 5.1.5 删除系统

`DELETE /api/tenants/{tenant_id}/integration-systems/{system_key}`

删除规则建议:

- 如果仍被 `CapabilityRoute` 引用，则返回 `409`
- 需要先解除 route 引用才能删除

#### 5.1.6 启停系统

`PUT /api/tenants/{tenant_id}/integration-systems/{system_key}/enabled`

请求:

```json
{
  "enabled": false
}
```

#### 5.1.7 连通性校验

`POST /api/tenants/{tenant_id}/integration-systems/{system_key}/connectivity-check`

返回示例:

```json
{
  "success": true,
  "data": {
    "system_key": "ins_prod",
    "status": "ok",
    "latency_ms": 183,
    "checked_at": "2026-05-27T17:20:00Z"
  }
}
```

这类接口非常适合后台管理页直接调用。

### 5.2 Capability Routes

#### 5.2.1 查询全部路由

`GET /api/tenants/{tenant_id}/capability-routes`

返回示例:

```json
{
  "success": true,
  "data": [
    {
      "capability_key": "asset.catalog",
      "primary_system_key": "ins_prod",
      "enrich_system_keys": [],
      "fallback_system_keys": [],
      "enabled": true
    },
    {
      "capability_key": "equipment.overview",
      "primary_system_key": "ins_prod",
      "enrich_system_keys": ["sms_prod", "erp_prod"],
      "fallback_system_keys": [],
      "enabled": true
    }
  ]
}
```

#### 5.2.2 覆盖单个路由

`PUT /api/tenants/{tenant_id}/capability-routes/{capability_key}`

请求示例:

```json
{
  "primary_system_key": "sms_prod",
  "enrich_system_keys": ["erp_prod"],
  "fallback_system_keys": ["ins_prod"],
  "enabled": true,
  "merge_policy": "primary_plus_enrich",
  "partial_failure_policy": "return_partial"
}
```

#### 5.2.3 批量覆盖路由

`PUT /api/tenants/{tenant_id}/capability-routes`

适用于租户初始化或大批量导入。

请求示例:

```json
{
  "routes": [
    {
      "capability_key": "asset.catalog",
      "primary_system_key": "ins_prod",
      "enrich_system_keys": []
    },
    {
      "capability_key": "health.assessment",
      "primary_system_key": "sms_prod",
      "enrich_system_keys": []
    }
  ]
}
```

### 5.3 Entity Links

#### 5.3.1 查询实体映射

`GET /api/tenants/{tenant_id}/entity-links`

支持查询参数:

- `entity_type`
- `canonical_id`
- `system_key`
- `remote_id`
- `status`

#### 5.3.2 创建实体映射

`POST /api/tenants/{tenant_id}/entity-links`

请求示例:

```json
{
  "entity_type": "asset",
  "canonical_id": "asset:tenant-a:pump-001",
  "display_name": "1# 给水泵",
  "links": [
    {
      "system_key": "ins_prod",
      "remote_id": "INS-10001",
      "remote_code": "PUMP-001",
      "is_primary": true
    },
    {
      "system_key": "sms_prod",
      "remote_id": "SMS-90088",
      "remote_code": "DEVICE-001",
      "is_primary": false
    }
  ],
  "confidence": 0.98,
  "status": "active"
}
```

#### 5.3.3 查询单个实体映射

`GET /api/tenants/{tenant_id}/entity-links/{entity_type}/{canonical_id}`

#### 5.3.4 更新实体映射

`PUT /api/tenants/{tenant_id}/entity-links/{entity_type}/{canonical_id}`

#### 5.3.5 删除实体映射

`DELETE /api/tenants/{tenant_id}/entity-links/{entity_type}/{canonical_id}`

---

## 6. 统一响应格式建议

建议沿用平台统一 envelope:

```json
{
  "success": true,
  "data": {},
  "error": null,
  "meta": {
    "tenant_id": "tenant-a"
  }
}
```

错误示例:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "CAPABILITY_ROUTE_INVALID_SYSTEM",
    "message": "primary_system_key 'sms_prod' does not exist"
  }
}
```

---

## 7. 校验规则

### 7.1 IntegrationSystem

- `system_key` 在租户内唯一
- `system_type` 必须在允许范围内
- `connector_ref` 必须指向已存在 connector
- `capabilities` 中的 key 必须来自平台 capability registry
- `transport_type=http` 时必须存在 `connector_ref`

### 7.2 CapabilityRoute

- `capability_key` 必须存在于 capability registry
- `primary_system_key` 必须存在且启用
- `enrich_system_keys` 与 `fallback_system_keys` 不能重复
- 被引用系统必须声明支持该 capability

### 7.3 EntityLink

- `canonical_id` 在 `entity_type` 范围内唯一
- 同一 `system_key + remote_id` 不能映射到多个 active canonical entity
- `links` 至少包含一个系统映射
- `confidence` 范围为 `0 ~ 1`

---

## 8. 安全与权限

建议与现有 `tenant_connectors` 对齐:

- 仅 `tenant_admin` 或更高角色可变更配置
- `tenant_admin` 只能操作自己的租户
- 普通 agent 运行时只能读取解析后的租户配置，不能修改

额外约束:

- 不在 `IntegrationSystem` 中明文保存 token
- 认证信息仍通过 `connector_ref -> secret/env ref` 间接获取
- 连通性测试结果中不回显敏感 header

---

## 9. 与 Shared Data Access Layer 的协作方式

共享接入层的推荐读取顺序:

1. 根据 `tenant_id + capability_key` 读取 `CapabilityRoute`
2. 解析 `primary_system_key`
3. 根据 `system_key` 读取 `IntegrationSystem`
4. 通过 `connector_ref` 读取底层 connector 配置
5. 装载对应 adapter 并执行查询
6. 如需 enrich，再读取 `enrich_system_keys`
7. 若查询对象跨系统对齐，则读取 `EntityLink`

这条读取链正好把三份配置串成一个闭环。

---

## 10. 与当前仓库的落地建议

### 10.1 推荐新增模块

```text
backend/app/gateway/routers/
  tenant_integration_systems.py
  tenant_capability_routes.py
  tenant_entity_links.py

backend/packages/harness/deerflow/integrations/
  registry/
    capability_registry.py
  repos/
    integration_system_repo.py
    capability_route_repo.py
    entity_link_repo.py
```

### 10.2 与现有 `tenant_connectors.py` 的关系

- `tenant_connectors.py` 继续保留
- 新 router 不直接替代它
- 新增资源以 `connector_ref` 的方式复用已有 connector 记录

这样可以避免 Phase 1 同时重做 transport 层和业务控制层。

---

## 11. 分阶段实施建议

### Phase 1

- 增加 `IntegrationSystem` 数据模型和 CRUD API
- 复用现有 connector 作为 transport 引用
- 先人工配置 capability route

### Phase 2

- 增加 `CapabilityRoute` CRUD API
- Shared Data Access Layer 改为按 route 查 adapter
- `InS` 成为第一个标准 system type

### Phase 3

- 增加 `EntityLink` CRUD API
- `InS + Sms` 开始通过 canonical asset id 聚合

### Phase 4

- 扩展 `CRM / ERP`
- 视情况支持 sync job、mapping suggestion、健康检查面板

---

## 12. 决策总结

推荐将租户级控制面拆成三类资源:

- `IntegrationSystem`
- `CapabilityRoute`
- `EntityLink`

并明确它们与现有 `connector` 的分工:

- `connector`: 低层传输配置
- `integration system`: 外部系统实例
- `capability route`: 能力到系统的路由
- `entity link`: 跨系统对象对齐

这能确保后续无论接入 `InS`、`Sms`、`CRM` 还是 `ERP`，平台都沿用同一套配置模型和调用链，而不是继续演化出新的 skill 私有接入方式。
