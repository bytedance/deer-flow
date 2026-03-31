# DeerFlow 身份隔离系统开发计划

## 项目背景

本计划描述 deer-sci-agent 身份隔离功能的完整开发路线图，包含 7 个阶段、18 个任务，实现**部门级 + 个人级 Agent 隔离**的全栈支持。

详细架构设计参见 [`docs/IDENTITY_ISOLATION.md`](./IDENTITY_ISOLATION.md)。

---

## 实现状态总览

| 阶段 | 主题 | 状态 | 关键交付 |
|------|------|------|---------|
| Phase 1 | 身份层 + Paths | ✅ 完成 | AgentIdentity、Paths 扩展、make_lead_agent 接入 |
| Phase 2 | Persona 系统 | ✅ 完成 | PersonaLoader、10 个 persona 文件、系统提示注入 |
| Phase 3 | 配置分层合并 | ✅ 完成 | LayeredAppConfig + LayeredExtensions + agent.py 接入 |
| Phase 4 | Memory 隔离 | ✅ 完成 | identity 路径隔离、缓存修复、OV Backend 实现、MemoryMiddleware OV 路由 |
| Phase 5 | Workspace 隔离 | ✅ 完成 | 接口 + Local/MinIO 后端 + SandboxMiddleware 集成 + WorkspaceConfig |
| Phase 6 | Skills/Plugin 隔离 | ✅ 完成 | 分层 skills 加载 + MCP 分层 extensions + get_available_tools 接入 |
| Phase 7 | API + 文档 | 📋 待开发 | Gateway 路由 + 测试补全 |

---

## Phase 1 — 身份层 + Paths 扩展 ✅

### 任务 1.1 — AgentIdentity 数据类 ✅

**文件**：`backend/packages/harness/deerflow/identity/agent_identity.py`

实际实现亮点（超出原设计）：
- 输入验证：ID 字段必须匹配 `[a-zA-Z0-9_.-]{1,64}`
- `ov_headers` 属性一次返回所有三个 OV header
- `has_dept` / `has_user` / `has_agent` 便捷谓词属性

---

### 任务 1.2 — Paths 扩展 ✅

**文件**：`backend/packages/harness/deerflow/config/paths.py`

新增方法（实际实现）：
- `dept_dir(dept_id)` — `{base_dir}/depts/{dept_id}/`
- `dept_user_dir(dept_id, user_id)` — 部门下用户目录
- `dept_user_agent_dir(dept_id, user_id, agent_name)` — agent 目录
- `identity_agent_dir(identity)` — 三层优先，降级到 legacy `agents/{name}/`
- `identity_config_files(identity)` — 按优先级排列的 config.yaml 路径列表
- `identity_extensions_dirs(identity)` — extensions_config.json 搜索目录
- `identity_memory_file(identity)` — identity 作用域的 memory.json 路径
- `identity_persona_dirs(identity)` — persona 文件搜索目录列表
- `identity_workspace_dir(identity)` — agent 持久化 workspace 目录

---

### 任务 1.3 — make_lead_agent 接入 Identity ✅

**文件**：`backend/packages/harness/deerflow/agents/lead_agent/agent.py`

已完成：
- `identity = AgentIdentity.from_config(config)` 在入口解析
- identity 传入 `PersonaLoader().load(identity)`
- identity 传入 `_build_middlewares(config, model_name, agent_name, identity)`
- identity 传入 `apply_prompt_template(..., identity=identity)`
- identity 字段写入 LangSmith trace metadata (`dept_id`, `user_id`)

---

## Phase 2 — Persona 系统 ✅

### 任务 2.1 — PersonaLoader ✅

**文件**：`backend/packages/harness/deerflow/identity/persona.py`

实现：
- `PersonaContext` dataclass（10 个字段）
- `PersonaLoader.load(identity, base_dir=None)` — 支持 base_dir 覆盖（方便测试）
- `PersonaLoader.load_global(base_dir=None)` — 向后兼容（无 identity 时）
- Override 文件（IDENTITY/SOUL/USER/AGENTS）：最细粒度覆盖（last-wins）
- Append 文件（BOOTSTRAP/HEARTBEAT/TOOLS/WORKFLOW_AUTO/ERRORS/LESSONS）：逐层拼接，`---` 分隔

---

### 任务 2.2 — 系统提示注入 ✅

**文件**：`backend/packages/harness/deerflow/agents/lead_agent/prompt.py`

实现：
- `apply_prompt_template(..., persona, identity)` — 接受 PersonaContext 和 AgentIdentity
- `_build_persona_sections(persona)` — 构建所有 10 个 XML 段
- `_get_memory_context(agent_name, identity)` — identity 作用域的 memory 注入
- 注入顺序：`<identity>`, `<user_context>`, `<bootstrap>`, `<tools_guidance>`, `<workflow>`, `<lessons>`, `<error_patterns>`, `<team_context>`, `<heartbeat>`

---

## Phase 3 — 配置分层合并 ✅

### 任务 3.1 — LayeredAppConfig ✅

**文件**：`backend/packages/harness/deerflow/config/layered_config.py`

实现：
- `load_layered_config_dict(identity)` — 返回深度合并的原始 config dict
- `_deep_merge(base, override)` — 递归合并，Scalar 覆盖 / Dict 递归 / 含 name 字段的 List 按名去重合并
- `_merge_named_list(base, override)` — 保留原始顺序，同名 item 深度合并

> **注意**：`agent.py` 目前仍使用 `get_app_config()` 全局配置。将其替换为 `load_layered_config(identity)` 是 Phase 3 的最后一步，待下一迭代完成。

---

### 任务 3.2 — LayeredExtensionsConfig ✅

**文件**：`backend/packages/harness/deerflow/config/layered_extensions.py`

实现：
- `load_layered_extensions(identity)` — MCP last-layer-wins + Skills 最严格原则（intersection）
- MCP servers：后层覆盖前层（浅合并）
- Skills：任一层禁用即最终禁用

---

## Phase 4 — Memory 隔离 ✅

### 任务 4.1 — OV Memory Backend ✅

**文件**：`backend/packages/harness/deerflow/agents/memory/ov_backend.py`

实现：
- `OVMemoryBackend(ov_url, api_key, identity)` — 每次请求自动携带三层 OV header
- `async store_memory(messages)` — POST `/api/memory/store`
- `async search_memory(query, limit)` — POST `/api/memory/search`，连接失败时优雅降级返回空列表
- `_agent_space_name(identity)` — MD5 哈希派生稳定的 agent space 名称

**文件**：`backend/packages/harness/deerflow/config/memory_config.py`

新增字段：
- `backend: Literal["local", "ov", "ov+local"] = "local"`
- `ov_url: str = "http://localhost:1933"`
- `ov_api_key: str | None = None`

---

### 任务 4.2 — Memory 注入路径修改 ✅

涉及文件：`updater.py` / `prompt.py` / `agent.py` / `memory_middleware.py`

**已修复（本次迭代）**：

| 文件 | 修复内容 |
|------|---------|
| `updater.py::_save_memory_to_file` | 接受 `identity`，使用 `_memory_cache_key()` 作为缓存键（原代码用 `agent_name` 字符串键，破坏多 identity 缓存） |
| `updater.py::update_memory` | 新增 `user_id` 和 `identity` 参数，读写均传入 `identity` |
| `updater.py::update_memory_from_conversation` | 同步新增 `identity` 参数 |
| `prompt.py::_get_memory_context` | 新增 `identity` 参数，按 identity 加载隔离的 memory 文件 |
| `prompt.py::apply_prompt_template` | 新增 `identity` 参数，透传给 `_get_memory_context` |
| `agent.py::_build_middlewares` | 新增 `identity` 参数，传给 `MemoryMiddleware` |
| `agent.py::make_lead_agent` | `apply_prompt_template` 和 `_build_middlewares` 均传入 `identity` |
| `memory_middleware.py::MemoryMiddleware` | `__init__` 新增 `identity` 参数，`after_agent` 传给 `queue.add()` |

> **待完善**：`MemoryMiddleware.after_agent` 目前始终走 local queue → `MemoryUpdater`。OV backend（`backend: ov / ov+local`）的双写路径尚未在 middleware 中接入，需在下一迭代中按 `memory_config.backend` 选择 backend。

---

## Phase 5 — Workspace 隔离 ⚠️ 部分完成

### 任务 5.1 — WorkspaceBackend 接口 ✅

**文件**：`backend/packages/harness/deerflow/sandbox/workspace/__init__.py`

实现：
- 抽象基类 `WorkspaceBackend` — async `sync_down / sync_up`

**文件**：`backend/packages/harness/deerflow/sandbox/workspace/local_backend.py`

实现：
- `LocalWorkspaceBackend` — 使用 `identity_workspace_dir(identity)` 作为持久化目录
- `sync_down`：持久化目录 → 线程临时目录（recursive copy）
- `sync_up`：线程临时目录 → 持久化目录（overwrite）

---

### 任务 5.2 — MinIO Workspace Backend ✅ 实现 / ⚠️ 未集成

**文件**：`backend/packages/harness/deerflow/sandbox/workspace/minio_backend.py`

实现：
- `MinIOWorkspaceBackend` — 路径：`{bucket}/{prefix}/{dept_id}/{user_id}/{agent_name}/`
- `sync_down` / `sync_up` — MinIO 对象存储双向同步

> **⚠️ 待完成**：
> - `SandboxMiddleware` 未集成 `WorkspaceBackend`（Acquire 时 sync_down，Release 时 sync_up）
> - 沙箱虚拟路径 `/mnt/agent-workspace` 映射未添加
> - `AppConfig` 未添加 `WorkspaceConfig` 字段（config.example.yaml 已有示例）

---

## Phase 6 — Skills/Plugin 隔离 📋 待开发

### 任务 6.1 — Skills 分层加载 📋

**待修改**：`backend/packages/harness/deerflow/skills/loader.py`

需实现：
- `load_skills(..., identity=None)` — 非 None 时调用 `load_layered_extensions(identity)` 获取有效 skills 集合
- 支持 `extra_paths`：从各层 config 读取额外 skills 目录

---

### 任务 6.2 — MCP 分层加载 📋

**待修改**：`backend/packages/harness/deerflow/mcp/tools.py`

需实现：
- `get_cached_mcp_tools(identity=None)` — 按 identity 获取有效 MCP tools
- 缓存 key 包含 identity hash
- OV MCP server 自动注入 identity headers

---

## Phase 7 — API 扩展 + 配置 + 文档 📋

### 任务 7.1 — Identity Gateway 路由 📋

**待新建**：`backend/app/gateway/routers/identity.py`

端点规划：
```
GET  /api/identity/depts
POST /api/identity/depts
GET  /api/identity/depts/{dept_id}/users
POST /api/identity/depts/{dept_id}/users/{uid}/agents
GET  /api/identity/effective-config
GET  /api/identity/persona
PUT  /api/identity/persona/{file_name}
GET  /api/identity/skills
```

---

### 任务 7.2 — config.example.yaml ✅

已更新：`config.example.yaml` 已包含 workspace 和 openviking 配置示例区块。

---

### 任务 7.3 — 测试补全 📋

**待新建**：
- `backend/tests/test_identity.py`
- `backend/tests/test_persona_loader.py`
- `backend/tests/test_layered_config.py`
- `backend/tests/test_layered_skills.py`
- `backend/tests/test_ov_memory_isolation.py`（需 OV 服务）
- `backend/tests/test_minio_workspace.py`（需 MinIO）

---

### 任务 7.4 — 文档更新 📋

**待更新**：`backend/CLAUDE.md` — Identity System / Memory System / Sandbox 章节

---

## 完整任务列表

| # | 任务 | 阶段 | 状态 | 关键文件 |
|---|------|------|------|---------|
| 1 | AgentIdentity 数据类 | P1 | ✅ | `identity/agent_identity.py` |
| 2 | Paths 扩展 | P1 | ✅ | `config/paths.py` |
| 3 | make_lead_agent 接入 | P1 | ✅ | `agents/lead_agent/agent.py` |
| 4 | PersonaLoader | P2 | ✅ | `identity/persona.py` |
| 5 | 系统提示 persona 注入 | P2 | ✅ | `agents/lead_agent/prompt.py` |
| 6 | LayeredAppConfig | P3 | ✅ | `config/layered_config.py` |
| 7 | LayeredExtensionsConfig | P3 | ✅ | `config/layered_extensions.py` |
| 8 | OV Memory Backend | P4 | ✅ | `agents/memory/ov_backend.py` |
| 9 | MemoryConfig 扩展 | P4 | ✅ | `config/memory_config.py` |
| 10 | Memory identity 隔离修复 | P4 | ✅ | `updater.py` / `prompt.py` / `agent.py` / `memory_middleware.py` |
| 10a | MemoryMiddleware OV 路由 | P4 | ✅ | `agents/middlewares/memory_middleware.py` |
| 11 | WorkspaceBackend 接口 | P5 | ✅ | `sandbox/workspace/__init__.py` |
| 12 | LocalWorkspaceBackend | P5 | ✅ | `sandbox/workspace/local_backend.py` |
| 13 | MinIOWorkspaceBackend | P5 | ✅ | `sandbox/workspace/minio_backend.py` |
| 14 | SandboxMiddleware 接入 | P5 | ✅ | `sandbox/middleware.py` |
| 15 | Skills 分层加载 | P6 | ✅ | `skills/loader.py` |
| 16 | MCP 分层加载 | P6 | ✅ | `tools/tools.py` |
| 17 | Identity Gateway 路由 | P7 | 📋 | `app/gateway/routers/identity.py` |
| 18 | 测试补全 | P7 | 📋 | `backend/tests/test_identity.py` 等 |

---

## 下一步优先级

### 高优先级 (P1)

**17 — Identity Gateway 路由**

规划端点：
```
GET  /api/identity/depts
POST /api/identity/depts
GET  /api/identity/depts/{dept_id}/users
POST /api/identity/depts/{dept_id}/users/{uid}/agents
GET  /api/identity/effective-config?dept_id=...&user_id=...&agent_name=...
GET  /api/identity/persona?dept_id=...&user_id=...&agent_name=...
PUT  /api/identity/persona/{file_name}
GET  /api/identity/skills?dept_id=...&user_id=...&agent_name=...
```

### 中优先级 (P2)

**18 — 测试补全**

- `backend/tests/test_identity.py`
- `backend/tests/test_persona_loader.py`
- `backend/tests/test_layered_config.py`
- `backend/tests/test_layered_skills.py`
- `backend/tests/test_ov_memory_isolation.py`（需 OV 服务）
- `backend/tests/test_minio_workspace.py`（需 MinIO）

---

## 验证方案

### 单元测试（无外部依赖）

```bash
cd backend
PYTHONPATH=. uv run pytest tests/test_identity.py tests/test_persona_loader.py \
  tests/test_layered_config.py tests/test_layered_skills.py -v
```

### Memory 隔离验证

```bash
# 快速验证 identity 路径隔离
PYTHONPATH=packages/harness uv run python -c "
from deerflow.identity.agent_identity import AgentIdentity
from deerflow.agents.memory.updater import _get_memory_file_path, _memory_cache_key

alice = AgentIdentity(dept_id='research', user_id='alice', agent_name='sci-agent')
bob   = AgentIdentity(dept_id='research', user_id='bob',   agent_name='sci-agent')

print('paths distinct:', _get_memory_file_path(identity=alice) != _get_memory_file_path(identity=bob))
print('keys distinct:', _memory_cache_key(None, alice) != _memory_cache_key(None, bob))
"
```

### 端到端验证

```bash
# 1. 创建部门/用户目录结构
mkdir -p ~/.deer-flow/depts/research/users/alice/agents/sci-agent

# 2. 写入 persona 文件
cat > ~/.deer-flow/depts/research/IDENTITY.md << 'EOF'
# Research Department Agent
You are an agent serving the Research Department.
EOF

cat > ~/.deer-flow/depts/research/users/alice/agents/sci-agent/SOUL.md << 'EOF'
# Alice's Sci-Agent
Proactive, detail-oriented scientific researcher.
EOF

# 3. 启动服务并携带 identity 请求
curl -X POST http://localhost:2026/api/langgraph/threads/$THREAD_ID/runs \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "lead_agent",
    "input": {"messages": [{"role": "user", "content": "hello"}]},
    "config": {
      "configurable": {
        "dept_id": "research",
        "user_id": "alice",
        "agent_name": "sci-agent"
      }
    }
  }'
```
