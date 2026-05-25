# 全局/租户能力边界规则

> 关联变更: ISSUE-11 tenant-global-capability-boundary  
> 依赖: [ISSUE-09 平台能力配置模型](../governance/platform-capability-config-model.md) | [ISSUE-10 统一能力配置视图](../system-capability-matrix.md)  
> 最后更新: 2026-05-23

## 1. 边界模型

```
┌──────────────────────────────────────┐
│            GLOBAL (全局)              │
│  平台级发布，所有租户自动继承          │
│  存储: config.yaml / extensions JSON  │
├──────────────────────────────────────┤
│  TENANT (租户)                        │
│  租户独立配置，不继承全局              │
│  存储: config.yaml http_connectors    │
│        租户级 Agent 文件系统           │
├──────────────────────────────────────┤
│  TENANT_OVERRIDE (租户覆盖)           │
│  继承全局配置 + 字段级覆盖             │
│  存储: extensions_config.json         │
│        用户级 Agent 配置               │
└──────────────────────────────────────┘
```

## 2. 五种能力类型的 scope 支持

| 类型 | GLOBAL | TENANT | TENANT_OVERRIDE | 继承方式 |
|------|--------|--------|-----------------|----------|
| Model | 支持 | — | — | 全租户自动继承 |
| Skill | 支持 | — | — | 全租户自动继承 |
| MCP | 支持 | — | — | 全租户自动继承 |
| Connector | — | 支持 | — | 租户独立配置 |
| Agent | 支持 (builtin) | 支持 (tenant) | 支持 (user) | builtin → tenant/user 覆盖 |

## 3. 继承规则

### 3.1 自动继承 (GLOBAL → TENANT)

**规则**: 全局能力发布后，所有已知租户自动获得访问权，无需手动启用。

- 租户无需任何操作即可使用全局 Model、Skill、MCP
- 在能力视图 API 中，租户看到 `resolution: "inherited"`
- 全局配置变更（升级、修复）自动传播到所有租户

### 3.2 字段级覆盖 (TENANT_OVERRIDE)

**规则**: 租户可以在继承全局配置的基础上，仅覆盖需要定制的字段。

当租户创建 TENANT_OVERRIDE 时：
- 未覆盖的字段：继续从全局继承，随全局更新自动同步
- 已覆盖的字段：使用租户自定义值，不受全局更新影响
- 删除覆盖后：自动回退到全局配置

**当前支持的覆盖能力**:
- Agent: 通过 user 级 agent 配置覆盖 builtin/tenant agent

### 3.3 租户独立 (TENANT)

**规则**: TENANT scope 的能力不继承全局，由租户独立维护。

- Connector 配置按 tenant_id 独立存储
- 每个租户的同名 Connector 可以指向不同 URL/配置
- 全局不存在 Connector 的"默认配置"

## 4. 停用传播规则

### 4.1 全局能力停用

| 场景 | 影响 | 屏蔽条件 |
|------|------|----------|
| 全局 Model 停用 | 所有租户失去该 Model | 无 |
| 全局 Skill 停用 | 所有租户失去该 Skill | 无 |
| 全局 MCP 停用 | 所有租户失去该 MCP | 无 |
| 全局 Agent 停用 | 所有租户失去该 Agent | 租户有 active TENANT_OVERRIDE |

### 4.2 传播流程

```
操作者发起停用
  → 系统计算受影响租户列表（impact_summary）
  → 操作者确认影响范围
  → 执行停用（记录审计日志）
  → 受影响租户：继承的失去访问，有覆盖的保持
```

### 4.3 警告级别

| 操作 | Scope | 受影响租户 | 警告级别 |
|------|-------|-----------|----------|
| Deactivate | GLOBAL | > 0 | **critical** |
| Deactivate | TENANT | > 0 | warning |
| Modify | GLOBAL | any | info |
| Modify | TENANT | 0 | none |

## 5. 审计记录

### 5.1 审计格式

每次能力 scope 变更都会生成 JSONL 格式审计记录：

```json
{
  "timestamp": "2026-05-23T10:30:00+00:00",
  "actor": "admin",
  "change_type": "deactivate",
  "capability_type": "model",
  "capability_name": "gpt-4",
  "scope": "GLOBAL",
  "affected_tenants": ["tenant-a", "tenant-b"],
  "details": {
    "shielded_tenants": [],
    "total_known_tenants": 2
  }
}
```

### 5.2 审计存储

- 位置: `.deer-flow/audit/capability_changes.jsonl`
- 格式: 每行一条 JSON 记录
- 查询: `GET /api/capabilities/{type}/{name}/audit`

## 6. API 端点

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/capabilities?tenant_id=X` | GET | 租户视角的能力列表（标注继承状态） |
| `/api/capabilities/resolve/{tenant_id}/{type}/{name}` | GET | 解析租户能力配置（含 resolution 信息） |
| `/api/capabilities/{type}/{name}/impact?action=deactivate` | GET | 停用/变更影响分析 |
| `/api/capabilities/{type}/{name}/deactivate` | POST | 模拟停用传播（一期 dry-run） |
| `/api/capabilities/{type}/{name}/audit` | GET | 查询审计记录 |

## 7. 与 ISSUE-09 治理口径的一致性

| ISSUE-09 要求 | 本规则实现 |
|---------------|-----------|
| scope 三态枚举 (GLOBAL/TENANT/TENANT_OVERRIDE) | 继承/覆盖/独立三层模型 |
| 12 字段统一基础属性 | 能力视图 API 返回统一字段 |
| 变更责任矩阵 | 审计记录包含 actor + affected_tenants |
| 停用前影响检查 | `impact_summary` + 警告级别 |

## 8. 与 ISSUE-10 配置视图的一致性

- 能力列表页面支持按 type/scope 过滤，边界规则无误
- 能力详情页面显示 scope 标签，颜色区分 (蓝=全局/紫=租户/橙=覆盖)
- 侧边栏导航 "平台能力" 链接到统一视图
