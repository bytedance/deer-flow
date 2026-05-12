# 租户自动识别 — Sprint 实施计划

> 创建日期：2026-05-12
> 设计文档：[tenant-auto-detection-design.md](./2026-05-12-tenant-auto-detection-design.md)

## Sprint Overview

```
Sprint Goal: 用户只需输入邮箱和密码即可登录，系统自动识别其所属租户
Duration: 1 week (5 working days)
Team Capacity: 10 SP (假设 1 后端 + 1 前端，各 5 SP/周)
Committed Stories: 7 SP (Phase 1 + Phase 2)
Buffer: 3 SP (30% — 首次涉及认证核心逻辑，预留较高缓冲)
```

---

## Stories

| # | Story | SP | Owner | Dependencies | Day |
|---|-------|----|-------|--------------|-----|
| 1 | 错误码 + AuthProvider 协议扩展 | 0.5 | 后端 | — | D1 |
| 2 | Repository: 新增 `get_users_by_email()`；修复 `get_user_by_email()` | 1 | 后端 | — | D1 |
| 3 | Provider: `authenticate()` 增加自动识别分支 | 2 | 后端 | Story 1-2 |D1-D2|
| 4 | Router: 登录响应增加 `tenant_id`；处理 409 | 1 | 后端 | Story 3 | D2 |
| 5 | 后端单元测试 | 1 | 后端 | Story 1-4 |D2-D3|
| 6 | 前端: 登录成功后读取 `tenant_id` 并存储 | 0.5 | 前端 | Story 4 | D3 |
| 7 | 前端: 处理 409 + 租户选择器 UI | 1 | 前端 | Story 4 | D3-D4|
| — | 集成测试 + 回归验证 | buffer | 全员 | Story 1-7 | D5 |

---

## Story 详细拆解

### Story 1: 错误码 + AuthProvider 协议扩展

**文件**:

- `backend/app/gateway/auth/errors.py` — 新增 `TENANT_SELECTION_REQUIRED` 到 `AuthErrorCode`；`AuthErrorResponse` 增加 `tenants: list[dict] | None = None`
- `backend/app/gateway/auth/providers.py` — 新增 `TenantSelectionRequired` dataclass；更新 `authenticate()` 返回类型

**Acceptance Criteria**:

- `AuthErrorCode.TENANT_SELECTION_REQUIRED = "tenant_selection_required"`
- `AuthErrorResponse` 可携带 `tenants` 字段（optional，仅 409 时使用）
- `TenantSelectionRequired` 是 frozen dataclass，包含 `tenants: list[dict]`
- `AuthProvider.authenticate()` 签名更新为 `-> User | TenantSelectionRequired | None`
- 现有调用方（router 中 `if user is None` 分支）不受影响

**实现要点**:

```python
# errors.py
class AuthErrorCode(StrEnum):
    # ... 现有值 ...
    TENANT_SELECTION_REQUIRED = "tenant_selection_required"

class AuthErrorResponse(BaseModel):
    code: AuthErrorCode
    message: str
    tenants: list[dict] | None = None

# providers.py
from dataclasses import dataclass

@dataclass(frozen=True)
class TenantSelectionRequired:
    tenants: list[dict]

class AuthProvider(ABC):
    @abstractmethod
    async def authenticate(self, credentials: dict) -> "User | TenantSelectionRequired | None":
        raise NotImplementedError
```

---

### Story 2: Repository — `get_users_by_email()` + 修复 `get_user_by_email()`

**文件**:

- `backend/app/gateway/auth/repositories/base.py` — 新增抽象方法
- `backend/app/gateway/auth/repositories/sqlite.py` — 实现 + 修复

**Acceptance Criteria**:

- `get_users_by_email(email)` 返回 `list[User]`，查询所有 tenant 下匹配该邮箱的用户
- 空结果返回 `[]`，不抛异常
- 使用参数化查询（已有模式，无 SQL 注入风险）
- `get_user_by_email(email)` 修复为使用 `.first()` 替代 `scalar_one_or_none()`，避免多租户下 `MultipleResultsFound` 崩溃

**实现要点**:

```python
# base.py 新增
@abstractmethod
async def get_users_by_email(self, email: str) -> list[User]:
    raise NotImplementedError

# sqlite.py 新增
async def get_users_by_email(self, email: str) -> list[User]:
    stmt = select(UserRow).where(UserRow.email == email)
    async with self._sf() as session:
        result = await session.execute(stmt)
        return [self._row_to_user(row) for row in result.scalars().all()]

# sqlite.py 修复
async def get_user_by_email(self, email: str) -> User | None:
    stmt = select(UserRow).where(UserRow.email == email).limit(1)
    async with self._sf() as session:
        result = await session.execute(stmt)
        row = result.scalars().first()
        return self._row_to_user(row) if row is not None else None
```

---

### Story 3: Provider — 自动识别分支

**文件**: `backend/app/gateway/auth/local_provider.py`

**Acceptance Criteria**:

- 当 `tenant_id == "default"` 或缺失时，走自动识别逻辑
- 当 `tenant_id` 为具体值（非 "default"）时，保持原有精确匹配逻辑不变
- 单用户匹配：验证密码后直接返回该用户（含 rehash）
- 多用户匹配：逐个验证密码（最多 10 个，超出直接返回 `TenantSelectionRequired`）
  - 仅 1 个密码匹配 → 返回该用户（含 rehash）
  - 多个密码匹配 → 返回 `TenantSelectionRequired`（不 rehash）
  - 0 个密码匹配 → 返回 None
- 0 用户匹配：返回 None

**新增异常**:

```python
# 已在 Story 1 中定义于 providers.py
@dataclass(frozen=True)
class TenantSelectionRequired:
    tenants: list[dict]  # [{"tenant_id": "zm", "email": "user@example.com"}, ...]
```

**核心逻辑变更** (`authenticate` 方法):

```python
_MAX_TENANT_VERIFY = 10

async def authenticate(self, credentials: dict) -> User | TenantSelectionRequired | None:
    email = credentials.get("email")
    password = credentials.get("password")
    tenant_id = credentials.get("tenant_id", "default")

    if not email or not password:
        return None

    # 显式指定租户 → 原有逻辑
    if tenant_id != "default":
        user = await self._repo.get_user_by_email_and_tenant(email, tenant_id)
        if user is None or user.password_hash is None:
            return None
        if not await verify_password_async(password, user.password_hash):
            return None
        await self._maybe_rehash(user, password)
        return user

    # 自动识别：按 email 查所有租户
    users = await self._repo.get_users_by_email(email)
    if not users:
        return None

    # 超出上限 → 直接要求选择
    if len(users) > _MAX_TENANT_VERIFY:
        return TenantSelectionRequired([
            {"tenant_id": u.tenant_id, "email": u.email} for u in users
        ])

    # 单用户快速路径
    if len(users) == 1:
        user = users[0]
        if user.password_hash and await verify_password_async(password, user.password_hash):
            await self._maybe_rehash(user, password)
            return user
        return None

    # 多用户：逐个验证密码
    matched = []
    for u in users:
        if u.password_hash and await verify_password_async(password, u.password_hash):
            matched.append(u)

    if len(matched) == 0:
        return None
    if len(matched) == 1:
        await self._maybe_rehash(matched[0], password)
        return matched[0]

    # 多个密码匹配 → 需要用户选择（不 rehash）
    return TenantSelectionRequired([
        {"tenant_id": u.tenant_id, "email": u.email} for u in matched
    ])

async def _maybe_rehash(self, user: User, password: str) -> None:
    """Opportunistic password rehash."""
    if needs_rehash(user.password_hash):
        try:
            user.password_hash = await hash_password_async(password)
            await self._repo.update_user(user)
        except Exception:
            logger.warning("Failed to rehash password for user %s", user.email, exc_info=True)
```

---

### Story 4: Router — 登录响应增强

**文件**: `backend/app/gateway/routers/auth.py`

**Acceptance Criteria**:

- `LoginResponse` 新增 `tenant_id: str | None = None` 字段
- 登录成功时返回用户的 `tenant_id`
- 检测 `authenticate()` 返回 `TenantSelectionRequired`，返回 HTTP 409
- 409 响应使用 `AuthErrorResponse` 格式（含 `tenants` 字段）
- 安全审计日志：自动识别成功和 409 场景均记录 INFO 级别日志

**变更**:

```python
from app.gateway.auth.providers import TenantSelectionRequired

class LoginResponse(BaseModel):
    expires_in: int
    needs_setup: bool = False
    tenant_id: str | None = None  # 新增

# login_local 端点中：
result = await get_local_provider().authenticate({...})

if isinstance(result, TenantSelectionRequired):
    logger.info("Tenant selection required for email=%s, tenants=%d", form_data.username, len(result.tenants))
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=AuthErrorResponse(
            code=AuthErrorCode.TENANT_SELECTION_REQUIRED,
            message="Multiple tenants found for this account. Please select one.",
            tenants=result.tenants,
        ).model_dump(),
    )

if result is None:
    _record_login_failure(client_ip)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, ...)

user = result
_record_login_success(client_ip)
logger.info("Auto-detected tenant=%s for email=%s", user.tenant_id, user.email)
# ... 签发 token ...

return LoginResponse(
    expires_in=...,
    needs_setup=user.needs_setup,
    tenant_id=user.tenant_id,
)
```

---

### Story 5: 后端单元测试

**文件**: `backend/tests/test_auth_tenant_detection.py`

**测试用例**:

1. 单租户自动识别 — email 仅存在于一个租户，密码正确 → 登录成功，返回正确 tenant_id
2. 单租户自动识别 — 密码错误 → 返回 None（401）
3. 多租户单密码匹配 — 同一 email 在两个租户，仅一个密码匹配 → 登录成功
4. 多租户多密码匹配 — 同一 email 在两个租户，密码相同 → 返回 `TenantSelectionRequired`
5. 显式指定租户 — `tenant_id != "default"` → 走原有逻辑，不受影响
6. 邮箱不存在 — 返回 None（401）
7. Repository `get_users_by_email` — 返回正确结果
8. `get_user_by_email` 修复 — 多租户下不崩溃，返回第一个匹配
9. 超出 10 用户上限 — 直接返回 `TenantSelectionRequired`（不验证密码）
10. Rehash 仅对单匹配胜出者执行 — mock `needs_rehash` 验证

---

### Story 6: 前端 — 登录成功后同步 tenant_id

**文件**: `frontend/src/app/(auth)/login/page.tsx`

**Acceptance Criteria**:

- 登录成功后，从 `/api/v1/auth/me` 响应中读取 `tenant_id`（已有逻辑，line 123-129）
- 确认 `LoginResponse` 中新增的 `tenant_id` 也被处理（可选优化：直接从登录响应读取，减少一次 /me 请求）

**当前状态**: 前端已在登录成功后调用 `/api/v1/auth/me` 并执行 `setCurrentTenantId(userData.tenant_id)`。此 Story 主要是验证现有逻辑在自动识别场景下仍然正确工作，无需大改。

---

### Story 7: 前端 — 409 处理 + 租户选择器

**文件**: `frontend/src/app/(auth)/login/page.tsx`

**Acceptance Criteria**:

- 当登录返回 409 时，解析 `detail.tenants` 列表
- 展示内联租户选择器（不跳转新页面）
- 用户选择后，手动注入 `X-DeerFlow-Tenant` header 重新提交登录（登录页用 raw `fetch`，不能依赖 `fetchGateway`）
- 选择器 UI 简洁：列出 tenant_id，用户点击即可

**实现要点**:

```typescript
// 新增状态
const [tenantChoices, setTenantChoices] = useState<{tenant_id: string; email: string}[]>([]);

// handleSubmit 中处理 409
if (res.status === 409) {
  const data = await res.json();
  if (data.detail?.code === "tenant_selection_required") {
    setTenantChoices(data.detail.tenants);
    setError("");
    return;
  }
}

// 选择租户后重新登录 — 必须手动注入 header
const handleTenantSelect = async (tenantId: string) => {
  setLoading(true);
  setTenantChoices([]);
  const res = await fetch("/api/v1/auth/login/local", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      "X-DeerFlow-Tenant": tenantId,  // 手动注入，raw fetch 不走 getTenantHeaders()
    },
    body: `username=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`,
    credentials: "include",
  });
  if (res.ok) {
    setCurrentTenantId(tenantId);
    router.push(redirectPath);
  } else {
    setError("Login failed. Please try again.");
  }
  setLoading(false);
};
```

**UI**: 在 error 区域下方展示按钮列表，每个按钮对应一个可选租户。当 `tenantChoices.length > 0` 时隐藏登录表单，展示选择器。

---

## Dependencies Map

```text
Story 1 (errors + protocol)  Story 2 (repo methods)
         \                      /
          └──── Story 3 (provider logic) ────┐
                                             │
                                    Story 4 (router response)
                                    /        |        \
                        Story 5 (tests)  Story 6    Story 7
                                        (verify)  (409 UI)
```

**Critical Path**: Story 1+2 → 3 → 4 → 7

---

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| bcrypt 多用户验证性能 | 同一邮箱跨 N 个租户时需验证 N 次 bcrypt（~100ms/次） | 低（实际 N ≤ 2） | 设置上限 10 个用户，超出直接返回 409 |
| 邮箱枚举攻击 | 攻击者可通过 409 判断邮箱是否存在 | 中 | 409 仅在密码验证通过后返回；未通过时统一返回 401 |
| `AuthProvider` 协议变更影响 | 现有调用方未处理新返回类型 | 低 | 使用 result type（非异常），`None` 分支不变；IM channels 不调用此方法 |
| `get_user_by_email` 崩溃 | 多租户数据下 `scalar_one_or_none()` 抛异常 | 高 | Story 2 修复为 `.first()`，测试覆盖 |
| 前端 409 重试 header 遗漏 | 登录页用 raw `fetch`，重试时忘记注入 header | 中 | Story 7 明确要求手动注入，不依赖 `fetchGateway` |
| 现有 E2E 测试回归 | 登录响应 schema 变更可能破坏现有测试 | 中 | `tenant_id` 字段设为 optional（`None`），向后兼容 |
| 知识集中 — 认证模块仅一人熟悉 | 如果该人请假，进度受阻 | 低 | Sprint 内完成 code review + 文档更新 |

---

## Definition of Done

- [ ] 所有 Story 代码合入 main
- [ ] `make test` 全部通过（后端）
- [ ] `pnpm check` 全部通过（前端）
- [ ] 手动验证场景：
  - 不带 `?tenant=` 参数，用 `yh@shenguyun.com` 登录 → 自动识别为 `zm` 租户
  - 带 `?tenant=zm` 参数登录 → 原有逻辑不受影响
  - 同一邮箱存在于多个租户 → 展示选择器，选择后成功登录
  - `get_user_by_email` 在多租户数据下不崩溃
- [ ] Code review 通过
- [ ] 设计文档状态更新为 "Implemented"

---

## Daily Plan

| Day | 后端 | 前端 |
|-----|------|------|
| D1 | Story 1（协议扩展）+ Story 2（repo）+ Story 3 开始 | 阅读设计文档，准备 UI 方案 |
| D2 | Story 3 完成 + Story 4（router） | Story 5 开始（可并行写测试） |
| D3 | Story 5 完成（测试） | Story 6 验证 + Story 7 开始 |
| D4 | Code review + 修复 | Story 7 完成 |
| D5 | 集成测试 + 回归验证 | 集成测试 + 回归验证 |
