# 角色路由与技能市场 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员进入独立运营后台，普通用户进入隔离的个人工作区，并可安装管理员发布的市场技能。

**Architecture:** 基于认证会话的 `system_role` 在服务端完成入口分流和路由保护；用户侧配置统一以认证用户 ID 作为所有者。市场技能作为平台公共发行版持久化，安装时写入现有的用户级技能存储，避免共享可写状态。

**Tech Stack:** Next.js App Router、React、FastAPI、SQLAlchemy/Alembic、现有 `UserScopedSkillStorage`、Rstest、pytest。

## Global Constraints

- 一个注册用户就是一个独立租户；用户侧接口必须从认证会话取得用户 ID。
- 记忆、集成、工具、技能及后续用户配置不能跨用户读取、写入或以客户端租户 ID 授权。
- 管理员只访问运营后台；普通用户不能访问运营后台。
- 不提交、推送或部署本次实施产生的改动，除非用户再次明确要求。

---

### Task 1: 服务端角色入口与路由保护

**Files:**
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/app/workspace/page.tsx`
- Modify: `frontend/src/app/workspace/layout.tsx`
- Create: `frontend/src/app/workspace/admin/layout.tsx`
- Create: `frontend/tests/unit/core/auth/role-routing.test.ts`

**Interfaces:**
- Consumes: `getServerSideUser(): AuthResult` and `User.system_role`.
- Produces: `getWorkspaceHomePath(role): "/workspace/admin" | "/workspace/chats/new"` and protected redirects.

- [ ] **Step 1: Write failing role-routing tests**

```ts
expect(getWorkspaceHomePath("admin")).toBe("/workspace/admin");
expect(getWorkspaceHomePath("user")).toBe("/workspace/chats/new");
```

- [ ] **Step 2: Run the focused test and confirm it fails because the helper does not exist.**

Run: `frontend/node_modules/.bin/rstest run tests/unit/core/auth/role-routing.test.ts --project node`

- [ ] **Step 3: Add the role-to-home helper and use it in the root/workspace server redirects.**

```ts
export function getWorkspaceHomePath(role: User["system_role"]) {
  return role === "admin" ? "/workspace/admin" : "/workspace/chats/new";
}
```

- [ ] **Step 4: Add an admin route layout that redirects non-admins and a workspace guard that redirects admins away from user-only routes.**

```ts
if (result.user.system_role !== "admin") redirect("/workspace/chats/new");
```

- [ ] **Step 5: Run the focused test and frontend type check.**

Run: `frontend/node_modules/.bin/rstest run tests/unit/core/auth/role-routing.test.ts --project node && frontend/node_modules/.bin/tsc --noEmit`

### Task 2: 角色化导航与设置入口

**Files:**
- Modify: `frontend/src/components/workspace/workspace-sidebar.tsx`
- Modify: `frontend/src/components/workspace/workspace-nav-menu.tsx`
- Modify: `frontend/src/components/workspace/settings/settings-dialog.tsx`
- Modify: `frontend/src/components/workspace/settings/skill-settings-page.tsx`
- Create: `frontend/tests/unit/components/workspace/settings-dialog.dom.test.tsx`

**Interfaces:**
- Consumes: `useAuth().user.system_role`.
- Produces: admin-only navigation, user-only settings sections, expanded personal skill rows.

- [ ] **Step 1: Write DOM tests asserting the “关于” tab is absent and admin navigation omits user-workspace links.**

```tsx
expect(screen.queryByText("关于")).toBeNull();
expect(screen.queryByText("新对话")).toBeNull();
```

- [ ] **Step 2: Run the DOM test and confirm it fails against current navigation.**

Run: `frontend/node_modules/.bin/rstest run tests/unit/components/workspace/settings-dialog.dom.test.tsx --project dom`

- [ ] **Step 3: Filter settings sections by role, remove the About section, and hide chat/settings links for administrators.**

```ts
const sections = user?.system_role === "admin" ? [] : userSettingsSections;
```

- [ ] **Step 4: Replace clipped skill rows with a detail/expand control showing full description, origin, version and installed state.**

```tsx
<Collapsible><CollapsibleTrigger>查看详情</CollapsibleTrigger><CollapsibleContent>{skill.description}</CollapsibleContent></Collapsible>
```

- [ ] **Step 5: Run the DOM test, ESLint, and Prettier checks.**

Run: `frontend/node_modules/.bin/rstest run tests/unit/components/workspace/settings-dialog.dom.test.tsx --project dom && frontend/node_modules/.bin/eslint src/components/workspace/settings/settings-dialog.tsx src/components/workspace/settings/skill-settings-page.tsx`

### Task 3: 租户所有者校验审计

**Files:**
- Modify: `backend/app/gateway/routers/memory.py`
- Modify: `backend/app/gateway/routers/skills.py`
- Modify: `backend/app/gateway/routers/mcp.py`
- Modify: `backend/app/gateway/routers/integrations.py` (if present)
- Create: `backend/tests/test_tenant_owner_scoping.py`

**Interfaces:**
- Consumes: `request.state.user.id` and trusted internal owner handling.
- Produces: `resolve_current_tenant_id(request) -> str` used for user-side storage calls.

- [ ] **Step 1: Write tests that call each user-side resolver with two users and assert the second user cannot see the first user’s memory/skill/tool/integration IDs.**

```py
assert resolve_current_tenant_id(request_for("user-a")) == "user-a"
assert list_user_resources("user-b") == []
```

- [ ] **Step 2: Run the test and capture any router that still falls back to a global owner.**

Run: `UV_CACHE_DIR=/private/tmp/deerflow-billing-uv-cache uv run pytest tests/test_tenant_owner_scoping.py -q`

- [ ] **Step 3: Centralize authenticated-user resolution and apply it to memory, custom skills, MCP/tools and integrations. Do not accept a client-provided user ID.**

```py
user = request.state.user
if user is None: raise HTTPException(status_code=401, detail="Authentication required")
return str(user.id)
```

- [ ] **Step 4: Run focused tests plus existing memory and skills tests.**

Run: `UV_CACHE_DIR=/private/tmp/deerflow-billing-uv-cache uv run pytest tests/test_tenant_owner_scoping.py tests/test_memory_router.py tests/test_skills_router.py -q`

### Task 4: 市场技能持久化与管理员 API

**Files:**
- Create: `backend/packages/harness/deerflow/persistence/skill_market/model.py`
- Create: `backend/packages/harness/deerflow/persistence/skill_market/service.py`
- Create: `backend/packages/harness/deerflow/persistence/migrations/versions/0012_skill_market.py`
- Create: `backend/app/gateway/routers/skill_market.py`
- Modify: `backend/app/gateway/app.py`
- Create: `backend/tests/test_skill_market.py`

**Interfaces:**
- Produces: `SkillMarketService.publish(...)`, `list_published()`, `install_for_user(user_id, skill_id)`, and `/api/admin/skill-market`, `/api/skill-market` endpoints.

- [ ] **Step 1: Write failing API tests for admin-only publication, public published listing, and tenant-specific installation.**

```py
response = client.post("/api/admin/skill-market", json=payload, headers=admin_headers)
assert response.status_code == 201
assert client.post(f"/api/skill-market/{skill_id}/install", headers=user_headers).status_code == 201
```

- [ ] **Step 2: Run the focused test and confirm the routes/tables are absent.**

Run: `UV_CACHE_DIR=/private/tmp/deerflow-billing-uv-cache uv run pytest tests/test_skill_market.py -q`

- [ ] **Step 3: Add immutable market-release records and installation records with unique `(user_id, market_skill_id)` ownership.**

```py
UniqueConstraint("user_id", "market_skill_id", name="uq_user_market_skill")
```

- [ ] **Step 4: Implement administrator create/update/publish/unpublish routes and user list/install/update/remove routes; installation writes a user-owned skill copy through `get_or_new_user_skill_storage(user_id)`.**

- [ ] **Step 5: Run focused API tests and migration model checks.**

Run: `UV_CACHE_DIR=/private/tmp/deerflow-billing-uv-cache uv run pytest tests/test_skill_market.py -q`

### Task 5: 市场管理与普通用户安装界面

**Files:**
- Modify: `frontend/src/app/workspace/admin/page.tsx`
- Create: `frontend/src/core/skills/market-api.ts`
- Create: `frontend/src/components/workspace/settings/skill-market-page.tsx`
- Modify: `frontend/src/components/workspace/settings/settings-dialog.tsx`
- Create: `frontend/tests/unit/core/skills/market-api.test.ts`
- Create: `frontend/tests/unit/components/workspace/settings/skill-market-page.dom.test.tsx`

**Interfaces:**
- Consumes: `GET /api/skill-market`, `POST /api/skill-market/{id}/install`, admin market CRUD routes.
- Produces: role-gated market management and an installable user skill catalog.

- [ ] **Step 1: Write failing API-client and DOM tests for published-skill rendering, full description expansion and the install action.**

```tsx
expect(await screen.findByText("安装到我的技能")).toBeVisible();
expect(screen.getByText("完整技能说明")).toBeVisible();
```

- [ ] **Step 2: Run tests to confirm the market UI is absent.**

Run: `frontend/node_modules/.bin/rstest run tests/unit/core/skills/market-api.test.ts tests/unit/components/workspace/settings/skill-market-page.dom.test.tsx`

- [ ] **Step 3: Add admin market publishing controls and a user settings tab that loads published releases and installs into the current user’s account.**

- [ ] **Step 4: Show installed version and an explicit “更新到最新版本” action; never overwrite a user copy without that action.**

```ts
await installMarketSkill(skill.id, { mode: "update" });
```

- [ ] **Step 5: Run tests, type check, ESLint, Prettier and backend market tests.**

Run: `frontend/node_modules/.bin/rstest run tests/unit/core/skills/market-api.test.ts tests/unit/components/workspace/settings/skill-market-page.dom.test.tsx && frontend/node_modules/.bin/tsc --noEmit && UV_CACHE_DIR=/private/tmp/deerflow-billing-uv-cache uv run pytest backend/tests/test_skill_market.py -q`
