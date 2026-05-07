# Admin 页面与登录用户关联改造计划

**目标：** 让 `/admin` 下的仪表盘、租户管理、用量报表、日志，真正与当前登录用户关联；一期先完成“按当前用户所属租户收口”，杜绝跨租户越权；二期再补“按具体用户本人”的 usage/log 追踪。

**现状：**
- 前端四个页面共用 admin 导航，但数据接口仍是全局 `getAdmin*` 查询。
- 后端 `backend/app/gateway/routers/admin.py` 只校验 `require_admin`，没有把当前登录用户转换成实际的数据范围。
- `system_role` 目前只有 `admin | user`，还没有显式的 `superadmin` / `tenant_admin` 角色拆分。

**实施假设：**
- 在显式 `superadmin` 角色落地前，保留一个过渡规则：
  - `tenant_id == "default"` 的管理员继续视为“系统管理员”，保留全局视角。
  - 其他租户的管理员按自己的 `tenant_id` 收口，只能查看和管理本租户数据。
- 一期不修改 usage / audit log 的底层存储结构，只做租户级关联；用户级关联放到二期。

**技术范围：**
- Backend: FastAPI admin router、认证上下文、租户范围校验
- Frontend: `/admin` 四页、admin 侧边栏、admin API 类型与交互
- Testing: 后端权限测试、前端 admin 区域单元测试、关键回归验证

---

### Task 1: 固化后台作用域规则

**Files:**
- Modify: `backend/app/gateway/routers/admin.py`
- Modify: `backend/tests/test_admin_router.py`

**Step 1: 先写失败用例**

补充测试覆盖：
- 非 `default` 租户管理员访问 `/api/admin/stats` 时，只返回自己租户的统计
- `/api/admin/tenants` 只返回当前租户
- `/api/admin/usage` 只返回当前租户记录
- `/api/admin/logs` 默认只查当前租户；手工传其他 `tenant_id` 时拒绝
- 非系统管理员不能创建/删除其他租户，不能管理其他租户用户

**Step 2: 实现作用域辅助方法**

在 admin router 中增加统一的“当前 admin 作用域”判断，至少包含：
- 是否为系统级管理员
- 当前生效的 `tenant_id`
- 跨租户访问时的拒绝逻辑

**Step 3: 收口四类数据接口**

让以下接口都经过统一作用域判断：
- `/stats`
- `/tenants`
- `/usage`
- `/logs`

**Step 4: 收口租户操作接口**

调整以下接口权限：
- 系统管理员：保留全局租户 CRUD 与跨租户用户管理
- 普通租户管理员：只能查看/更新自己租户，只能管理自己租户用户，不能创建/删除租户

**Step 5: 运行针对性测试**

Run: `python -m pytest backend/tests/test_admin_router.py backend/tests/test_auth_type_system.py -q`

---

### Task 2: 让前端 admin 四页进入“当前账号 / 当前租户”视角

**Files:**
- Modify: `frontend/src/components/admin/admin-sidebar.tsx`
- Modify: `frontend/src/app/admin/page.tsx`
- Modify: `frontend/src/app/admin/tenants/page.tsx`
- Modify: `frontend/src/app/admin/usage/page.tsx`
- Modify: `frontend/src/app/admin/logs/page.tsx`
- Modify: `frontend/src/core/i18n/locales/types.ts`
- Modify: `frontend/src/core/i18n/locales/zh-CN.ts`
- Modify: `frontend/src/core/i18n/locales/en-US.ts`

**Step 1: 展示当前登录账号与租户信息**

在 admin 侧边栏和页面顶部明确展示：
- 当前账号邮箱
- 当前角色
- 当前租户 ID

**Step 2: 调整非系统管理员的交互**

对非系统管理员收口 UI：
- 租户页隐藏“创建租户”“删除租户”
- 日志页隐藏手工切换租户输入
- 页面提示当前看到的是“当前租户范围”的数据

**Step 3: 保持系统管理员全局视图**

对于 `default` 租户管理员，保留原有全局管理入口，但页面文案需要明确“当前为全局视图”。

**Step 4: 确保文案可国际化**

新增必要的 i18n key，不在组件中硬编码说明文字。

---

### Task 3: 补前端回归测试

**Files:**
- Modify: `frontend/tests/unit/components/admin/admin-sidebar.test.ts`
- Create or modify: `frontend/tests/unit/components/admin/*.test.tsx`

**Step 1: 覆盖账号与租户展示**

验证 admin 侧边栏能显示：
- 邮箱
- 角色
- 当前租户

**Step 2: 覆盖租户作用域 UI**

验证：
- 非系统管理员看不到“创建租户”入口
- 系统管理员仍能看到全局管理入口
- 日志页在非系统管理员场景下不暴露租户切换输入

**Step 3: 运行前端测试**

Run: `npx.cmd vitest run frontend/tests/unit/components/admin/admin-sidebar.test.ts frontend/tests/unit/core/admin/api.test.ts`

---

### Task 4: 验证与收尾

**Step 1: 回归关键权限路径**

至少验证：
- 同为 admin，A 租户登录后无法看到 B 租户 stats / usage / logs / users
- `default` 租户管理员仍能访问全局视图

**Step 2: 回归 UI 体验**

确认 `/admin` 四页都能明确体现当前账号范围，不再像“未绑定登录用户的全局后台”。

**Step 3: 记录剩余二期事项**

二期继续推进：
- usage 记录补 `user_id`
- audit log 补 `actor_user_id`
- 角色模型拆分为 `superadmin / tenant_admin / user`
