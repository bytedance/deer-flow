# 合并登录与租户管理

## Context

当前登录系统和租户管理系统完全独立运行：

- **User 模型无 `tenant_id` 字段** — 用户是全局的，不属于任何租户
- **JWT Token 不含租户信息** — token 仅包含 `sub=user_id` 和 `ver=token_version`
- **登录后租户来自 HTTP Header** — `X-DeerFlow-Tenant` header 决定租户上下文，默认为 `"default"`
- **租户管理的 `user_count` 硬编码为 1** — 没有真正的用户-租户关联

目标：让用户归属于租户，登录自动确定租户上下文，租户管理员能管理自己租户内的用户。

---

## 实施计划

### 1. 后端 — User 模型添加 tenant_id

**修改 `backend/packages/harness/deerflow/persistence/user/model.py`**:
- `UserRow` 添加字段 `tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default", index=True)`
- 添加复合唯一索引 `(email, tenant_id)` — 同邮箱可属于不同租户

**修改 `backend/app/gateway/auth/models.py`**:
- `User` Pydantic 模型添加 `tenant_id: str = Field(default="default")`
- `UserResponse` 添加 `tenant_id: str`

**修改 `backend/app/gateway/auth/repositories/sqlite.py`**:
- `_row_to_user()` 和 `_user_to_row()` 包含 `tenant_id`
- `update_user()` 更新 `row.tenant_id`

### 2. 后端 — JWT Token 添加 tenant_id

**修改 `backend/app/gateway/auth/jwt.py`**:
- `TokenPayload` 添加 `tenant_id: str = "default"`
- `create_access_token()` 接受 `tenant_id` 参数，写入 payload
- `decode_token()` 解析 `tenant_id`

### 3. 后端 — Auth endpoints 租户感知

**修改 `backend/app/gateway/auth/local_provider.py`**:
- `create_user()` 接受 `tenant_id` 参数
- 新增 `count_users_by_tenant(tenant_id)` 和 `list_users(tenant_id, limit, offset)` 
- `authenticate()` 按 `(email, tenant_id)` 查找用户（从 credentials 中获取 tenant_id）

**修改 `backend/app/gateway/auth/repositories/base.py`**:
- `UserRepository` 抽象接口新增：
  - `get_user_by_email_and_tenant(email, tenant_id)` 
  - `count_users(tenant_id=None)`
  - `list_users(tenant_id, limit, offset)`

**修改 `backend/app/gateway/auth/repositories/sqlite.py`**:
- 实现新增的抽象方法

**修改 `backend/app/gateway/routers/auth.py`**:
- `POST /login/local` — 从 header `X-DeerFlow-Tenant` 获取 tenant_id，传入 `authenticate()`；JWT 携带 tenant_id
- `POST /register` — 从 header 获取 tenant_id 或使用 body 中的 tenant_id，传入 `create_user()`
- `POST /initialize` — 自动确保 "default" 租户存在，admin 创建在 "default" 租户下
- `GET /me` — 返回 `tenant_id`
- `POST /change-password` — 不变，但 User 对象已含 tenant_id

**修改 `backend/app/gateway/deps.py`**:
- `get_current_user_from_request()` 从 JWT payload 取出 tenant_id 并通过 `set_current_tenant_id()` 设置 ContextVar
- 不再仅依赖 `X-DeerFlow-Tenant` header

### 4. 后端 — Auth Middleware 更新

**修改 `backend/app/gateway/auth/middleware.py`** (`create_auth_middleware`):
- Cookie-based auth: JWT 验证通过后，用 token 中的 `tenant_id` 设置 ContextVar（替代 header 中的值）
- Bearer JWT: 从 payload 读取 `tenant_id` 设置 ContextVar
- API Key: 保持现有逻辑（从 header 获取）

### 5. 后端 — Admin 租户用户管理

**修改 `backend/app/gateway/routers/admin.py`**:
- `_build_tenant_summary()` — 使用 `provider.count_users_by_tenant()` 获取真实 user_count
- 新增端点：
  - `GET /api/admin/tenants/{tenant_id}/users` — 列出租户内用户
  - `DELETE /api/admin/tenants/{tenant_id}/users/{user_id}` — 从租户移除用户

### 6. 前端 — 类型和 API 更新

**修改 `frontend/src/core/auth/types.ts`**:
- `userSchema` 添加 `tenant_id: z.string()` 和 `tenant_name: z.string().optional()`
- `User` 类型更新

**修改 `frontend/src/core/admin/api.ts` 和 `types.ts`**:
- 新增 `listTenantUsers(tenantId)` — GET /api/admin/tenants/{id}/users
- 新增 `deleteTenantUser(tenantId, userId)` — DELETE
- 新增 `TenantUser` 类型

### 7. 前端 — Admin 租户管理页

**修改 `frontend/src/app/admin/tenants/page.tsx`**:
- user_count 变为真实数据
- 添加"管理用户"按钮 → 弹出用户列表对话框
- 用户列表支持删除

### 8. 数据库迁移

- `UserRow.tenant_id` 添加列（SQLite ALTER TABLE ADD COLUMN）
- 现有用户自动迁移到 `tenant_id = "default"`
- 唯一索引：从 `(email)` 变为 `(email, tenant_id)`

---

## 关键文件变更清单

| 操作 | 文件 |
|------|------|
| 修改 | `backend/packages/harness/deerflow/persistence/user/model.py` |
| 修改 | `backend/app/gateway/auth/models.py` |
| 修改 | `backend/app/gateway/auth/jwt.py` |
| 修改 | `backend/app/gateway/auth/local_provider.py` |
| 修改 | `backend/app/gateway/auth/repositories/base.py` |
| 修改 | `backend/app/gateway/auth/repositories/sqlite.py` |
| 修改 | `backend/app/gateway/routers/auth.py` |
| 修改 | `backend/app/gateway/auth/middleware.py` |
| 修改 | `backend/app/gateway/deps.py` |
| 修改 | `backend/app/gateway/routers/admin.py` |
| 修改 | `frontend/src/core/auth/types.ts` |
| 修改 | `frontend/src/core/admin/api.ts` |
| 修改 | `frontend/src/core/admin/types.ts` |
| 修改 | `frontend/src/app/admin/tenants/page.tsx` |

## 验证方式

1. **后端测试**: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_auth.py tests/test_auth_config.py tests/test_auth_jwt.py tests/test_auth_middleware.py tests/test_admin_router.py -v`
2. **前端类型检查**: `cd frontend && pnpm typecheck`
3. **端到端验证**:
   - 启动 gateway，访问 `/setup` 创建 admin → 自动创建 "default" 租户
   - 登录 admin → JWT 含 `tenant_id: "default"`
   - Admin 面板 → 租户列表显示 user_count=1
   - 创建新租户 → 用户可在该租户下注册
   - 同邮箱可在不同租户注册
