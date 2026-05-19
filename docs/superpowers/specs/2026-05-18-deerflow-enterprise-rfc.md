# DeerFlow 企业级扩展设计

> 日期：2026-05-18
> 方案：B — 独立 enterprise 包，分层放置,配置驱动

## 目录

1. [需求总结](#1-需求总结)
2. [开发规范约束](#2-开发规范约束)
3. [整体架构](#3-整体架构) — 包结构、配置集成、中间件注入
4. [RBAC 权限控制](#4-rbac-权限控制) — 数据模型、PermissionProvider、与现有权限体系集成
5. [审计日志](#5-审计日志) — 事件、存储、签名、中间件、v2 异步队列
6. [审批工作流](#6-审批工作流) — 状态机、规则引擎、Checkpoint、超时、通知器、GuardrailProvider 复用
7. [OIDC 单点登录](#7-oidc-单点登录) — 配置、OIDCClient、AuthProvider 适配器、安全设计
8. [持久化层](#8-持久化层) — Alembic 集成、表结构、Repository、迁移
9. [Gateway API 路由](#9-gateway-api-路由) — 路由表、请求/响应模型、依赖注入、启动集成
10. [前端集成](#10-前端集成)
11. [对原有代码的改动](#11-对原有代码的改动) — 必要改动、优化改动、简化收益
12. [测试策略](#12-测试策略)

---

## 1. 需求总结

| 维度 | 决定 |
|------|------|
| 目标用户 | 单一组织内部部署 |
| 部署环境 | Docker / Docker Compose |
| 功能优先级 | RBAC > 审计日志 > 审批工作流 > 企业知识库 |
| 审批通知 | Web UI + 飞书 + 企业微信 |
| 知识库 | 用现有 MCP/上传能力，不单独建 |
| 存储后端 | 可切换（SQLite 开发 / PostgreSQL 生产） |
| 代码边界 | 分层：核心抽象放 harness，路由放 app |

## 2. 开发规范约束

严格遵循现有代码规范，不做任何偏离：

- Python 3.12+，type hints，双引号，空格缩进
- ruff lint/format，行宽 240
- Pydantic BaseModel 做数据模型，ABC + Protocol 做抽象接口
- `resolve_variable()`/`resolve_class()` 反射模式做插件加载
- `config.yaml` 配置驱动，`$VAR` 环境变量替换
- harness/app 严格边界：app 可导入 deerflow，deerflow 不导入 app（CI `test_harness_boundary.py` 执行）
- TDD：每个功能必须配单元测试
- 中间件继承 `AgentMiddleware[AgentState]`，用 `@Next`/`@Prev` 定位
- AuthProvider ABC 做认证扩展
- UserRepository ABC 做存储抽象

## 3. 整体架构

### 3.1 包结构

> **路径约定**：本仓库 Python 代码全部位于 `backend/` 下。下文以仓库根为基准，因此 harness 层完整路径为 `backend/packages/harness/deerflow/...`，app 层为 `backend/app/...`。

```
# Harness 层 — 核心抽象与逻辑（不依赖 app）
backend/packages/harness/deerflow/enterprise/
├── __init__.py
├── config.py                     # EnterpriseConfig (Pydantic)
├── middlewares.py                 # 中间件组装器（仅 AuditMiddleware）
├── rbac/
│   ├── __init__.py
│   ├── models.py                  # Role, Permission, 角色权限映射
│   ├── permission_provider.py     # RbacPermissionProvider（实现 PermissionProvider 协议）
│   └── repository.py             # RbacRepository ABC + SQLite/PG 实现
├── audit/
│   ├── __init__.py
│   ├── events.py                  # AuditEvent, AuditEventType
│   ├── storage.py                 # AuditStorage ABC + SQLite/PG 实现
│   ├── signer.py                  # AuditSigner HMAC 防篡改
│   └── middleware.py              # AuditMiddleware (@Next("sandbox_audit"))
├── approval/
│   ├── __init__.py
│   ├── models.py                  # Approval, ApprovalRule, ApprovalStatus
│   ├── engine.py                  # ApprovalRuleEngine
│   ├── checkpoint.py              # ApprovalCheckpoint（断点保存/恢复）
│   ├── timeout.py                 # ApprovalTimeoutChecker（超时自动过期）
│   ├── guardrail_provider.py      # ApprovalGuardrailProvider（复用 GuardrailMiddleware）
│   ├── notifiers/
│   │   ├── __init__.py
│   │   ├── base.py                # ApprovalNotifier ABC
│   │   ├── web.py                 # WebNotifier（写 DB）
│   │   ├── feishu.py              # FeishuNotifier（飞书卡片）
│   │   └── wecom.py               # WeComNotifier（企微消息）
│   └── repository.py             # ApprovalRepository ABC + SQLite/PG 实现
├── auth/
│   ├── __init__.py
│   ├── oidc_client.py             # OIDCClient — OIDC 协议实现（harness 层，不依赖 AuthProvider）
│   ├── oidc_config.py             # OIDCConfig (Pydantic)
│   └── role_mapper.py             # OIDCRoleMapper claim → Role
└── persistence/
    ├── __init__.py
    ├── database.py                 # EnterpriseDatabase + SQLAlchemy Base
    └── migrations/
        └── versions/                # Alembic 修订脚本（共用 backend/packages/harness/deerflow/persistence/migrations/ 的 env.py 与 alembic.ini）
            ├── <hash>_initial_enterprise_schema.py
            └── <hash>_oidc_links.py

# App 层 — Gateway 路由与 HTTP 适配
backend/app/enterprise/
├── __init__.py
├── deps.py                        # FastAPI 依赖注入（单例模式）
├── models.py                      # 请求/响应 Pydantic 模型
├── oidc_auth_adapter.py           # OIDCAuthProvider(AuthProvider) — app 层适配器
└── routers/
    ├── rbac.py                     # /api/enterprise/rbac/*
    ├── audit.py                    # /api/enterprise/audit/*
    ├── approval.py                 # /api/enterprise/approval/*
    ├── auth.py                     # /api/enterprise/auth/oidc/*
    └── dashboard.py                # /api/enterprise/dashboard/*
```

> **设计提示**：上述包结构有意**不**新建 user-role 关联表。用户角色直接挂在 `User.roles: list[str]` 字段上（详见 §11.5 / §11.7），因此 `rbac/repository.py` 只处理 `roles` 与 `role_permissions` 两张表，不涉及用户-角色绑定。

### 3.2 配置集成

在 `config.yaml` 新增 `enterprise:` 段：

```yaml
enterprise:
  enabled: true

  rbac:
    enabled: true
    default_role: member
    # 覆盖默认角色权限映射（可选，为空则用内置默认值）
    role_permissions: null

  audit:
    enabled: true
    storage:
      use: "deerflow.enterprise.persistence.database:SqliteAuditStorage"
    retention_days: 2555
    sign_key: "$AUDIT_SIGN_KEY"

  approval:
    enabled: true
    rules:
      - id: "sandbox_dangerous_cmd"
        name: "危险沙箱命令审批"
        action_type: "sandbox:command"
        condition: "command in ['rm', 'sudo', 'chmod']"
        approver_roles: ["admin", "project_manager"]
        urgency: "normal"
        deadline_hours: 24
        min_approvals: 1
        enabled: true
      - id: "data_export"
        name: "数据导出审批"
        action_type: "data:export"
        condition: null
        approver_roles: ["admin"]
        urgency: "urgent"
        deadline_hours: 48
        min_approvals: 2
        enabled: true
    notifiers:
      - use: "deerflow.enterprise.approval.notifiers.web:WebNotifier"
      - use: "deerflow.enterprise.approval.notifiers.feishu:FeishuNotifier"
        app_id: "$FEISHU_APP_ID"
        app_secret: "$FEISHU_APP_SECRET"
      - use: "deerflow.enterprise.approval.notifiers.wecom:WeComNotifier"
        corp_id: "$WECOM_CORP_ID"
        agent_id: "$WECOM_AGENT_ID"
        secret: "$WECOM_SECRET"

  auth:
    oidc:
      enabled: true
      issuer: "https://keycloak.example.com/realms/myorg"
      client_id: "deerflow"
      client_secret: "$OIDC_CLIENT_SECRET"
      scopes: ["openid", "profile", "email", "groups"]
      redirect_uri: "https://deerflow.example.com/api/enterprise/auth/oidc/callback"
      role_mapping:
        claim_field: "groups"
        mappings:
          "deerflow-admin": "admin"
          "deerflow-pm": "project_manager"
          "deerflow-member": "member"
        default_role: "member"
      auto_provision: true

  database:
    url: "sqlite:///./enterprise.db"
    echo: false
```

### 3.3 中间件注入

通过 `_make_lead_agent` 透传 `custom_middlewares` 到 `_build_middlewares()`（~3 行改动，参数已就位，详见 §11.1 / §11.4）。

**简化后企业版只需 1 个 Agent 中间件**（AuditMiddleware）：
- RBAC：通过 `PermissionProvider` 在 HTTP 层生效，不需要 Agent 层中间件
- 审批：复用现有 `GuardrailMiddleware`，实现为 `ApprovalGuardrailProvider`
- 审计：`AuditMiddleware` 是唯一新增的 Agent 层中间件

| 中间件 | 位置 | 原因 |
|--------|------|------|
| `AuditMiddleware` | `@Next("sandbox_audit")` | 在现有 SandboxAuditMiddleware 之后，记录 Agent 层事件到结构化存储 |

```python
# deerflow/enterprise/middlewares.py

def get_enterprise_middlewares(config: EnterpriseConfig) -> list[AgentMiddleware]:
    middlewares = []
    if not config.enabled:
        return middlewares
    if config.audit.enabled:
        middlewares.append(AuditMiddleware(config.audit))
    return middlewares
```

当 `enterprise.enabled = false` 时，无中间件加载，零开销。

## 4. RBAC 权限控制

### 4.1 数据模型

```python
# deerflow/enterprise/rbac/models.py

class Role(str, Enum):
    ADMIN = "admin"
    PROJECT_MANAGER = "project_manager"
    MEMBER = "member"
    VIEWER = "viewer"

class Permission(str, Enum):
    # Agent
    AGENT_CREATE = "agent:create"
    AGENT_DELETE = "agent:delete"
    AGENT_VIEW = "agent:view"
    AGENT_EXECUTE = "agent:execute"
    # Thread
    THREAD_CREATE = "thread:create"
    THREAD_READ = "thread:read"
    THREAD_WRITE = "thread:write"
    THREAD_DELETE = "thread:delete"
    # Approval
    APPROVAL_CREATE = "approval:create"
    APPROVAL_GRANT = "approval:grant"
    APPROVAL_REJECT = "approval:reject"
    APPROVAL_VIEW = "approval:view"
    # Data
    DATA_READ = "data:read"
    DATA_WRITE = "data:write"
    DATA_DELETE = "data:delete"
    DATA_EXPORT = "data:export"
    # Admin
    USER_MANAGE = "user:manage"
    ROLE_MANAGE = "role:manage"
    SYSTEM_SETTINGS = "system:settings"

DEFAULT_ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: {
        # 所有 Permission
        Permission.AGENT_CREATE, Permission.AGENT_DELETE, Permission.AGENT_VIEW, Permission.AGENT_EXECUTE,
        Permission.THREAD_CREATE, Permission.THREAD_READ, Permission.THREAD_WRITE, Permission.THREAD_DELETE,
        Permission.APPROVAL_CREATE, Permission.APPROVAL_GRANT, Permission.APPROVAL_REJECT, Permission.APPROVAL_VIEW,
        Permission.DATA_READ, Permission.DATA_WRITE, Permission.DATA_DELETE, Permission.DATA_EXPORT,
        Permission.USER_MANAGE, Permission.ROLE_MANAGE, Permission.SYSTEM_SETTINGS,
    },
    Role.PROJECT_MANAGER: {
        Permission.AGENT_CREATE, Permission.AGENT_VIEW, Permission.AGENT_EXECUTE,
        Permission.THREAD_CREATE, Permission.THREAD_READ, Permission.THREAD_WRITE,
        Permission.APPROVAL_CREATE, Permission.APPROVAL_GRANT, Permission.APPROVAL_REJECT, Permission.APPROVAL_VIEW,
        Permission.DATA_READ, Permission.DATA_WRITE,
    },
    Role.MEMBER: {
        Permission.AGENT_VIEW, Permission.AGENT_EXECUTE,
        Permission.THREAD_CREATE, Permission.THREAD_READ, Permission.THREAD_WRITE,
        Permission.APPROVAL_VIEW,
        Permission.DATA_READ, Permission.DATA_WRITE,
    },
    Role.VIEWER: {
        Permission.AGENT_VIEW, Permission.THREAD_READ, Permission.DATA_READ, Permission.APPROVAL_VIEW,
    },
}

# 与 doc 14 §14.4 Permission 枚举的差异：
# - 丢弃 PROJECT_* 系列（PROJECT_CREATE/UPDATE/DELETE/VIEW）
# - 丢弃 TENANT_SETTINGS
# 原因：本 RFC §1 限定单组织部署，无 Project/Tenant 概念。如未来引入项目维度，
# 按相同模式新增 PROJECT_* 即可，不影响现有权限解析路径。
#
# 当前消费/预留状态：
# - 实际被 §9.1 路由消费的字符串：
#     approval:view / approval:grant / approval:reject / approval:create,
#     data:read / data:export,
#     role:manage, user:manage, system:settings
# - **预留枚举值**（定义但 §9.1 尚未引用）：
#     AGENT_CREATE / AGENT_DELETE / AGENT_VIEW / AGENT_EXECUTE,
#     THREAD_CREATE / THREAD_READ / THREAD_WRITE / THREAD_DELETE,
#     DATA_WRITE / DATA_DELETE
#   这些枚举为未来把 /api/agents/* 与 /api/threads/* 路由迁移到企业权限模型时
#   预留命名空间。现有 threads:* / runs:* 路由仍由 §4.3 描述的 LEGACY 映射兜底，
#   两者并存不冲突。

# 现有 Permissions 命名空间到企业 Role 的映射（resolve_permissions 必须同时返回）
# 见 §4.3 — 否则注册 PermissionProvider 后现有 threads/runs 路由会 403。
LEGACY_PERMISSIONS_FOR_ROLE: dict[Role, set[str]] = {
    Role.ADMIN: {"threads:read", "threads:write", "threads:delete",
                 "runs:create", "runs:read", "runs:cancel"},
    Role.PROJECT_MANAGER: {"threads:read", "threads:write",
                           "runs:create", "runs:read", "runs:cancel"},
    Role.MEMBER: {"threads:read", "threads:write",
                  "runs:create", "runs:read", "runs:cancel"},
    Role.VIEWER: {"threads:read", "runs:read"},
}
```

### 4.2 PermissionProvider 实现

实现 `authz.py` 的 `PermissionProvider` 协议，复用现有 `@require_permission` 装饰器体系：

```python
# deerflow/enterprise/rbac/permission_provider.py

class RbacPermissionProvider:
    """企业 RBAC 权限解析器 — 实现 PermissionProvider 协议"""

    def __init__(self, config: RbacConfig, repo: RbacRepository):
        self.config = config
        self.repo = repo

    async def resolve_permissions(self, user: "User") -> list[str]:
        """解析用户权限 — 供 authz.py 调用"""
        # 1. 从 User.roles + User.system_role 确定角色
        roles = self._resolve_roles(user)

        # 2. 合并各角色的企业权限 + 现有 threads/runs 权限（见 §4.3）
        permissions: set[str] = set()
        for role in roles:
            # 企业 Permission 枚举
            perms = await self.repo.get_role_permissions(role)
            permissions.update(p.value for p in perms)
            # 现有 Permissions 常量（threads/runs 路由依赖）
            permissions.update(LEGACY_PERMISSIONS_FOR_ROLE.get(role, set()))

        return list(permissions)

    def _resolve_roles(self, user: "User") -> list[Role]:
        """从 User 模型解析角色"""
        # 优先使用 User.roles（企业角色）
        if user.roles:
            return [Role(r) for r in user.roles if r in Role._value2member_map_]

        # 回退到 system_role 映射
        mapping = {"admin": Role.ADMIN, "user": Role.MEMBER}
        return [mapping.get(user.system_role, self.config.default_role)]
```

**启动时注册**：

`set_permission_provider()` 必须在 `lifespan()` 启动阶段、第一个请求到达前调用，详见 §9.4。`app/enterprise/deps.py` 中的 `get_rbac_checker()` 是惰性单例工厂，由 `lifespan` 显式拉取并交给 `set_permission_provider()`：

```python
# app/enterprise/deps.py 中
async def get_rbac_checker() -> RbacPermissionProvider:
    """惰性单例：构造 RbacPermissionProvider；不在此处调用 set_permission_provider"""
    global _rbac_checker
    if _rbac_checker is None:
        from deerflow.enterprise.rbac.permission_provider import RbacPermissionProvider
        config = get_enterprise_config()
        rbac_repo = await _get_rbac_repo()
        _rbac_checker = RbacPermissionProvider(config.rbac, rbac_repo)
    return _rbac_checker
```

### 4.3 与现有权限体系集成

**核心原则**：企业 `Permission` 枚举是**新增、独立**的命名空间，与现有 `app.gateway.authz.Permissions` 常量并存，**不替换、不重命名**任何现有权限字符串。

- 现有 [authz.py:48-59](backend/app/gateway/authz.py#L48-L59) 中的 `Permissions` 常量（`threads:read`、`threads:write`、`threads:delete`、`runs:create`、`runs:read`、`runs:cancel`）保持原样，所有现有路由的 `@require_permission("threads", "read")` 写法**完全不动**
- 企业新增的 `agent:*`、`approval:*`、`data:*`、`user:*`、`role:*`、`system:*` 字符串只用于**新增的企业路由**（§9.1）和企业路由内部的细粒度判断
- 同一权限字符串格式（`{resource}:{action}`）下，两套权限可以混合存在于同一 `AuthContext.permissions` 列表中
- 现有 `@require_permission` 装饰器**完全复用**，无需修改任何现有路由代码
- 不注册 `PermissionProvider` 时，`_authenticate()` 仍返回 `_ALL_PERMISSIONS`（仅含 threads/runs），行为与改造前一致
- 注册 `RbacPermissionProvider` 后：
  - **现有路由**：`AuthContext.permissions` 由企业 provider 决定。`RbacPermissionProvider.resolve_permissions()` 必须**同时返回**现有 `threads:*`/`runs:*` 字符串和新企业字符串，否则现有路由会 403。这通过 §4.1 的 `LEGACY_PERMISSIONS_FOR_ROLE` 提供——`resolve_permissions()` 把它和 `DEFAULT_ROLE_PERMISSIONS` 的结果并集返回。注意：`DEFAULT_ROLE_PERMISSIONS` 类型是 `dict[Role, set[Permission]]`（枚举值），legacy 字符串只能走 `LEGACY_PERMISSIONS_FOR_ROLE` 这条路，不要尝试塞入 `DEFAULT_ROLE_PERMISSIONS`
  - **企业路由**：使用 §9.1 的新 permission 字符串
- 不区分来源：`AuthContext.has_permission("threads", "read")` 和 `has_permission("data", "read")` 走同一条代码路径，企业 provider 负责让两者都返回正确结果

### 4.4 与现有 User 模型集成

- `User.system_role` 从 `Literal["admin", "user"]` 放宽为 `str`（~1 行改动）
- `User` 新增 `roles: list[str]` 字段（~2 行改动）
- RBAC 查询：优先读 `User.roles`，无角色时回退到 `User.system_role` 映射
- 不需要独立的 `enterprise_user_roles` 表
- `UserRow` 新增 `roles TEXT` 列存 JSON，`system_role` 列已是 `String(16)` 无需改动

## 5. 审计日志

### 5.1 事件模型

```python
# deerflow/enterprise/audit/events.py

class AuditEventType(str, Enum):
    AUTH_LOGIN = "auth:login"
    AUTH_LOGOUT = "auth:logout"
    AUTH_FAILED = "auth:failed"
    AUTH_OIDC_LOGIN = "auth:oidc_login"
    AGENT_CREATED = "agent:created"
    AGENT_TASK_STARTED = "agent:task_started"
    AGENT_TASK_COMPLETED = "agent:task_completed"
    AGENT_ERROR = "agent:error"
    DATA_READ = "data:read"
    DATA_WRITTEN = "data:written"
    DATA_DELETED = "data:deleted"
    DATA_EXPORTED = "data:exported"
    APPROVAL_REQUESTED = "approval:requested"
    APPROVAL_GRANTED = "approval:granted"
    APPROVAL_REJECTED = "approval:rejected"
    APPROVAL_EXPIRED = "approval:expired"
    APPROVAL_CANCELLED = "approval:cancelled"
    SANDBOX_ACQUIRED = "sandbox:acquired"
    SANDBOX_RELEASED = "sandbox:released"
    SANDBOX_COMMAND_EXECUTED = "sandbox:command_executed"
    ROLE_CHANGED = "rbac:role_changed"
    PERMISSION_DENIED = "rbac:permission_denied"

class AuditEvent(BaseModel):
    event_type: AuditEventType
    user_id: str
    timestamp: datetime
    project_id: str | None = None
    agent_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    action: str | None = None
    result: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    signature: str | None = None
```

### 5.2 存储抽象

> 接口的权威定义见 §8.3；本节列出供本章上下文阅读所需的子集。
>
> **v1 同步路径下** `append_batch` 不会被调用，可作为简单的 for-loop fallback 实现（`for e in events: await self.append(e)`），无需额外优化。仅当切换到 §5.5 的 v2 异步队列方案时才有真实批写收益，届时各 Storage 实现可独立优化为单 `executemany` / `COPY` 语句。

```python
# deerflow/enterprise/audit/storage.py

class AuditStorage(ABC):
    @abstractmethod
    async def append(self, event: AuditEvent) -> None: ...

    @abstractmethod
    async def append_batch(self, events: list[AuditEvent]) -> None: ...

    @abstractmethod
    async def query(self, filters: AuditQuery, page: int, page_size: int) -> list[AuditEvent]: ...

    @abstractmethod
    async def count(self, filters: AuditQuery) -> int: ...

    @abstractmethod
    async def verify_integrity(self, user_id: str | None = None) -> bool: ...

class SqliteAuditStorage(AuditStorage): ...
class PostgresAuditStorage(AuditStorage): ...
```

### 5.3 防篡改签名

```python
# deerflow/enterprise/audit/signer.py

class AuditSigner:
    def sign(self, event: AuditEvent) -> str:
        data = event.model_dump(exclude={"signature"})
        content = json.dumps(data, sort_keys=True, default=str)
        return hmac.new(
            self.secret_key, content.encode(), hashlib.sha256
        ).hexdigest()

    def verify(self, event: AuditEvent) -> bool:
        stored = event.signature
        computed = self.sign(event.model_copy(update={"signature": None}))
        return hmac.compare_digest(stored, computed)
```

### 5.4 中间件

```python
# deerflow/enterprise/audit/middleware.py

@Next("sandbox_audit")
class AuditMiddleware(AgentMiddleware[AgentState]):
    async def aafter_agent(self, state, runtime):
        user_id = get_effective_user_id()
        event = AuditEvent(
            event_type=AuditEventType.AGENT_TASK_COMPLETED,
            user_id=user_id,
            timestamp=datetime.now(UTC),
            agent_id=runtime.config.get("configurable", {}).get("agent_name"),
            resource_type="thread",
            resource_id=state.get("thread_id"),
            action="agent.complete",
            result="success",
            request_id=runtime.config.get("configurable", {}).get("run_id"),
        )
        event.signature = self.signer.sign(event)
        # v1：同步写入 SQLite/PG（微秒级开销，零丢失）
        # v2（可选）：切换为 self.audit_queue.enqueue(event) — 见 §5.5
        # 与 doc 14 §14.5.3 差异：doc 14 用 asyncio.create_task() fire-and-forget，适合
        # PostgreSQL 远程实例场景；v1 同步路径与 SqliteAuditStorage 的微秒级延迟匹配，
        # 实现更简单且零丢失，对应 doc 14 fire-and-forget 模式是本 RFC §5.5 的 v2 优化
        await self.storage.append(event)

    async def awrap_tool_call(self, request, handler):
        # 工具执行前后各记一条事件：SANDBOX_COMMAND_EXECUTED / DATA_EXPORTED 等
        # 具体 event_type 由 _map_tool_to_event_type(request.tool_name) 决定，
        # 实现参照 §6.7 ApprovalGuardrailProvider._map_tool_to_action 的工具名映射风格
        result = await handler(request)
        return result
```

### 5.5 审计写入队列（v2 优化，可选）

> **v1 实现建议**：在 `AuditMiddleware` 中**同步调用** `await storage.append(event)`。SQLite 的单条写入只需百微秒级，对 Agent 链路延迟基本无感；同步路径既简单又零数据丢失风险。
>
> 仅当后续压测发现审计写入成为瓶颈（如启用 PostgreSQL 远程实例、单 Agent 高频小工具调用），再切换到下述异步队列方案。本节保留作为未来优化的设计参考。

审计事件需要可靠写入，不能因应用关闭而丢失。

```python
# deerflow/enterprise/audit/queue.py

class AuditQueue:
    """审计事件队列 — 异步写入，保证不丢失"""

    def __init__(self, storage: AuditStorage, flush_interval: float = 1.0):
        self.storage = storage
        self._queue: asyncio.Queue[AuditEvent] = asyncio.Queue()
        self._flush_interval = flush_interval
        self._flush_task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动后台 flush 协程"""
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def enqueue(self, event: AuditEvent) -> None:
        """入队 — 非阻塞"""
        await self._queue.put(event)

    async def flush(self) -> None:
        """立即刷写所有待写入事件"""
        events: list[AuditEvent] = []
        while not self._queue.empty():
            events.append(self._queue.get_nowait())
        if events:
            await self.storage.append_batch(events)

    async def close(self) -> None:
        """关闭队列 — 刷写剩余事件"""
        if self._flush_task:
            self._flush_task.cancel()
        await self.flush()

    async def _flush_loop(self) -> None:
        """定期刷写"""
        while True:
            await asyncio.sleep(self._flush_interval)
            await self.flush()
```

`EnterpriseDatabase.close()` 时调用 `await self.audit_queue.close()`，保证应用关闭前所有审计事件落盘。

### 5.6 与现有 SandboxAuditMiddleware 的关系

- 现有 `SandboxAuditMiddleware`：记录沙箱操作到文本安全日志（runtime 安全）
- 企业 `AuditMiddleware`：写入结构化存储，支持查询和合规审计（企业合规）
- 两者并存，不冲突

## 6. 审批工作流

> 对齐 `13-human-in-the-loop.md` 的设计模式：Approval（事前审批）、Checkpoint（断点恢复）、多级审批、超时过期、拒绝修订闭环。

### 6.1 状态机

```
PENDING ──────────────────────────────────────────── 初始状态
    │
    ├── (超时) ──▶ EXPIRED
    │
    ├── (取消) ──▶ CANCELLED（仅发起人）
    │
    ├── (批准) ──▶ APPROVED ──▶ Agent 断点恢复执行
    │
    └── (拒绝) ──▶ REJECTED ──▶ 修订闭环
                                    │
                                    ├── 发起人修订后重新提交 ──▶ PENDING（新工单）
                                    └── 发起人放弃 ──▶ CANCELLED
```

### 6.2 数据模型

```python
# deerflow/enterprise/approval/models.py

class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"   # 替代 doc 13 §13.2.2 的 REVOKED：更清晰表达"发起人主动取消未决工单"的语义
    EXPIRED = "expired"

class ApprovalAction(str, Enum):
    SANDBOX_COMMAND = "sandbox:command"
    DATA_EXPORT = "data:export"
    DATA_DELETE = "data:delete"
    AGENT_CONFIG_CHANGE = "agent:config_change"
    FINANCIAL_OPERATION = "financial:operation"

class ApprovalUrgency(str, Enum):
    URGENT = "urgent"
    NORMAL = "normal"
    LOW = "low"

class Approval(BaseModel):
    id: str
    title: str
    description: str
    action_type: ApprovalAction
    action_detail: dict[str, Any]   # 操作详情（结构化），Repository 层负责 DB JSON 序列化
    requester_id: str
    requester_name: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    urgency: ApprovalUrgency = ApprovalUrgency.NORMAL
    approver_ids: list[str]         # 可审批人列表（支持多人）
    approved_by: str | None = None
    rejected_by: str | None = None
    rejection_reason: str | None = None
    revision_of: str | None = None  # 被修订的原始工单 ID（修订闭环）
    created_at: datetime
    deadline: datetime | None = None
    resolved_at: datetime | None = None
    thread_id: str | None = None
    # Checkpoint：审批点的状态快照，用于断点恢复
    checkpoint: str | None = None   # JSON 序列化的 AgentState 快照

class ApprovalRule(BaseModel):
    id: str
    name: str
    action_type: ApprovalAction
    condition: str | None = None     # 受限表达式，非 eval()
    approver_roles: list[Role]       # 支持多角色审批
    urgency: ApprovalUrgency = ApprovalUrgency.NORMAL
    deadline_hours: int = 24
    enabled: bool = True
    # 多级审批：当 min_approvals > 1 时，需要多个审批人批准
    min_approvals: int = 1
```

### 6.3 规则引擎

```python
# deerflow/enterprise/approval/engine.py

class ApprovalRequirement(BaseModel):
    required: bool
    rule: ApprovalRule | None = None
    approvers: list[str] = []       # 解析后的审批人 user_id 列表

class ApprovalRuleEngine:
    async def check_requires_approval(
        self, action_type: ApprovalAction, action_detail: dict, user_id: str,
    ) -> ApprovalRequirement:
        for rule in self.rules:
            if rule.action_type == action_type and rule.enabled:
                if await self._evaluate_condition(rule.condition, action_detail):
                    return ApprovalRequirement(
                        required=True, rule=rule,
                        approvers=await self._resolve_approvers(rule, user_id),
                    )
        return ApprovalRequirement(required=False)

    async def _evaluate_condition(self, condition: str | None, detail: dict) -> bool:
        if condition is None:
            return True
        # 受限表达式解析器：仅支持以下语法
        # - 字段比较：field == value, field != value, field >= value, field <= value, field > value, field < value
        # - 包含检查：field in [literal, ...]
        # - 布尔组合：expr and expr, expr or expr, not expr
        # - 括号分组：( expr )
        # 不支持：任意代码执行、函数调用、属性访问、下标取值、推导式、lambda、import
        #
        # 实现方式：用 `ast.parse(condition, mode="eval")` 得到 AST，然后遍历 AST 并对
        # 每个节点做白名单校验，只允许以下节点类型：
        #   Expression, BoolOp(And|Or), UnaryOp(Not), Compare,
        #   Eq/NotEq/Lt/LtE/Gt/GtE/In/NotIn,
        #   Name（仅作 detail 字段名解析）, Constant, List, Tuple
        # 任何其他节点（Call, Attribute, Subscript, Lambda, …）直接抛 ValueError。
        # 校验通过后用一个自实现的 evaluator 递归 detail 字段查找 + 比较，不调用 `eval()`。
        # 注意：不要用 `ast.literal_eval`——它仅接受字面量，不支持比较运算。
        ...

    async def _resolve_approvers(self, rule: ApprovalRule, requester_id: str) -> list[str]:
        """根据 rule.approver_roles 反查可审批人 user_id 列表（排除发起人自己）。
        通过 §11.2 改动 #8 引入的 `UserRepository.get_users_by_role(role)` 实现。"""
        approvers: set[str] = set()
        for role in rule.approver_roles:
            users = await self.user_repo.get_users_by_role(role.value)
            approvers.update(str(u.id) for u in users if str(u.id) != requester_id)
        return sorted(approvers)
```

### 6.4 Checkpoint 断点恢复

在审批点保存 Agent 完整状态快照，审批通过后从快照恢复执行，而非依赖前端重发。

```python
# deerflow/enterprise/approval/checkpoint.py

class ApprovalCheckpoint:
    """审批检查点 — 保存/恢复 Agent 执行状态"""

    def serialize_state(self, state: dict) -> str:
        """序列化 AgentState 为 JSON 快照"""
        # 仅保留恢复执行所需的关键字段：
        # - messages（对话历史）
        # - thread_id
        # - sandbox_id
        # - uploaded_files
        # - viewed_images（视觉模型已查看图像的虚拟路径列表）
        # 不保存：sandbox 对象、不可序列化的运行时引用
        ...

    def deserialize_state(self, snapshot: str) -> dict:
        """反序列化快照为 AgentState"""
        ...

    async def save_suspend_point(
        self, thread_id: str, approval_id: str, state: dict,
    ) -> None:
        """在审批点持久化暂停状态"""
        snapshot = self.serialize_state(state)
        await self.approval_repo.update_checkpoint(approval_id, snapshot)

    async def restore(self, approval_id: str) -> dict | None:
        """审批通过后恢复执行状态"""
        approval = await self.approval_repo.get(approval_id)
        if approval is None or approval.checkpoint is None:
            return None
        return self.deserialize_state(approval.checkpoint)
```

**与 GuardrailProvider 的配合**：`ApprovalGuardrailProvider` 在拦截工具调用时，将当前 AgentState 快照写入 `Approval.checkpoint`。审批通过后，`/api/enterprise/approval/{id}/approve` 路由调用 `checkpoint.restore()`，通过 `RunManager` 恢复该 thread 的执行。

**Sandbox 恢复策略**：Checkpoint **不**保存 sandbox 对象本身（不可序列化），只保存 `thread_id`/`sandbox_id` 引用。恢复执行时由 `SandboxMiddleware` 在 `before_agent` 钩子中调用 `provider.acquire(thread_id)` 重新取得 sandbox：
- `LocalSandboxProvider.acquire(thread_id)` 基于 `thread_id` 返回新的 `LocalSandbox` 实例（id `local:{thread_id}`），其 `path_mappings` 仍指向同一物理目录 `backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/...`，因此 LRU 缓存即使已驱逐也不会丢数据
- AIO 模式下，`AioSandboxProvider.acquire(thread_id)` 重新挂载同一组卷，行为一致
- `uploaded_files`、`viewed_images` 等引用虚拟路径的字段在反序列化后仍然有效

### 6.5 超时与过期

```python
# deerflow/enterprise/approval/timeout.py

class ApprovalTimeoutChecker:
    """审批超时检查 — 定期扫描过期工单"""

    def __init__(self, repo: ApprovalRepository, notifiers: list[ApprovalNotifier],
                 interval: float = 300.0):
        self.repo = repo
        self.notifiers = notifiers
        self.interval = interval
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._check_loop())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()

    async def _check_loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            expired = await self.repo.mark_expired()
            # 对每个过期工单发送通知
            for approval in expired:
                await self._notify_expired(approval)

    async def _notify_expired(self, approval: Approval) -> None:
        """通知发起人审批已过期，可重新提交"""
        for notifier in self.notifiers:
            await notifier.notify_result(approval)
```

启动时 `ApprovalTimeoutChecker.start()`，关闭时 `ApprovalTimeoutChecker.close()`，与 `lifespan()` 生命周期绑定。

### 6.6 通知器

```python
# deerflow/enterprise/approval/notifiers/base.py

class ApprovalNotifier(ABC):
    @abstractmethod
    async def notify(self, approval: Approval) -> None: ...

    @abstractmethod
    async def notify_result(self, approval: Approval) -> None: ...

# Web：写 DB，前端查询
class WebNotifier(ApprovalNotifier): ...

# 飞书：发送交互式卡片，支持回调按钮（批准/拒绝）
class FeishuNotifier(ApprovalNotifier): ...

# 企业微信：发送文本/卡片消息
class WeComNotifier(ApprovalNotifier): ...
```

通知器通过 `config.use` 反射路径加载，与现有 AuthProvider/ToolProvider 模式一致。

飞书通知卡片支持交互按钮，审批人可直接在飞书中批准/拒绝（回调到 `/api/enterprise/approval/{id}/approve` 或 `/reject`）。

> **与 doc 13 §13.5 通知渠道差异**：doc 13 列出 `in_app / email / feishu / sms` 四个渠道。本 RFC §1 已限定为「Web UI + 飞书 + 企业微信」，未实现 email 和 sms。如后续需要扩展，按相同的 `ApprovalNotifier` ABC + `notifier.use` 反射路径添加即可，无需改动审批引擎。

### 6.7 复用 GuardrailMiddleware（对齐实际 GuardrailProvider 协议）

现有 `GuardrailMiddleware` 已经提供了工具调用拦截框架。审批逻辑直接实现为 `GuardrailProvider`，**必须对齐实际协议签名**：

```python
# 实际 GuardrailProvider 协议（deerflow.guardrails.provider）
class GuardrailProvider(Protocol):
    name: str
    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision: ...
    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision: ...

# GuardrailRequest 字段：tool_name, tool_input, agent_id, thread_id, is_subagent, timestamp
# GuardrailDecision 字段：allow, reasons, policy_id, metadata
```

```python
# deerflow/enterprise/approval/guardrail_provider.py

from deerflow.guardrails.provider import (
    GuardrailDecision, GuardrailProvider, GuardrailReason, GuardrailRequest,
)

class ApprovalGuardrailProvider:
    """审批守卫 — 实现 GuardrailProvider 协议"""

    name: str = "approval"

    def __init__(self, engine: ApprovalRuleEngine, repo: ApprovalRepository,
                 checkpoint: ApprovalCheckpoint, notifiers: list[ApprovalNotifier],
                 **kwargs):
        self.engine = engine
        self.repo = repo
        self.checkpoint = checkpoint
        self.notifiers = notifiers

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        """同步评估（审批必须异步，同步路径直接放行）"""
        return GuardrailDecision(allow=True)

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        """异步评估 — 判断工具调用是否需要审批"""
        user_id = get_effective_user_id()

        # 1. 检查是否已有审批通过（通过 metadata 中的 approval_id）
        existing_id = request.tool_input.get("_approval_id")
        if existing_id:
            approval = await self.repo.get(existing_id)
            if approval and approval.status == ApprovalStatus.APPROVED:
                return GuardrailDecision(allow=True, metadata={"approval_id": existing_id})

        # 2. 判断工具调用是否需要审批
        action_type = self._map_tool_to_action(request.tool_name)
        requirement = await self.engine.check_requires_approval(
            action_type, {"tool": request.tool_name, "args": request.tool_input}, user_id,
        )

        if not requirement.required:
            return GuardrailDecision(allow=True)

        # 3. 需要审批：创建工单 + 保存 Checkpoint + 通知
        approval = await self._create_and_notify(requirement, request, user_id)

        # 4. 拒绝工具调用，返回审批等待消息
        return GuardrailDecision(
            allow=False,
            reasons=[GuardrailReason(
                code="approval.required",
                message=f"操作需要审批，审批工单: {approval.id}，已通知审批人",
            )],
            policy_id=requirement.rule.id if requirement.rule else None,
            metadata={"approval_id": approval.id},
        )

    def _map_tool_to_action(self, tool_name: str) -> ApprovalAction:
        """映射工具名到审批动作类型

        当前仅列出高风险沙箱工具子集。其余工具的处理策略：
        - 内置只读工具（read_file, ls, present_files, view_image, write_todos,
          ask_clarification）默认不要求审批，返回默认 AGENT_CONFIG_CHANGE 并被
          ApprovalRule.action_type 不匹配过滤掉
        - MCP 工具按 `mcp:{server}:{tool}` 前缀规则映射（如 `mcp:db:query` → DATA_EXPORT）
        - Community 工具按工具名前缀（tavily_*/jina_*/firecrawl_*/image_search_*）
          统一映射到 DATA_EXPORT，因这类工具通常会把外部网络内容引入沙箱
        - `task`（subagent 委派）默认不要求审批；子 Agent 自身执行时由同一
          GuardrailMiddleware 重新评估每个底层工具调用
        """
        mapping = {
            # 沙箱写入类
            "bash": ApprovalAction.SANDBOX_COMMAND,
            "write_file": ApprovalAction.SANDBOX_COMMAND,
            "str_replace": ApprovalAction.SANDBOX_COMMAND,
        }
        if tool_name in mapping:
            return mapping[tool_name]
        # Community / 外网拉取类
        if tool_name.startswith(("tavily_", "jina_", "firecrawl_", "image_search_")):
            return ApprovalAction.DATA_EXPORT
        # 默认：被 ApprovalRule.action_type 过滤掉，等同不要求审批
        return ApprovalAction.AGENT_CONFIG_CHANGE
```

**配置集成**：

```yaml
guardrails:
  enabled: true
  provider:
    use: "deerflow.enterprise.approval.guardrail_provider:CompositeGuardrailProvider"
    providers:
      - use: "deerflow.guardrails.allowlist:AllowlistProvider"
        # ... allowlist 配置
      - use: "deerflow.enterprise.approval.guardrail_provider:ApprovalGuardrailProvider"
```

**组合策略决定**：现有 `GuardrailsConfig` 只支持单 `provider`。审批 provider 不取代 AllowlistProvider，而是与之**串联**：先做 allowlist 黑白名单粗筛，通过后再判断是否需要审批。因此本设计**默认提供** `CompositeGuardrailProvider`：

**YAML → kwargs 映射约定**：现有 `GuardrailsConfig.provider` schema 中，`use` 字段决定 provider 类，其余字段全部作为 `kwargs` 透传给 `__init__`。因此上面 YAML 中 `provider.providers` 列表会以 `providers=[...]` 形式传入 `CompositeGuardrailProvider.__init__`。子项的 `use` 是 Composite 内部的二级字段，**不会**与外层 `provider.use` 冲突——外层 `use` 由 `GuardrailsConfig` 的反射加载消费，到达 `__init__` 时已被剥离。

```python
# deerflow/enterprise/approval/guardrail_provider.py

class CompositeGuardrailProvider:
    """串联多个 GuardrailProvider，按序评估，任一拒绝即拒绝（短路）"""

    name: str = "composite"

    def __init__(self, providers: list[dict], **kwargs):
        # providers 来自 yaml 配置，子项形如 {"use": "...", "<其他字段>": ...}
        # 逐个 resolve_class 实例化时，把 "use" 取出做类查找，剩余字段作为 kwargs 传入
        from deerflow.reflection import resolve_class
        from deerflow.guardrails.provider import GuardrailProvider
        self.providers = [
            resolve_class(p["use"], GuardrailProvider)(**{k: v for k, v in p.items() if k != "use"})
            for p in providers
        ]

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        for provider in self.providers:
            decision = provider.evaluate(request)
            if not decision.allow:
                return decision
        return GuardrailDecision(allow=True)

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        for provider in self.providers:
            decision = await provider.aevaluate(request)
            if not decision.allow:
                return decision
        return GuardrailDecision(allow=True)
```

仅使用审批 provider（不需要组合）时，直接 `provider.use` 指向 `ApprovalGuardrailProvider` 即可，无需配置 `providers` 列表。

> **现有 `GuardrailsConfig` 适配**：现有 `GuardrailsConfig.provider` 已经支持任意 `use` + `**kwargs` 透传给 provider 构造函数。`CompositeGuardrailProvider` 通过 `providers: list[dict]` 接收子 provider 列表，这是 `kwargs` 中的一个普通字段，**不需要修改 `GuardrailsConfig` schema**。yaml 中 `providers` 子节点会原样传入 `__init__(**kwargs)`，与现有 `AllowlistProvider(allow_list=[...])` 的传参方式一致。

### 6.8 审批流程

```
用户操作 → GuardrailMiddleware → ApprovalGuardrailProvider.aevaluate()
  ├── 不需要审批 → GuardrailDecision(allow=True) → 正常执行
  └── 需要审批 → 创建审批工单
              → Checkpoint 保存 AgentState 快照
              → 通知审批人（Web UI + 飞书卡片 + 企微消息）
              → GuardrailDecision(allow=False, reason="approval.required")
              → Agent 收到 ToolMessage(status="error")，显示审批等待消息
              → 审批人在 Web UI / 飞书 / 企微 操作
              ├── 批准 → 审批状态更新为 approved
              │        → Checkpoint.restore() 恢复 AgentState
              │        → RunManager 恢复 thread 执行（携带 _approval_id）
              │        → ApprovalGuardrailProvider 检测到 _approval_id → 放行
              │        → 审计日志记录
              ├── 拒绝 → 审批状态更新为 rejected + rejection_reason
              │        → 前端提示拒绝原因
              │        → 发起人可选择修订后重新提交（修订闭环）
              │        → 审计日志记录
              └── 超时 → ApprovalTimeoutChecker 自动标记 EXPIRED
                       → 通知发起人审批已过期
```

**关键设计**：

1. **Checkpoint 断点恢复**（对齐 13-human-in-the-loop.md）：审批点保存完整 AgentState 快照，审批通过后从 Checkpoint 恢复执行，而非依赖前端轮询+重发。这比前端重发更可靠——不丢失对话上下文，不依赖客户端在线。

2. **修订闭环**：拒绝后发起人可修订操作重新提交，新工单的 `revision_of` 指向原工单，形成审计链。

3. **多级审批**：`ApprovalRule.min_approvals > 1` 时，需要多个审批人批准。`Approval.approver_ids` 列出所有可审批人，`approved_by` 记录实际批准人。多级审批通过 `approval_decisions` 关联表跟踪每个审批人的决定。

4. **超时自动过期**：`ApprovalTimeoutChecker` 定期扫描，将超过 `deadline` 的 PENDING 工单标记为 EXPIRED 并通知发起人。

5. **飞书交互卡片**：审批人可直接在飞书卡片中点击「批准/拒绝」按钮，回调到审批 API，无需打开 Web UI。

## 7. OIDC 单点登录

### 7.1 配置模型

```python
# deerflow/enterprise/auth/oidc_config.py

class OIDCRoleMapping(BaseModel):
    claim_field: str = "groups"
    mappings: dict[str, Role] = {}
    default_role: Role = Role.MEMBER

class OIDCConfig(BaseModel):
    enabled: bool = False
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    scopes: list[str] = ["openid", "profile", "email", "groups"]
    redirect_uri: str = ""
    role_mapping: OIDCRoleMapping | None = None
    auto_provision: bool = True
```

### 7.2 OIDC Provider（app 层实现）

**关键约束**：`AuthProvider` ABC 定义在 `app.gateway.auth.providers`，属于 app 层。
harness 层 (`deerflow.*`) 不能导入 app 层（CI `test_harness_boundary.py` 强制执行）。
因此 OIDC 的核心逻辑放在 harness 层（`deerflow/enterprise/auth/`，含 `oidc_client.py`、`oidc_config.py`、`role_mapper.py`，见 §3.1 包结构树），但 Provider 适配器必须放在 app 层（`app/enterprise/oidc_auth_adapter.py`）。两层职责：

- **Harness 层 (`deerflow/enterprise/auth/`)**：纯 OIDC 协议实现——Discovery、code exchange、ID Token 验证、JWKS 拉取、claim → Role 映射。不依赖 `AuthProvider` ABC。
- **App 层 (`app/enterprise/oidc_auth_adapter.py`)**：`OIDCAuthProvider(AuthProvider)` 适配器，把上面的 harness 逻辑桥接到现有 auth 体系。

```python
# deerflow/enterprise/auth/oidc_client.py

class OIDCClient:
    """OIDC 协议客户端 — 纯 harness 层，不依赖 AuthProvider"""

    def __init__(self, config: OIDCConfig):
        self.config = config
        self._discovery_meta: dict | None = None

    async def get_authorization_url(self, state: str, nonce: str, redirect_uri: str) -> str:
        """构建 IdP 授权 URL（state 防 CSRF，nonce 防 ID Token replay — 见 §7.6）"""
        meta = await self._discover()
        params = {
            "client_id": self.config.client_id,
            "response_type": "code",
            "scope": " ".join(self.config.scopes),
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce,
        }
        return f"{meta['authorization_endpoint']}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> dict:
        """authorization_code → access_token + id_token"""
        meta = await self._discover()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                meta["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def verify_id_token(self, id_token: str, expected_nonce: str | None = None) -> dict:
        """验证 ID Token：JWKS 签名 + issuer + audience + exp + nonce，返回 claims。
        expected_nonce 必须由 callback 从 session/cookie 取出后传入；不匹配则抛出。"""
        ...

    async def _discover(self) -> dict:
        """通过 Discovery Document 获取 IdP 元数据（带缓存）"""
        if self._discovery_meta is None:
            url = f"{self.config.issuer.rstrip('/')}/.well-known/openid-configuration"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url)
                resp.raise_for_status()
                self._discovery_meta = resp.json()
        return self._discovery_meta
```

```python
# app/enterprise/oidc_auth_adapter.py

# 复用现状（无需新增改动）：
# - User 模型已具备 `oauth_provider: str | None` 和 `oauth_id: str | None` 字段
#   （见 backend/app/gateway/auth/models.py:27-28）
# - UserRepository ABC 已具备 `get_user_by_email(email)` 与 `get_user_by_oauth(provider, oauth_id)`
#   （见 backend/app/gateway/auth/repositories/base.py:53, 92；SQLite 实现：repositories/sqlite.py:84, 122）
# 因此 §11.2 改动清单**无需**再追加 oauth 字段或 oauth 查找方法

class OIDCAuthProvider(AuthProvider):
    """OIDC AuthProvider 适配器 — app 层，桥接 OIDCClient 到 AuthProvider ABC"""

    def __init__(self, config: OIDCConfig, user_repo: UserRepository):
        self.client = OIDCClient(config)
        self.role_mapper = OIDCRoleMapper(config.role_mapping)
        self.user_repo = user_repo

    async def authenticate(self, credentials: dict) -> User | None:
        code = credentials.get("code")
        if not code:
            return None

        redirect_uri = credentials.get("redirect_uri", self.client.config.redirect_uri)
        # nonce 由 /callback 路由从 session/cookie 取出并写入 credentials，必传
        expected_nonce = credentials.get("nonce")
        tokens = await self.client.exchange_code(code, redirect_uri)
        claims = await self.client.verify_id_token(tokens["id_token"], expected_nonce=expected_nonce)
        user = await self._find_or_create_user(claims)
        return user

    async def get_user(self, user_id: str) -> User | None:
        return await self.user_repo.get_user_by_id(user_id)

    async def _find_or_create_user(self, claims: dict) -> User:
        """JIT provisioning：首次登录自动创建/更新用户

        三条查找路径，按顺序：
        1. 已有 oauth_id 绑定 → 直接更新角色
        2. email 已注册（如已通过密码登录创建过）→ 绑定 oauth_id 到现有账号，更新角色
        3. 全新用户且 auto_provision=true → 创建新账号

        路径 2 避免了 create_user 因 email 唯一约束（UserRepository.create_user
        raises ValueError，见 base.py:37）而失败的场景。
        """
        email = claims.get("email")
        sub = claims.get("sub")
        role = self.role_mapper.map(claims)
        system_role = "admin" if role == Role.ADMIN else "user"

        # 路径 1：oauth_id 已绑定
        user = await self.user_repo.get_user_by_oauth("oidc", sub)
        if user is not None:
            user.system_role = system_role
            user.roles = [role.value]
            return await self.user_repo.update_user(user)

        # 路径 2：email 已注册但未绑定 oauth_id
        if email:
            user = await self.user_repo.get_user_by_email(email)
            if user is not None:
                user.oauth_provider = "oidc"
                user.oauth_id = sub
                user.system_role = system_role
                user.roles = [role.value]
                return await self.user_repo.update_user(user)

        # 路径 3：全新用户
        if not self.client.config.auto_provision:
            return None  # 由调用方处理为 401
        return await self.user_repo.create_user(User(
            email=email,
            oauth_provider="oidc",
            oauth_id=sub,
            system_role=system_role,
            roles=[role.value],
        ))
```

### 7.3 RoleMapper

```python
# deerflow/enterprise/auth/role_mapper.py

class OIDCRoleMapper:
    def __init__(self, mapping: OIDCRoleMapping):
        self.mapping = mapping

    def map(self, claims: dict) -> Role:
        claim_values = claims.get(self.mapping.claim_field, [])
        if isinstance(claim_values, str):
            claim_values = [claim_values]
        for value in claim_values:
            if value in self.mapping.mappings:
                return self.mapping.mappings[value]
        return self.mapping.default_role
```

### 7.4 与现有 Auth 共存

| 场景 | 行为 |
|------|------|
| `enterprise.auth.oidc.enabled = false` | 完全走现有本地登录，无变化 |
| `enterprise.auth.oidc.enabled = true` | 登录页同时展示「密码登录」和「SSO 登录」 |
| OIDC 登录 | 走 OIDC 流程，创建/更新本地 User 记录，签发相同格式 JWT |
| 本地登录 | 现有流程不变 |
| JWT 验证 | 统一走现有 `decode_token()`，不区分来源 |

### 7.5 与 RBAC 的集成

`User` 模型已扩展 `roles: list[str]` 字段（见 11.5 节），OIDC 登录时直接写入 `user.roles`：
- 一条路径，不需要双表同步
- `RbacPermissionProvider` 从 `User.roles` 读取角色，自动解析权限
- 每次登录时 IdP 角色变更自动同步到 `User.roles`

### 7.6 安全设计

- `state` 参数防 CSRF：登录时生成、callback 验证，与现有 CSRF double-submit 一致
- `nonce` 参数防 replay：登录时随机生成并写入 session/cookie，IdP 必须把它原样回写到 ID Token 的 `nonce` claim；callback 解码 ID Token 后核对，不匹配则拒登（OIDC Core 1.0 §3.1.2.1 要求）
- ID Token 验证：issuer 匹配、audience 匹配（必须含 `client_id`）、`exp` 未过期、`nonce` 匹配、签名验证（通过 JWKS 拉取 IdP 公钥并缓存）
- 不暴露 OIDC client_secret 到前端
- JWT cookie 设置与现有一致：HttpOnly、Secure（HTTPS 时）、SameSite
- `token_version` 机制不变，OIDC 登录后同样受密码重置失效约束

## 8. 持久化层

### 8.1 数据库管理

> **迁移体系对齐**：项目已经在 `backend/packages/harness/deerflow/persistence/migrations/` 下使用 **Alembic**（见 `env.py`、`alembic.ini`），管理 DeerFlow 应用表（runs、threads_meta、cron_jobs、users）。企业版表共用同一个 Alembic 环境与 `Base.metadata`：在 `deerflow.enterprise.persistence` 下定义企业表的 ORM 模型，让 `env.py` 中的 `target_metadata = Base.metadata` 自动覆盖，新增的修订脚本放在 `migrations/versions/` 即可被检测。
>
> 不引入第二套迁移机制，也不在运行时调用 `Base.metadata.create_all`。

```python
# deerflow/enterprise/persistence/database.py

class EnterpriseDatabase:
    def __init__(self, config: EnterpriseDatabaseConfig):
        self.engine = create_async_engine(config.url, echo=config.echo)
        self.session_factory = async_sessionmaker(self.engine)

    async def init(self) -> None:
        """初始化连接池。建表交给 Alembic（启动前/部署时执行 `alembic upgrade head`）。
        如希望应用启动时自动 upgrade，可在此调用 `command.upgrade(alembic_cfg, "head")`，
        但默认建议保持显式迁移以便审计。"""
        # 仅做连接探测；不再调用 Base.metadata.create_all
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self.engine.dispose()
```

### 8.2 表结构

| 表 | 主键 | 关键列 |
|----|------|--------|
| `roles` | id (TEXT) | name (UNIQUE), description, is_default |
| `role_permissions` | role_id + permission (复合) | granted_by |
| `audit_events` | id (INTEGER AUTO) | event_type, user_id, timestamp, signature, ...全部 AuditEvent 字段 |
| `approvals` | id (TEXT) | title, action_type, requester_id, status, urgency, deadline, **action_detail (TEXT, JSON)**, **checkpoint (TEXT, JSON)**, revision_of, ...全部 Approval 字段 |
| `approval_decisions` | id (INTEGER AUTO) | approval_id, approver_id, decision (approved/rejected), comment, decided_at |
| `oidc_links` | user_id + provider (复合) | oidc_subject, updated_at |

**JSON 列约定**：`approvals.action_detail` 和 `approvals.checkpoint` 都以 TEXT 列存储 JSON 字符串。Repository 实现负责 `json.dumps()` / `json.loads()` 转换——Pydantic `Approval` 模型层暴露的是 `dict[str, Any]` / `str`，Repository 在 `create()` / `update_checkpoint()` 等写路径序列化，在 `get()` / `list_*()` 读路径反序列化。PostgreSQL 实现可选择改用原生 `JSONB` 列（建议生产环境用），SQLite 始终为 TEXT。

角色直接存在 `User.roles` 字段上（User 模型扩展见 11.5 节），不需要独立的用户-角色关联表。

### 8.3 Repository 抽象

```python
# deerflow/enterprise/rbac/repository.py
class RbacRepository(ABC):
    """角色权限 CRUD — 操作 roles 和 role_permissions 表

    约定：`roles.id` 列直接存 `Role` 枚举值字符串（`"admin"`、`"member"` 等）。
    `roles.name` 是面向人类的显示名，可与 id 不同；id 才是外键和查询主键。
    """
    async def get_role_permissions(self, role: Role) -> set[Permission]: ...
    async def set_custom_permission(self, role: Role, permission: Permission, granted_by: str) -> None: ...
    async def remove_custom_permission(self, role: Role, permission: Permission) -> None: ...
    async def list_roles(self) -> list[Role]: ...

# 用户角色操作直接通过 UserRepository.update_user() 修改 User.roles 字段，
# 不需要单独的 RbacRepository 方法

# deerflow/enterprise/audit/storage.py  (与 5.2 节统一，名 AuditStorage)
class AuditStorage(ABC):
    async def append(self, event: AuditEvent) -> None: ...
    async def append_batch(self, events: list[AuditEvent]) -> None: ...
    async def query(self, filters: AuditQuery, page: int, page_size: int) -> list[AuditEvent]: ...
    async def count(self, filters: AuditQuery) -> int: ...
    async def verify_integrity(self, user_id: str | None = None) -> bool: ...

# deerflow/enterprise/approval/repository.py
class ApprovalRepository(ABC):
    async def create(self, approval: Approval) -> None: ...
    async def get(self, approval_id: str) -> Approval | None: ...
    async def update_status(self, approval_id: str, status: ApprovalStatus, resolved_by: str, reason: str | None = None) -> None: ...
    async def update_checkpoint(self, approval_id: str, checkpoint: str) -> None: ...
    async def list_pending(self, approver_id: str) -> list[Approval]: ...
    async def list_by_requester(self, requester_id: str) -> list[Approval]: ...
    async def mark_expired(self) -> list[Approval]: ...
    # 多级审批：记录每个审批人的决定
    async def record_approval_decision(self, approval_id: str, approver_id: str, decision: str, comment: str | None = None) -> None: ...
    async def count_approvals(self, approval_id: str) -> int: ...
```

每个 Repository 提供 SQLite 和 PostgreSQL 两种实现，通过配置切换。

### 8.4 迁移策略

- **Schema 迁移**：复用项目现有 Alembic 环境。新增企业表通过 `alembic revision --autogenerate` 生成修订脚本，放入 `backend/packages/harness/deerflow/persistence/migrations/versions/`。部署时执行 `alembic upgrade head` 完成升级
- **扩展 `users` 表**：新增 `roles TEXT` 列（存 JSON，默认 `"[]"`），同样通过 Alembic 修订脚本完成
- `system_role` 列无需改动（已是 `String(16)`，类型放宽在 Pydantic 层完成）
- **数据迁移**：遍历现有 `users` 表，`system_role="admin"` → `roles='["admin"]'`，`system_role="user"` → `roles='["member"]'`。这部分作为 Alembic 修订脚本的 `op.execute(...)` 内联完成（或独立的 `scripts/migrate_enterprise.py`，支持 `--dry-run`，与现有 `scripts/migrate_user_isolation.py` 风格一致）
- **运行时 `init()`**：不建表，仅探活；schema 状态以 `alembic upgrade head` 为准

## 9. Gateway API 路由

### 9.1 路由表

> 下表"所需权限"列使用的是 §4.1 定义的**企业 Permission** 字符串（如 `data:read`、`role:manage`）。这些字符串只在 `enterprise.rbac.enabled=true` 且 `RbacPermissionProvider` 已注册时才会出现在 `AuthContext.permissions` 中。未启用企业 RBAC 时，企业路由不会被挂载（`create_app()` 条件 include_router，见 §9.4），因此不存在"启用前路由全开放"的问题。

**RBAC** (`/api/enterprise/rbac/`):

| Method | Path | 说明 | 所需权限 |
|--------|------|------|----------|
| GET | `/roles` | 列出所有角色 | role:manage |
| GET | `/roles/{id}` | 角色详情+权限 | role:manage |
| PUT | `/roles/{id}/permissions` | 设置角色权限 | role:manage |
| GET | `/users/{id}/role` | 获取用户角色 | user:manage |
| PUT | `/users/{id}/role` | 设置用户角色 | user:manage |
| GET | `/permissions` | 列出所有权限 | role:manage |
| GET | `/my-permissions` | 当前用户权限 | 任何认证用户 |

**审计** (`/api/enterprise/audit/`):

| Method | Path | 说明 | 所需权限 |
|--------|------|------|----------|
| GET | `/events` | 查询审计事件 | data:read |
| GET | `/events/{id}` | 单条事件详情 | data:read |
| GET | `/integrity` | 验证日志完整性 | system:settings |
| GET | `/stats` | 审计统计 | data:read |
| GET | `/export` | 导出审计日志 | data:export |

**审批** (`/api/enterprise/approval/`):

| Method | Path | 说明 | 所需权限 |
|--------|------|------|----------|
| GET | `/pending` | 我的待审批 | approval:view |
| GET | `/history` | 我发起的审批 | approval:view |
| GET | `/all` | 所有审批 | approval:view + admin |
| GET | `/{id}` | 审批详情 | approval:view |
| POST | `/{id}/approve` | 批准 | approval:grant |
| POST | `/{id}/reject` | 拒绝 | approval:reject |
| POST | `/{id}/cancel` | 取消 | approval:create（仅发起人） |
| POST | `/{id}/resubmit` | 修订后重新提交（修订闭环） | approval:create（仅发起人） |

**OIDC Auth** (`/api/enterprise/auth/oidc/`):

| Method | Path | 说明 | 所需权限 |
|--------|------|------|----------|
| GET | `/login` | 重定向到 IdP | 公开 |
| GET | `/callback` | IdP 回调处理 | 公开 |
| GET | `/discovery` | OIDC 配置信息 | 公开 |

**Dashboard** (`/api/enterprise/dashboard/`):

| Method | Path | 说明 | 所需权限 |
|--------|------|------|----------|
| GET | `/stats` | 汇总统计 | system:settings |
| GET | `/recent-activity` | 近期活动 | data:read |

### 9.2 请求/响应模型

```python
# app/enterprise/models.py

class AuditQueryRequest(BaseModel):
    event_types: list[AuditEventType] | None = None
    user_id: str | None = None
    resource_type: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    page: int = 1
    page_size: int = 50

class AuditEventsResponse(BaseModel):
    events: list[AuditEvent]
    total: int
    page: int
    page_size: int

class ApprovalListResponse(BaseModel):
    approvals: list[Approval]
    total: int

class ApprovalActionRequest(BaseModel):
    reason: str | None = None

class ApprovalResubmitRequest(BaseModel):
    """修订后重新提交"""
    action_detail: dict[str, Any]       # 修订后的操作详情（结构化）
    description: str | None = None      # 修订说明

class RolePermissionsUpdate(BaseModel):
    permissions: list[Permission]

class UserRoleUpdate(BaseModel):
    role_id: str
```

### 9.3 依赖注入

```python
# app/enterprise/deps.py

_enterprise_db: EnterpriseDatabase | None = None

async def get_enterprise_db() -> EnterpriseDatabase:
    global _enterprise_db
    if _enterprise_db is None:
        config = get_enterprise_config()
        _enterprise_db = EnterpriseDatabase(config.database)
        await _enterprise_db.init()
    return _enterprise_db

async def get_rbac_checker() -> RbacPermissionProvider: ...
async def get_audit_storage() -> AuditStorage: ...
# get_audit_queue 仅在 v2 异步队列方案启用时需要（见 §5.5）
async def get_approval_engine() -> ApprovalRuleEngine: ...
async def get_timeout_checker() -> ApprovalTimeoutChecker: ...
```

### 9.4 Gateway 启动集成

现有 `create_app()` 无条件挂载所有路由。需要做两处最小改动：

1. **`create_app()` 中条件挂载企业路由**：当 `enterprise.enabled = true` 时 `include_router`
2. **`lifespan()` 中初始化企业数据库**：当 `enterprise.enabled = true` 时初始化和清理

```python
# create_app() 中新增（约 5 行）：
enterprise_config = get_enterprise_config()
if enterprise_config.enabled:
    from app.enterprise.routers import rbac, audit, approval, auth, dashboard
    app.include_router(rbac.router, prefix="/api/enterprise/rbac")
    app.include_router(audit.router, prefix="/api/enterprise/audit")
    app.include_router(approval.router, prefix="/api/enterprise/approval")
    app.include_router(auth.router, prefix="/api/enterprise/auth")
    app.include_router(dashboard.router, prefix="/api/enterprise/dashboard")

# lifespan() 中新增（约 14 行）：
if enterprise_config.enabled:
    from app.enterprise.deps import (
        get_enterprise_db, get_timeout_checker, get_rbac_checker,
    )
    # v2 启用 AuditQueue 时再补 `get_audit_queue` 的 import 和 await get_audit_queue().start()
    db = await get_enterprise_db()

    # 注册 PermissionProvider —— 必须在第一个请求到达前完成
    # 不注册时，_authenticate() 仍走 _ALL_PERMISSIONS 兼容路径（见 §11.3）
    if enterprise_config.rbac.enabled:
        from app.gateway.authz import set_permission_provider
        set_permission_provider(await get_rbac_checker())

    if enterprise_config.auth.oidc.enabled:
        from app.enterprise.oidc_auth_adapter import OIDCAuthProvider
        # 注册 OIDC provider 到现有 auth 体系

    if enterprise_config.approval.enabled:
        timeout_checker = await get_timeout_checker()
        await timeout_checker.start()

# lifespan 清理中新增（约 6 行）：
if enterprise_config.enabled:
    from app.enterprise.deps import get_enterprise_db, get_timeout_checker
    timeout_checker = await get_timeout_checker()
    await timeout_checker.close()
    # v1 同步审计写入，无需关闭队列；v2 启用 AuditQueue 时再加 await get_audit_queue().close()
    db = await get_enterprise_db()
    await db.close()
```

## 10. 前端集成

**不修改现有前端代码**。企业版前端作为独立页面/组件，通过条件渲染加载：

```
frontend/src/
├── app/                          # 现有页面（不动）
├── enterprise/                   # 新增企业版
│   ├── rbac/page.tsx              # 角色权限管理
│   ├── audit/page.tsx             # 审计日志
│   ├── approval/
│   │   ├── page.tsx              # 审批列表
│   │   └── [id]/page.tsx         # 审批详情
│   ├── dashboard/page.tsx        # 企业仪表盘
│   ├── layout.tsx                # 企业版布局（侧边栏导航）
│   ├── EnterpriseNav.tsx         # 导航组件
│   └── OIDCLoginButton.tsx       # SSO 登录按钮
```

**前端判断企业版是否启用**：调用 `GET /api/enterprise/dashboard/stats`，404 = 未启用，200 = 已启用。根据结果决定是否显示企业版导航入口。

**审批 Web UI 交互**：
- 用户发起操作 → 被拦截 → 页面显示「需要审批」提示（含审批工单 ID）
- 审批人在「待审批」列表看到工单 → 点击详情 → 批准/拒绝（可填写原因）
- 操作发起人收到审批结果通知（页面内通知）
- 拒绝后：发起人可点击「修订重提」，修改操作参数后重新提交（修订闭环）
- 超时后：发起人收到过期通知，可重新发起审批
- 多级审批：进度条显示审批进度（如 2/3 人已批准）

## 11. 对原有代码的改动

允许对现有代码做小量改动（共约 70~90 行，含权限解析、中间件透传、模型扩展、Repository 方法、生命周期挂载），换取架构大幅简化。下表中"文件"列以仓库根为基准。

### 11.1 必要改动

| # | 文件 | 改动内容 | 行数 | 影响 |
|---|------|----------|------|------|
| 1 | `backend/app/gateway/authz.py` | 新增 `PermissionProvider` Protocol + `set_permission_provider()` 注册函数；`_authenticate()` 中默认走 `_ALL_PERMISSIONS`（保持现状），有 provider 时委托 | ~20 | **核心**：让 RBAC 真正生效。改造点即 [authz.py:143](backend/app/gateway/authz.py#L143) 已留的"In future, permissions could be stored in user record"注释处 |
| 2 | `backend/app/gateway/auth_middleware.py` | `dispatch()` 中同样调用 `PermissionProvider`（实际权限解析逻辑集中在 `authz.py`，本文件只是复用） | ~5 | 与 #1 配合 |
| 3 | `backend/packages/harness/deerflow/agents/lead_agent/agent.py` | `_build_middlewares` 已接受 `custom_middlewares` 参数（agent.py:244）并已在链尾注入（agent.py:313-314）。仅需在 [agent.py:419](backend/packages/harness/deerflow/agents/lead_agent/agent.py#L419) 和 [agent.py:437](backend/packages/harness/deerflow/agents/lead_agent/agent.py#L437) 两处 `_build_middlewares(...)` 调用补 `custom_middlewares=` 参数 + `_make_lead_agent` 顶端读 1 行配置 | ~3 | 让企业中间件注入生效 |
| 4 | `backend/app/gateway/app.py` | `create_app()` 条件 include_router + `lifespan()` 初始化/清理 | ~25 | 企业路由和生命周期 |
| 5 | `backend/packages/harness/deerflow/config/app_config.py` | 新增 `enterprise: EnterpriseConfig = EnterpriseConfig()` 字段 | +1 | 配置集成 |

### 11.2 优化改动（推荐，简化设计）

| # | 文件 | 改动内容 | 行数 | 收益 |
|---|------|----------|------|------|
| 6 | `backend/app/gateway/auth/models.py` | `system_role` 类型从 `Literal["admin", "user"]` 改为 `str` | ~1 | 让角色可扩展，不再需要独立的 `enterprise_user_roles` 表 |
| 7 | `backend/app/gateway/auth/models.py` | `User` 新增 `roles: list[str]` 字段（默认空列表） | ~2 | 多角色支持，OIDC/JIT 直接写入 |
| 8 | `backend/app/gateway/auth/repositories/base.py` | `UserRepository` ABC 新增 `get_users_by_role(role)` 方法 | ~3 | 用于 §9.1 RBAC 路由 `GET /users/{id}/role` 反向查询「某角色下所有用户」、`ApprovalRuleEngine._resolve_approvers()` 按 `approver_roles` 找审批人 |

### 11.3 改动 #1-2 详情：PermissionProvider（最高优先级）

这是整个企业版最关键的改动。现有 `authz.py` 中所有认证用户都获得 `_ALL_PERMISSIONS`，`@require_permission` 装饰器形同虚设。

```python
# app/gateway/authz.py 新增

class PermissionProvider(Protocol):
    """权限解析协议 — 企业 RBAC 通过实现此协议接入"""
    async def resolve_permissions(self, user: "User") -> list[str]: ...

_permission_provider: PermissionProvider | None = None

def set_permission_provider(provider: PermissionProvider) -> None:
    """注册企业权限解析器。不注册时，行为与现有一致（所有用户全权限）。"""
    global _permission_provider
    _permission_provider = provider
```

```python
# _authenticate() 中修改（约 3 行）
if _permission_provider is not None:
    permissions = await _permission_provider.resolve_permissions(user)
else:
    permissions = _ALL_PERMISSIONS
return AuthContext(user=user, permissions=permissions)
```

```python
# auth_middleware.py dispatch() 中同样修改（约 3 行）
if _permission_provider is not None:
    permissions = await _permission_provider.resolve_permissions(user)
else:
    permissions = _ALL_PERMISSIONS
request.state.auth = AuthContext(user=user, permissions=permissions)
```

**不注册 provider 时行为完全不变**。企业版启动时注册 `RbacPermissionProvider`，RBAC 立即生效。

### 11.4 改动 #3 详情：中间件透传

`_build_middlewares` 的 `custom_middlewares` 参数已经存在并已在链尾接入（[agent.py:244](backend/packages/harness/deerflow/agents/lead_agent/agent.py#L244)、[agent.py:313-314](backend/packages/harness/deerflow/agents/lead_agent/agent.py#L313-L314)）。当前 `_make_lead_agent` 的两处调用（[agent.py:419](backend/packages/harness/deerflow/agents/lead_agent/agent.py#L419)、[agent.py:437](backend/packages/harness/deerflow/agents/lead_agent/agent.py#L437)）尚未传入企业中间件。只需补 3 行：

> **与 doc 13 §13.7.2 的差异**：doc 13 示例用 `MiddlewareChain.from_agent(agent).add_middleware(...)` 这个 API 在当前 DeerFlow 代码中不存在。本 RFC 改用 `_build_middlewares(custom_middlewares=...)` 参数透传，与现有 `_build_middlewares` 签名一致，是更贴近实际架构的做法。

```python
# _make_lead_agent 顶端（1 行）
from deerflow.enterprise.middlewares import get_enterprise_middlewares
custom_mws = get_enterprise_middlewares(resolved_app_config.enterprise)

# agent.py:419 bootstrap 分支调用（1 行修改）
middleware=_build_middlewares(config, model_name=model_name, app_config=resolved_app_config, custom_middlewares=custom_mws),

# agent.py:437 默认分支调用（1 行修改）
middleware=_build_middlewares(config, model_name=model_name, agent_name=agent_name, app_config=resolved_app_config, custom_middlewares=custom_mws),
```

### 11.5 改动 #6-7 详情：User 模型扩展

```python
# app/gateway/auth/models.py 修改
class User(BaseModel):
    # ...
    system_role: str = Field(default="user")  # 从 Literal["admin", "user"] 放宽为 str
    roles: list[str] = Field(default_factory=list, description="Additional roles for enterprise RBAC")
```

**收益**：
- 不再需要独立的 `enterprise_user_roles` 表——角色直接存 `User.roles`
- OIDC JIT provisioning 直接写入 `user.roles = ["admin"]`，无需额外表操作
- RBAC 查询：`user.roles` + `user.system_role` 联合解析
- 数据库层：`UserRow` 新增 `roles TEXT` 列（JSON 序列化），`system_role` 列已是 `String(16)`，无需改动
- 迁移：`system_role` 从 `Literal` 放宽为 `str` 对现有数据无影响

### 11.6 简化收益速览

§11.1-§11.5 列出的小量改动让以下原本设想的复杂设计被消除：

| 原设计 | 优化后 |
|--------|--------|
| 独立 `enterprise_user_roles` 表 | 用 `User.roles` 字段（§11.5） |
| OIDC 双路径同步 | `User.roles` 单写路径（§11.5） |
| 独立 `RbacChecker` | `PermissionProvider` 协议（§11.3） |
| Agent 层 RBAC 中间件 | HTTP 层 `PermissionProvider` 拦截 |
| 独立审批中间件 | `ApprovalGuardrailProvider`（§6.7） |

### 11.7 简化后的表结构

| 表 | 主键 | 关键列 |
|----|------|--------|
| `roles` | id (TEXT) | name (UNIQUE), description, is_default |
| `role_permissions` | role_id + permission (复合) | granted_by |
| `audit_events` | id (INTEGER AUTO) | event_type, user_id, timestamp, signature, ... |
| `approvals` | id (TEXT) | title, action_type, requester_id, status, urgency, deadline, **action_detail (TEXT, JSON)**, **checkpoint (TEXT, JSON)**, revision_of, ... |
| `approval_decisions` | id (INTEGER AUTO) | approval_id, approver_id, decision, comment, decided_at |
| `oidc_links` | user_id + provider (复合) | oidc_subject, updated_at |

~~`enterprise_user_roles` 表~~ → 不再需要，角色直接存在 `User.roles` 上。

### 11.8 简化后的中间件

| 中间件 | 原设计 | 优化后 |
|--------|--------|--------|
| RBAC | `RbacMiddleware` (Agent 层) | 删除。通过 `PermissionProvider` 在 HTTP 层生效 |
| 审计 | `AuditMiddleware` (Agent 层) | 保留，但简化为仅 Agent 层事件 |
| 审批 | `ApprovalMiddleware` (Agent 层) | 简化为 `GuardrailProvider` 实现，复用 `GuardrailMiddleware` |

最终企业版只需 **1 个 Agent 中间件**（AuditMiddleware），而非原来的 3 个。

## 12. 测试策略

遵循现有 TDD 要求：

- 每个模块必须配单元测试
- 测试放在 `backend/tests/` 下，命名 `test_enterprise_<module>.py`
- harness/app 边界测试：确保 `deerflow.enterprise.*` 不导入 `app.*`
- Repository 测试使用内存 SQLite
- 中间件测试参照现有 `tests/test_*_middleware.py` 模式
- OIDC 测试 mock JWKS 和 token endpoint
- 迁移脚本测试包含 `--dry-run` 覆盖