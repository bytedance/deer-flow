# 多层级 Agent 体系技术设计方案

> 系统初始化后自动提供预置 Agent，支持内置、租户、公共、用户四级 Agent 体系，每个 Agent 可绑定特定的 Skills、MCP Server 和 Tools。

**Goal:** 建立完整的多层级 Agent 管理体系，支持平台内置 Agent、租户专属 Agent、租户公共 Agent 和用户自定义 Agent，满足 SaaS 多租户场景下的 Agent 分发与隔离需求。  
**Architecture:** 复用现有 Agent 发现机制（`load_agent_config` + `list_custom_agents`），通过分层目录 + 数据库元数据扩展发现范围，不改变运行时 Agent 创建流程。

---

## 1. 背景与动机

### 1.1 当前状态

- Agent 通过 `.deer-flow/users/{user_id}/agents/{name}/` 目录发现
- 每个 Agent 由 `config.yaml`（配置）+ `SOUL.md`（人格/指令）组成
- Agent 绑定 `tool_groups`（工具过滤）和 `skills`（技能过滤）
- MCP 工具通过 `extensions_config.json` 全局启用，所有 Agent 共享
- 目前没有"系统级预置 Agent"或"租户级 Agent"的概念
- 多租户隔离已有基础（`tenant_id`、`user_id`），但 Agent 层面未体现

### 1.2 需求

1. 系统初始化后自动存在若干平台级内置 Agent，开箱即用
2. 租户管理员可创建租户专属 Agent，仅本租户用户可见
3. 租户管理员可将 Agent 设为租户公共，本租户所有用户可用
4. 用户可创建个人 Agent，仅自己可见
5. 各级 Agent 可独立绑定 Skills、MCP Server、Tool Groups
6. 高优先级 Agent 覆盖低优先级同名 Agent
7. 管理员可禁用/启用各级 Agent

---

## 2. Agent 分层模型

### 2.1 四级 Agent 体系

```text
Agent 发现优先级（高 → 低）：

1. 用户 Agent      用户个人创建，仅自己可见
2. 租户公共 Agent  租户管理员创建，本租户所有用户可见
3. 租户 Agent      租户管理员创建，指定用户/角色可见
4. 内置 Agent      平台预置，所有租户所有用户可见
```

| 层级 | 归属 | 可见性 | 可修改 | 可删除 | 存储位置 |
| --- | --- | --- | --- | --- | --- |
| 内置 Agent | 平台 | 所有租户、所有用户 | 不可 | 不可 | `agents/builtin/`（git tracked） |
| 租户 Agent | 租户 | 本租户指定用户/角色 | 租户管理员 | 租户管理员 | DB `agents` 表 + 文件存储 |
| 租户公共 Agent | 租户 | 本租户所有用户 | 租户管理员 | 租户管理员 | DB `agents` 表 + 文件存储 |
| 用户 Agent | 用户 | 仅创建者 | 创建者 | 创建者 | `.deer-flow/users/{uid}/agents/` |

### 2.2 存储架构

```text
deer-flow/
├── agents/                                 # 新增目录，与 skills/ 平级
│   └── builtin/                            # 平台内置，git tracked
│       ├── researcher/
│       │   ├── config.yaml
│       │   └── SOUL.md
│       ├── code-reviewer/
│       │   ├── config.yaml
│       │   └── SOUL.md
│       ├── data-analyst/
│       │   ├── config.yaml
│       │   └── SOUL.md
│       └── writer/
│           ├── config.yaml
│           └── SOUL.md
├── skills/                                 # 已有
│   ├── public/
│   └── custom/
├── backend/.deer-flow/
│   ├── tenants/{tenant_id}/agents/         # 租户级 Agent 文件存储（SOUL.md）
│   │   └── {agent_name}/
│   │       └── SOUL.md
│   └── users/{user_id}/agents/             # 用户级 Agent（已有）
│       └── {agent_name}/
│           ├── config.yaml
│           └── SOUL.md
└── extensions_config.json
```

> **注意：** 内置 Agent 目录 `agents/builtin/` 是新增的项目根目录，与 `skills/` 平级。
> 租户 Agent 的元数据（config）存储在数据库 `agents` 表中，仅 SOUL.md 存储在文件系统。

### 2.3 数据库模型（租户 Agent 元数据）

内置 Agent 和用户 Agent 继续使用文件系统。租户级 Agent 引入数据库元数据表，支持更灵活的权限和查询。

> **前置依赖：** 当前 `TenantRow` 仅有 `is_active` 字段，无角色/权限模型。
> Phase 2 实施前需先扩展租户用户角色体系（新增 `tenant_user_roles` 表或在 `users` 表增加 `role` 字段），
> 以支持"租户管理员"概念。在此之前，Phase 1 可暂以 tenant 创建者作为管理员。

```sql
-- 前置：租户用户角色（Phase 2 前置）
CREATE TABLE tenant_user_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR NOT NULL,
    user_id VARCHAR NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'member',  -- 'admin' | 'member'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, user_id)
);

-- 租户 Agent 元数据
CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR NOT NULL,
    name VARCHAR(100) NOT NULL,
    display_name VARCHAR(200),
    description TEXT,
    icon VARCHAR(100),
    visibility VARCHAR(20) NOT NULL DEFAULT 'tenant_public',
        -- 'tenant_public': 本租户所有用户可见
        -- 'tenant_restricted': 本租户指定用户/角色可见
    model VARCHAR(100),
    tool_groups JSONB,              -- ["web", "bash"]
    skills JSONB,                   -- ["deep-research"] or null
    mcp_servers JSONB,             -- ["arxiv-search"] or null
    tags JSONB,                    -- ["research", "writing"]
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_by VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, name)
);

CREATE TABLE agent_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    principal_type VARCHAR(20) NOT NULL,  -- 'user' | 'role'
    principal_id VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(agent_id, principal_type, principal_id)
);
```

---

## 3. Agent Config 扩展

### 3.1 统一配置 Schema

```yaml
# 适用于所有层级的 Agent config.yaml
name: researcher
display_name: "研究助手"
description: "擅长深度信息检索、文献分析和报告撰写"
icon: "search"
model: null                         # null = 使用全局默认模型

# 可见性（仅租户级 Agent 使用）
visibility: tenant_public           # tenant_public | tenant_restricted

# 工具绑定
tool_groups:                        # null = 所有工具组；[] = 无工具
  - web
  - bash

# 技能绑定
skills:                             # null = 所有启用技能；[] = 无技能
  - deep-research

# MCP Server 绑定
mcp_servers:                        # null = 全局启用的 MCP；[] = 无 MCP
  - arxiv-search
  - web-browser

# 标签
tags:
  - research
  - writing

# 高级配置
advanced:
  subagent_enabled: false           # 是否允许委派子任务
  max_turns: 50                     # 最大对话轮次
  thinking_enabled: true            # 是否启用深度思考
```

### 3.2 AgentConfig 数据模型扩展

现有 `AgentConfig` 是 Pydantic `BaseModel`，扩展如下：

```python
from pydantic import BaseModel

class AgentConfig(BaseModel):
    name: str
    description: str = ""
    display_name: str | None = None       # 新增
    icon: str | None = None               # 新增
    model: str | None = None
    visibility: str = "public"            # 新增: public | tenant_public | tenant_restricted | private
    tool_groups: list[str] | None = None
    skills: list[str] | None = None
    mcp_servers: list[str] | None = None  # 新增
    tags: list[str] | None = None         # 新增
    advanced: dict | None = None          # 新增

class AgentInfo(BaseModel):
    """API 返回的 Agent 信息（含运行时元数据）"""
    name: str
    description: str = ""
    display_name: str | None = None
    icon: str | None = None
    source: str = "user"                  # builtin | tenant | user
    tenant_id: str | None = None
    editable: bool = True
    enabled: bool = True
    tags: list[str] | None = None
    tool_groups: list[str] | None = None
    skills: list[str] | None = None
    mcp_servers: list[str] | None = None
```

> **设计决策：** 运行时元数据（source、editable、enabled）不持久化到 config.yaml，
> 而是在 `list_available_agents()` 返回时动态计算。这保持了 AgentConfig 的纯粹性。

---

## 4. Agent 发现与加载

### 4.1 发现逻辑

现有 `load_agent_config(name, user_id)` 按 user → legacy 顺序查找。扩展为三级查找：

```python
def list_available_agents(tenant_id: str, user_id: str) -> list[AgentInfo]:
    """按优先级合并所有层级的 Agent，高优先级覆盖同名低优先级"""
    agents: dict[str, AgentInfo] = {}

    # 1. 内置 Agent（最低优先级）— Phase 1
    for agent in scan_builtin_agents():
        if is_agent_enabled("builtin", agent.name):
            agents[agent.name] = to_agent_info(agent, source="builtin", editable=False)

    # 2. 租户 Agent（覆盖同名内置）— Phase 2
    for agent in load_tenant_agents(tenant_id, user_id):
        if agent.enabled:
            agents[agent.name] = agent

    # 3. 用户 Agent（最高优先级）— 已有
    for agent in scan_user_agents(user_id):
        agents[agent.name] = to_agent_info(agent, source="user", editable=True)

    return sorted(agents.values(), key=lambda a: a.display_name or a.name)


def load_agent_config(
    name: str | None,
    user_id: str | None = None,
    tenant_id: str | None = None,  # 新增参数（Phase 2）
) -> AgentConfig | None:
    """
    按优先级查找 Agent 配置。
    
    现有签名: load_agent_config(name, user_id) — 向后兼容。
    扩展: 新增可选 tenant_id 参数，启用三级查找。
    """
    # 用户 Agent（已有逻辑）
    user_agent = _load_user_agent(user_id, name)
    if user_agent:
        return user_agent

    # 租户 Agent（Phase 2 新增）
    if tenant_id:
        tenant_agent = _load_tenant_agent(tenant_id, name, user_id)
        if tenant_agent:
            return tenant_agent

    # 内置 Agent（Phase 1 新增）
    builtin_agent = _load_builtin_agent(name)
    if builtin_agent and is_agent_enabled("builtin", name):
        return builtin_agent

    return None
```

> **向后兼容：** `tenant_id` 参数默认为 None，不传时退化为现有的 user → legacy 两级查找。
> `make_lead_agent()` 中已有 `tenant_id` 可直接传入。

### 4.2 租户 Agent 权限检查

```python
def load_tenant_agents(tenant_id: str, user_id: str) -> list[AgentConfig]:
    """加载当前用户可见的租户 Agent"""
    agents = []

    # 租户公共 Agent：本租户所有用户可见
    public_agents = db.query(agents_table).filter(
        tenant_id=tenant_id,
        visibility="tenant_public",
        enabled=True,
    )
    agents.extend(public_agents)

    # 租户受限 Agent：检查用户权限
    restricted_agents = db.query(agents_table).filter(
        tenant_id=tenant_id,
        visibility="tenant_restricted",
        enabled=True,
    ).join(agent_permissions).filter(
        principal_type="user", principal_id=user_id
    )
    agents.extend(restricted_agents)

    return [to_agent_config(a, source="tenant") for a in agents]
```

### 4.3 MCP Server 过滤

当前 MCP 工具通过 `get_cached_mcp_tools()` 全局加载，工具名称带有 server name prefix（格式：`{server_name}__{tool_name}`）。利用此 prefix 实现 Agent 级过滤：

```python
def get_available_tools(
    groups: list[str] | None = None,
    include_mcp: bool = True,
    mcp_servers: list[str] | None = None,  # 新增：Agent 级 MCP 过滤
    model_name: str | None = None,
    subagent_enabled: bool = False,
    *,
    app_config: AppConfig | None = None,
) -> list[BaseTool]:
    tools = []
    # ... 现有 config tools + builtin tools 逻辑 ...

    if include_mcp:
        all_mcp_tools = get_cached_mcp_tools()
        if mcp_servers is not None:
            # 利用 tool name prefix 过滤：server_name__tool_name
            server_prefixes = tuple(f"{s}__" for s in mcp_servers)
            tools += [t for t in all_mcp_tools if t.name.startswith(server_prefixes)]
        else:
            tools += all_mcp_tools

    return deduplicate_tools(tools)
```

> **实现说明：** MCP 工具加载时使用 `tool_name_prefix=True`，生成的工具名格式为
> `{server_name}__{tool_name}`。过滤通过 `str.startswith()` 匹配 prefix 实现，
> 无需修改 MCP 工具的 metadata 结构。

---

## 5. 预置内置 Agent

### 5.1 研究助手（researcher）

```yaml
name: researcher
display_name: "研究助手"
description: "擅长深度信息检索、文献分析、数据整理和研究报告撰写"
icon: "search"
model: null
tool_groups:
  - web
skills:
  - deep-research
mcp_servers: null
tags: [research, writing]
```

**SOUL.md 要点：**
- 系统化的研究方法论
- 多源交叉验证
- 结构化输出（摘要、正文、参考文献）

### 5.2 代码审查（code-reviewer）

```yaml
name: code-reviewer
display_name: "代码审查"
description: "专注代码质量、安全漏洞、性能问题和最佳实践的审查"
icon: "code"
model: null
tool_groups:
  - bash
skills:
  - code-documentation
mcp_servers: null
tags: [development, review]
```

### 5.3 数据分析（data-analyst）

```yaml
name: data-analyst
display_name: "数据分析"
description: "擅长数据处理、统计分析、可视化和洞察提取"
icon: "chart"
model: null
tool_groups:
  - bash
skills: []
mcp_servers: null
tags: [data, analysis]
advanced:
  subagent_enabled: false
```

### 5.4 写作助手（writer）

```yaml
name: writer
display_name: "写作助手"
description: "擅长文案撰写、内容编辑、翻译和文风调整"
icon: "pen"
model: null
tool_groups: []
skills: []
mcp_servers: null
tags: [writing, content]
```

---

## 6. 租户 Agent 管理

### 6.1 租户 Agent 生命周期

```text
创建 → 配置 → 启用 → 使用 → 更新 → 禁用/删除
```

### 6.2 租户管理员操作

| 操作 | 说明 |
| --- | --- |
| 创建 Agent | 指定 name、SOUL.md、config；选择 visibility |
| 绑定工具 | 选择 tool_groups、mcp_servers、skills |
| 设置权限 | tenant_restricted 时指定可见用户/角色 |
| 启用/禁用 | 控制 Agent 是否出现在用户列表 |
| Fork 内置 | 复制内置 Agent 到租户级进行定制 |
| 删除 | 移除 Agent（已有对话历史不受影响） |

### 6.3 租户 MCP Server 隔离

租户可以有自己的 MCP Server 配置（扩展 `extensions_config` 为租户级）：

```text
全局 MCP Servers（extensions_config.json）
    ↓ 合并
租户 MCP Servers（DB tenant_mcp_servers 表）
    ↓ 过滤
Agent 级 mcp_servers 字段
    ↓
最终可用 MCP 工具
```

```sql
CREATE TABLE tenant_mcp_servers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR NOT NULL,
    server_name VARCHAR(100) NOT NULL,
    config JSONB NOT NULL,          -- {type, command, args, env, url, ...}
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, server_name)
);
```

---

## 7. Gateway API 设计

### 7.1 Agent 列表（所有用户）

```
GET /api/agents
Query: ?tags=research&enabled=true
Headers: X-Tenant-Id (从 auth 获取)

Response:
{
  "agents": [
    {
      "name": "researcher",
      "display_name": "研究助手",
      "description": "...",
      "icon": "search",
      "source": "builtin",
      "editable": false,
      "tags": ["research", "writing"],
      "enabled": true,
      "tool_groups": ["web"],
      "skills": ["deep-research"],
      "mcp_servers": null
    },
    {
      "name": "company-assistant",
      "display_name": "企业助手",
      "description": "...",
      "icon": "building",
      "source": "tenant",
      "editable": false,
      "tags": ["enterprise"],
      "enabled": true,
      "tool_groups": ["web", "bash"],
      "skills": null,
      "mcp_servers": ["company-kb", "jira"]
    }
  ]
}
```

### 7.2 租户 Agent 管理（租户管理员）

```
POST   /api/tenants/{tenant_id}/agents          # 创建
GET    /api/tenants/{tenant_id}/agents          # 列表（含禁用的）
GET    /api/tenants/{tenant_id}/agents/{name}   # 详情
PUT    /api/tenants/{tenant_id}/agents/{name}   # 更新配置
DELETE /api/tenants/{tenant_id}/agents/{name}   # 删除
PUT    /api/tenants/{tenant_id}/agents/{name}/enabled   # 启用/禁用
POST   /api/tenants/{tenant_id}/agents/{name}/permissions  # 设置权限
```

### 7.3 租户 MCP Server 管理

```
GET    /api/tenants/{tenant_id}/mcp-servers
POST   /api/tenants/{tenant_id}/mcp-servers
PUT    /api/tenants/{tenant_id}/mcp-servers/{name}
DELETE /api/tenants/{tenant_id}/mcp-servers/{name}
```

### 7.4 用户 Agent 管理（已有，扩展）

```
GET    /api/agents/mine                         # 用户自己的 Agent
POST   /api/agents/mine                         # 创建用户 Agent
POST   /api/agents/fork/{name}                  # Fork 内置/租户 Agent
```

---

## 8. 前端集成

### 8.1 Agent 选择器

- 新建对话时展示可用 Agent 列表
- 按 source 分组：内置 | 企业 | 我的
- 按 tags 过滤
- 选择后 `context.agent_name` 传入后端

### 8.2 Agent 管理界面

| 角色 | 可见页面 |
| --- | --- |
| 普通用户 | 我的 Agent（CRUD）、可用 Agent 列表（只读） |
| 租户管理员 | 租户 Agent 管理（CRUD）、MCP Server 管理、权限设置 |
| 平台管理员 | 内置 Agent 启用/禁用、全局 MCP 管理 |

### 8.3 Agent 详情页

展示：
- 基本信息（名称、描述、图标、标签）
- 绑定的工具组
- 绑定的技能
- 绑定的 MCP Server
- 使用统计（可选）

---

## 9. 安全与隔离

### 9.1 权限矩阵

| 操作 | 内置 Agent | 租户公共 Agent | 租户受限 Agent | 用户 Agent |
| --- | --- | --- | --- | --- |
| 查看列表 | 所有用户 | 本租户所有用户 | 授权用户 | 仅创建者 |
| 使用 | 所有用户 | 本租户所有用户 | 授权用户 | 仅创建者 |
| 修改 | 不允许 | 租户管理员 | 租户管理员 | 创建者 |
| 删除 | 不允许 | 租户管理员 | 租户管理员 | 创建者 |
| 禁用 | 平台管理员 | 租户管理员 | 租户管理员 | 创建者 |

### 9.2 工具隔离

```text
Agent 可用工具 = 
    全局工具（按 tool_groups 过滤）
  ∩ 全局 MCP 工具（按 mcp_servers 过滤）
  ∪ 租户 MCP 工具（按 mcp_servers 过滤）
```

- `tool_groups: null` → 所有工具组可用
- `tool_groups: []` → 无工具（纯对话）
- `mcp_servers: null` → 全局 + 租户所有启用的 MCP
- `mcp_servers: ["server-a"]` → 仅 server-a 的工具

### 9.3 数据隔离

- 租户 Agent 的 SOUL.md 和配置存储在租户隔离目录
- 租户 A 的 Agent 对租户 B 完全不可见
- 用户 Agent 对同租户其他用户不可见
- 沙箱隔离不变：每个线程独立 workspace

### 9.4 防止越权

- 租户 Agent 引用的 MCP Server 必须是全局启用或本租户配置的
- 租户 Agent 引用的 Skills 必须是全局启用的
- 启动时校验：引用不存在的资源打印 warning 并降级

---

## 10. 初始化与升级流程

### 10.1 首次启动

```text
1. 应用启动
2. 扫描 agents/builtin/ 目录，加载内置 Agent
3. 初始化 agents 表（若使用 PostgreSQL）
4. 内置 Agent 默认全部启用
5. Agent 列表 API 可用
```

### 10.2 新租户初始化

```text
1. 创建租户记录
2. 可选：自动 fork 指定内置 Agent 到租户级（支持定制）
3. 可选：为租户创建默认 MCP Server 配置
4. 租户用户登录后即可看到内置 + 租户 Agent
```

### 10.3 版本升级

```text
1. 代码更新带来新的 builtin Agent
2. 应用重启后自动发现
3. 新 Agent 默认启用
4. 已有租户的同名 Agent 不受影响（租户优先级更高）
```

---

## 11. 实施计划

### Phase 1：内置 Agent + 基础框架（1 Sprint, 22 SP）

> 前置条件：无。Phase 1 不依赖租户角色体系。

| Story | SP | 说明 |
| --- | --- | --- |
| 扩展 `AgentConfig` 数据模型 | 3 | 新增 display_name, icon, mcp_servers, tags, visibility（Pydantic BaseModel） |
| 实现多级 Agent 发现（builtin + user） | 5 | `load_agent_config()` 增加 builtin 查找；`scan_builtin_agents()` 扫描 `agents/builtin/` |
| `get_available_tools()` 支持 `mcp_servers` 过滤 | 3 | 利用 tool name prefix（`server__tool`）过滤 |
| 创建 4 个内置 Agent（config.yaml + SOUL.md） | 5 | 新建 `agents/builtin/` 目录；researcher, code-reviewer, data-analyst, writer |
| 扩展 `GET /api/agents` API | 3 | 返回合并结果（builtin + user），含 source/editable 元数据 |
| 单元测试 | 3 | 发现优先级、MCP prefix 过滤、配置解析 |

### Phase 2：租户 Agent 体系（2 Sprint, 44 SP）

> 前置条件：需先实现 `tenant_user_roles` 表（租户管理员角色）。

| Story | SP | 说明 |
| --- | --- | --- |
| `tenant_user_roles` 表 ORM + API | 4 | Alembic migration；`is_tenant_admin()` 工具函数 |
| `agents` 表 + `agent_permissions` 表 ORM | 5 | Alembic migration；放在 `persistence/` 目录 |
| 租户 Agent CRUD API | 8 | POST/PUT/DELETE /api/tenants/{tid}/agents；权限校验 |
| 租户 Agent 权限管理 | 5 | tenant_restricted 可见性 + permissions API |
| 租户 MCP Server 管理 | 8 | `tenant_mcp_servers` 表 + CRUD API + 工具加载合并 |
| Agent 发现扩展为三级 | 5 | `load_agent_config()` 增加 tenant_id 参数；builtin → tenant → user |
| Agent 启用/禁用机制 | 3 | 内置用 extensions_config；租户用 DB enabled 字段 |
| 前端 Agent 选择器 | 5 | 分组展示（内置/企业/我的）、标签过滤、搜索 |
| 单元 + 集成测试 | 5 | 多租户隔离、权限检查、优先级覆盖 |

### Phase 3：前端管理 + 增强（1 Sprint, 24 SP）

| Story | SP | 说明 |
| --- | --- | --- |
| 前端租户 Agent 管理界面 | 8 | 管理员 CRUD、权限设置、MCP 绑定 |
| 用户 Fork Agent 功能 | 3 | 复制内置/租户 Agent 到用户目录 |
| Agent 使用统计 | 5 | 记录使用次数、满意度 |
| Agent 推荐 | 3 | 根据用户输入推荐合适 Agent |
| 运维文档更新 | 5 | CLAUDE.md、API 文档、管理员指南 |

---

## 11.5 Agent 使用日志与 Token 流量追踪

### 11.5.1 背景

当前系统存在两套独立的使用追踪机制：

1. **Token 用量追踪**（已有）：`TokenUsageMiddleware` 在每次 LLM 调用后记录 token 消耗，存储在 `RunRepository` 中，按 thread/run 维度聚合。API：`GET /{thread_id}/token-usage`。
2. **Agent 使用计数**（新增）：`AgentUsageRepository` 记录 Agent 被选择使用的次数，由前端在开始对话时主动调用 `POST /agents/{name}/usage`。

**问题：** 两套系统未关联。无法回答"researcher Agent 本月消耗了多少 token"或"哪个 Agent 的 token 成本最高"。且 Agent 使用记录依赖前端主动调用，后端无自动记录机制。

### 11.5.2 设计方案（方案 B：完整集成）

将 Agent 使用记录与 Token 流量追踪统一，由后端在 run 结束时自动记录，不再依赖前端调用。

#### 数据模型扩展

```sql
-- 扩展 agent_usage 表，增加 token 字段
ALTER TABLE agent_usage ADD COLUMN thread_id VARCHAR(64);
ALTER TABLE agent_usage ADD COLUMN run_id VARCHAR(64);
ALTER TABLE agent_usage ADD COLUMN token_input INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_usage ADD COLUMN token_output INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_usage ADD COLUMN duration_ms INTEGER;

CREATE INDEX ix_agent_usage_thread ON agent_usage(thread_id);
CREATE INDEX ix_agent_usage_time_range ON agent_usage(tenant_id, used_at);
```

扩展后的 `AgentUsageRow`：

```python
class AgentUsageRow(Base):
    __tablename__ = "agent_usage"

    id: Mapped[str]
    tenant_id: Mapped[str]
    agent_name: Mapped[str]
    user_id: Mapped[str]
    thread_id: Mapped[str | None]       # 新增：关联的 thread
    run_id: Mapped[str | None]          # 新增：关联的 run
    token_input: Mapped[int]            # 新增：输入 token 数
    token_output: Mapped[int]           # 新增：输出 token 数
    duration_ms: Mapped[int | None]     # 新增：run 耗时（毫秒）
    used_at: Mapped[datetime]
```

#### 自动记录机制

在 `TokenUsageMiddleware` 的 `after_model` 或 run 结束回调中，自动写入 `agent_usage` 记录：

```python
# 在 run 结束时（StreamBridge 或 RunManager 回调）
async def _record_agent_usage_on_run_end(
    tenant_id: str,
    user_id: str,
    agent_name: str,
    thread_id: str,
    run_id: str,
    token_input: int,
    token_output: int,
    duration_ms: int,
):
    await usage_repo.record(
        tenant_id=tenant_id,
        agent_name=agent_name,
        user_id=user_id,
        thread_id=thread_id,
        run_id=run_id,
        token_input=token_input,
        token_output=token_output,
        duration_ms=duration_ms,
    )
```

**触发时机：** Run 结束时（`task_completed` / stream 结束），由 `RunManager` 或 `StreamBridge` 的 `on_end` 回调触发。此时 `TokenUsageMiddleware` 已累计完整的 token 用量。

#### API 扩展

```text
GET /api/agents/stats                    # 已有，扩展返回 token 统计
GET /api/agents/stats/mine               # 已有，扩展返回 token 统计
GET /api/agents/{name}/stats             # 新增：单个 Agent 详细统计
GET /api/agents/stats/summary?period=7d  # 新增：时间范围聚合
```

响应格式扩展：

```json
{
  "stats": [
    {
      "agent_name": "researcher",
      "count": 42,
      "token_input_total": 125000,
      "token_output_total": 89000,
      "avg_duration_ms": 3200,
      "last_used_at": "2026-05-11T10:30:00Z"
    }
  ]
}
```

#### 与现有系统的关系

```text
TokenUsageMiddleware（每次 LLM 调用累计 token）
    ↓ run 结束时汇总
RunManager.on_end / StreamBridge.on_end
    ↓ 自动写入
AgentUsageRepository.record(含 token_input, token_output, duration_ms)
    ↓ 查询
GET /api/agents/stats（按 agent_name 聚合 token 流量）
```

- **不再依赖前端调用** `POST /agents/{name}/usage`（该端点保留向后兼容，但标记为 deprecated）
- **不修改** `TokenUsageMiddleware` 的核心逻辑，仅在 run 结束时读取其累计值
- **不修改** 现有 `GET /{thread_id}/token-usage` 端点（thread 维度统计保持不变）
- **新增** Agent 维度的 token 聚合查询

#### 安全与隔离

- Agent 统计严格按 `tenant_id` 隔离
- 普通用户仅可查看自己的统计（`/stats/mine`）
- 租户管理员可查看租户维度统计（`/stats`）
- 平台管理员可查看全局统计（未来扩展）

---

## 12. 与现有系统的兼容性

### 12.1 与 Subagent 系统

- 公共/租户 Agent 是**顶层 Agent**（用户直接对话入口）
- Subagent 是**任务委派目标**（lead_agent 通过 `task` 工具调用）
- 两者独立：顶层 Agent 可配置 `advanced.subagent_enabled`

### 12.2 与 Agent Bootstrap

- 现有 `setup_agent` / `update_agent` 工具用于用户自定义 Agent
- 内置/租户 Agent 不通过 bootstrap 流程创建
- 用户可 fork 后通过 `update_agent` 修改

### 12.3 与多租户系统

- 复用现有 `tenant_id` 隔离机制
- 租户 Agent 的 MCP Server 配置与全局配置合并
- 租户 Agent 的 Skills 引用全局 Skills 池（不支持租户私有 Skill，Phase 3 可扩展）

### 12.4 向后兼容

- 现有用户 Agent（`.deer-flow/users/{uid}/agents/`）继续工作
- 无 tenant_id 场景（单租户/no-auth 模式）退化为两级：builtin → user
- `context.agent_name` 传递方式不变

---

## 13. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 租户 Agent 数量膨胀导致查询慢 | DB 索引 (tenant_id, enabled)；分页加载 |
| 租户 MCP Server 配置错误影响稳定性 | 工具加载失败时降级（跳过该 server）；不影响其他 Agent |
| 内置 Agent SOUL.md 质量影响体验 | 迭代优化；租户可 fork 定制 |
| 多级覆盖导致用户困惑 | 前端明确标注 Agent 来源（内置/企业/个人） |
| 租户间 Agent 配置泄露 | 严格 tenant_id 过滤；API 层强制校验 |
| MCP Server 过滤增加复杂度 | 过滤在缓存层之后执行；单元测试覆盖边界 |

---

## 14. 关键设计决策

| 决策 | 选择 | 理由 |
| --- | --- | --- |
| 内置 Agent 存储 | `agents/builtin/`（项目根目录，与 `skills/` 平级） | 随代码版本发布，升级自动生效；与 skills 目录结构对齐 |
| 租户 Agent 存储 | DB 元数据 + 文件系统（SOUL.md） | 支持动态 CRUD、权限管理、查询过滤 |
| 用户 Agent 存储 | 文件系统（已有） | 向后兼容，无需迁移 |
| 发现优先级 | 用户 > 租户 > 内置 | 用户定制优先，内置兜底 |
| MCP 绑定粒度 | Agent 级 Server 过滤（name prefix 匹配） | 利用现有 `tool_name_prefix=True` 机制，无需修改 MCP 工具结构 |
| 租户 MCP 隔离 | 独立表 + 合并加载 | 租户可有私有 MCP Server，不影响全局 |
| 权限模型 | `tenant_user_roles` 表（admin/member） | 简单灵活；当前 TenantRow 无角色字段，需新建 |
| AgentConfig 类型 | Pydantic BaseModel（非 frozen dataclass） | 与现有代码一致 |
| 运行时元数据 | 独立 `AgentInfo` 模型 | 保持 AgentConfig 纯粹，不混入 source/editable 等运行时字段 |

---

## 15. 与代码现状的对齐说明

本设计经过架构审查，以下是针对代码现状的关键对齐点：

| 现状 | 设计适配 |
| --- | --- |
| `AgentConfig` 是 Pydantic BaseModel | 扩展字段保持 BaseModel 风格，不引入 dataclass |
| `load_agent_config(name, user_id)` 已有 | 新增可选 `tenant_id` 参数，向后兼容 |
| `get_available_tools()` 无 `mcp_servers` 参数 | Phase 1 新增参数，利用 name prefix 过滤 |
| MCP 工具无 `server_name` metadata | 利用 `tool_name_prefix=True` 生成的 `server__tool` 格式过滤 |
| `TenantRow` 仅有 `is_active` 字段 | Phase 2 前置新建 `tenant_user_roles` 表 |
| Agent 路由无 tenant 隔离 | Phase 2 扩展路由加入 tenant_id 过滤 |
| 项目根目录无 `agents/` 目录 | Phase 1 新建 `agents/builtin/` 目录 |
| `make_lead_agent()` 已接收 `tenant_id` | 可直接传递到扩展后的 `load_agent_config()` |
