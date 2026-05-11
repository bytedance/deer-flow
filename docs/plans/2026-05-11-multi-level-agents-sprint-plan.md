# 多层级 Agent 体系 Sprint 计划

> 基于 [技术设计方案](./2026-05-11-default-public-agents-design.md) 按"内置 Agent 基础框架 → 租户 Agent 体系 → 前端管理与增强"顺序编排。

---

## 团队容量估算

| 参数 | 值 |
| --- | --- |
| 团队规模 | 2 名后端工程师 + 1 名前端工程师 |
| Sprint 周期 | 2 周（10 工作日） |
| 后端每人每 Sprint 可用 SP | 20 SP |
| 前端每人每 Sprint 可用 SP | 20 SP |
| 总容量 | 60 SP |
| Buffer（20%） | 12 SP |
| 可承诺容量 | 48 SP / Sprint |

---

## 代码现状基线

> 以下为实施前需了解的关键代码现状，影响 Story 设计和工作量估算。

| 现状 | 文件 | 影响 |
| --- | --- | --- |
| `AgentConfig` 仅有 5 字段（name, description, model, tool_groups, skills） | `config/agents_config.py:38-49` | Phase 1 需扩展 6 个新字段 |
| `load_agent_config(name, *, user_id)` 仅支持 user → legacy 两级查找 | `config/agents_config.py:80-126` | Phase 1 需增加 builtin 查找 |
| `get_available_tools()` 无 `mcp_servers` 参数 | `tools/tools.py:37-176` | Phase 1 需新增参数 |
| MCP 工具已使用 `tool_name_prefix=True` | `mcp/tools.py:120` | MCP 过滤可直接利用 prefix |
| `make_lead_agent()` 已接收 `tenant_id` | `agents/lead_agent/agent.py:384` | 可直接传递到扩展后的 `load_agent_config()` |
| User 模型已有 `system_role: Literal["superadmin", "tenant_admin", "user"]` | `gateway/auth/models.py:17-37` | Phase 2 租户管理员判断可复用此字段 |
| 项目根目录无 `agents/` 目录 | — | Phase 1 需新建 `agents/builtin/` |
| Agent API 路由已有完整 CRUD | `gateway/routers/agents.py` | Phase 2 扩展路由而非重写 |

---

## Sprint 1：内置 Agent + 基础框架

**Sprint Goal:** 系统启动后自动提供 4 个内置 Agent，用户可在 Agent 列表中看到内置 + 个人 Agent，Agent 可独立绑定 MCP Server。

**Duration:** 2 周
**Committed:** 37 SP / 8 Stories
**Buffer:** 0 SP（超容量 1 SP，Story 1.8 可由 BE-2 在 1.7 完成后紧接执行）

### Stories

| # | Story | SP | Owner | 依赖 | AC |
| --- | --- | --- | --- | --- | --- |
| 1.1 | 扩展 `AgentConfig` 数据模型 | 3 | BE-1 | 无 | 新增 `display_name`, `icon`, `mcp_servers`, `tags`, `visibility`, `advanced` 字段；Pydantic BaseModel 保持向后兼容；现有 config.yaml 无新字段时不报错 |
| 1.2 | 新增 `AgentInfo` API 响应模型 | 2 | BE-1 | 1.1 | 独立 Pydantic 模型含 `source`, `editable`, `enabled` 运行时元数据；`to_agent_info()` 转换函数 |
| 1.3 | 实现 `scan_builtin_agents()` + builtin 目录结构 | 5 | BE-1 | 1.1 | 新建 `agents/builtin/` 目录；扫描函数读取所有子目录的 `config.yaml`；目录不存在时返回空列表 |
| 1.4 | 扩展 `load_agent_config()` 支持 builtin 查找 | 5 | BE-2 | 1.3 | 新增可选 `tenant_id` 参数（Phase 2 使用）；查找顺序：user → builtin；向后兼容现有调用 |
| 1.5 | `get_available_tools()` 支持 `mcp_servers` 过滤 | 3 | BE-2 | 无 | 新增 `mcp_servers: list[str] | None` 参数；利用 tool name prefix（`server__tool`）过滤；`None` 时不过滤 |
| 1.6 | 创建 4 个内置 Agent（config.yaml + SOUL.md） | 8 | BE-1 | 1.3 | researcher, code-reviewer, data-analyst, writer 各有完整 config.yaml 和 SOUL.md；SOUL.md 内容 ≥ 500 字 |
| 1.7 | 扩展 `GET /api/agents` 返回合并结果 | 6 | BE-2 | 1.2, 1.3, 1.4 | 返回 builtin + user Agent 合并列表；含 `source`/`editable` 元数据；同名 user Agent 覆盖 builtin；支持 `?tags=xxx&enabled=true` 查询过滤 |
| 1.8 | 单元测试：发现优先级 + MCP 过滤 + 配置解析 | 5 | BE-2 | 1.4, 1.5 | 覆盖：builtin → user 优先级覆盖、MCP prefix 过滤正确性、AgentConfig 新字段解析与默认值、config.yaml 缺少新字段时向后兼容；覆盖率 ≥ 80% |

### 依赖图

```
1.1 → 1.2
1.1 → 1.3
1.3 → 1.4
1.2, 1.3, 1.4 → 1.7
1.4, 1.5 → 1.8
1.5 (独立)
1.6 依赖 1.3（目录结构）
```

### 关键路径

```
1.1 → 1.3 → 1.4 → 1.7
1.4, 1.5 → 1.8
```

### 风险

| 风险 | 缓解 |
| --- | --- |
| SOUL.md 内容质量影响内置 Agent 体验 | 1.6 安排 8 SP 含内容迭代；后续可持续优化 |
| `load_agent_config` 签名变更影响现有调用方 | `tenant_id` 为可选参数，不传时退化为现有逻辑 |
| 内置 Agent 的 skills 引用不存在的 skill | 启动时校验引用有效性，无效时打印 warning 并降级 |

---

## Sprint 2：租户 Agent 数据层 + 权限

**Sprint Goal:** 租户管理员可通过 API 创建和管理租户级 Agent，租户 Agent 对本租户用户可见。

**Duration:** 2 周
**Committed:** 37 SP / 7 Stories
**Buffer:** -1 SP（微超容量，2.6 为轻量路由扩展可快速完成）

### 前置条件

- Sprint 1 完成
- User 模型已有 `system_role` 字段（✅ 已满足）
- 需确认是否需要独立 `tenant_user_roles` 表或复用 `system_role`

### 关于租户管理员判断

> **重要发现：** 当前 User 模型已有 `system_role: Literal["superadmin", "tenant_admin", "user"]`。
> 设计文档中的 `tenant_user_roles` 表可简化为：直接使用 `system_role == "tenant_admin"` 判断。
> 若未来需要更细粒度的租户内角色（如 editor、viewer），再引入独立角色表。
> 本 Sprint 采用简化方案，减少 4 SP 工作量。

### Stories

| # | Story | SP | Owner | 依赖 | AC |
| --- | --- | --- | --- | --- | --- |
| 2.1 | `agents` 表 ORM Model + Alembic migration | 5 | BE-2 | Sprint 1 | `AgentRow` 含 tenant_id, name, display_name, description, icon, visibility, model, tool_groups, skills, mcp_servers, tags, enabled, created_by；Alembic migration 可执行；UNIQUE(tenant_id, name)；索引 `(tenant_id, enabled)` 防止列表查询慢 |
| 2.2 | `agent_permissions` 表 ORM + Repository | 5 | BE-1 | 2.1 | `AgentPermissionRow` 含 agent_id, principal_type, principal_id；`AgentPermissionRepository` CRUD；UNIQUE(agent_id, principal_type, principal_id) |
| 2.3 | `is_tenant_admin()` 工具函数 | 2 | BE-1 | 无 | 基于 User.system_role 判断；支持 superadmin 视为所有租户管理员；单元测试覆盖 |
| 2.4 | 租户 Agent CRUD API | 8 | BE-2 | 2.1, 2.2, 2.3 | POST/PUT/DELETE `/api/tenants/{tid}/agents`；权限校验（仅 tenant_admin）；SOUL.md 存储到文件系统 `tenants/{tid}/agents/{name}/SOUL.md` |
| 2.5 | 扩展 Agent 发现为三级（builtin → tenant → user） | 8 | BE-1 | 2.1, Sprint 1 | `load_agent_config()` 增加 tenant 查找层；`list_available_agents(tenant_id, user_id)` 新函数；`make_lead_agent()` 传递 tenant_id 到 load 函数 |
| 2.6 | 用户 Agent 路由扩展（`/api/agents/mine`） | 3 | BE-2 | Sprint 1 | 新增 `GET /api/agents/mine`（仅返回用户自己的 Agent）和 `POST /api/agents/mine`（创建用户 Agent）；与现有 `GET /api/agents` 区分：mine 仅返回 source=user |
| 2.7 | 单元 + 集成测试 | 6 | BE-2 | 2.4, 2.5 | 覆盖：三级发现优先级、同名覆盖、权限校验拒绝非管理员、tenant_public/tenant_restricted 可见性；覆盖率 ≥ 80% |

### 依赖图

```
2.1 → 2.2
2.1 → 2.4
2.2 → 2.4
2.3 → 2.4
2.1, Sprint 1 → 2.5
Sprint 1 → 2.6
2.4, 2.5 → 2.7
```

### 关键路径

```
2.1 → 2.4 → 2.7
2.1 → 2.5 → 2.7
```

### 风险

| 风险 | 缓解 |
| --- | --- |
| `system_role` 粒度不够（同一用户在不同租户角色不同） | 当前单租户绑定（user.tenant_id），暂不存在跨租户场景；若未来需要，再引入 `tenant_user_roles` |
| 租户 Agent SOUL.md 文件存储路径与现有用户 Agent 冲突 | 租户 Agent 存储在 `tenants/{tid}/agents/`，与 `users/{uid}/agents/` 物理隔离 |
| Alembic migration 与 PostgreSQL 迁移 Sprint 冲突 | 确认 PostgreSQL Sprint 1 先完成配置收口；本 Sprint 的 migration 兼容 SQLite + PostgreSQL |

---

## Sprint 3：租户 MCP Server + Agent 启用/禁用

**Sprint Goal:** 租户可配置私有 MCP Server，Agent 可独立绑定 MCP Server，管理员可启用/禁用各级 Agent。

**Duration:** 2 周
**Committed:** 33 SP / 6 Stories
**Buffer:** 3 SP

### Stories

| # | Story | SP | Owner | 依赖 | AC |
| --- | --- | --- | --- | --- | --- |
| 3.1 | `tenant_mcp_servers` 表 ORM + Alembic | 5 | BE-2 | Sprint 2 | `TenantMcpServerRow` 含 tenant_id, server_name, config(JSONB), enabled；UNIQUE(tenant_id, server_name) |
| 3.2 | 租户 MCP Server CRUD API | 5 | BE-2 | 3.1 | GET/POST/PUT/DELETE `/api/tenants/{tid}/mcp-servers`；权限校验；config 格式校验 |
| 3.3 | MCP 工具加载合并（全局 + 租户） | 8 | BE-1 | 3.1, 3.2 | 运行时合并全局 `extensions_config` + 租户 `tenant_mcp_servers`；Agent 级 `mcp_servers` 字段过滤合并后的工具集 |
| 3.4 | Agent 启用/禁用机制 | 5 | BE-1 | Sprint 2 | 内置 Agent 通过配置文件控制启用；租户 Agent 通过 DB `enabled` 字段；API `PUT /agents/{name}/enabled` |
| 3.5 | 租户 Agent 权限管理 API | 5 | BE-2 | Sprint 2 | `POST /api/tenants/{tid}/agents/{name}/permissions`；支持 user/role 两种 principal_type；tenant_restricted 可见性生效 |
| 3.6 | 集成测试：MCP 隔离 + 启用/禁用 | 5 | BE-1 | 3.3, 3.4 | 验证：租户 A 的 MCP Server 对租户 B 不可见；禁用 Agent 不出现在列表；Agent 级 MCP 过滤正确 |

### 依赖图

```
3.1 → 3.2
3.1, 3.2 → 3.3
Sprint 2 → 3.4
Sprint 2 → 3.5
3.3, 3.4 → 3.6
```

### 关键路径

```
3.1 → 3.2 → 3.3 → 3.6
```

### 风险

| 风险 | 缓解 |
| --- | --- |
| 租户 MCP Server 配置错误导致工具加载失败 | 加载失败时降级（跳过该 server），不影响其他 Agent；记录 warning |
| MCP 工具合并后名称冲突（全局与租户同名 server） | 租户 server 优先覆盖全局同名 server；或拒绝创建与全局同名的租户 server |
| 运行时动态加载租户 MCP Server 的性能影响 | 使用缓存（per-tenant LRU）；MCP 连接池复用 |

---

## Sprint 4：前端 Agent 选择器 + 管理界面

**Sprint Goal:** 用户可在前端选择 Agent 开始对话，管理员可在前端管理租户 Agent。

**Duration:** 2 周
**Committed:** 39 SP / 7 Stories
**Buffer:** -3 SP（超容量，4.6 可由 FE-1 在 4.5 完成后复用相同组件快速实现）

### Stories

| # | Story | SP | Owner | 依赖 | AC |
| --- | --- | --- | --- | --- | --- |
| 4.1 | 前端 Agent 列表 API 对接 | 3 | FE-1 | Sprint 1 API | 调用 `GET /api/agents`；按 source 分组（内置/企业/我的）；支持 tags 过滤 |
| 4.2 | Agent 选择器组件 | 8 | FE-1 | 4.1 | 新建对话时展示 Agent 列表；分组展示；搜索过滤；选择后传入 `context.agent_name` |
| 4.3 | Agent 详情页组件 | 5 | FE-1 | 4.1 | 展示基本信息、绑定工具组、技能、MCP Server、标签 |
| 4.4 | 租户 Agent 管理界面（管理员） | 8 | FE-1 | Sprint 3 API | Agent CRUD 表单；SOUL.md 编辑器；工具/技能/MCP 绑定选择；启用/禁用开关 |
| 4.5 | 租户 MCP Server 管理界面 | 5 | FE-1 | Sprint 3 API | MCP Server CRUD 表单；配置 JSON 编辑器；启用/禁用 |
| 4.6 | 平台管理员界面（内置 Agent 启用/禁用 + 全局 MCP） | 5 | FE-1 | Sprint 3 API | 平台管理员可启用/禁用内置 Agent；全局 MCP Server 管理界面；仅 `system_role=superadmin` 可见 |
| 4.7 | 用户 Fork Agent 功能 | 5 | BE-1 + FE-1 | Sprint 2 | `POST /api/agents/fork/{name}`；复制内置/租户 Agent 到用户目录；前端 Fork 按钮 |

### 依赖图

```
Sprint 1 API → 4.1
4.1 → 4.2, 4.3
Sprint 3 API → 4.4, 4.5, 4.6
Sprint 2 → 4.7
```

### 关键路径

```
4.1 → 4.2（用户可见的核心功能）
Sprint 3 → 4.4（管理员功能）
Sprint 3 → 4.6（平台管理员功能）
```

### 风险

| 风险 | 缓解 |
| --- | --- |
| Agent 选择器 UX 不够直观 | 参考 ChatGPT/Claude 的 Agent 选择交互；支持搜索和标签过滤 |
| 管理界面与后端 API 字段不匹配 | 4.4 开发前确认 API schema；使用 Zod 校验前端表单 |
| SOUL.md 编辑器需要 Markdown 预览 | 复用现有 Markdown 渲染组件 |

---

## Sprint 5：增强功能 + 端到端验收

**Sprint Goal:** Agent 推荐、使用统计上线，全流程端到端验收通过。

**Duration:** 2 周
**Committed:** 34 SP / 8 Stories
**Buffer:** 2 SP（留给前几个 Sprint 的 spillover）

### Stories

| # | Story | SP | Owner | 依赖 | AC |
| --- | --- | --- | --- | --- | --- |
| 5.1 | Agent 使用统计 | 5 | BE-2 | Sprint 2 | 记录每次 Agent 使用（tenant_id, agent_name, user_id, timestamp）；API 返回使用次数 |
| 5.2 | Agent 推荐（基于输入） | 3 | BE-1 | Sprint 1 | 根据用户输入关键词匹配 Agent tags/description；返回 Top-3 推荐 |
| 5.3 | 端到端验收测试 | 8 | BE-1 + FE-1 | Sprint 4 | 完整流程：选择内置 Agent → 对话 → 工具调用；租户 Agent 创建 → 用户可见 → 对话；Fork → 定制 → 使用 |
| 5.4 | 多租户隔离验证 | 5 | BE-2 | Sprint 3 | 租户 A Agent 对租户 B 不可见；租户 A MCP Server 对租户 B 不可见；跨租户 API 调用返回 403 |
| 5.5 | 运维文档更新 | 5 | BE-2 | Sprint 4 | 更新 CLAUDE.md；新增 Agent 管理员指南；API 文档更新 |
| 5.6 | 防越权安全审查 | 2 | BE-1 | Sprint 3 | 验证：Agent 引用不存在的 MCP Server 降级；引用不存在的 Skill 降级；非管理员无法操作租户 Agent |
| 5.7 | 新租户初始化流程 | 3 | BE-2 | Sprint 2 | 创建租户时可选自动 fork 指定内置 Agent 到租户级；可选为租户创建默认 MCP Server 配置；支持配置 `tenant.auto_fork_agents: [researcher, writer]` |
| 5.8 | Subagent/Bootstrap 兼容性验证 | 3 | BE-1 | Sprint 2 | 验证：内置/租户 Agent 作为顶层 Agent 时 subagent（task_tool）正常工作；用户 fork 后可通过 `update_agent` 修改；`advanced.subagent_enabled` 配置生效 |

### 依赖图

```
Sprint 2 → 5.1
Sprint 1 → 5.2
Sprint 4 → 5.3
Sprint 3 → 5.4, 5.6
Sprint 4 → 5.5
Sprint 2 → 5.7, 5.8
```

### 风险

| 风险 | 缓解 |
| --- | --- |
| 端到端测试发现前几个 Sprint 的遗留问题 | 5.3 安排 8 SP 含修复时间；Buffer 8 SP 可吸收 spillover |
| Agent 推荐准确率低 | 初版使用关键词匹配，后续可升级为 embedding 相似度 |
| 文档更新遗漏 | 使用 checklist 对照设计文档 §7-§9 逐项确认 |

---

## Sprint 6：Agent 使用日志与 Token 流量追踪

**Sprint Goal:** Agent 使用记录由后端自动完成（不再依赖前端调用），每次 run 结束时自动记录 token 消耗，支持按 Agent 维度查询 token 流量统计。

**Duration:** 2 周
**Committed:** 28 SP / 6 Stories
**Buffer:** 8 SP

### 前置条件

- Sprint 5 完成（`agent_usage` 表已存在，`AgentUsageRepository` 已有基础 CRUD）
- `TokenUsageMiddleware` 已在 middleware chain 中运行
- `RunManager` / `StreamBridge` 有 run 结束回调机制

### Stories

| # | Story | SP | Owner | 依赖 | AC |
| --- | --- | --- | --- | --- | --- |
| 6.1 | 扩展 `AgentUsageRow` 数据模型 | 3 | BE-2 | Sprint 5 | 新增 `thread_id`, `run_id`, `token_input`, `token_output`, `duration_ms` 字段；Alembic migration；现有数据向后兼容（新字段 nullable 或有默认值） |
| 6.2 | 扩展 `AgentUsageRepository` 方法 | 3 | BE-2 | 6.1 | `record()` 接受新字段；新增 `stats_by_agent(tenant_id, period)` 聚合查询（按 agent_name 汇总 token_input/output/count/avg_duration）；新增 `stats_for_agent(tenant_id, agent_name, period)` 单 Agent 详细统计 |
| 6.3 | Run 结束自动记录 Agent 使用 | 8 | BE-1 | 6.2 | 在 `RunManager.on_end` 或 `StreamBridge` 的 run 结束回调中，读取 `TokenUsageMiddleware` 累计的 token 用量 + `agent_name`（从 config.configurable 获取），自动调用 `AgentUsageRepository.record()`；无 agent_name 时跳过（普通对话不记录）；记录 duration_ms（run 开始到结束的耗时） |
| 6.4 | 扩展 Agent Stats API | 5 | BE-2 | 6.2, 6.3 | 扩展 `GET /api/agents/stats` 返回 token_input_total, token_output_total, avg_duration_ms, last_used_at；新增 `GET /api/agents/{name}/stats` 单 Agent 详细统计；新增 `GET /api/agents/stats/summary?period=7d` 时间范围聚合；`POST /agents/{name}/usage` 标记为 deprecated（保留向后兼容） |
| 6.5 | 前端 Agent 统计展示 | 5 | FE-1 | 6.4 | Agent 详情页展示使用次数、token 消耗、平均耗时；Agent Gallery 卡片展示使用热度；可选：简单的 token 消耗趋势图 |
| 6.6 | 单元 + 集成测试 | 4 | BE-1 | 6.3, 6.4 | 覆盖：run 结束自动记录、token 累计正确性、stats API 聚合结果、无 agent_name 时不记录、多租户隔离统计；覆盖率 ≥ 80% |

### 依赖图

```text
6.1 → 6.2
6.2 → 6.3
6.2, 6.3 → 6.4
6.4 → 6.5
6.3, 6.4 → 6.6
```

### 关键路径

```text
6.1 → 6.2 → 6.3 → 6.4 → 6.6
```

### 风险

| 风险 | 缓解 |
| --- | --- |
| `TokenUsageMiddleware` 累计值在 run 结束时不可靠（中断/超时） | 使用 best-effort 记录；中断时记录已累计的部分值；duration_ms 为 nullable |
| Run 结束回调与 `AgentUsageRepository` 的 async 上下文不匹配 | 复用 `_load_tenant_mcp_configs()` 中已验证的 sync/async 桥接模式 |
| 高并发下 agent_usage 表写入压力 | 索引已有 `(tenant_id, agent_name)` 和 `(user_id)`；新增 `(tenant_id, used_at)` 支持时间范围查询；必要时可引入批量写入 |
| 前端 deprecated 的 `POST /usage` 仍在调用 | 保留端点但内部改为 no-op（自动记录已覆盖）；前端下个版本移除调用 |

### 实现要点

1. **触发位置**：优先在 `RunManager` 的 run 完成回调中触发（而非 middleware），因为此时 token 累计已完成且有完整的 run 上下文（thread_id, run_id, duration）。
2. **agent_name 获取**：从 `config["configurable"]["agent_name"]` 获取，与 `make_lead_agent()` 中的传递路径一致。
3. **向后兼容**：新字段均有默认值（token_input=0, token_output=0, duration_ms=None, thread_id=None, run_id=None），现有 `POST /agents/{name}/usage` 调用不会报错。
4. **Harness/App 边界**：`AgentUsageRepository` 在 harness 层（persistence/），run 结束回调在 runtime 层（也是 harness），不违反边界规则。

---

## 总览

| Sprint | 目标 | SP | 关键交付 |
| --- | --- | --- | --- |
| Sprint 1 | 内置 Agent + 基础框架 | 37 | AgentConfig 扩展、builtin 发现、MCP 过滤、4 个内置 Agent、单元测试 |
| Sprint 2 | 租户 Agent 数据层 + 权限 | 37 | agents 表、三级发现、CRUD API、权限校验、用户路由扩展 |
| Sprint 3 | 租户 MCP Server + 启用/禁用 | 33 | tenant_mcp_servers、MCP 合并加载、启用/禁用机制 |
| Sprint 4 | 前端 Agent 选择器 + 管理界面 | 39 | Agent 选择器、管理界面、平台管理员界面、Fork 功能 |
| Sprint 5 | 增强功能 + 端到端验收 | 34 | 使用统计、推荐、E2E 验收、安全审查、租户初始化、兼容性验证 |
| Sprint 6 | Agent 使用日志与 Token 流量追踪 | 28 | AgentUsageRow 扩展、run 结束自动记录、Agent 维度 token 统计 API、前端统计展示 |
| **合计** | | **208 SP** | **12 周完成全量实施** |

---

## 里程碑

| 日期（相对） | 里程碑 |
| --- | --- |
| Sprint 1 结束（第 2 周） | 内置 Agent 可用，用户可在列表中看到并使用 |
| Sprint 2 结束（第 4 周） | 租户管理员可创建 Agent，三级发现生效 |
| Sprint 3 结束（第 6 周） | 租户 MCP 隔离完成，Agent 可独立绑定 MCP Server |
| Sprint 4 结束（第 8 周） | 前端管理界面上线，用户体验完整 |
| Sprint 5 结束（第 10 周） | 全量验收通过，生产就绪 |
| Sprint 6 结束（第 12 周） | Agent 维度 token 流量追踪上线，自动记录无需前端调用 |

---

## 前置条件

1. Sprint 1 无外部依赖，可立即启动
2. Sprint 2 依赖 Sprint 1 完成（AgentConfig 扩展 + builtin 目录）
3. Sprint 4 前端工作可在 Sprint 1 API 就绪后提前启动 Agent 选择器部分
4. 若 PostgreSQL 迁移 Sprint 1（配置收口）已完成，本计划的 Alembic migration 可直接在 PostgreSQL 上执行
5. 若 PostgreSQL 迁移未完成，本计划的 migration 需同时兼容 SQLite + PostgreSQL

---

## 与 PostgreSQL 迁移计划的协调

| 本计划 Story | PostgreSQL 迁移依赖 | 协调策略 |
| --- | --- | --- |
| 2.1 `agents` 表 Alembic | 需要 Alembic 基础设施 | 若 PG Sprint 0 已完成则直接用 PostgreSQL；否则先在 SQLite 上建表 |
| 3.1 `tenant_mcp_servers` 表 | 同上 | 同上 |
| 2.5 三级发现 | 无直接依赖 | 文件系统 + DB 混合查找，与存储后端无关 |
| 3.3 MCP 合并加载 | 无直接依赖 | 运行时逻辑，不涉及存储迁移 |

建议：本计划可与 PostgreSQL 迁移并行推进，Sprint 2 的 Alembic migration 编写时同时支持两种后端。

---

## Definition of Done

每个 Story 完成标准：

- [ ] 代码通过 `make lint && make test`（后端）或 `pnpm check`（前端）
- [ ] 新增/修改代码有对应单元测试（覆盖率 ≥ 80%）
- [ ] 不引入新的 harness → app 反向依赖
- [ ] API 变更更新 OpenAPI schema
- [ ] PR 通过 code review
- [ ] 向后兼容：现有 Agent 功能不受影响
