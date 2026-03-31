# DeerFlow 身份隔离架构设计

## 概述

本文档描述 deer-sci-agent 的**部门级 + 个人级 Agent 隔离系统**的架构设计。该系统引入三层身份模型，支持科研团队在共享平台上进行模型配置、工作空间、记忆系统、个性化设置、技能和插件的全维度隔离。

> **实现状态**：Phase 1–4 已完成，Phase 5 部分完成，Phase 6–7 待开发。
> 详见 [`docs/DEVELOPMENT_PLAN.md`](./DEVELOPMENT_PLAN.md)。

---

## 1. 身份模型 (Identity Model)

### 三层身份层级

```
Department (dept_id)          ← 部门级
  └── User (user_id)          ← 个人级
       └── Agent (agent_name) ← Agent 级（已有）
```

| 层级 | 标识符 | 典型值 | 说明 |
|------|--------|--------|------|
| 部门 | `dept_id` | `research`, `engineering` | 共享模型配置、基础技能集 |
| 用户 | `user_id` | `alice`, `bob` | 个人偏好、个人 memory、个人 skills |
| Agent | `agent_name` | `sci-agent`, `code-helper` | 专属 persona、专属 workspace |

### 映射到 OpenViking 三层隔离

OpenViking 原生支持三层隔离（Account/User/Agent），与本设计对齐：

| DeerFlow 层级 | OV HTTP Header | OV URI 命名空间 |
|-------------|---------------|----------------|
| `dept_id` | `X-OpenViking-Account` | `/local/{dept_id}/` |
| `user_id` | `X-OpenViking-User` | `viking://user/{user_id}/` |
| `agent_name` | `X-OpenViking-Agent` | `viking://agent/{space}/` |

### 传递方式

身份通过 LangGraph `config.configurable` 传入（向后兼容，缺省时退回全局配置）：

```python
config = RunnableConfig(
    configurable={
        "dept_id": "research",      # 新增
        "user_id": "alice",         # 新增
        "agent_name": "sci-agent",  # 已有
        "model_name": "doubao-seed-2.0-pro",
        "thinking_enabled": True,
        "subagent_enabled": True,
    }
)
```

### AgentIdentity 数据类（实际实现）

```python
# deerflow/identity/agent_identity.py

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")

@dataclass
class AgentIdentity:
    """Three-tier agent identity: department / user / agent."""

    dept_id: str | None = field(default=None)
    user_id: str | None = field(default=None)
    agent_name: str | None = field(default=None)

    def __post_init__(self) -> None:
        # Validates each field against _SAFE_ID_RE on construction
        self.dept_id = _validate_id(self.dept_id, "dept_id")
        ...

    @classmethod
    def from_config(cls, config: RunnableConfig) -> "AgentIdentity":
        cfg = config.get("configurable", {}) if config else {}
        return cls(
            dept_id=cfg.get("dept_id") or None,
            user_id=cfg.get("user_id") or None,
            agent_name=cfg.get("agent_name") or None,
        )

    @property
    def ov_account(self) -> str: return self.dept_id or "default"
    @property
    def ov_user(self) -> str: return self.user_id or "default"
    @property
    def ov_agent(self) -> str: return self.agent_name or "default"

    @property
    def ov_headers(self) -> dict[str, str]:
        """All three OV identity headers as a dict (convenience property)."""
        return {
            "X-OpenViking-Account": self.ov_account,
            "X-OpenViking-User": self.ov_user,
            "X-OpenViking-Agent": self.ov_agent,
        }

    @property
    def is_global(self) -> bool: return not (self.dept_id or self.user_id)

    @property
    def has_dept(self) -> bool: return self.dept_id is not None
    @property
    def has_user(self) -> bool: return self.user_id is not None
    @property
    def has_agent(self) -> bool: return self.agent_name is not None
```

---

## 2. 目录结构设计

### 完整路径结构

```
$DEER_FLOW_HOME/  (默认 ~/.deer-flow/ 或 backend/.deer-flow/)
│
├── config.yaml                     # 全局：模型/工具/sandbox/memory 默认值
├── extensions_config.json          # 全局：MCP + skills 启用列表
├── memory.json                     # 全局 memory（无 identity 时使用）
├── SOUL.md                         # 全局 persona（最低优先级）
├── USER.md
├── IDENTITY.md
├── [其他 persona 文件]
│
├── depts/
│   └── {dept_id}/
│       ├── config.yaml                    # 部门：覆盖全局模型/工具配置
│       ├── extensions_config.json         # 部门：MCP + skills 子集/扩展
│       ├── IDENTITY.md                    # 部门级 persona
│       ├── SOUL.md
│       ├── TOOLS.md
│       ├── AGENTS.md
│       │
│       └── users/
│           └── {user_id}/
│               ├── config.yaml
│               ├── extensions_config.json
│               ├── USER.md
│               ├── LESSONS.md
│               │
│               └── agents/
│                   └── {agent_name}/
│                       ├── config.yaml
│                       ├── extensions_config.json
│                       ├── memory.json                    # Agent 本地 memory
│                       ├── workspace/                     # Agent 持久化工作空间
│                       ├── SOUL.md
│                       ├── IDENTITY.md
│                       ├── BOOTSTRAP.md
│                       ├── HEARTBEAT.md
│                       ├── WORKFLOW_AUTO.md
│                       ├── ERRORS.md
│                       └── LESSONS.md
│
└── threads/
    └── {thread_id}/
        └── user-data/
            ├── workspace/
            ├── uploads/
            └── outputs/
```

### Paths 类实际实现

```python
# deerflow/config/paths.py（新增方法，已实现）

class Paths:
    def dept_dir(self, dept_id: str) -> Path:
        return self.base_dir / "depts" / dept_id

    def dept_user_dir(self, dept_id: str, user_id: str) -> Path:
        return self.dept_dir(dept_id) / "users" / user_id

    def dept_user_agent_dir(self, dept_id: str, user_id: str, agent_name: str) -> Path:
        return self.dept_user_dir(dept_id, user_id) / "agents" / agent_name.lower()

    def identity_agent_dir(self, identity: AgentIdentity) -> Path | None:
        """三层优先，降级到 legacy agents/{agent_name}/"""
        if not identity.has_agent:
            return None
        if identity.has_dept and identity.has_user:
            return self.dept_user_agent_dir(identity.dept_id, identity.user_id, identity.agent_name)
        return self.agent_dir(identity.agent_name)   # legacy

    def identity_config_files(self, identity: AgentIdentity) -> list[Path]:
        """按优先级从低到高排列（不过滤不存在的文件，调用方负责 skip）"""
        ...

    def identity_extensions_dirs(self, identity: AgentIdentity) -> list[Path]:
        """global → dept → user → agent"""
        ...

    def identity_memory_file(self, identity: AgentIdentity) -> Path:
        """identity 作用域的 memory.json，降级到全局"""
        ...

    def identity_persona_dirs(self, identity: AgentIdentity) -> list[Path]:
        """persona 文件搜索目录，global → dept → user → agent"""
        ...

    def identity_workspace_dir(self, identity: AgentIdentity) -> Path | None:
        """agent 持久化 workspace 目录"""
        agent_dir = self.identity_agent_dir(identity)
        return agent_dir / "workspace" if agent_dir else None
```

---

## 3. 配置分层合并 (Layered Config)

### 合并规则

```
全局 config.yaml
  ↓ merge (dept 覆盖全局)
部门 config.yaml
  ↓ merge (user 覆盖部门)
用户 config.yaml
  ↓ merge (agent 覆盖用户)
Agent config.yaml
  = 最终有效配置
```

### 实际实现

```python
# deerflow/config/layered_config.py

def load_layered_config_dict(identity: AgentIdentity) -> dict[str, Any]:
    """返回深度合并后的原始 config dict（调用方再 model_validate 为 AppConfig）。"""
    config_files = get_paths().identity_config_files(identity)
    merged: dict[str, Any] = {}
    for path in config_files:
        layer = _load_yaml(path)   # 文件不存在返回 {}
        if layer:
            merged = _deep_merge(merged, layer)
    return merged

def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并；含 name 字段的列表按名去重合并（model 列表 union）。"""
    ...

def _merge_named_list(base: list, override: list) -> list:
    """同名 item 深度合并，新名称 item 追加，保留原始顺序。"""
    ...
```

> **⚠️ 待完成**：`agent.py` 中 `get_app_config()` 尚未替换为 `load_layered_config_dict(identity)` + `AppConfig.model_validate()`。

---

## 4. 个性化文件系统 (Persona System)

### 文件定义与合并策略

| 文件 | 用途 | 合并策略 | 提示词注入段 |
|------|------|---------|--------------|
| `IDENTITY.md` | Agent 身份定义 | **Override** — last-wins | `<identity>` |
| `SOUL.md` | Agent 性格/风格 | **Override** — last-wins | `<soul>` |
| `USER.md` | 用户画像/偏好 | **Override** — last-wins | `<user_context>` |
| `AGENTS.md` | 团队/子代理协作 | **Override** — last-wins | `<team_context>` |
| `BOOTSTRAP.md` | 初始化指令 | **Append** — `---` 分隔 | `<bootstrap>` |
| `HEARTBEAT.md` | 定期自检任务 | **Append** — `---` 分隔 | `<heartbeat>` |
| `TOOLS.md` | 工具使用规范和偏好 | **Append** — `---` 分隔 | `<tools_guidance>` |
| `WORKFLOW_AUTO.md` | 自动化工作流模式 | **Append** — `---` 分隔 | `<workflow>` |
| `ERRORS.md` | 错误处理和恢复模式 | **Append** — `---` 分隔 | `<error_patterns>` |
| `LESSONS.md` | 经验教训库 | **Append** — `---` 分隔 | `<lessons>` |

### PersonaLoader 实际实现

```python
# deerflow/identity/persona.py

class PersonaLoader:
    def load(self, identity: AgentIdentity, base_dir: Path | None = None) -> PersonaContext:
        """加载并合并指定 identity 的所有 persona 文件。

        base_dir: 覆盖 DEER_FLOW_HOME（用于测试隔离）。
        """
        paths = get_paths()
        if base_dir is not None:
            paths = Paths(base_dir)
        dirs = paths.identity_persona_dirs(identity)   # global → dept → user → agent
        return self._merge(dirs)

    def load_global(self, base_dir: Path | None = None) -> PersonaContext:
        """仅加载全局层 persona 文件（向后兼容）。"""
        ...
```

### 系统提示注入（prompt.py 实际实现）

```python
# deerflow/agents/lead_agent/prompt.py

def apply_prompt_template(
    subagent_enabled: bool = False,
    max_concurrent_subagents: int = 3,
    *,
    agent_name: str | None = None,
    available_skills: set[str] | None = None,
    persona: PersonaContext | None = None,
    identity: AgentIdentity | None = None,   # ← 新增，用于 identity-scoped memory 注入
) -> str:
    # memory 按 identity 加载隔离的 memory.json
    memory_context = _get_memory_context(agent_name, identity)
    ...
    # persona sections 追加在 prompt 末尾
    if persona_sections:
        result += f"\n\n{persona_sections}"

def _get_memory_context(agent_name: str | None = None, identity: AgentIdentity | None = None) -> str:
    """按 identity 加载对应 memory.json，注入 <memory> 标签。"""
    memory_data = get_memory_data(agent_name, identity)
    ...
```

---

## 5. Skills & Plugin 隔离

### 分层加载策略（待实现）

```
全局 extensions_config.json   →  所有可用 skills + MCP（基准集）
     ↓ intersect
部门 extensions_config.json   →  部门允许集
     ↓ intersect
用户 extensions_config.json   →  用户允许集
     ↓ intersect
Agent extensions_config.json  →  Agent 最终使用集
```

规则：
1. **全局层** = 所有可用资源的完整声明
2. **部门/用户/Agent 层** = `enabled: true/false` 控制子集
3. **最终生效** = 所有层均 `enabled: true` 才可用（最严格原则）

### LayeredExtensionsConfig 实际实现

```python
# deerflow/config/layered_extensions.py（已实现）

def load_layered_extensions(identity: AgentIdentity) -> ExtensionsConfig:
    """MCP last-layer-wins + Skills intersection（任一层禁用即禁用）。"""
    dirs = get_paths().identity_extensions_dirs(identity)
    merged_mcp: dict[str, Any] = {}
    skill_states: dict[str, bool | None] = {}

    for d in dirs:
        layer = _load_json(d / "extensions_config.json")
        # MCP: 后层浅合并覆盖
        # Skills: disabled at any layer → stays disabled
        ...

    return ExtensionsConfig.model_validate({"mcpServers": merged_mcp, "skills": final_skills})
```

> **⚠️ 待完成**：`skills/loader.py` 和 `mcp/tools.py` 尚未接入 `load_layered_extensions(identity)`。

---

## 6. Memory 隔离（OV Memory Backend）

### 配置字段

```yaml
# config.yaml memory 新增字段
memory:
  enabled: true
  backend: local          # local | ov | ov+local
  ov_url: http://localhost:1933
  ov_api_key: $OV_API_KEY
```

### OV Memory Backend 实际实现

```python
# deerflow/agents/memory/ov_backend.py

class OVMemoryBackend:
    """通过 OpenViking HTTP API 实现 agent-level 隔离记忆存储。"""

    def __init__(self, ov_url: str, api_key: str | None, identity: AgentIdentity) -> None:
        self._base_url = ov_url.rstrip("/")
        self._identity = identity
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        # 自动注入三层 OV header + 可选 Authorization
        return {"Content-Type": "application/json", **self._identity.ov_headers, ...}

    async def store_memory(self, messages: list[dict]) -> None:
        """POST /api/memory/store"""
        ...

    async def search_memory(self, query: str, limit: int = 15) -> list[dict]:
        """POST /api/memory/search，连接失败时降级返回 []"""
        ...
```

### Memory 隔离链路（实际实现）

```
make_lead_agent
  ├── identity = AgentIdentity.from_config(config)
  ├── apply_prompt_template(..., identity=identity)   → _get_memory_context(agent_name, identity)
  │                                                      → get_memory_data(agent_name, identity)
  │                                                        → identity_memory_file(identity)
  │
  └── _build_middlewares(..., identity=identity)
        └── MemoryMiddleware(agent_name=agent_name, identity=identity)
              └── after_agent: queue.add(..., identity=identity)
                    └── MemoryUpdater.update_memory(..., identity=identity)
                          ├── get_memory_data(agent_name, identity)   # 读
                          └── _save_memory_to_file(data, agent_name, identity)  # 写
                                └── _memory_cache_key(agent_name, identity)    # 正确的缓存键
```

**Memory 文件路径隔离**：
- `alice/sci-agent` → `depts/research/users/alice/agents/sci-agent/memory.json`
- `bob/sci-agent` → `depts/research/users/bob/agents/sci-agent/memory.json`
- 全局（无 identity）→ `memory.json`

> **⚠️ 待完成**：`MemoryMiddleware.after_agent` 目前始终走 local queue。按 `memory_config.backend` 路由到 `OVMemoryBackend` 的逻辑尚未接入。

---

## 7. Workspace 隔离（含 MinIO）

### WorkspaceBackend 接口（已实现）

```python
# deerflow/sandbox/workspace/__init__.py

class WorkspaceBackend(ABC):
    @abstractmethod
    async def sync_down(self, identity: AgentIdentity, local_dir: Path) -> None:
        """从后端同步到本地目录（sandbox Acquire 时调用）"""

    @abstractmethod
    async def sync_up(self, identity: AgentIdentity, local_dir: Path) -> None:
        """从本地目录同步到后端（sandbox Release 后调用）"""
```

### LocalWorkspaceBackend（已实现）

```python
# deerflow/sandbox/workspace/local_backend.py

class LocalWorkspaceBackend(WorkspaceBackend):
    """持久化路径：identity_workspace_dir(identity) = .../agents/{agent_name}/workspace/"""

    async def sync_down(self, identity, local_dir):
        workspace = get_paths().identity_workspace_dir(identity)
        # 递归复制 persistent → thread-local
        ...

    async def sync_up(self, identity, local_dir):
        workspace = get_paths().identity_workspace_dir(identity)
        # 递归复制 thread-local → persistent
        ...
```

### MinIOWorkspaceBackend（已实现，未集成）

```python
# deerflow/sandbox/workspace/minio_backend.py

class MinIOWorkspaceBackend(WorkspaceBackend):
    """对象路径：{bucket}/{prefix}/{dept_id}/{user_id}/{agent_name}/"""
    ...
```

### config.yaml 新增字段

```yaml
workspace:
  backend: local  # local | minio

  # minio:
  #   endpoint: $MINIO_ENDPOINT
  #   bucket: deer-flow
  #   access_key: $MINIO_ACCESS_KEY
  #   secret_key: $MINIO_SECRET_KEY
  #   secure: false
  #   prefix: workspaces
```

> **⚠️ 待完成**：`SandboxMiddleware` 未集成 `WorkspaceBackend`，`/mnt/agent-workspace` 虚拟路径映射未添加，`AppConfig` 未添加 `WorkspaceConfig` 字段。

---

## 8. Gateway API 扩展（待开发）

### 规划端点 `/api/identity`

```python
GET  /api/identity/depts
POST /api/identity/depts
GET  /api/identity/depts/{dept_id}/users
POST /api/identity/depts/{dept_id}/users/{uid}/agents
GET  /api/identity/effective-config?dept_id=...&user_id=...&agent_name=...
GET  /api/identity/persona?dept_id=...&user_id=...&agent_name=...
PUT  /api/identity/persona/{file_name}
GET  /api/identity/skills?dept_id=...&user_id=...&agent_name=...
```

---

## 9. 向后兼容保证

- `dept_id` / `user_id` 均为**可选字段**，缺省时完全退回现有全局行为
- 现有 `agents/{agent_name}/` 目录路径继续有效（映射为 `dept=None, user=None` 场景）
- 现有 `extensions_config.json` 继续作为全局层使用，结构不变
- 现有 `SOUL.md` / `USER.md` 加载逻辑保持，通过 `PersonaLoader` 统一兼容
- `memory.backend` 默认为 `local`，行为与现有完全一致
- `workspace.backend` 默认为 `local`，行为与现有完全一致
- 新字段均有默认值，不破坏现有 `config.yaml`
- Memory 缓存键使用 `_memory_cache_key(agent_name, identity)`，全局 identity 降级到 `("agent", agent_name)` 键，与原有缓存兼容
