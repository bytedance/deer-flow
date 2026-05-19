# 权限架构修复设计方案

> **范围**：针对 [2026-05-19 权限架构诊断报告](#) 列出的 13 条问题（C1-C3 致命 / H1-H4 高危 / M1-M5 中危），给出 RBAC 落地、JWT 体系合并、租户隔离强化、`"default"` 语义拆分、ins-base 角色源迁移的端到端改造设计。**不重写**用户/租户/Agent/KB 的数据模型，只在权限决策层、装饰器层、仓库过滤层做收口。
>
> **目标读者（Audience）**：
> - **主**：DeerFlow backend 开发（实现 / Code Review）
> - **辅**：SRE（灰度操作 / 监控）、安全 Reviewer（C1-C3 闭环验证）、EM（Sprint 排期 / 资源分配）、ins-base 团队（§4.2 字段对齐）
>
> **关联文档**：
> - 多级知识库设计：[2026-05-10-multi-level-knowledge-base-design.md](./2026-05-10-multi-level-knowledge-base-design.md)
> - 多级 Agent Sprint：[2026-05-11-multi-level-agents-sprint-plan.md](./2026-05-11-multi-level-agents-sprint-plan.md)
> - 租户自动检测：[2026-05-12-tenant-auto-detection-design.md](./2026-05-12-tenant-auto-detection-design.md)
> - PostgreSQL 存储迁移：[2026-05-08-postgresql-storage-migration-design.md](./2026-05-08-postgresql-storage-migration-design.md)
> - 后端架构指南：[backend/CLAUDE.md](../../backend/CLAUDE.md)
> - 执行计划：[2026-05-19-permission-architecture-fix-sprint-plan.md](./2026-05-19-permission-architecture-fix-sprint-plan.md)（**SoT for Story 拆分与排期**；本设计文档中 §7 Sprint 摘要仅作概览，与 Sprint plan 不一致时以 Sprint plan 为准）
>
> **创建日期**：2026-05-19
>
> **最后修订**：2026-05-19（Review v2 — 加 §4.1.1 KB 集成边界、§4.2 ins-base 契约假设、§4.4 token_version 单一信号、§4.3 internal token 必带 tenant_id、§6.4 与 PG 迁移协调）
>
> **作者**：诊断责任人 → Claude

---

## 1. 背景

DeerFlow 当前的多用户 / 多租户 / 超级管理员权限体系是在多次迭代中累积形成的：

- **角色模型**：在 `User.system_role` 中声明了 `superadmin / tenant_admin / user` 三档；
- **权限装饰器**：[backend/app/gateway/authz.py](../../backend/app/gateway/authz.py) 提供 `@require_auth` + `@require_permission(resource, action, owner_check)`；
- **租户上下文**：通过 ContextVar `set_current_tenant_id` 在请求 / 后台任务中传递；
- **用户隔离**：通过 `get_effective_user_id()` 与 `resolve_user_id(AUTO)` 的 sentinel 模式由仓库层强制注入；
- **多 provider**：本地 SQLite + ins-base RPC（Java 后端）双 provider 并存；
- **双 JWT 路径**：cookie 模式 (pyjwt) 与 Bearer 模式 (python-jose) 并行。

诊断结论按优先级汇总（详见诊断报告）：

| ID | 严重度 | 主题 | 根因 |
|----|--------|------|------|
| C1 | Critical | `_ALL_PERMISSIONS` 对所有已认证用户全开 | 装饰器 + 中间件 |
| C2 | Critical | ins-base 角色基于用户名字符串匹配 | provider 实现 |
| C3 | Critical | `user_id="default"` 行被任意已认证用户读写 | `check_access` + sentinel 重载 |
| H1 | High | 两套 JWT 体系并存，role claim 不一致 | jwt.py vs jwt_handler.py |
| H2 | High | RunRow 无 tenant_id；token 聚合接口无过滤 | 仓库层 schema + 查询 |
| H3 | High | tenant_admin 可改自己租户额度 | `update_tenant` 守卫错配 |
| H4 | High | `/api/runs/stream` `/api/runs/wait` 缺装饰器 | 路由 |
| M1 | Medium | 租户作用域 LIST 仅允许 tenant_admin | 路由 |
| M2 | Medium | `_resolve_tenant_id` 在 repo=None 时返回未持久化 orgId | provider |
| M3 | Medium | 默认回退角色 `"member"` 与 Literal 不一致 | 类型 |
| M4 | Medium | `auth.enabled=False` 硬编码 superadmin | dependencies |
| M5 | Medium | ins-base authenticate / get_user 返回 user.id 不同 | provider |

> **指导原则**：
> 1. **DB schema 改动只做加法**（加列、加索引）。不删字段、不改字段语义、不动既有外键。
> 2. **路由契约保持不变**。返回的 4xx 错误 code 可以增多，但已存在的 200 响应不允许"突然变 403"——通过 feature flag `auth.strict_rbac` 灰度。
> 3. **沿用现有装饰器形态**。不引入新框架（OPA / Casbin），所有规则用 Python 装饰器 + dataclass 表达。
> 4. **default 字面量不再做"行无主"语义**。它只代表"未鉴权的占位身份"。"行无主"由 `user_id IS NULL` 表达。

---

## 2. 设计目标

### 2.1 必须满足

1. **C1 闭环**：`@require_permission(r, a)` 真正按 `system_role → 权限位 → resource:action` 三段决策；非授权调用返回 403。
2. **C2 闭环**：ins-base provider 不再基于用户名字符串匹配角色；改为读取 ins-base 返回的 `permissions[]` 或显式角色字段，并在 DeerFlow 侧做映射。
3. **C3 闭环**：`check_access` 不再因 `user_id="default"` 直通；`internal_user.id` 改为独立 sentinel `__internal__`，`DEFAULT_USER_ID` 仅在 `auth.enabled=False` 路径出现。历史数据通过一次性迁移脚本归属化。
4. **H1 闭环**：保留 cookie + pyjwt 一条 JWT 主链；废弃 jwt_handler.py 并把仍在用的 Bearer 路径迁移到主链；token 内显式带 `system_role` claim 并参与签名校验。
5. **H2 闭环**：`runs` 表加 `tenant_id NOT NULL` 列 + 复合索引；`aggregate_tokens_by_thread` 必须接受 `(thread_id, user_id)` 双键。
6. **H3/H4 闭环**：`update_tenant` 的 quota 字段需 superadmin；`runs.py` 入口补 `@require_permission`。
7. **租户隔离强约束**：所有租户作用域表（runs / agents / kb / mcp / connectors）加 `tenant_id`，`SELECT` 默认带 `tenant_id` 过滤；DB 层加复合索引 + 触发器或 CHECK 约束保证不可绕过。
8. **可灰度 / 可回滚**：所有改动通过 `auth.strict_rbac=true|false` 控制；缺省 `false`（沿用旧行为），上线两周后切 `true`。

### 2.2 非目标

1. **不**引入 ABAC / 策略外置（OPA / Casbin）。所有规则用 Python 数据结构表达。
2. **不**把租户/角色模型外迁到 ins-base。DeerFlow 侧仍维护 `system_role` 真相源。
3. **不**重写 LangGraph Server 内 [langgraph_auth.py](../../backend/app/gateway/langgraph_auth.py) 的契约（`add_owner_filter`），只补它对应的 user_id 注入。
4. **不**改前端 token 存储形态。前端依旧用 HttpOnly cookie。
5. **不**重做知识库的 visibility 模型——它已经是范式实现，留作其它模块的对照样例。新 `RoleRegistry` 仅做"路由级粗粒度门"，KB 既有 `KbPermissionRow` 继续做"资源级细粒度门"，两层串行评估，详见 §4.1.1。
6. **不**重写 LangGraph thread checkpointer / Postgres saver。
7. **不**修改既有 OpenAPI 响应 schema：4xx code 可以增多（新加 403 / 422 路径），但 200 response body 不允许变更。前端契约（`AuthMeResponse` / `TenantResponse` / `RunResponse`）不破坏。
8. **不**与并行进行的 [PostgreSQL 存储迁移](./2026-05-08-postgresql-storage-migration-design.md)耦合。两条工作流通过共享 Alembic 链协作（详见 §6.4），但本设计可以独立合入并回滚。

---

## 3. 总体架构变更

```
                              ┌──────────────────────────────────────────────┐
                              │  Gateway Routers (FastAPI)                   │
                              └────────────────────────┬─────────────────────┘
                                                       │
                  ┌────────────────────────────────────┼────────────────────────────────┐
                  │                                    │                                │
              auth.enabled=False              auth.enabled=True                  internal token
                  │                                    │                                │
                  ▼                                    ▼                                ▼
         ★ AnonymousIdentity              ★ AuthenticatedIdentity              ★ InternalIdentity
           (id=DEFAULT_USER_ID)              (id=user.id, role=...)              (id=__internal__)
                  │                                    │                                │
                  └────────────────────┬───────────────┴────────────────────────────────┘
                                       │
                                       ▼
                          ★ AuthMiddleware (refactored)
                            ├── 校验 cookie / Bearer / internal token
                            ├── 解出 Identity（含真实 system_role）
                            ├── 注入 ContextVar:
                            │     - current_user
                            │     - current_tenant_id
                            │     - current_identity_kind (anonymous/auth/internal)
                            └── stamps request.state.auth = AuthContext
                                       │
                                       ▼
                          ★ AuthContext (refactored)
                            ├── identity: Identity
                            ├── permissions: 由 RoleRegistry.permissions_for(role) 计算
                            └── has_permission(resource, action) 严格匹配
                                       │
                                       ▼
                          ★ require_permission decorator
                            ├── 按 (role, resource, action) 查表
                            ├── owner_check=True → ThreadStore.check_access (修复后)
                            └── 拒绝时 403 + 结构化 reason
                                       │
                                       ▼
                          ★ Repository layer
                            ├── 所有租户作用域查询自动注入 tenant_id 过滤
                            ├── 所有用户作用域查询自动注入 user_id 过滤
                            └── ★ check_access(thread_id, user_id, tenant_id, require_existing)
                                  - "default" 不再 short-circuit
                                  - "__internal__" 仅在显式声明时通过

(★ = 改动)
```

---

## 4. 详细设计

> 每条诊断结论一节，结构：**现状 → 目标 → 设计 → 影响面 → 测试**。

### 4.1 C1 — RBAC 真正落地

**现状**

[authz.py:152](../../backend/app/gateway/authz.py#L152) `_authenticate()` 对任何已登录用户都赋予 `_ALL_PERMISSIONS`：

```python
return AuthContext(user=user, permissions=_ALL_PERMISSIONS)
```

[auth_middleware.py:177](../../backend/app/gateway/auth_middleware.py#L177) 同样行为。`@require_permission` 表面上是 RBAC，实际等价于 `@require_auth`。

**目标**

- `system_role` → `permissions[]` 的映射唯一，可单测、可灰度。
- 现有所有 `@require_permission(...)` 路由不动；通过 `auth.strict_rbac` 开关切换"放行 vs 严格匹配"。

**设计**

新增 [backend/app/gateway/auth/roles.py](../../backend/app/gateway/auth/roles.py)：

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class RoleDefinition:
    name: str
    permissions: frozenset[str]
    description: str = ""

# 所有权限位（含 closure 等扩展）
_R = "threads"; _W = "runs"; _C = "closure"
_K = "knowledge_bases"; _A = "agents"; _T = "tenants"; _M = "mcp"

ALL_PERMISSIONS: frozenset[str] = frozenset({
    f"{_R}:read", f"{_R}:write", f"{_R}:delete",
    f"{_W}:create", f"{_W}:read", f"{_W}:cancel",
    f"{_C}:read", f"{_C}:write", f"{_C}:verify",
    f"{_K}:read", f"{_K}:write", f"{_K}:admin",
    f"{_A}:read", f"{_A}:write", f"{_A}:admin",
    f"{_T}:read", f"{_T}:write", f"{_T}:admin",
    f"{_M}:read", f"{_M}:write",
})

USER_PERMISSIONS = frozenset({
    f"{_R}:read", f"{_R}:write", f"{_R}:delete",
    f"{_W}:create", f"{_W}:read", f"{_W}:cancel",
    f"{_C}:read", f"{_C}:write",          # ← 普通用户不能 verify
    f"{_K}:read",                           # ← 普通用户只读 KB（粗粒度门）
    f"{_A}:read",
    f"{_M}:read",
})

TENANT_ADMIN_PERMISSIONS = USER_PERMISSIONS | frozenset({
    f"{_C}:verify",
    f"{_K}:write", f"{_K}:admin",
    f"{_A}:write", f"{_A}:admin",
    f"{_T}:read",                           # 仅自己 tenant
    f"{_M}:write",
})

SUPERADMIN_PERMISSIONS = ALL_PERMISSIONS

ROLE_REGISTRY: dict[str, RoleDefinition] = {
    "user":         RoleDefinition("user",         USER_PERMISSIONS),
    "tenant_admin": RoleDefinition("tenant_admin", TENANT_ADMIN_PERMISSIONS),
    "superadmin":   RoleDefinition("superadmin",   SUPERADMIN_PERMISSIONS),
}

def permissions_for(role: str | None) -> frozenset[str]:
    if role is None:
        return frozenset()
    return ROLE_REGISTRY.get(role, ROLE_REGISTRY["user"]).permissions
```

`AuthContext` 改为按 role 计算权限位：

```python
class AuthContext:
    __slots__ = ("user", "_permissions")
    def __init__(self, user, permissions=None):
        self.user = user
        # auth.strict_rbac=False 时仍 fall back 到 ALL_PERMISSIONS（兼容旧行为）
        if get_auth_config().strict_rbac and user is not None:
            self._permissions = permissions_for(getattr(user, "system_role", "user"))
        else:
            self._permissions = ALL_PERMISSIONS if user else frozenset()
```

新增配置项 `auth.strict_rbac: bool = False`（[backend/packages/harness/deerflow/config/auth_config.py](../../backend/packages/harness/deerflow/config/auth_config.py)）。

**影响面**

- [authz.py:117-127](../../backend/app/gateway/authz.py#L117) 的 `_ALL_PERMISSIONS` 常量删除（仍保留向后兼容 alias 一段时间）。
- [auth_middleware.py:177](../../backend/app/gateway/auth_middleware.py#L177) 改为 `AuthContext(user=user)`（不再传第二参）。
- 各路由的 `@require_permission(r, a)` 调用点不动。

**测试**

- `tests/test_role_registry.py`：每个角色对每个 resource:action 的 allow/deny 矩阵。
- `tests/test_strict_rbac_toggle.py`：开关 false 时旧行为，true 时新行为。
- `tests/test_require_permission_with_roles.py`：`role=user` 调用 `closure:verify` → 403；`role=tenant_admin` → 200。

---

### 4.1.1 RBAC 与既有资源级 ACL 的集成边界（重要）

DeerFlow 当前已有两套**资源级 ACL** 与新 `RoleRegistry` 共存。本节明确**串行评估顺序**，避免误判。

**双层授权模型**：

| 层 | 实现 | 粒度 | 例子 |
|----|------|------|------|
| **L1 RBAC（路由级粗粒度门）** | `@require_permission(resource, action)` + `RoleRegistry` | 角色 → 权限位 | 只有 `tenant_admin` 能调 `POST /api/knowledge-bases` |
| **L2 资源级 ACL（细粒度门）** | 服务层显式 `check_xxx_access()` | 资源 ↔ 用户 | 即使 `tenant_admin`，也不能写他没有 `KbPermissionRow` 的某个具体 KB |

**评估顺序**：**L1 → L2**（必须串行，**全过才放行**）。

```
HTTP 请求
   │
   ▼
[1] AuthMiddleware → 解析 token / identity_kind
   │
   ▼
[2] @require_auth → 401 if 未鉴权
   │
   ▼
[3] @require_permission("kb", "write") → 403 if role 不在 RoleRegistry 表中
   │              ↑ L1 在此结束（粗粒度）
   ▼
[4] 路由 handler → service.create_document_with_access_check(...)
   │              ↑ L2 在此开始（细粒度）
   ▼
[5] service 内部 → KbPermissionRow lookup → 403/404 if 无 access
   │
   ▼
[6] 返回 200
```

**已识别的 L2 系统**：

1. **KB 子系统**（[knowledge_base/service.py](../../backend/packages/harness/deerflow/knowledge_base/service.py) `*_with_access_check` 方法 + [access_control.py](../../backend/packages/harness/deerflow/knowledge_base/access_control.py)）—— `KbPermissionRow` 表 + visibility (`private/tenant/public`)。
2. **Agent 子系统**（[agents/service.py](../../backend/packages/harness/deerflow/agents/service.py)）—— `AgentPermissionRow` 表。
3. **Thread 子系统**（[thread_meta/sql.py](../../backend/packages/harness/deerflow/persistence/thread_meta/sql.py) `check_access`）—— 单字段 `user_id` 持有者匹配。

**RoleRegistry 中 KB / Agent 权限位的语义**：粗粒度门用于"是否允许尝试这个动作"，例如 `knowledge_bases:write` 仅判定"能不能调 KB 写接口"——具体能写哪个 KB 仍由 L2 `KbPermissionRow` 决定。L1 与 L2 是 **AND** 关系。

**对应到角色矩阵**：

| 角色 | L1 `knowledge_bases:write` | L2 KbPermission | 实际可写的 KB 子集 |
|------|---|---|---|
| `user` | ✗ | — | 无（在 L1 即被拒） |
| `tenant_admin` | ✓ | 自动持有本租户全部 KB | 本租户全部 |
| `superadmin` | ✓ | bypass L2 | 全部 |

**实现细节**：

- L2 在 strict_rbac=true 之前已经存在并工作；本设计**不修改**任何 L2 行为。
- `superadmin` 在 L2 自动 bypass，由现有 `is_superadmin(role)` 守卫处理，本设计不引入新 bypass。
- 两个 `tenant_admin` 跨租户操作：L1 通过（持 `knowledge_bases:write` 权限位），L2 拒绝（`KbPermission` 行不存在）。这正是设计期望——本设计**不**承担"防止 tenant_admin 跨租户"的职责，那是 L2 既有逻辑。

**回归保护**：Sprint 加 Story `A.5b` (1 SP) `tests/test_kb_rbac_under_strict_mode.py`：在 `strict_rbac=true` 下跑既有 KB 140 个测试，验证 L1+L2 串行不破坏既有行为。

**为什么不合并 L1 + L2**：合并需要把 `KbPermissionRow` 抽到通用 `permissions` 表，那是 ABAC 改造，已在 §2.2 排除。本期保持双层分工。

---

### 4.2 C2 — ins-base 角色源切换

**现状**

[ins_base_provider.py:25-37](../../backend/app/gateway/auth/ins_base_provider.py#L25-L37)：

```python
def _map_system_role(username: str) -> str:
    lower = username.lower()
    if lower == "superadmin": return "superadmin"
    if lower == "admin": return "tenant_admin"
    return "user"
```

每次 `get_user()` 调用都重算（[ins_base_provider.py:316](../../backend/app/gateway/auth/ins_base_provider.py#L316)）——任何 ins-base 中名为 `admin` 的账号自动获得 tenant_admin。

**目标**

- 角色由 ins-base 返回的"权限/角色字段"决定，而不是用户名。
- 如果 ins-base 不返回角色信息，DeerFlow 侧默认所有 ins-base 用户为 `user`，超管/租管由 DeerFlow 自己的 `users.system_role` 表决定。

#### 4.2.1 ins-base API 契约假设清单（**Sprint 0 必须验证**）

> ⚠️ **本节列出的契约必须在 Sprint A 启动前由 ins-base 团队书面确认**。如果任一假设未被确认，对应的回退路径见 §4.2.2。

| 编号 | 假设 | 验证方式 | 状态 |
|------|------|---------|------|
| ASM-1 | ins-base `getUserInfo(token)` 响应 body 含 `permissions: list[dict]` 字段 | 协议文档 / 抓包样例 | **待验证** |
| ASM-2 | `permissions[*].code` 是字符串枚举（候选值如 `PLATFORM_ADMIN` / `TENANT_ADMIN`） | 协议文档 / 与对方协商命名 | **待验证** |
| ASM-3 | 同一用户跨调用返回稳定的 `userId`（`get_user(token).userId == authenticate(...).userId`） | mock 联调 | **已知不一致**（M5 待修） |
| ASM-4 | ins-base 不会以"会话级"返回不同 permissions（角色绑定到账号，不绑定到 token） | 与对方核对授权模型 | **待验证** |
| ASM-5 | ins-base 提供失败/降权事件回调或轮询接口（角色实时下沉） | 协议文档 | **可选**——若无，DeerFlow 仍可通过 `token_version` bump 实现降权立即生效（§4.4） |

**Sprint 0 工作清单**（独立于本设计的实施 Story，由 EM 与 ins-base 团队并行推进）：

1. 与 ins-base 团队同步 ASM-1 ~ ASM-4（建议 1 次会议 + 一份字段对齐 doc）。
2. 提供 ins-base mock fixture（`backend/tests/fixtures/ins_base/`）：
   - `auth_response_with_platform_admin.json`
   - `auth_response_with_tenant_admin.json`
   - `auth_response_user_only.json`
   - `auth_response_no_permissions_array.json`（兜底）
3. 阻塞条件：ASM-1 + ASM-2 任一未确认时，启动 §4.2.2 的回退路径并通知 PM 调整 Sprint 计划。

#### 4.2.2 回退路径（ins-base 字段未对齐时）

若 Sprint 0 末仍无法确认 `permissions[].code` 字段：

- **降级实现**：仍删除 `_map_system_role` 用户名 hack，但 `InsBaseRoleResolver.resolve_role()` **跳过 ins-base permissions[] 解析**，直接使用 DeerFlow 本地 `users.system_role` 作为唯一真相源（设计图中第 2 步）。
- ins-base 侧返回的所有用户首次登录均落表为 `system_role="user"`；提权由 DeerFlow superadmin 通过 `PUT /admin/users/{id}/role` 显式操作。
- 缺点：超管必须先通过 DeerFlow 后台手动提权，不能利用 ins-base 现有角色体系自动同步。可接受——比"用户名 admin 自动 tenant_admin"安全得多。
- **B.1.1 Story 调整**：从 2 SP 降到 1 SP（无需 permissions[] 解析）；新增 D 期 Story `D.4` (1 SP) 在字段对齐后补充 ins-base 自动同步（视字段确认时间决定是否本期实现）。

**设计**

1. 引入 `InsBaseRoleResolver`（[backend/app/gateway/auth/ins_base_role_resolver.py](../../backend/app/gateway/auth/ins_base_role_resolver.py)，新文件）：

```python
INS_BASE_PERM_TO_ROLE = {
    "PLATFORM_ADMIN": "superadmin",
    "TENANT_ADMIN":   "tenant_admin",
}

async def resolve_role(
    user_data: dict,
    permissions: list[dict],          # ins-base 返回的 permissions[]
    deerflow_repo: UserRepository,    # 本地 user 表
    *,
    real_user_id: str,
) -> str:
    # 1) ins-base permissions[] 中显式标记（仅当 ASM-1/2 已确认时启用）
    if get_auth_config().trust_ins_base_permissions:
        perm_codes = {p.get("code") for p in permissions if isinstance(p, dict)}
        for code, role in INS_BASE_PERM_TO_ROLE.items():
            if code in perm_codes:
                return role
    # 2) DeerFlow 本地 user 表覆盖（管理员后台手动指定）
    local = await deerflow_repo.get(real_user_id)
    if local and local.system_role:
        return local.system_role
    # 3) 默认 user
    return "user"
```

新增配置项 `auth.trust_ins_base_permissions: bool = False`（默认关闭，待 Sprint 0 确认 ASM-1/2 后再开启；与回退路径 §4.2.2 完全兼容）。

2. 删除 [ins_base_provider.py:25-37](../../backend/app/gateway/auth/ins_base_provider.py#L25-L37) 的 `_map_system_role`，相关调用切换到 `InsBaseRoleResolver.resolve_role(...)`。
3. 在 ins-base 用户首次登录时把 `(real_user_id, default role="user")` 落到本地 `users` 表，方便 DeerFlow 管理员通过 `PUT /admin/users/{id}/role` 显式提权。
4. 新增管理后台路由 `PUT /admin/users/{user_id}/role`（仅 superadmin 可调）。Body：`{"system_role": "tenant_admin" | "user"}`。

**影响面**

- [ins_base_provider.py](../../backend/app/gateway/auth/ins_base_provider.py)：删除函数级 hack，新增 resolver 注入。
- [admin.py](../../backend/app/gateway/routers/admin.py)：新增 `update_user_role` 路由 + Pydantic schema。
- 数据迁移脚本：把当前所有名为 `superadmin` / `admin` 的本地 / ins-base 镜像用户的 role 一次性回写到 `users` 表（保留现有特权用户的可用性）。

**测试**

- `tests/test_ins_base_role_resolver.py`：matrix 覆盖 ins-base permissions 三种返回 + 本地 override + 默认。
- `tests/test_admin_user_role.py`：tenant_admin 不能调用 `PUT /admin/users/{id}/role`，superadmin 可以。
- 安全测试：构造 ins-base mock 返回 `userName="admin"` + 空 permissions[] → `resolve_role()` 返回 `"user"`（落表前）。

---

### 4.3 C3 — `default` 字面量去重载化 + 历史数据归属化

**现状**

[thread_meta/sql.py:116-118](../../backend/packages/harness/deerflow/persistence/thread_meta/sql.py#L116-L118)：

```python
if row.user_id is None or row.user_id == "default":
    return True
return row.user_id == user_id
```

[internal_auth.py](../../backend/app/gateway/internal_auth.py) `internal_user.id = "default"` —— 三种语义混用。

**目标**

- `DEFAULT_USER_ID = "default"` 仅代表"`auth.enabled=False` 模式下的占位身份"。
- 内部 token 的合成 user 用独立 sentinel `INTERNAL_USER_ID = "__internal__"`。
- "行无主"由 DB 中 `user_id IS NULL` 表达；`check_access` 不再因 `user_id="default"` 直通。
- 历史数据通过一次性迁移脚本归属：把现存 `user_id="default"` 的行根据 `created_at` 推断或显式归到 `tenant_id` 的 admin。

**设计**

1. **新增 sentinel**（[backend/packages/harness/deerflow/runtime/user_context.py](../../backend/packages/harness/deerflow/runtime/user_context.py)）：

```python
DEFAULT_USER_ID: Final[str] = "default"        # 沿用
INTERNAL_USER_ID: Final[str] = "__internal__"  # 新增

# Identity kind ContextVar
_identity_kind: ContextVar[Literal["anonymous", "authenticated", "internal"]] = (
    ContextVar("identity_kind", default="anonymous")
)
```

2. **`internal_auth.get_internal_user()`**：

```python
def get_internal_user(*, tenant_id: str):
    """Construct synthetic internal identity. ``tenant_id`` is REQUIRED.

    Internal token 的调用方（IM channel webhook、后台 dispatcher）必须
    显式传入要操作的 tenant_id。禁止 ``tenant_id=None``——这能阻断
    "internal token 跨租户访问"的隐式越权（H4 风险）。
    """
    if not tenant_id:
        raise ValueError(
            "internal identity requires explicit tenant_id; "
            "see docs/plans/2026-05-19-permission-architecture-fix-design.md §4.3"
        )
    return SimpleNamespace(
        id=INTERNAL_USER_ID,
        system_role="internal",
        tenant_id=tenant_id,
    )
```

调用方迁移：

- IM channel webhook 接收消息时已能从 `store.py` 的 `(channel_name, chat_id)` 反查到 `thread_id`，进而通过 `threads_meta.tenant_id` 拿到目标租户。webhook handler 在生成 internal user 之前必须先做这一步反查。
- 后台 dispatcher（`IndexingDispatcher` / `MemoryQueue`）的 job row 已持久化 `tenant_id`，出队时直接传入。
- 单元测试：`test_internal_token_must_pass_tenant_id.py` 断言 `get_internal_user(tenant_id=None)` 抛 `ValueError`；`test_internal_token_scope.py` 断言 internal token 调 `/api/threads/{tid}` 时 `tid` 所在租户与 internal context 的 `tenant_id` 不一致 → 404（不是 200，也不是 403——保持与"thread 不存在"同一响应避免泄露存在性）。

3. **`check_access` 改写**（[backend/packages/harness/deerflow/persistence/thread_meta/sql.py](../../backend/packages/harness/deerflow/persistence/thread_meta/sql.py)）：

```python
async def check_access(
    self,
    thread_id: str,
    user_id: str,
    *,
    require_existing: bool = False,
    identity_kind: Literal["anonymous","authenticated","internal"] = "authenticated",
    caller_tenant_id: str | None = None,   # internal token 必传
) -> bool:
    row = await self._fetch(thread_id)
    if row is None:
        return not require_existing
    # 内部调用：必须显式声明 identity_kind="internal" + 同租户
    if identity_kind == "internal":
        if caller_tenant_id is None:
            raise ValueError("internal check_access requires caller_tenant_id")
        # internal token 仅能访问与 caller 同租户的 thread
        return row.tenant_id == caller_tenant_id
    # 历史无主行（NULL）：仅在 require_existing=False 时放行（兼容遗留）
    if row.user_id is None:
        return not require_existing
    # 严格匹配（不再因 row.user_id == "default" 直通）
    return row.user_id == user_id
```

4. **历史数据迁移脚本**（[backend/scripts/migrate_default_user_threads.py](../../backend/scripts/migrate_default_user_threads.py)，新增）：
   - `--dry-run`：只打印分布
   - `--assign-to USER_ID`：把所有 `user_id="default"` 的 thread / run / kb_doc 行回写为 `USER_ID`
   - 默认行为：把行归属到该 tenant 的最早一个 `tenant_admin`（如不存在则不改、由管理员手动处理）。

5. **后台任务身份注入**：所有 `IndexingDispatcher` / `MemoryQueue` / `ChannelManager` 异步任务在入队时把 `identity_kind` 一并保存，出队时通过 `with_identity_context(...)` 还原。

**影响面**

- [thread_meta/sql.py](../../backend/packages/harness/deerflow/persistence/thread_meta/sql.py)：`check_access` 加 `identity_kind` 参数，内部分支改写。
- [authz.py:286-309](../../backend/app/gateway/authz.py#L286-L309)：`require_permission(owner_check=True)` 调用处把 `identity_kind` 从 `request.state.auth` 传下去。
- [internal_auth.py](../../backend/app/gateway/internal_auth.py)：`get_internal_user()` 改返回 `__internal__`。
- 一次性迁移脚本（不可逆，但可 dry-run）。

**测试**

- `tests/test_check_access_default_purge.py`：用户 A 创建 `user_id="default"` thread → 用户 B 登录 → 访问 → 应 404；迁移脚本运行后归属正确。
- `tests/test_internal_identity_isolation.py`：internal token 调 `GET /api/threads/{owned_by_user_b}` → 200（白名单），但 `auth.user.id` 不会污染下游 user_id 过滤。
- `tests/test_runtime_identity_kind_propagation.py`：dispatcher 任务能恢复正确 identity。

---

### 4.4 H1 — JWT 主链合并

**现状**

- [auth/jwt.py](../../backend/app/gateway/auth/jwt.py)：cookie 路径，pyjwt，5 字段，**无 role**。
- [auth/jwt_handler.py](../../backend/app/gateway/auth/jwt_handler.py)：Bearer 路径，python-jose，**含 role**。

**目标**

- 单一 JWT 实现 + 单一 token 格式 + 单一签名密钥。
- token claims 显式包含 `system_role` 与 `tenant_id`，参与签名校验。
- **降权 / 角色变更立即生效**——通过 `token_version` 单一信号实现，避免与 DB 一致性校验路径冗余。

#### 4.4.1 降权立即生效的"单一信号"决策

设计上有两种实现"role 改变后旧 token 立刻失效"的路径：

| 路径 | 机制 | 性能开销 | 维护成本 |
|------|------|----------|---------|
| **A. token_version bump** | 改 role 时同步 bump `users.token_version`；解码时比对 `payload.ver != db.ver` → 401 | 每请求一次 PK 查询 `users.token_version`（可缓存） | 低，已存在该字段 |
| **B. role drift 校验** | 解码时比对 `payload.system_role != db.system_role` → 401 | 每请求一次 `users.system_role` 查询 | 与 A 等价但语义重复 |

**决策：仅采用路径 A**。理由：

- `token_version` 已是 schema 的一部分，复用零额外字段；
- "版本号"语义清晰、单调递增，便于排查问题；
- 路径 B 是路径 A 的子集——任何 role 改动都会 bump token_version，因此 role drift 不可能独立发生；
- 减少代码歧义：`get_current_user_from_request` 只看 `ver`，不看 `system_role` 是否漂移。

**实现要求**：

- `PUT /admin/users/{id}/role` 在事务内同时更新 `system_role` 和 `token_version`。
- `decode_token` 比对 `payload.ver` 与 `users.token_version`；不一致返回 401 `token_revoked`。
- token claims 中仍然带 `system_role`（直接用，无需查 DB），仅用于 `AuthContext` 构造，不参与一致性校验。

**设计**

1. **保留 [auth/jwt.py](../../backend/app/gateway/auth/jwt.py) 作为唯一实现**（pyjwt 无 cffi 依赖，部署更友好）。
2. **扩展 claims**：

```python
class TokenPayload(BaseModel):
    sub: str                    # user_id
    ver: int                    # token_version (revocation 单一信号)
    tenant_id: str
    system_role: Literal["user", "tenant_admin", "superadmin"]
    iat: int
    exp: int
```

3. **签发路径**：登录成功后 `encode_token(user)` 把 `system_role` 一并写入。
4. **解码路径**：`decode_token(token)` 解出 `TokenPayload`；`get_current_user_from_request` 查 `users.token_version`，比对不一致即 401 `token_revoked`；之后直接用 `payload.system_role` 构造 `AuthContext`，不再单独查 `users.system_role` 验漂移。
5. **删除 [auth/jwt_handler.py](../../backend/app/gateway/auth/jwt_handler.py)**：调用方迁移到 jwt.py。Bearer 路径仍可走 cookie 同款 token，只是从 `Authorization: Bearer <token>` 头读出。
6. **签名算法迁移**：jwt.py 当前用 HS256；不变。密钥从 `auth.jwt_secret` 读，如未设置则启动失败（fail-fast）。

**影响面**

- [auth/jwt.py](../../backend/app/gateway/auth/jwt.py)：claims schema 扩展。
- [auth/dependencies.py](../../backend/app/gateway/auth/dependencies.py) `get_current_user_from_request`：加 `token_version` 比对。
- [auth/jwt_handler.py](../../backend/app/gateway/auth/jwt_handler.py)：删除（保留 deprecation shim 一个 sprint 后清理）。
- [routers/admin.py](../../backend/app/gateway/routers/admin.py) `update_user_role`：事务内同时改 role + bump token_version。
- 调用方：`grep -r "jwt_handler" backend/`，逐一替换。

**测试**

- `tests/test_jwt_payload_role.py`：encode → decode 后 role 守恒。
- `tests/test_jwt_token_version_revocation.py`：bump token_version → 旧 token 401；新 token 通过。
- `tests/test_admin_user_role_bumps_token_version.py`：`PUT /admin/users/{id}/role` 后 `users.token_version` 单调递增。
- `tests/test_jwt_handler_removed.py`：导入 jwt_handler 应 raise（防止回归，D.3 之后）。

---

### 4.5 H2 — RunRow 加 tenant_id + 聚合接口加双键过滤

**现状**

- [run/model.py](../../backend/packages/harness/deerflow/persistence/run/model.py)：`RunRow` 无 `tenant_id`。
- [run/sql.py:208](../../backend/packages/harness/deerflow/persistence/run/sql.py#L208)：`aggregate_tokens_by_thread(thread_id)` 无任何身份过滤。
- 路由层 [thread_runs.py:371](../../backend/app/gateway/routers/thread_runs.py#L371) 通过 `@require_permission("threads", "read", owner_check=True)` 兜底，但 ownership 检查刚才（C3）才修。

**目标**

- `runs` 表加 `tenant_id` 列 + 复合索引 `(tenant_id, thread_id)`。
- 所有仓库方法接受并强制 `(tenant_id, user_id)` 过滤。

**设计**

1. **DB 迁移**（[backend/packages/harness/deerflow/persistence/migrations/versions/003_add_tenant_id_to_runs.py](../../backend/packages/harness/deerflow/persistence/migrations/versions/003_add_tenant_id_to_runs.py)）：

```python
def upgrade():
    op.add_column("runs", sa.Column("tenant_id", sa.String(), nullable=True))
    # 数据回填：从 thread_meta 关联
    op.execute("""
        UPDATE runs
        SET tenant_id = (
            SELECT tenant_id FROM threads_meta tm
            WHERE tm.thread_id = runs.thread_id
            LIMIT 1
        )
    """)
    # 仍允许 NULL（历史数据兼容），但应用层 strict_rbac=true 时必须非空
    op.create_index("ix_runs_tenant_thread", "runs", ["tenant_id", "thread_id"])
```

2. **`RunRepository.aggregate_tokens_by_thread`** 改签：

```python
async def aggregate_tokens_by_thread(
    self,
    thread_id: str,
    user_id: str | None = None,
    tenant_id: str | None = None,
) -> dict:
    # auth.strict_rbac=True 时 user_id+tenant_id 必填
    if get_auth_config().strict_rbac:
        if not user_id or not tenant_id:
            raise ValueError("aggregate_tokens_by_thread requires (user_id, tenant_id) under strict_rbac")
    stmt = select(...).where(RunRow.thread_id == thread_id)
    if user_id:
        stmt = stmt.where(RunRow.user_id == user_id)
    if tenant_id:
        stmt = stmt.where(RunRow.tenant_id == tenant_id)
    ...
```

3. **`RunRepository.create / update_status / update_run_completion`**：参数加 `(tenant_id, user_id)`，写入时填充 `RunRow.tenant_id`。
4. 所有调用方一次性补齐。

**影响面**

- [persistence/migrations/versions/](../../backend/packages/harness/deerflow/persistence/migrations/versions/) 新增 `003_*.py`。
- [run/model.py](../../backend/packages/harness/deerflow/persistence/run/model.py)、[run/sql.py](../../backend/packages/harness/deerflow/persistence/run/sql.py)。
- [thread_runs.py](../../backend/app/gateway/routers/thread_runs.py)、[runs.py](../../backend/app/gateway/routers/runs.py)：调用 aggregator 时显式传 tenant_id。

**测试**

- `tests/test_runs_tenant_isolation.py`：tenant A 用 thread B 的 ID 调 `aggregate_tokens_by_thread` → 应返回空 / 403。
- `tests/test_runs_migration_backfill.py`：升级前历史数据；升级后 `tenant_id` 已回填。

---

### 4.6 H3 — `update_tenant` quota 字段需 superadmin

**现状**

[admin.py update_tenant](../../backend/app/gateway/routers/admin.py#L258) 用 `_resolve_scope_tenant_id`（允许 tenant_admin 操作自己的租户），但 body `TenantUpdateRequest` 含 `daily_quota_usd` / `monthly_quota_usd`，tenant_admin 可越权调高自己额度。

**目标**

- tenant_admin 仍能改自己租户的非敏感字段（name、description）。
- quota 字段（`daily_quota_usd`、`monthly_quota_usd`、`is_active`）只有 superadmin 能改。

**设计**

1. **拆分 schema**：

```python
class TenantBasicUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None

class TenantQuotaUpdateRequest(BaseModel):
    daily_quota_usd: int | None = None
    monthly_quota_usd: int | None = None
    is_active: bool | None = None
```

2. **拆分路由**：

```python
@router.put("/{tenant_id}")
@require_permission("tenants", "write")
async def update_tenant_basic(...): ...   # tenant_admin OK

@router.put("/{tenant_id}/quota")
@require_permission("tenants", "admin")   # 仅 superadmin 持有
async def update_tenant_quota(...): ...
```

3. 旧 `PUT /admin/tenants/{tenant_id}` 仍接受全量字段，但**在 strict_rbac=True 时**对非 basic 字段做白名单过滤（携带额外字段 → 422）。

**影响面**

- [admin.py](../../backend/app/gateway/routers/admin.py)：路由拆分 + schema 调整。
- 前端管理面板：调用点拆成两个按钮 / 两个 form。

**测试**

- `tests/test_update_tenant_quota_role_check.py`：tenant_admin 调 `/quota` → 403；superadmin → 200。
- `tests/test_update_tenant_basic_filters_quota.py`：tenant_admin 调老接口带 quota 字段 → 422。

---

### 4.7 H4 — `/api/runs/stream` 与 `/api/runs/wait` 补装饰器

**现状**

[runs.py:35](../../backend/app/gateway/routers/runs.py#L35)、[runs.py:60](../../backend/app/gateway/routers/runs.py#L60)：无 `@require_permission`。

**目标**

- 路由层显式 `@require_permission("runs", "create")`。
- 中间件失败时仍能保证路由层兜底。

**设计**

```python
@router.post("/stream")
@require_auth
@require_permission("runs", "create")
async def runs_stream(payload: RunRequest, request: Request): ...

@router.post("/wait")
@require_auth
@require_permission("runs", "create")
async def runs_wait(payload: RunRequest, request: Request): ...
```

**影响面**：仅 [runs.py](../../backend/app/gateway/routers/runs.py)。

**测试**

- `tests/test_runs_stateless_decorator.py`：移除 AuthMiddleware 后路由仍 401。

---

### 4.8 M1 — 租户 LIST 接口对 user 角色开放只读

**现状**

`tenant_agents` / `tenant_mcp_servers` / `tenant_connectors` 等 LIST 路由要求 tenant_admin。普通用户无法看到本租户内可用资源。

**目标**

- LIST 路由对 `user` 开放只读；返回结果按"该用户被授权访问的子集"过滤。
- 写操作（POST/PUT/DELETE）仍要 tenant_admin。

**设计**

```python
@router.get("/api/tenants/{tenant_id}/agents")
@require_auth
@require_permission("agents", "read")           # ← 改为 read（user 持有）
async def list_tenant_agents(tenant_id: str, request: Request):
    auth = request.state.auth
    if auth.user.tenant_id != tenant_id and auth.user.system_role != "superadmin":
        raise HTTPException(403)
    # 按 user 持有的 permission rows 过滤
    return await agent_service.list_for(tenant_id, viewer=auth.user)
```

`agent_service.list_for(tenant_id, viewer)` 中按 `is_tenant_admin(viewer.system_role)` 决定返回全集还是按 `agent_permissions` 表过滤的子集。

**影响面**

- [tenant_agents.py](../../backend/app/gateway/routers/tenant_agents.py)、[tenant_mcp_servers.py](../../backend/app/gateway/routers/tenant_mcp_servers.py)、[tenant_connectors.py](../../backend/app/gateway/routers/tenant_connectors.py) 的 LIST。
- 仓库层 `list_for(viewer)` 新接口。

**测试**

- `tests/test_tenant_list_visibility.py`：user 调 LIST → 200 + 子集；tenant_admin → 全集。

---

### 4.9 M2 — `_resolve_tenant_id` 失败时拒绝登录

**现状**

[ins_base_provider.py:130-136](../../backend/app/gateway/auth/ins_base_provider.py#L130-L136)：

```python
if self._tenant_repo is None:
    logger.error(...)
    return factory_org_id
```

**目标**

- 任何依赖未就绪都应拒绝登录而非降级，避免后续 `tenant_id` 在 DB 中不存在导致静默查空。

**设计**

```python
if self._tenant_repo is None and self._session_factory is None:
    raise HTTPException(503, "Tenant repository not available — cannot resolve tenant_id")
```

并把 `tenant_repo` 注入移到 `langgraph_runtime()` 启动期，确保 `init_engine_from_config` 之后就能创建。

**影响面**：[ins_base_provider.py](../../backend/app/gateway/auth/ins_base_provider.py)、[deps.py langgraph_runtime](../../backend/app/gateway/deps.py)。

**测试**

- `tests/test_ins_base_tenant_repo_required.py`：`tenant_repo=None` 启动 + ins-base 登录 → 503。

---

### 4.10 M3 — 默认回退角色对齐 Literal

**现状**

[dependencies.py:54、70](../../backend/app/gateway/auth/dependencies.py#L54)：fallback `"member"`；`User.system_role` Literal 仅有 `superadmin / tenant_admin / user`。

**目标**

- fallback 改为 `"user"`（最低权限），与 Literal 一致。
- `require_admin` 显式拒绝 `"user"`（行为不变，类型对齐）。

**设计**

```python
# dependencies.py
DEFAULT_ROLE: Final[Literal["user"]] = "user"

class CurrentUser(BaseModel):
    id: str
    username: str
    role: Literal["superadmin", "tenant_admin", "user"] = DEFAULT_ROLE
```

**影响面**：[auth/dependencies.py](../../backend/app/gateway/auth/dependencies.py)。

**测试**

- `tests/test_currentuser_default_role.py`：缺字段 → role="user"。

---

### 4.11 M4 — 生产模式禁止 `auth.enabled=False`

**现状**

[dependencies.py](../../backend/app/gateway/auth/dependencies.py) `auth.enabled=False` 时 `get_current_user` 返回 `username="admin", role="superadmin"`。生产配置漂移会让所有请求自动 superadmin。

**目标**

- `ENV=prod and auth.enabled=False` 启动时 fail-fast。
- dev 模式仍兼容。

**设计**

```python
# app/gateway/app.py 启动钩子
def _validate_auth_config():
    env = os.environ.get("DEER_FLOW_ENV", "dev").lower()
    if env == "prod" and not get_auth_config().enabled:
        raise RuntimeError(
            "auth.enabled=False is forbidden when DEER_FLOW_ENV=prod. "
            "Set auth.enabled=true in config.yaml."
        )
```

**影响面**：[app/gateway/app.py](../../backend/app/gateway/app.py) lifespan。

**测试**

- `tests/test_prod_auth_required.py`：`DEER_FLOW_ENV=prod` + `auth.enabled=false` → app 启动 raise。

---

### 4.12 M5 — ins-base authenticate / get_user 用同一 user.id

**现状**

[ins_base_provider.py:232](../../backend/app/gateway/auth/ins_base_provider.py#L232) `authenticate()` 用 `uuid4()`；[ins_base_provider.py:297-303](../../backend/app/gateway/auth/ins_base_provider.py#L297-L303) `get_user()` 用 ins-base 真实 userId。

**目标**

- `authenticate()` 内部直接调用 `get_user(token)` 拿到真实 user_id，不再生成 uuid4。

**设计**

```python
async def authenticate(self, credentials):
    ...
    response = await self._auth_service.login(...)
    token = response["data"]["token"]
    # 复用 get_user 的解析路径，保证 user.id 跨调用一致
    user = await self.get_user(token)
    if user is None:
        return None
    user.ins_base_token = token
    user.ins_base_refresh = response["data"].get("refresh", "")
    return user
```

**影响面**：[ins_base_provider.py](../../backend/app/gateway/auth/ins_base_provider.py)。

**测试**

- `tests/test_ins_base_user_id_consistency.py`：登录后立刻 list threads → 用 token 解 user_id 应一致。

---

## 5. 数据模型改动汇总

只做加列 / 加索引，不改字段语义。

### 5.1 `runs` 表

| 改动 | 列 | 说明 |
|------|----|------|
| 加列 | `tenant_id VARCHAR NULL` | strict_rbac 模式下应用层强制非空 |
| 加索引 | `(tenant_id, thread_id)` | 聚合查询热点 |

### 5.2 `users` 表

| 改动 | 列 | 说明 |
|------|----|------|
| 加索引 | `(system_role)` | 列出 superadmin / tenant_admin 用 |

### 5.3 `threads_meta` 表

| 改动 | 列 | 说明 |
|------|----|------|
| **不**加列 | — | check_access 改为应用层逻辑 |
| 数据迁移 | `UPDATE threads_meta SET user_id = NULL WHERE user_id = 'default'` | 通过迁移脚本人工确认后再执行 |

### 5.4 配置项

| 配置 | 默认 | 说明 |
|------|------|------|
| `auth.strict_rbac` | `false` | true 时启用真正 RBAC |
| `auth.jwt_secret` | 必填 | 启动 fail-fast 校验 |
| `DEER_FLOW_ENV` | `dev` | `prod` 时禁止 auth.enabled=false |

---

## 6. 兼容性与灰度

### 6.1 兼容矩阵

| 客户端 / 调用方 | strict_rbac=false | strict_rbac=true |
|----------------|-------------------|------------------|
| 前端（cookie + JWT） | 不变 | role-aware 子集；管理菜单按 role 隐藏 |
| IM channels（internal token） | 不变 | identity_kind=internal，bypass owner_check 但仍限定 tenant_id |
| LangGraph Studio（Bearer） | 不变 | 走相同 jwt.py 主链 |
| 旧 jwt_handler 调用方 | 一个 sprint deprecation 期 | 第二个 sprint 删除 |

### 6.2 灰度步骤

1. **Sprint A (W1–W2)**：DB 迁移（runs.tenant_id）+ RoleRegistry 落地 + 测试矩阵覆盖；feature flag 默认 false，行为完全不变。
2. **Sprint B (W3–W4)**：ins-base resolver 切换 + JWT 主链合并 + check_access 改写 + 历史数据归属化（dry-run）。
3. **Sprint C (W5)**：dev/staging 切 `strict_rbac=true`，跑端到端 + 黑盒回归。
4. **Sprint D (W6)**：生产灰度 strict_rbac=true（按租户灰度，先内部租户再客户）。
5. 上线两周稳定后，删除 `_ALL_PERMISSIONS` 的 backward-compat alias 与 jwt_handler.py。

### 6.3 回滚

- **C1 RBAC**：`auth.strict_rbac=false` 即刻回退；权限位重新等价于 `_ALL_PERMISSIONS`。
- **C2 ins-base resolver**：保留 `_map_system_role` 一个 sprint 作为 fallback，可通过配置 `auth.ins_base.legacy_username_role=true` 临时切回。
- **C3 default 字面量**：迁移脚本支持 `--rollback`：把 `user_id IS NULL` 行批量改回 `"default"`（前提是该 user_id 列允许 default 值）。
- **H1 JWT**：`jwt_handler.py` 保留 deprecation 一个 sprint，回滚只需把调用点改回。
- **H2 runs.tenant_id**：列允许 NULL；strict_rbac=false 时无影响。

### 6.4 与 PostgreSQL 存储迁移的协调

并行进行的 [PostgreSQL 存储迁移](./2026-05-08-postgresql-storage-migration-design.md) 与本设计共享 Alembic 链。三种合入顺序：

| 顺序 | 影响 | 处理 |
|------|------|------|
| **PG 迁移先合入，权限修复后合入** | 推荐路径。`runs.tenant_id` 在 PG 上加列时已是稳定的 PG schema | 本设计的 003 直接 ADD COLUMN；测试在 PG 上跑一次 |
| **本设计先合入，PG 迁移后合入** | 003 在 SQLite 上加列；之后 PG 迁移把整库导入新 PG | PG 迁移工程师需要把 003 的等效 ADD COLUMN 加到 PG 全量初始化脚本，或由 alembic head 重放——必须由 PG 迁移工程师 review 003 |
| **同时进行** | 风险最高 | 禁止——两个 Sprint 在 Alembic 链上有冲突时分支起争抢 |

**操作约定**：

- 003 PR 的 reviewer 列表必须包含 PG 迁移负责人。
- Sprint A 启动前，PM 与 PG 迁移 owner 同步合入顺序，更新本节决策。
- 风险表已增加该项。
- `index_status` ENUM 在 PG 上的 ADD VALUE 限制（不能在 transaction 中执行）已在 KB Sprint plan 踩过，本设计的 003 不涉及 ENUM 变更，无该风险。

### 6.5 性能与监控

- **L1 路由级 RBAC**：增加每请求一次 `RoleRegistry.permissions_for(role)` 调用——本质上是 frozenset 查表 + `in` 判定，O(1)，可忽略。
- **token_version 校验**：每请求一次 `users.token_version` PK 查询。预期 < 1 ms（含连接复用）；如 P95 涨 > 5%，加 `lru_cache(maxsize=10000, ttl=60s)` 缓存（容忍 1 分钟降权延迟）。
- **C.5.4 性能 smoke 测试**（Sprint plan 已加）：strict_rbac=false vs true 下 `/api/threads/{id}` GET P95 对比，回归 < 5%；超过则评估缓存策略。
- **灰度监控指标**（D.1.2 详细化）：
  - 基线（切换前 24h）：403 计数、平均 latency、客服工单总量。
  - 回滚阈值：403 同比涨 > 30% 持续 30 分钟 / 客服工单关键词命中 ≥ 3 单 / 黑盒测试在 staging 红 1 次。
  - On-call：SRE 主、backend dev 副；CronJob 每 5 分钟 dump dashboard 到 Slack。

---

## 7. Sprint 拆分

> 详细 Story 拆分、依赖关系、状态跟踪见 [2026-05-19-permission-architecture-fix-sprint-plan.md](./2026-05-19-permission-architecture-fix-sprint-plan.md)（待写）。

### Sprint A（Week 1–2，地基 + RBAC 表 + tenant_id 列）

| # | Story | SP | 文件 |
|---|-------|----|------|
| A.0 | Alembic 迁移 003：`runs.tenant_id` 加列 + 回填 + 索引 | 2 | `persistence/migrations/versions/003_*.py` |
| A.1 | C1 RoleRegistry + AuthContext 改写 + `auth.strict_rbac` 开关 | 5 | `auth/roles.py`、`authz.py`、`auth_middleware.py`、`config/auth_config.py` |
| A.2 | M3 default role 对齐 Literal | 1 | `auth/dependencies.py` |
| A.3 | M4 prod 模式禁止 auth.enabled=false | 1 | `app/gateway/app.py` |
| A.4 | 单元测试 RoleRegistry / strict_rbac toggle | 3 | `tests/test_role_registry.py`、`tests/test_strict_rbac_toggle.py` |

容量 ≈ 12 SP。

### Sprint B（Week 3–4，ins-base resolver + JWT 主链 + default 拆分）

| # | Story | SP |
|---|-------|----|
| B.1 | C2 InsBaseRoleResolver + `users.system_role` override 后台路由 | 4 |
| B.2 | C3 default / __internal__ sentinel 拆分 + check_access 改写 + identity_kind ContextVar | 5 |
| B.3 | H1 JWT 主链合并 + token claims 加 role/tenant_id + jwt_handler deprecation | 4 |
| B.4 | M2 ins-base tenant_repo 缺失时拒绝登录 | 1 |
| B.5 | M5 authenticate / get_user 共享 user.id | 1 |
| B.6 | 历史数据迁移脚本（dry-run + 真实 run） | 3 |
| B.7 | 集成测试：跨 provider、跨 token、跨 identity_kind | 4 |

容量 ≈ 22 SP。

### Sprint C（Week 5，运行时仓库强约束 + 路由补丁）

| # | Story | SP |
|---|-------|----|
| C.1 | H2 RunRepository 双键过滤 + 调用方一次性补齐 | 4 |
| C.2 | H3 update_tenant quota 拆分路由 + 前端对齐 | 2 |
| C.3 | H4 runs.py 装饰器补齐 | 1 |
| C.4 | M1 LIST 路由对 user 开放 + viewer-aware 过滤 | 3 |
| C.5 | 端到端测试 + 安全黑盒（dev/staging strict_rbac=true） | 3 |

容量 ≈ 13 SP。

### Sprint D（Week 6，灰度 + 文档收尾）

| # | Story | SP |
|---|-------|----|
| D.1 | 生产灰度按租户切 strict_rbac=true | 2 |
| D.2 | 文档更新（CLAUDE.md、AUTH.md、README） | 2 |
| D.3 | 删除 `_ALL_PERMISSIONS` alias + jwt_handler.py | 1 |

容量 ≈ 5 SP。

**总容量** ≈ 52 SP（A=12 / B=22 / C=13 / D=5）。

---

## 8. 测试策略

### 8.1 既有测试

- 不允许修改现有断言以"绕开"诊断结论。
- `tests/test_authz.py`、`tests/test_auth_middleware.py`、`tests/test_admin.py` 等必须全部继续通过；新行为只在 `auth.strict_rbac=true` 的新 fixture 下断言。

### 8.2 新增测试模块

| 文件 | 覆盖 |
|------|------|
| `tests/test_role_registry.py` | C1 RoleRegistry 矩阵 |
| `tests/test_strict_rbac_toggle.py` | C1 开关行为 |
| `tests/test_require_permission_with_roles.py` | C1 各路由 role 矩阵 |
| `tests/test_ins_base_role_resolver.py` | C2 resolver 优先级 |
| `tests/test_admin_user_role.py` | C2 后台路由 |
| `tests/test_check_access_default_purge.py` | C3 default 行不再直通 |
| `tests/test_internal_identity_isolation.py` | C3 internal sentinel |
| `tests/test_runtime_identity_kind_propagation.py` | C3 后台任务恢复 identity |
| `tests/test_jwt_payload_role.py` | H1 token claims |
| `tests/test_jwt_role_drift.py` | H1 DB / token 不一致 |
| `tests/test_runs_tenant_isolation.py` | H2 仓库双键过滤 |
| `tests/test_runs_migration_backfill.py` | H2 迁移正确性 |
| `tests/test_update_tenant_quota_role_check.py` | H3 quota 路由 |
| `tests/test_runs_stateless_decorator.py` | H4 |
| `tests/test_tenant_list_visibility.py` | M1 |
| `tests/test_ins_base_tenant_repo_required.py` | M2 |
| `tests/test_currentuser_default_role.py` | M3 |
| `tests/test_prod_auth_required.py` | M4 |
| `tests/test_ins_base_user_id_consistency.py` | M5 |
| `tests/test_default_user_migration_script.py` | C3 历史数据迁移 |

### 8.3 安全黑盒

- `tests/security/test_rbac_blackbox.py`：构造 user / tenant_admin / superadmin 三种 token，对每条管理类路由发请求，断言响应码矩阵。
- `tests/security/test_thread_cross_user_access.py`：用户 A 的 thread_id → 用户 B 调 GET/PATCH/DELETE → 全部 404。
- `tests/security/test_internal_token_scope.py`：internal token 仍能调内部接口，但调 `/admin/tenants` 之类 → 403。

### 8.4 回归

- `tests/test_harness_boundary.py`：保证 `auth/roles.py`、`runtime/identity.py` 等新文件不违反 harness 边界。
- 对外契约：`AuthMeResponse`、`TenantResponse`、`RunResponse` 结构不变，前端 contract test 不破坏。

---

## 9. 风险与缓解

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| RoleRegistry 与现有路由 resource:action 名不对齐导致大面积 403 | **高** | Sprint A 先把当前所有 `@require_permission` 调用点导出成清单，逐条核对；strict_rbac=false 默认回退保平安 |
| ins-base permissions[] 字段缺失，所有用户 → user 角色，超管被锁在外面 | 中 | 迁移脚本先把所有名为 `superadmin` / `admin` 的镜像账号写入 `users.system_role` 落表；strict_rbac 切换前 dev 完整跑通 |
| `check_access` 改写后历史 thread 全部 404 | **高** | 迁移脚本支持 dry-run；先把 `user_id="default"` 行打印出来人工确认 → 显式归属或保留 NULL |
| jwt_handler 被外部调用方依赖（IM channel 等） | 中 | 一个 sprint deprecation 期；保留 import shim 转发到 jwt.py |
| 生产灰度时切 strict_rbac=true 导致租户管理员功能突然受限 | 中 | 按租户灰度（feature flag per-tenant），先内部租户 → 信任客户 → 全量 |
| 多人并发 PUT `/admin/users/{id}/role` 出现竞态 | 低 | 用乐观锁（`token_version` 字段已存在），role 改写同时 bump token_version → 强制对方重新登录 |

---

## 10. 文档更新清单

| 文档 | 改动 |
|------|------|
| [backend/CLAUDE.md](../../backend/CLAUDE.md) | "Authorization" 章节加 RoleRegistry + strict_rbac + identity_kind 描述 |
| [README.md](../../README.md) | 用户可见配置项 `auth.strict_rbac` / `DEER_FLOW_ENV` 列入 |
| `docs/AUTH.md`（如不存在则新建） | 完整记录角色矩阵、JWT claims、ins-base resolver、internal token 语义 |
| `docs/security/rbac-matrix.md`（新建） | 每条路由 × 每个角色的 allow/deny 表，作为权威清单 |
| `docs/migrations/2026-05-19-permission-fix.md`（新建） | DB 迁移 + 历史数据归属化操作手册 |

---

## 11. DoD（Definition of Done）

- [ ] 13 条诊断结论全部映射到具体 Story 并完成
- [ ] Alembic 迁移 003 已合入，SQLite/PG `upgrade head` 幂等通过
- [ ] 既有测试全部通过；新增测试 ≥ 25 个
- [ ] `pytest tests/test_harness_boundary.py` 通过——所有新增 harness 文件不引入 `app.*` 依赖
- [ ] `make test` 全绿（含 `tests/security/`）
- [ ] dev 切 `auth.strict_rbac=true` 后，三种角色全部端到端可用（user 看不到管理菜单 / tenant_admin 改 quota 被 403 / superadmin 全通）
- [ ] `auth.enabled=False + DEER_FLOW_ENV=prod` 启动 fail-fast
- [ ] ins-base 名为 `admin` 的账号 + 空 permissions[] → role=user（除非 DeerFlow 本地 `users.system_role` 显式提权）
- [ ] 用户 A 的 thread_id 被用户 B 直接 GET → 404；含历史 `user_id="default"` 行经迁移后已归属
- [ ] internal token 能走内部接口，但不能调 `/admin/tenants` 之类
- [ ] runs.tenant_id 列已回填；`aggregate_tokens_by_thread` 在 strict_rbac=true 下要求双键
- [ ] [backend/CLAUDE.md](../../backend/CLAUDE.md) / [README.md](../../README.md) / `docs/AUTH.md` / `docs/security/rbac-matrix.md` 已更新

---

## 12. 附录

### 12.1 相关文件路径速查

| 模块 | 路径 |
|------|------|
| 鉴权装饰器 | [backend/app/gateway/authz.py](../../backend/app/gateway/authz.py) |
| 中间件 | [backend/app/gateway/auth_middleware.py](../../backend/app/gateway/auth_middleware.py) |
| 内部 token | [backend/app/gateway/internal_auth.py](../../backend/app/gateway/internal_auth.py) |
| 依赖注入 | [backend/app/gateway/deps.py](../../backend/app/gateway/deps.py) |
| 用户依赖 | [backend/app/gateway/auth/dependencies.py](../../backend/app/gateway/auth/dependencies.py) |
| JWT 主链 | [backend/app/gateway/auth/jwt.py](../../backend/app/gateway/auth/jwt.py) |
| JWT 旧链（待删） | [backend/app/gateway/auth/jwt_handler.py](../../backend/app/gateway/auth/jwt_handler.py) |
| ins-base provider | [backend/app/gateway/auth/ins_base_provider.py](../../backend/app/gateway/auth/ins_base_provider.py) |
| 本地 provider | [backend/app/gateway/auth/local_provider.py](../../backend/app/gateway/auth/local_provider.py) |
| 用户仓库 | [backend/app/gateway/auth/repositories/sqlite.py](../../backend/app/gateway/auth/repositories/sqlite.py) |
| 管理后台路由 | [backend/app/gateway/routers/admin.py](../../backend/app/gateway/routers/admin.py) |
| Thread 路由 | [backend/app/gateway/routers/threads.py](../../backend/app/gateway/routers/threads.py) |
| Run 路由 | [backend/app/gateway/routers/runs.py](../../backend/app/gateway/routers/runs.py)、[backend/app/gateway/routers/thread_runs.py](../../backend/app/gateway/routers/thread_runs.py) |
| ThreadMeta 仓库 | [backend/packages/harness/deerflow/persistence/thread_meta/sql.py](../../backend/packages/harness/deerflow/persistence/thread_meta/sql.py) |
| Run 仓库 | [backend/packages/harness/deerflow/persistence/run/sql.py](../../backend/packages/harness/deerflow/persistence/run/sql.py)、[run/model.py](../../backend/packages/harness/deerflow/persistence/run/model.py) |
| Tenant 仓库 | [backend/packages/harness/deerflow/persistence/tenant/sql.py](../../backend/packages/harness/deerflow/persistence/tenant/sql.py) |
| Auth 配置 | [backend/packages/harness/deerflow/config/auth_config.py](../../backend/packages/harness/deerflow/config/auth_config.py) |
| 用户上下文 | [backend/packages/harness/deerflow/runtime/user_context.py](../../backend/packages/harness/deerflow/runtime/user_context.py) |
| 租户上下文 | [backend/packages/harness/deerflow/config/tenant.py](../../backend/packages/harness/deerflow/config/tenant.py) |
| KB 访问控制（参考） | [backend/packages/harness/deerflow/knowledge_base/access_control.py](../../backend/packages/harness/deerflow/knowledge_base/access_control.py) |

### 12.2 RBAC 矩阵（节选）

| 路由 | resource:action | user | tenant_admin | superadmin |
|------|-----------------|------|--------------|------------|
| `GET  /api/threads/{id}` | threads:read（owner_check） | 自己 | 自己 | 全部 |
| `DELETE /api/threads/{id}` | threads:delete（owner_check, require_existing） | 自己 | 自己 | 全部 |
| `POST /api/runs/stream` | runs:create | ✓ | ✓ | ✓ |
| `POST /api/closure/{id}/verify` | closure:verify | ✗ | ✓ | ✓ |
| `POST /api/knowledge-bases` (visibility=public) | knowledge_bases:admin | ✗ | ✗ | ✓ |
| `POST /api/knowledge-bases` (visibility=tenant) | knowledge_bases:write | ✗ | ✓ | ✓ |
| `POST /admin/tenants` | tenants:admin | ✗ | ✗ | ✓ |
| `PUT /admin/tenants/{id}` (basic) | tenants:write | ✗ | 自己 | 全部 |
| `PUT /admin/tenants/{id}/quota` | tenants:admin | ✗ | ✗ | ✓ |
| `PUT /admin/users/{id}/role` | tenants:admin | ✗ | ✗ | ✓ |
| `GET /api/tenants/{id}/agents` (LIST) | agents:read | 自己租户 | 自己租户 | 全部 |
| `POST /api/tenants/{id}/agents` (CREATE) | agents:write | ✗ | 自己租户 | 全部 |

完整矩阵见 `docs/security/rbac-matrix.md`。

### 12.3 Token 主链 Claims Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DeerFlowAccessToken",
  "type": "object",
  "required": ["sub", "ver", "tenant_id", "system_role", "iat", "exp"],
  "properties": {
    "sub": {"type": "string", "description": "user_id"},
    "ver": {"type": "integer", "description": "token_version (revocation)"},
    "tenant_id": {"type": "string"},
    "system_role": {"type": "string", "enum": ["user", "tenant_admin", "superadmin"]},
    "iat": {"type": "integer"},
    "exp": {"type": "integer"}
  }
}
```

### 12.4 Identity Kind 状态机

```
                ┌────────────────────────┐
   request ────►│   AuthMiddleware       │
                └────────────┬───────────┘
                             │
            ┌────────────────┼─────────────────┐
            │                │                 │
       cookie/Bearer    internal token    auth.enabled=False
            │                │                 │
            ▼                ▼                 ▼
       authenticated      internal         anonymous
       id=user.id        id=__internal__   id=default
       role=db.role      role=internal     role=user
       tenant=jwt.tid    tenant=injected   tenant=default
            │                │                 │
            └────────────────┼─────────────────┘
                             │
                  set_current_identity(...)
                             │
                  ContextVar 在子任务 / 后台
                  worker 中通过 with_identity_context
                  显式继承
```

### 12.5 Story → 文件改动矩阵（速查）

| Story | 主要文件 | 测试 |
|-------|----------|------|
| A.0 | `persistence/migrations/versions/003_add_tenant_id_to_runs.py` | `test_runs_migration_backfill.py` |
| A.1 | `auth/roles.py`(新)、`authz.py`、`auth_middleware.py`、`config/auth_config.py` | `test_role_registry.py`、`test_strict_rbac_toggle.py`、`test_require_permission_with_roles.py` |
| A.2 | `auth/dependencies.py` | `test_currentuser_default_role.py` |
| A.3 | `app/gateway/app.py` | `test_prod_auth_required.py` |
| B.1 | `auth/ins_base_role_resolver.py`(新)、`auth/ins_base_provider.py`、`routers/admin.py` | `test_ins_base_role_resolver.py`、`test_admin_user_role.py` |
| B.2 | `runtime/user_context.py`、`runtime/identity.py`(新)、`internal_auth.py`、`persistence/thread_meta/sql.py`、`authz.py` | `test_check_access_default_purge.py`、`test_internal_identity_isolation.py`、`test_runtime_identity_kind_propagation.py` |
| B.3 | `auth/jwt.py`、`auth/jwt_handler.py`(deprecate) | `test_jwt_payload_role.py`、`test_jwt_role_drift.py`、`test_jwt_handler_removed.py` |
| B.4 | `auth/ins_base_provider.py` | `test_ins_base_tenant_repo_required.py` |
| B.5 | `auth/ins_base_provider.py` | `test_ins_base_user_id_consistency.py` |
| B.6 | `scripts/migrate_default_user_threads.py`(新) | `test_default_user_migration_script.py` |
| C.1 | `persistence/run/model.py`、`persistence/run/sql.py`、`routers/thread_runs.py`、`routers/runs.py` | `test_runs_tenant_isolation.py` |
| C.2 | `routers/admin.py` | `test_update_tenant_quota_role_check.py` |
| C.3 | `routers/runs.py` | `test_runs_stateless_decorator.py` |
| C.4 | `routers/tenant_agents.py`、`routers/tenant_mcp_servers.py`、`routers/tenant_connectors.py`、各 service.list_for | `test_tenant_list_visibility.py` |
| C.5 | `tests/security/test_rbac_blackbox.py`(新)、`tests/security/test_thread_cross_user_access.py`(新)、`tests/security/test_internal_token_scope.py`(新) | — |
| D.1 | feature flag 切换（无代码改动） | manual smoke |
| D.2 | `backend/CLAUDE.md`、`README.md`、`docs/AUTH.md`、`docs/security/rbac-matrix.md` | — |
| D.3 | 删除 `_ALL_PERMISSIONS` alias、`auth/jwt_handler.py` | `test_jwt_handler_removed.py` |

---
