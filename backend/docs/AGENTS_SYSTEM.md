# 多级 Agent 系统 (Multi-Level Agent System)

三级 Agent 发现机制，支持优先级覆盖：**user > tenant > builtin**。

## 层级结构

```
┌─────────────────────────────────────────────────────────────────┐
│                      User Level (最高优先级)                      │
│  路径: {base_dir}/users/{user_id}/agents/{name}/                │
│  特点: 每用户自定义，通过 fork 或 bootstrap 创建                    │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Tenant Level                                │
│  路径: {base_dir}/tenants/{tenant_id}/agents/{name}/            │
│  特点: 租户内共享，通过 CRUD API + 文件系统同步管理                   │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Builtin Level (最低优先级)                    │
│  路径: packages/harness/deerflow/agents/builtin/                 │
│  特点: 平台内置，只读，通过 scan_builtin_agents() 发现              │
└─────────────────────────────────────────────────────────────────┘
```

## Agent 发现与加载

### 发现函数 (`deerflow/config/agents_config.py`)

| 函数 | 用途 |
|------|------|
| `list_available_agents(tenant_id, user_id)` | 合并三级 Agent，高优先级覆盖同名 |
| `load_agent_config(name)` | 解析 user → tenant → builtin 回退链 |
| `scan_tenant_agents(tenant_id)` | 租户级文件系统扫描 |
| `load_tenant_agent_soul(tenant_id, name)` | 加载租户 Agent 的 SOUL.md |

### Agent 配置 (`AgentConfig` Pydantic 模型)

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | Agent 唯一标识 |
| `description` | str | Agent 描述 |
| `display_name` | str | 显示名称 |
| `icon` | str | 图标路径 |
| `model` | str | 使用的 LLM 模型 |
| `tool_groups` | list[str] | 工具组 |
| `skills` | list[str] | 启用的技能 |
| `mcp_servers` | list[str] | MCP 服务器过滤（按 `server_name__tool_name` 前缀） |
| `tags` | list[str] | 标签 |
| `visibility` | str | 可见性 |

## Tenant Agent CRUD API

**路由**: `app/gateway/routers/tenant_agents.py`

| 方法 | 端点 | 操作 |
|------|------|------|
| POST | `/api/tenants/{tenant_id}/agents` | 创建（写入 config.yaml + SOUL.md） |
| GET | `/api/tenants/{tenant_id}/agents` | 列出租户 Agent |
| PUT | `/api/tenants/{tenant_id}/agents/{name}` | 更新 |
| DELETE | `/api/tenants/{tenant_id}/agents/{name}` | 删除（DB 行 + 文件系统目录） |
| PUT | `/api/tenants/{tenant_id}/agents/{name}/enabled` | 启用/禁用 |
| POST | `/api/tenants/{tenant_id}/agents/{name}/permissions` | 设置权限 |

**权限要求**: `superadmin` 或 `tenant_admin` 角色

## Agent API 扩展

**路由**: `app/gateway/routers/agents.py`

| 方法 | 端点 | 操作 |
|------|------|------|
| GET | `/api/agents` | 三级合并列表（含禁用状态） |
| GET | `/api/agents/mine` | 用户自己的 Agent |
| PUT | `/api/agents/{name}/enabled` | 每用户启用/禁用（存储在 `disabled_agents.json`） |
| POST | `/api/agents/fork/{name}` | Fork builtin/tenant Agent 到用户目录 |
| POST | `/api/agents/{name}/usage` | 记录使用事件 |
| GET | `/api/agents/stats` | 租户范围使用计数 |
| GET | `/api/agents/stats/mine` | 用户使用计数 |
| GET | `/api/agents/recommend?q=` | 基于关键词的 top-3 推荐 |

## Tenant MCP Servers

**路由**: `app/gateway/routers/tenant_mcp_servers.py`

| 方法 | 端点 | 操作 |
|------|------|------|
| POST | `/api/tenants/{tenant_id}/mcp-servers` | 创建 |
| GET | `/api/tenants/{tenant_id}/mcp-servers` | 列出 |
| GET | `/api/tenants/{tenant_id}/mcp-servers/{name}` | 详情 |
| PUT | `/api/tenants/{tenant_id}/mcp-servers/{name}` | 更新 |
| DELETE | `/api/tenants/{tenant_id}/mcp-servers/{name}` | 删除 |
| PUT | `/api/tenants/{tenant_id}/mcp-servers/{name}/enabled` | 启用/禁用 |

**配置验证**:
- `type` 必须是 `stdio` / `sse` / `http`
- `stdio` 需要 `command`
- `sse` / `http` 需要 `url`

**工具合并**: Tenant MCP 工具合并到 `get_available_tools()`，同名 server 前缀的工具覆盖全局工具。

## 持久化层 (`packages/harness/deerflow/persistence/`)

| 模块 | 类/函数 | 职责 |
|------|---------|------|
| `agent/repository.py` | `AgentRepository` | SQLAlchemy async，租户级 Agent 行 |
| `agent/usage_repository.py` | `AgentUsageRepository` | 记录/计数使用事件 |
| `agent/tenant_init.py` | `initialize_tenant_agents()` | 新租户自动 fork builtin agents |
| `mcp_server/repository.py` | `TenantMcpServerRepository` | Tenant MCP server 配置 CRUD |

## MCP 工具合并 (`deerflow/tools/tools.py`)

`get_available_tools()` 接受可选 `tenant_mcp_configs` 参数：
1. Tenant 工具替换同 server 名前缀的全局工具
2. Agent 级 `mcp_servers` 过滤器在合并后应用

## 最佳实践

### 创建自定义 Agent

1. **Fork 内置 Agent**: `POST /api/agents/fork/{name}` 到用户目录
2. **编辑 SOUL.md**: 定义 Agent 人格和行为
3. **编辑 config.yaml**: 配置模型、工具、技能
4. **测试**: 通过 Agent API 调用测试

### Agent 隔离

- **User 级**: 完全隔离，只有创建者可见
- **Tenant 级**: 租户内共享，管理员可管理
- **Builtin 级**: 全局可用，不可修改

### 性能考虑

- Agent 发现结果会被缓存
- 文件系统变更后自动失效
- 大量 Agent 时考虑使用 Tenant 级集中管理
