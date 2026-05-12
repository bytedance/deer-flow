# Phase 2 Implementation Plan: 二期收尾

## Context

Phase 1 已完成按当前用户所属租户的收口，但使用了过渡规则（`role == "admin" and tenant_id == "default"`）。Phase 2 将完成三件事：

1. **角色模型拆分**：`admin/user` → `superadmin / tenant_admin / user`
2. **usage 记录补 `user_id`**：UsageRecord 增加用户维度
3. **audit log 补 `actor_user_id`**：AuditLogEntry 增加操作人维度

## 角色流转

| Phase 1 | Phase 2 |
|---------|---------|
| admin + tenant_id="default" | superadmin |
| admin + tenant_id="acme" | tenant_admin |
| user | user (不变) |
| member (API key) | member (不变) |

---

## Task A: 角色模型拆分

### A1. Pydantic 模型 + ORM 注释
- `backend/app/gateway/auth/models.py:25` — `User.system_role: Literal["admin", "user"]` → `Literal["superadmin", "tenant_admin", "user"]`
- `backend/app/gateway/auth/models.py:45` — `UserResponse.system_role` 同上
- `backend/packages/harness/deerflow/persistence/user/model.py:31` — 更新注释

### A2. 依赖层
- `backend/app/gateway/auth/dependencies.py:100` — 默认用户 `role="admin"` → `role="superadmin"`
- `backend/app/gateway/auth/dependencies.py:146` — `require_admin` 检查改为 `user.role not in ("superadmin", "tenant_admin")`
- `backend/app/gateway/auth/local_provider.py:72` — `create_user` docstring 更新

### A3. Admin Router 作用域规则
- `backend/app/gateway/routers/admin.py:83` — `_is_system_admin` → `user.role == "superadmin"`（去掉 tenant_id 条件）
- `backend/app/gateway/routers/admin.py:345-353` — `delete_tenant_user` 角色检查更新

### A4. Auth 路由
- `backend/app/gateway/routers/auth.py:449` — initialize_admin → `system_role="superadmin"`

### A5. 启动迁移
- `backend/app/gateway/app.py:136` — orphan thread migration 查询更新
- `backend/app/gateway/app.py` — 新增 role 迁移：已有 `"admin"` 用户按 tenant_id 更新
- `backend/app/gateway/auth/reset_admin.py:52` — 查询更新

### A6-7. 前端类型+逻辑
- `frontend/src/core/auth/types.ts:8` — `z.enum(["superadmin", "tenant_admin", "user"])`
- `frontend/src/core/admin/scope.ts:3` — `isSystemAdminView` → `user?.system_role === "superadmin"`
- `frontend/src/app/admin/layout.tsx:19` — 权限检查更新
- `frontend/src/components/workspace/workspace-header.tsx` — badge 显示条件

### A8-9. 测试更新
- 后端：`test_admin_router.py`, `test_auth_type_system.py`, `test_auth.py`
- 前端：`admin-sidebar.test.ts`, `admin-tenants-page.test.ts`, `admin-logs-page.test.ts`, `workspace-header.test.ts`

---

## Task B: UsageRecord 补 `user_id`

### B1. 数据模型
- `backend/packages/harness/deerflow/cost/storage.py` — dataclass 增加 `user_id: str | None = None`，to_dict/from_dict 同步

### B2. PostgreSQL 存储
- `backend/packages/harness/deerflow/cost/pg_storage.py` — CREATE TABLE / INSERT / SELECT 加 `user_id` 列

### B3. 测试更新
- `test_cost_storage.py`, `test_cost_budget.py`, `test_admin_router.py` — 所有 UsageRecord 构造增加 `user_id`

---

## Task C: AuditLogEntry 补 `actor_user_id`

### C1. 数据模型
- `backend/packages/harness/deerflow/content_safety/log_storage.py` — dataclass 增加 `actor_user_id: str | None = None`，to_dict/from_dict 同步

### C2. 中间件传递
- `input_guard_middleware.py` — `_log_audit` 加参数，用 `get_effective_user_id()` 获取 user_id
- `output_guard_middleware.py` — 同上

### C3. 测试更新
- `test_admin_router.py` — `_make_audit_entry()` 增加参数

---

## 实施顺序

1. Task C（AuditLogEntry）— 最独立
2. Task B（UsageRecord）— 独立数据模型变更
3. Task A（角色拆分）— 影响面最广

## 验证

- 后端：`PYTHONPATH=. uv run pytest tests/test_admin_router.py tests/test_auth_type_system.py tests/test_cost_storage.py tests/test_auth.py -q`
- 前端：`npx vitest run tests/unit/components/admin/`
- 全量：`make test` + `npx vitest run`
