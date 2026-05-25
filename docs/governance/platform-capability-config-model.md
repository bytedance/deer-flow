# DeerFlow 平台能力配置模型

最后更新：2026-05-23 | ISSUE-09 | 状态：评审完成

## 1. 概述

本文档定义 DeerFlow 五类平台能力（Model、Skill、MCP、Connector、Agent）的统一配置词汇表、作用域边界和生命周期治理规则。

本文档的输出是 ISSUE-10（统一配置视图）和 ISSUE-11（租户/全局边界）的直接输入。

## 2. 当前差异对照

| 维度 | Model | Skill | MCP | Connector | Agent |
|------|-------|-------|-----|-----------|-------|
| **存储位置** | `config.yaml` | `extensions_config.json` + 文件系统 | `extensions_config.json` | `config.yaml` (http_connectors) | 文件系统 + DB |
| **启用/禁用** | 无 | `enabled: bool` | `enabled: bool` | 无 | 多级（extensions_config + disabled_agents.json） |
| **作用域** | GLOBAL | GLOBAL | GLOBAL + TENANT | TENANT (keyed) | user > tenant > builtin |
| **版本** | 无 | SKILL.md frontmatter | 无 | 无 | 无 |
| **Owner** | 无字段 | 无字段 | 无字段 | 无字段 | user_id / tenant_id |
| **审计** | 无 | 无 | 无 | 无 | 无 |
| **发布方式** | 编辑 config.yaml，重启 | API + .skill 归档安装 | API CRUD | 编辑 config.yaml，重启 | API CRUD + 文件系统写入 |
| **回滚** | Git revert + 重启 | 重新安装旧版本 | 无内置 | Git revert + 重启 | 无内置 |
| **停用** | 删除配置行 | 设置 enabled=false | 设置 enabled=false | 删除配置块 | 设置 enabled=false |
| **变更责任人** | 模型接入负责人 | Skills 平台负责人 | 集成平台负责人 | 集成平台负责人 | Agent 平台负责人 |

## 3. 统一配置模型

### 3.1 统一基础属性 (Base)

所有五类能力共享以下基础属性：

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 唯一标识名，kebab-case |
| `type` | enum | 是 | `model` \| `skill` \| `mcp` \| `connector` \| `agent` |
| `scope` | enum | 是 | `GLOBAL` \| `TENANT` \| `TENANT_OVERRIDE`（见 §4.1） |
| `status` | enum | 是 | `enabled` \| `disabled` \| `deprecated` |
| `owner` | object | 是 | `{ business: string, technical: string }`，引用 ISSUE-05 能力矩阵 |
| `version` | string | 否 | 语义化版本号（semver），`v{major}.{minor}.{patch}` |
| `audit` | object | 是 | `{ enabled: bool, events: string[] }`（见 §4.2） |
| `description` | string | 否 | 人类可读描述 |
| `display_name` | string | 否 | UI 展示名称 |
| `created_at` | datetime | 自动 | 创建时间 |
| `updated_at` | datetime | 自动 | 最后更新时间 |
| `updated_by` | string | 自动 | 最后更新者标识 |

### 3.2 各类型扩展属性

#### Model

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `provider.use` | string | 是 | Provider 类路径 |
| `provider.model` | string | 是 | 模型名称 |
| `capabilities.supports_thinking` | bool | 否 | 是否支持思考模式 |
| `capabilities.supports_vision` | bool | 否 | 是否支持视觉 |
| `capabilities.supports_reasoning_effort` | bool | 否 | 是否支持推理力度控制 |
| `capabilities.use_responses_api` | bool | 否 | 是否使用 /v1/responses |
| `overrides.when_thinking_enabled` | object | 否 | 思考模式专属参数 |
| `overrides.when_thinking_disabled` | object | 否 | 非思考模式专属参数 |

#### Skill

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source.path` | string | 是 | 技能目录路径 |
| `source.container_path` | string | 否 | 沙箱内挂载路径 |
| `metadata.license` | string | 否 | 许可证 |
| `metadata.author` | string | 否 | 作者 |
| `metadata.compatibility` | string | 否 | 兼容性声明 |
| `allowed_tools` | string[] | 否 | 允许使用的工具列表 |
| `report_scripts` | string[] | 否 | 关联的报告脚本列表 |

#### MCP

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `transport.type` | enum | 是 | `stdio` \| `sse` \| `http` |
| `transport.command` | string | 条件 | stdio 命令 |
| `transport.args` | string[] | 否 | stdio 参数 |
| `transport.url` | string | 条件 | SSE/HTTP URL |
| `transport.headers` | object | 否 | HTTP headers |
| `transport.env` | object | 否 | 环境变量 |
| `auth.oauth` | object | 否 | OAuth 配置 |

#### Connector

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `endpoint.url` | string | 是 | 目标 URL |
| `endpoint.method` | enum | 是 | `GET` \| `POST` \| `PUT` |
| `endpoint.headers` | object | 否 | 请求头 |
| `auth.type` | enum | 否 | `none` \| `bearer` \| `api_key` |
| `auth.token_env` | string | 否 | Token 环境变量名 |
| `limits.timeout_seconds` | number | 否 | 超时（默认 30） |
| `limits.max_response_bytes` | number | 否 | 响应上限（默认 512KB） |
| `retry.max_retries` | number | 否 | 重试次数 |
| `retry.on_status` | int[] | 否 | 触发重试的状态码 |
| `cache.ttl_seconds` | number | 否 | 缓存 TTL |

#### Agent

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | 否 | 绑定的模型名称 |
| `visibility` | enum | 是 | `public` \| `private` \| `tenant` |
| `tool_groups` | string[] | 否 | 工具组列表 |
| `exclude_tools` | string[] | 否 | 排除的工具 |
| `skills` | string[] | 否 | 关联技能 |
| `mcp_servers` | string[] | 否 | 关联 MCP 服务 |
| `tags` | string[] | 否 | 标签 |
| `ui.starters` | object[] | 否 | 欢迎页启动提示 |
| `ui.nav_items` | object[] | 否 | 侧边栏导航项 |
| `ui.icon` | string | 否 | 图标 |
| `lineage.type` | enum | 否 | `builtin` \| `fork` |
| `lineage.parent` | string | 否 | 父 agent 名称 |
| `advanced` | object | 否 | 扩展配置（schema-reviewed） |

## 4. 作用域与审计

### 4.1 Scope 三值模型

| Scope | 含义 | 示例 |
|-------|------|------|
| `GLOBAL` | 平台级，所有租户共享 | 内置模型定义、公共 Skills |
| `TENANT` | 租户级，租户独立配置 | 租户专用 Connector、租户 Agent |
| `TENANT_OVERRIDE` | 租户覆盖全局，租户可定制但平台提供默认值 | 租户自定义 MCP 覆盖全局 MCP |

### 4.2 各能力类型字段的 Scope 归属

| 能力类型 | GLOBAL 字段 | TENANT 字段 | TENANT_OVERRIDE 字段 |
|----------|-------------|-------------|---------------------|
| Model | name, use, model, capabilities | — | display_name, overrides |
| Skill | name, source, metadata, allowed_tools | — | enabled |
| MCP | — | transport.*, auth.* | enabled, description |
| Connector | — | 全部字段 | — |
| Agent | builtin agents 全部字段 | tenant/user agents 全部字段 | enabled |

### 4.3 审计字段

以下字段的变更必须生成审计记录：

| 字段 | 原因 |
|------|------|
| `status` | 启用/停用影响平台行为 |
| `scope` | 作用域变更影响所有租户 |
| `owner` | 责任制变更 |
| `version` | 版本升级/回滚可追溯 |
| `enabled` (所有能力) | 启用/停用事件 |
| `auth.*` (MCP, Connector) | 认证配置影响安全 |
| `visibility` (Agent) | 可见性变更影响租户访问 |

审计记录格式：
```json
{
  "timestamp": "ISO8601",
  "actor": "user_id",
  "capability_type": "model|skill|mcp|connector|agent",
  "capability_name": "string",
  "field": "field_path",
  "old_value": "previous",
  "new_value": "current",
  "scope": "GLOBAL|TENANT"
}
```

## 5. 生命周期治理

### 5.1 发布流程

| 能力类型 | 发布动作 | 审批人 | 影响范围 | 部署方式 |
|----------|----------|--------|----------|----------|
| Model | 新增/修改 config.yaml | 模型接入负责人 | 全局即时 | 重启生效 |
| Skill | POST /api/skills/install | Skills 平台负责人 | 全局即时 | 热加载 |
| MCP | PUT /api/mcp/config | 集成平台负责人 | 全局即时 | 热加载 |
| Connector | 新增/修改 config.yaml | 集成平台负责人 | 租户即时 | 重启生效 |
| Agent (builtin) | PR + 合并到仓库 | Agent 平台负责人 | 全局 | 重启生效 |
| Agent (tenant) | POST /api/tenants/{id}/agents | 租户管理员 | 租户即时 | 热加载 |
| Agent (user) | POST /api/agents/fork/{name} | 用户自助 | 用户即时 | 热加载 |

### 5.2 回滚规则

| 能力类型 | 回滚方式 | 前置条件 | 审批 |
|----------|----------|----------|------|
| Model | Git revert + 重启 | 无正在运行的依赖该模型的会话 | 模型接入负责人 |
| Skill | 重新安装旧版本 .skill 归档 | 版本归档可用 | Skills 平台负责人 |
| MCP | PUT /api/mcp/config 恢复旧配置 | 旧配置已备份 | 集成平台负责人 |
| Connector | Git revert + 重启 | 无关键链路强依赖 | 集成平台负责人 |
| Agent (builtin) | Git revert + 重启 | 无 | Agent 平台负责人 |
| Agent (tenant/user) | 手动恢复旧 config.yaml + SOUL.md | 备份可用 | 租户管理员 / 用户 |

### 5.3 停用规则

| 能力类型 | 停用方式 | 前置条件 | 通知期 |
|----------|----------|----------|--------|
| Model | 从 config.yaml 删除 | 无 Agent 绑定该模型 | 提前 1 周 |
| Skill | enabled=false | 无 Agent 或报告模板强依赖 | 提前 2 周 |
| MCP | enabled=false | 无 Agent 绑定 | 提前 2 周 |
| Connector | 从 config.yaml 删除 | 无报告模板强依赖 | 提前 2 周 |
| Agent | enabled=false | 无 | 即时 |

### 5.4 变更责任矩阵

| 变更类型 | 提案人 | 审批人 | 执行人 |
|----------|--------|--------|--------|
| 新增能力（任意类型） | 各域产品负责人 | 平台产品负责人 | 对应技术 owner |
| 修改 GLOBAL 能力 | 各域产品负责人 | 平台产品负责人 | 对应技术 owner |
| 修改 TENANT 能力 | 租户管理员 | 平台治理负责人（抽查） | 租户管理员 |
| 停用能力 | 各域产品负责人 | 平台产品负责人 + 受影响的租户管理员 | 对应技术 owner |
| 回滚能力 | 对应技术 owner | 平台产品负责人 | 对应技术 owner |

## 6. 对下游 ISSUE 的传递

### 6.1 传递给 ISSUE-10 (unified-capability-config-view)

- §3 的统一基础属性 → 配置视图的 Schema 定义
- §3.2 的扩展属性 → 各能力类型的详情表单字段
- §5.1 的发布流程 → 配置视图的操作按钮和审批流

### 6.2 传递给 ISSUE-11 (tenant-global-capability-boundary)

- §4.1 的 Scope 三值模型 → 租户/全局边界的实现依据
- §4.2 的字段 Scope 归属表 → 配置 API 的权限校验矩阵
- §5.4 的变更责任矩阵 → 租户侧的操作权限边界

## 7. 评审签字

| 角色 | 姓名/标识 | 日期 |
|------|-----------|------|
| 平台产品负责人 | 待确认 | |
| 集成平台负责人 | 待确认 | |

> 注：本文档由 ISSUE-09 自动生成，基于现有代码配置模型和能力矩阵（ISSUE-05）推导。实际签字需由对应角色线下完成。
