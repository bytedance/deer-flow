# 权限架构修复 Sprint 计划

> **关联设计文档**: [docs/plans/2026-05-19-permission-architecture-fix-design.md](./2026-05-19-permission-architecture-fix-design.md)
> **创建日期**: 2026-05-19
> **最后修订**: 2026-05-19（Review v2 — Sprint 0 / Sprint B 拆分 / 加前端 Story / 加性能 smoke / 测试数 21→27 / 监控指标具体化）
> **作者**: Claude
> **目标读者**: backend devs（主），SRE / EM / security reviewer（辅）

---

## Sprint 概览

| 属性 | 值 |
|------|-----|
| Sprint Goal | 闭环 13 条诊断结论（C1-C3 致命 / H1-H4 高危 / M1-M5 中危），让 RBAC 真正落地、JWT 主链合一、`default` 字面量去重载、租户隔离强约束、ins-base 角色源切换 |
| Duration | Sprint 0（0.5 周契约对齐） + Sprint A（1.5 周） + Sprint B1（1.5 周） + Sprint B2（1.5 周） + Sprint C（1.5 周） + Sprint D（1.5 周） = **8 周**（含每周 Demo + 灰度窗口） |
| 总估算 | 56 Story Points（A=14 / B1=12 / B2=12 / C=14 / D=4；不含 Sprint 0 协作工作量） |
| 涉及模块 | gateway authz / auth_middleware / providers / JWT / runtime user_context / persistence(threads_meta, runs, users) / Alembic / 管理后台路由 / 前端 role-aware 菜单 / 文档 |
| 主要约束 | 不破坏现有 4xx 契约；通过 `auth.strict_rbac` 灰度；harness 边界（`tests/test_harness_boundary.py`）必须通过；DB schema 只做加法（加列、加索引），不删字段、不改语义；与 PG 迁移并行时遵循 [设计文档 §6.4](./2026-05-19-permission-architecture-fix-design.md) |
| 团队配置 | 假定 2 名 backend dev；如仅 1 名，B1+B2 各延长 1 周（总周期 → 10 周） |

诊断结论与 Sprint 映射：

| Sprint | 涉及诊断 ID | 主题 |
|--------|--------------|------|
| 0（Week 0，0.5 周） | C2 ASM-1~4 字段对齐 | ins-base 契约验证（不阻塞但前置） |
| A（Week 1-2.5） | A.0 Alembic 003 + C1 / M3 / M4 | 地基：tenant_id 列、RoleRegistry、strict_rbac 开关、默认 role 对齐、prod fail-fast |
| B1（Week 2.5-4） | C2 / C3 / M2 / M5 | 身份基础：ins-base resolver、default/__internal__ 拆分（含 tenant_id 必传）、ins-base 一致性 |
| B2（Week 4-5.5） | H1 + 历史数据 | JWT 主链合并（token_version 单一信号）、历史数据归属化 |
| C（Week 5.5-7） | H2 / H3 / H4 / M1 + 前端 | 仓储与路由：runs 双键过滤、quota 路由拆分、stateless runs 装饰器、LIST viewer-aware、前端 role-aware 菜单 |
| D（Week 7-8） | 灰度 + 文档 + 清理 | 生产灰度切 strict_rbac=true、文档同步、删除 `_ALL_PERMISSIONS` alias / jwt_handler.py |

---

## Sprint 0：ins-base 契约对齐 + 测试 fixture 准备（Week 0，0.5 周）

**Sprint Goal**: 在写代码之前确认 ins-base API 契约（设计文档 §4.2.1 的 ASM-1 ~ ASM-5），为 B1 的 InsBaseRoleResolver 准备 mock fixture，并决定是否启用 `auth.trust_ins_base_permissions=true` 路径。

**容量**: 不计入 SP（协作工作量）。**owner: EM + ins-base 团队联系人**。

### Stories

| # | Story | 优先级 | 涉及人 | 涉及文件 |
|---|-------|--------|--------|----------|
| S0.1 | 与 ins-base 团队对齐 ASM-1 ~ ASM-4（1 次会议 + 一份字段确认 doc） | P0 | EM, ins-base 团队, backend dev 1 人 | `docs/integration/ins_base_field_alignment.md`(新) |
| S0.2 | 准备 4 个 ins-base mock fixture（含极端 case） | P0 | backend dev | `backend/tests/fixtures/ins_base/auth_response_*.json`(新) |
| S0.3 | 决定是否本期启用 `auth.trust_ins_base_permissions=true`；若否则按 §4.2.2 回退 | P0 | EM + 安全 reviewer | (决策记录到 §6.4 `permission-fix.md`) |

### 验收标准

- [ ] `docs/integration/ins_base_field_alignment.md` 含 ins-base permissions 字段名 / 字段类型 / userId 一致性 / 角色绑定语义 4 个明确答复
- [ ] mock fixture 4 个 JSON 文件存在并能被 pytest fixture 加载
- [ ] B1.1 的 SP 估算被确认（如启用 permissions[] = 2 SP；如回退 = 1 SP）

### 出口判定

如果 ASM-1 + ASM-2 任一未对齐 → 启用回退路径（设计 §4.2.2），通知 PM 把 B1.1 SP 调整为 1，并把"ins-base 自动同步"作为新 Story `D.4` (1 SP) 推迟。**不阻塞 Sprint A 启动**——A 期不依赖 ins-base 字段。

---

## Sprint A：地基 + RBAC 表 + tenant_id 列（Week 1 – Week 2.5）

**Sprint Goal**: 把后续所有改动都依赖的"地基"先打好——Alembic 迁移 003 落地 `runs.tenant_id`、RoleRegistry 上线、`auth.strict_rbac` 开关默认 `false`（行为完全不变）、prod 模式禁止 `auth.enabled=false`。Sprint A 结束时，**线上行为零变化**，但所有后续 Sprint 需要的 hook 全部就位。

**容量**: ~14 Story Points

### Stories

| # | Story | Points | 优先级 | 依赖 | 涉及文件 |
|---|-------|--------|--------|------|----------|
| A.0a | grep `RunRow` 模型确认 `user_id` 列是否存在；不存在则 003 同时加 `user_id` 列 + 回填 | 1 | P0 | 无 | `persistence/run/model.py`、`persistence/run/sql.py` |
| A.0 | **Alembic 迁移 003：`runs.tenant_id` 加列 + 回填 + `(tenant_id, thread_id)` 复合索引**（SQLite & PG 双兼容；列允许 NULL，strict_rbac=true 时应用层强制非空） | 2 | P0 | A.0a | `persistence/migrations/versions/003_add_tenant_id_to_runs.py`(新)、`persistence/run/model.py` |
| A.1 | C1 RoleRegistry + AuthContext 改写 + `auth.strict_rbac` 开关 | 5 | P0 | 无 | `auth/roles.py`(新)、`authz.py`、`auth_middleware.py`、`config/auth_config.py` |
| A.1b | grep 全部 `@require_permission(...)` 调用点导出清单，逐条核对 (resource, action) 是否在 `ALL_PERMISSIONS` 中 | 1 | P0 | A.1 | `docs/security/decorator_inventory.md`(新) |
| A.2 | M3 default role 对齐 Literal（`"member"` → `"user"`） | 1 | P0 | 无 | `auth/dependencies.py` |
| A.3 | M4 prod 模式禁止 `auth.enabled=false`（lifespan fail-fast） | 1 | P0 | 无 | `app/gateway/app.py` |
| A.4 | 单元测试 RoleRegistry / strict_rbac toggle / prod fail-fast | 2 | P0 | A.0-A.3 | `tests/test_role_registry.py`(新)、`tests/test_strict_rbac_toggle.py`(新)、`tests/test_currentuser_default_role.py`(新)、`tests/test_prod_auth_required.py`(新)、`tests/test_runs_migration_backfill.py`(新) |
| A.5b | KB RBAC 串行集成回归：`tests/test_kb_rbac_under_strict_mode.py` 在 strict_rbac=true 下跑既有 KB 140 个测试（B1 集成边界保护） | 1 | P0 | A.1 | `tests/test_kb_rbac_under_strict_mode.py`(新) |

### 验收标准

- [ ] **Alembic 003 在干净 SQLite 上 `upgrade head` 成功；`downgrade -1` 后再 `upgrade head` 幂等**
- [ ] PG 上 `runs.tenant_id` 列存在，已从 `threads_meta` 回填（孤儿 run 保持 NULL）
- [ ] `(tenant_id, thread_id)` 复合索引已建
- [ ] 003 PR review 列表含 PG 迁移 owner（设计 §6.4）
- [ ] `auth.strict_rbac=false`（默认）下，旧测试 `tests/test_authz.py` / `tests/test_auth_middleware.py` / `tests/test_admin.py` **全绿**，行为完全不变
- [ ] `auth.strict_rbac=true` 下，`role=user` 调 `closure:verify` 路由 → 403；`role=tenant_admin` → 200；`role=superadmin` → 200
- [ ] `RoleRegistry.permissions_for("user")` ⊂ `permissions_for("tenant_admin")` ⊂ `permissions_for("superadmin") == ALL_PERMISSIONS`
- [ ] `decorator_inventory.md` 列出每个 `@require_permission(resource, action)` 的 (resource, action) 都在 `ALL_PERMISSIONS` 中
- [ ] `CurrentUser` 缺 role 字段 → fallback `"user"`（不再是 `"member"`）
- [ ] `DEER_FLOW_ENV=prod` + `auth.enabled=false` 启动 → `RuntimeError`
- [ ] strict_rbac=true 下既有 KB 140 个测试全部通过（L1+L2 串行不破坏既有行为）
- [ ] **`pytest tests/test_harness_boundary.py` 通过**（`auth/roles.py` 落在 `app/`，不属于 harness；A.0 Alembic 在 `persistence/migrations/`，无 harness→app 引用）

### 技术注意事项

- **A.0 为什么是阻塞所有 column-add 故事的前置**：项目当前 `init_engine()` 走 `Base.metadata.create_all`，**只创建缺失的表**，**不会**给已有表加列。SQLite 上 `create_all` 不报错也不加列；运行时第一次 `SELECT new_column` 才会炸。所以 A.0 必须在 Sprint A 第一周完成。
- **A.0a 列存在性验证**：`grep -n "user_id" packages/harness/deerflow/persistence/run/model.py`；如未发现独立 `user_id` 列（可能仅通过 thread_id 间接关联），需要扩展 003 同时加 `user_id` 列 + 同样从 thread_meta 回填。
- **A.0 SQLite vs PG 差异**：SQLite 不支持 `ALTER COLUMN ... NOT NULL` 在线变更，本期保留列允许 NULL，应用层在 strict_rbac=true 下断言非空。PG 加列默认值 NULL 即可，回填 `UPDATE runs SET tenant_id = (SELECT ... FROM threads_meta ...)` 在事务内完成。
- **A.0 回填范围**：仅回填能从 `threads_meta` 关联到的行。无对应 thread_meta 的孤儿 run（来自 `auth.enabled=false` 时期）保持 `tenant_id=NULL`，由 B2 期迁移脚本 `migrate_default_user_threads.py` 处理。
- **A.0 与 PG 迁移协调**：合入顺序见设计 §6.4；PR 必须由 PG 迁移 owner co-review。
- **A.1 strict_rbac 开关的默认值**：必须默认 `false`，否则任何已部署环境一升级就会让所有非 superadmin 用户撞 403。设计文档 §6.2 明确 dev/staging 切 true 之前先跑 1 周回归。
- **A.1b 装饰器清单**：A.1 完成 RoleRegistry 后立即跑 grep + 人工核对，遗漏会导致 strict_rbac=true 时整路由 403。建议交付物为 markdown 表格 `route | resource:action | role_required | last_verified_date`。
- **A.5b KB 集成回归**：本 Story 是 B1 的资源级 ACL 串行评估保护；如 strict_rbac=true 下既有 KB 测试有红，回到 §4.1.1 设计重新检视双层授权评估顺序。

---

## Sprint B1：身份基础 — ins-base resolver + sentinel 拆分（Week 2.5 – Week 4）

**Sprint Goal**: 完成 ins-base 角色源切换、`default` / `__internal__` sentinel 拆分（含 `tenant_id` 必传）、ins-base 字段一致性。结束时 dev 环境的"身份解析层"已经满足 strict_rbac=true 的所有前置条件。

**容量**: ~12 Story Points

> **依赖前置**：本 Sprint 多个 Story 依赖 Sprint A.1 已上线的 `RoleRegistry` 和 Sprint 0 的 ins-base 字段对齐结论。

### Stories

| # | Story | Points | 优先级 | 依赖 | 涉及文件 |
|---|-------|--------|--------|------|----------|
| B1.1 | C2 `InsBaseRoleResolver` 类骨架（permissions[] 解析 + 本地 override + 默认 user）。**SP 受 Sprint 0 决策影响**：trust_ins_base_permissions=true → 2 SP；回退路径 → 1 SP | 1-2 | P0 | A.1, S0.3 | `auth/ins_base_role_resolver.py`(新)、`config/auth_config.py` |
| B1.2 | 删除 `_map_system_role` 用户名匹配 hack；ins-base provider `get_user()` 调 resolver | 1 | P0 | B1.1 | `auth/ins_base_provider.py` |
| B1.3 | 后台路由 `PUT /admin/users/{user_id}/role` (superadmin only) + 首次登录落表 | 1 | P0 | B1.1 | `routers/admin.py`、`auth/repositories/sqlite.py` |
| B1.4 | C3 `INTERNAL_USER_ID = "__internal__"` sentinel + `identity_kind` ContextVar | 1 | P0 | A.1 | `runtime/user_context.py`、`runtime/identity.py`(新) |
| B1.5 | `internal_auth.get_internal_user(*, tenant_id)` 强制 tenant_id 必传，`tenant_id=None` 抛 ValueError；保留 `DEFAULT_USER_ID` 仅用于 anonymous | 1 | P0 | B1.4 | `internal_auth.py` |
| B1.6 | IM channel webhook handler 调用前先反查 `(channel, chat_id) → thread_id → tenant_id`；后台 dispatcher 入队时持久化 `tenant_id` | 1 | P0 | B1.5 | `app/channels/manager.py`、`app/channels/store.py`、`knowledge_base/dispatcher.py`（如已存在） |
| B1.7 | `ThreadMetaStore.check_access` 加 `identity_kind` 参数 + `caller_tenant_id` 参数（internal 必传）+ 删除 `user_id == "default"` 直通分支 | 2 | P0 | B1.4 | `persistence/thread_meta/sql.py`、`authz.py:286-309` |
| B1.8 | 后台任务 identity_kind 显式传播（`IndexingDispatcher` / `MemoryQueue` / `ChannelManager` / `RunManager`） | 1 | P1 | B1.4 | 各 dispatcher 入队/出队点 |
| B1.9 | M2 ins-base `_resolve_tenant_id` 在 `tenant_repo=None` 时拒绝登录（503） | 1 | P0 | 无 | `auth/ins_base_provider.py`、`deps.py langgraph_runtime` |
| B1.10 | M5 `authenticate()` 内部调用 `get_user(token)` 取 user.id（删除 uuid4） | 1 | P0 | 无 | `auth/ins_base_provider.py` |
| B1.11 | 集成测试：跨 provider role 解析 + identity_kind 三态 + check_access default 行为 + internal token 必带 tenant_id + ins-base 一致性 | 1 | P0 | B1.1-B1.10 | `tests/test_ins_base_role_resolver.py`(新)、`tests/test_admin_user_role.py`(新)、`tests/test_check_access_default_purge.py`(新)、`tests/test_internal_identity_isolation.py`(新)、`tests/test_internal_token_must_pass_tenant_id.py`(新)、`tests/test_runtime_identity_kind_propagation.py`(新)、`tests/test_ins_base_tenant_repo_required.py`(新)、`tests/test_ins_base_user_id_consistency.py`(新) |

### 验收标准

- [ ] ins-base mock 返回 `{userName: "admin", permissions: []}` → `resolve_role()` 返回 `"user"`（不再因为名字匹配自动 tenant_admin）
- [ ] ins-base mock 返回 `permissions: [{"code": "PLATFORM_ADMIN"}]` + `trust_ins_base_permissions=true` → `resolve_role()` 返回 `"superadmin"`
- [ ] `trust_ins_base_permissions=false` 时所有 ins-base 用户 → 默认 `user`（除非本地表显式 override）
- [ ] DeerFlow 本地 `users.system_role="tenant_admin"` 覆盖 ins-base 默认 user 角色
- [ ] `PUT /admin/users/{id}/role` 由 tenant_admin 调用 → 403；superadmin → 200，并 bump `token_version`
- [ ] `internal_user.id == "__internal__"`；`get_internal_user(tenant_id=None)` 抛 `ValueError`
- [ ] `DEFAULT_USER_ID == "default"` 保留但仅用于 `auth.enabled=False` 路径
- [ ] 用户 A 创建 `user_id="default"` 的 thread → 用户 B 登录 → GET `/api/threads/{id}` → **404**（旧行为是 200）
- [ ] internal token 调跨租户 thread → 404（不是 200，也不是 403——保持与"thread 不存在"同一响应避免泄露存在性）
- [ ] internal token 调 `/admin/tenants` → 403
- [ ] `tenant_repo=None` 启动 + ins-base 登录 → HTTP 503（不再降级用 `factory_org_id`）
- [ ] ins-base `authenticate()` 返回的 `user.id` 与立刻调 `get_user(token).id` 一致
- [ ] **`pytest tests/test_harness_boundary.py` 通过**

### 技术注意事项

- **B1.1 SP 弹性**：Sprint 0 决策直接影响实现量。回退路径下，整个 `INS_BASE_PERM_TO_ROLE` 解析分支不存在，仅做 `users.system_role` 单一查询。
- **B1.5 internal token tenant_id 必传**：禁止 `tenant_id=None` 是 H4 的核心修复——避免"internal token 跨租户读取"的隐式越权。webhook 调用方必须先做 chat→thread→tenant 反查（B1.6）。
- **B1.7 check_access `identity_kind` / `caller_tenant_id` 默认值**：`identity_kind` 默认 `"authenticated"`，`caller_tenant_id` 默认 None；`require_permission(owner_check=True)` 的 wrapper 从 `request.state.auth` 读取 identity_kind 和 user.tenant_id 传下去。internal kind 时强制 caller_tenant_id 非 None。
- **B1.6 IM channel 入站反查**：[app/channels/store.py](../../backend/app/channels/store.py) 当前 `get_thread_id(channel, chat_id)` 已存在；新增 `get_tenant_id_for_thread(thread_id)` 从 `threads_meta` 反查。首次会话（无 thread_id）时，channel handler 应引导用户先选租户而不是直接走 internal sentinel。
- **B1.8 后台任务 identity_kind 传播**：dispatcher 入队时持久化 `identity_kind` 到 job row（已有 `tenant_id` / `user_id`，加一个字段即可）；出队时通过 `with_identity_context()` 还原 ContextVar。本期最小实现是把 `identity_kind="authenticated"` 作为常量入队，但 ContextVar 必须显式 set 而非依赖 fork 复制。

---

## Sprint B2：JWT 主链合并 + 历史数据归属化（Week 4 – Week 5.5）

**Sprint Goal**: 把双 JWT 体系合并为单一主链，token claims 显式带 role + tenant_id，通过 `token_version` 单一信号实现降权立即生效；历史 `user_id="default"` 数据归属化迁移。

**容量**: ~12 Story Points

> **依赖前置**：本 Sprint 依赖 Sprint A.1（RoleRegistry）和 B1.4（INTERNAL_USER_ID sentinel）。

### Stories

| # | Story | Points | 优先级 | 依赖 | 涉及文件 |
|---|-------|--------|--------|------|----------|
| B2.1 | H1 `TokenPayload` schema 扩展（`system_role` / `tenant_id`） + `encode_token` / `decode_token` | 2 | P0 | A.1 | `auth/jwt.py` |
| B2.2 | `get_current_user_from_request` 用 token role + `token_version` 一致性校验（不一致 401 token_revoked） | 1 | P0 | B2.1 | `auth/dependencies.py` |
| B2.3 | `PUT /admin/users/{id}/role` 事务内同时更新 `system_role` + bump `token_version`（已部分由 B1.3 实现，本 Story 补 token_version 字段事务约束） | 1 | P0 | B2.1, B1.3 | `routers/admin.py`、`auth/repositories/sqlite.py` |
| B2.4 | `jwt_handler.py` 标 deprecated + import shim 转发；调用方 grep 替换 | 1 | P0 | B2.1 | `auth/jwt_handler.py`、各调用方 |
| B2.5 | 历史数据迁移脚本骨架 `migrate_default_user_threads.py`（dry-run / `--assign-to USER_ID` / 默认归属租户首个 tenant_admin） | 2 | P0 | B1.4 | `scripts/migrate_default_user_threads.py`(新) |
| B2.6 | 迁移脚本扩展扫描范围：`runs.user_id`、`{base_dir}/users/default/agents/`、`{base_dir}/users/default/memory.json`、`{base_dir}/users/default/threads/uploads/`（与 `scripts/migrate_user_isolation.py` 协同） | 1 | P0 | B2.5 | 同上 |
| B2.7 | 脚本支持 `--rollback` + `--audit`（生产 dump 扫 `user_id="default"` 行作为 lint） + 结构化日志输出 | 1 | P1 | B2.5 | 同上、`tests/test_no_default_user_in_prod_dump.py`(新) |
| B2.8 | 集成测试：JWT claims 守恒 + token_version revocation + admin role 改写 bumps token_version + jwt_handler removed + 迁移脚本 dry-run/真实 run | 2 | P0 | B2.1-B2.7 | `tests/test_jwt_payload_role.py`(新)、`tests/test_jwt_token_version_revocation.py`(新)、`tests/test_admin_user_role_bumps_token_version.py`(新)、`tests/test_jwt_handler_removed.py`(新)、`tests/test_default_user_migration_script.py`(新) |
| B2.9 | dev 切 strict_rbac=true 跑端到端回归（B1 + B2 累计变更） | 1 | P0 | 全部 B1 + B2 | dev 环境验证 |

### 验收标准

- [ ] JWT 主链 token 解码后 `payload.system_role == user.system_role`（写入时即一致，无需漂移校验）
- [ ] `PUT /admin/users/{id}/role` 后 `users.token_version` 单调 +1；旧 token 在下次请求时 → 401 `token_revoked`
- [ ] `import jwt_handler` 触发 `DeprecationWarning`（而非 ImportError，shim 期）；deprecation 期内调用 `jwt_handler.encode_token` 仍可用，但内部转发到 `jwt.py`
- [ ] 迁移脚本 dry-run 输出 `user_id="default"` 行的分布报告（按 tenant + 表）
- [ ] 真实 run 后 `check_access` 对历史 thread 仍能正确判定归属
- [ ] `--audit` 模式扫到 `user_id="default"` 行 → CI 红
- [ ] 迁移脚本扫描范围包含 runs / agents 目录 / memory / uploads；与 `migrate_user_isolation.py` 协同（不重复迁移）
- [ ] dev `strict_rbac=true` 跑全套回归无 P0 退化
- [ ] **`pytest tests/test_harness_boundary.py` 通过**

### 技术注意事项

- **B2.2 token_version 单一信号**：设计 §4.4.1 决策——只通过 `token_version` 实现降权立即生效。`get_current_user_from_request` 不再单独校验 `users.system_role` 是否漂移（那是冗余）。
- **B2.2 性能**：每请求多一次 `users.token_version` PK 查询。如 P95 涨 > 5%（C.5.4 测得），加 `lru_cache(maxsize=10000, ttl=60s)`，容忍 1 分钟降权延迟。
- **B2.3 事务约束**：role 更新和 token_version bump 必须在同一事务，否则可能出现 role 已变但 token 仍能用的窗口。Repository 层用 `BEGIN; UPDATE users SET system_role=?, token_version=token_version+1 WHERE id=?; COMMIT;`。
- **B2.4 deprecation shim**：

```python
# auth/jwt_handler.py
import warnings
from app.gateway.auth.jwt import encode_token as _new_encode

def encode_token(*args, **kwargs):
    warnings.warn(
        "auth.jwt_handler is deprecated; use auth.jwt instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return _new_encode(*args, **kwargs)
```

  - 一个 sprint 后（D.3）整个文件删除。
- **B2.5/B2.6 迁移脚本归属策略**：默认归属到 thread 所在租户的最早一个 `tenant_admin`。如果租户内无 tenant_admin（小概率），脚本打印"待人工指派"清单并跳过该批次，不强行归属避免数据错乱。
- **B2.6 与 `migrate_user_isolation.py` 协同**：[backend/CLAUDE.md](../../backend/CLAUDE.md) 已有该脚本（处理 memory/threads/agents 目录的 user 隔离）；本 Story 在新脚本中检测旧脚本是否已跑，避免重复迁移。
- **B2.7 不可逆性**：脚本支持 `--rollback`，但回滚只能把 `user_id IS NULL` 改回 `"default"`，不能撤销已经归属到具体用户的行——所以建议先 `--dry-run` 跑一遍人工 review 后再真实 run。
- **B2.7 prod dump lint**：`tests/test_no_default_user_in_prod_dump.py` 用预合并 PR 的种子数据（含 prod-like fixture）验证不存在 `user_id="default"` 行；如有则 CI 红，提示开发者跑迁移脚本。

---

## Sprint C：仓储与路由强约束 + 前端 role-aware（Week 5.5 – Week 7）

**Sprint Goal**: 把"运行时强约束"全部落地——`runs` 仓储双键过滤、`update_tenant` quota 路由拆分、stateless `runs.py` 装饰器补齐、租户 LIST 路由对 user 开放只读、前端管理菜单按 role 条件渲染。结束时 dev 环境跑全套安全黑盒测试通过。

**容量**: ~14 Story Points

> **依赖前置**：本 Sprint 依赖 Sprint A.0（`runs.tenant_id` 列）和 Sprint B2.1（`TokenPayload.tenant_id`）已就位。

### Stories

| # | Story | Points | 优先级 | 依赖 | 涉及文件 |
|---|-------|--------|--------|------|----------|
| C.1.1 | H2 `RunRepository.aggregate_tokens_by_thread` 加 `(user_id, tenant_id)` 双键过滤 + strict_rbac=true 时必填校验 | 2 | P0 | A.0, B2.1 | `persistence/run/sql.py:208`、`run/model.py` |
| C.1.2 | `RunRepository.create / update_status / update_run_completion` 写入时填充 `tenant_id`；assert `user_id != INTERNAL_USER_ID` 防 sentinel 入库 | 1 | P0 | A.0 | `persistence/run/sql.py` |
| C.1.3 | 调用方一次性补齐：`thread_runs.py`、`runs.py` 显式传 `tenant_id` | 1 | P0 | C.1.1 | 上述路由 |
| C.2.1 | H3 `update_tenant` 路由拆分：`PUT /admin/tenants/{id}` (basic, tenant_admin) vs `PUT /admin/tenants/{id}/quota` (superadmin only) | 1.5 | P0 | A.1 | `routers/admin.py` |
| C.2.2 | strict_rbac=true 下旧 `PUT /admin/tenants/{id}` 携带 quota 字段 → 422 | 0.5 | P1 | C.2.1 | 同上 |
| C.3 | H4 `/api/runs/stream` `/api/runs/wait` 补 `@require_auth` + `@require_permission("runs", "create")` | 1 | P0 | A.1 | `routers/runs.py:35,60` |
| C.4.1 | M1 LIST 路由对 user 开放只读：`tenant_agents` / `tenant_mcp_servers` / `tenant_connectors` GET 改 `@require_permission("agents", "read")` 等 | 1.5 | P0 | A.1 | 三个 tenant_* 路由 |
| C.4.2 | `agent_service.list_for(tenant_id, viewer)` 等服务层方法：tenant_admin 返回全集，user 按 `agent_permissions` 过滤 | 1.5 | P1 | C.4.1 | `agents/service.py`、`mcp_server/service.py`、`http_connector/service.py` |
| **C.6.1** | **前端 `useCurrentUser()` hook 暴露 `system_role` 字段** | 1 | P0 | B2.1 | `frontend/src/hooks/use-current-user.ts` |
| **C.6.2** | **前端管理菜单 / 按钮按 role 条件渲染**（user 看不到 `/admin/*` 入口；tenant_admin 看不到 quota 编辑按钮） | 1.5 | P0 | C.6.1 | `frontend/src/components/layout/sidebar.tsx`、`frontend/src/components/settings/tenant-form.tsx` |
| **C.6.3** | **前端 401 `token_revoked` 自动清 cookie + 跳登录页** | 0.5 | P0 | B2.2 | `frontend/src/lib/http-client.ts` |
| C.5.1 | 端到端测试：dev/staging 切 `strict_rbac=true` 跑全套黑盒（user / tenant_admin / superadmin × 全部管理类路由） | 2 | P0 | C.1-C.4, C.6 | `tests/security/test_rbac_blackbox.py`(新) |
| C.5.2 | 安全黑盒：用户 A 的 thread_id → 用户 B GET/PATCH/DELETE → 全部 404；internal token 跨租户 → 404 | 1 | P0 | B1 | `tests/security/test_thread_cross_user_access.py`(新)、`tests/security/test_internal_token_scope.py`(新) |
| C.5.3 | 回归测试：runs tenant_isolation + update_tenant quota role check + runs stateless decorator + tenant list visibility + 路由装饰器覆盖率 | 1 | P0 | C.1-C.4 | `tests/test_runs_tenant_isolation.py`(新)、`tests/test_update_tenant_quota_role_check.py`(新)、`tests/test_runs_stateless_decorator.py`(新)、`tests/test_tenant_list_visibility.py`(新)、`tests/test_route_decorator_coverage.py`(新) |
| **C.5.4** | **性能 smoke：strict_rbac=false vs true 下 `/api/threads/{id}` GET P95 对比，回归 < 5%** | 1 | P0 | B2.2 | `tests/perf/test_authz_overhead.py`(新) |

### 验收标准

- [ ] `aggregate_tokens_by_thread(thread_id)` 在 strict_rbac=true 下不传 `(user_id, tenant_id)` → `ValueError`
- [ ] tenant A 用户用 thread B 的 ID 调 `aggregate_tokens_by_thread` → 返回空（不再泄露 tenant B 的 token 计数）
- [ ] 新建 run 写入时 `RunRow.tenant_id` 已填；`user_id == "__internal__"` 写入触发 assert
- [ ] 历史 NULL 行在 strict_rbac=true 下被聚合查询忽略
- [ ] `PUT /admin/tenants/{id}` (basic) 由 tenant_admin 调（仅 name/description）→ 200
- [ ] `PUT /admin/tenants/{id}` 由 tenant_admin 调且携带 `daily_quota_usd` → strict_rbac=true 时 422
- [ ] `PUT /admin/tenants/{id}/quota` 由 tenant_admin 调 → 403；superadmin → 200
- [ ] `POST /api/runs/stream` 移除 AuthMiddleware 后仍 401（路由层兜底）
- [ ] `POST /api/runs/wait` 同上
- [ ] `GET /api/tenants/{id}/agents` 由 user 调 → 200 + 该 user 被授权访问的子集；tenant_admin 调 → 全集
- [ ] 前端 `useCurrentUser()` 在 strict_rbac=true 下能拿到 `system_role`
- [ ] role=user 登录前端，sidebar 不显示 `/admin/*` 菜单
- [ ] role=tenant_admin 登录前端，settings 页 quota 编辑按钮 disabled
- [ ] HTTP 401 `token_revoked` 响应 → 前端自动清 cookie 跳 `/login`
- [ ] `tests/security/test_rbac_blackbox.py` 中 user × superadmin-only 路由矩阵全部 403
- [ ] `tests/test_route_decorator_coverage.py` 验证所有 `routers/*.py` 中的写路由都至少有一个 `@require_permission`（防 H4 类回归）
- [ ] **C.5.4 性能 smoke**：strict_rbac=true 下 P95 ≤ strict_rbac=false 的 105%；超出则评估 `lru_cache` 启用
- [ ] **`pytest tests/test_harness_boundary.py` 通过**

### 技术注意事项

- **C.1.1 strict_rbac=false 兼容**：双键参数加上去后 strict_rbac=false 时 `(user_id, tenant_id)` 都为 None，仓库走原始无过滤路径——保证旧契约不破。
- **C.1.2 `user_id != INTERNAL_USER_ID` 守卫**：CI 加 grep 检查 `RunRepository.create` 调用方不传 `__internal__`；防止 internal token 创建的 run 把 sentinel 写入 DB（H4 衍生风险）。
- **C.2.1 旧路由保留 vs 拆新路由**：保留 `PUT /admin/tenants/{id}` 全字段接口一个 sprint 作为兼容窗口；strict_rbac=true 时对非 basic 字段做白名单过滤。前端 C.6.2 先切 `/quota` 子路由，旧字段在 D 期清理。
- **C.4 viewer-aware 过滤的代价**：tenant_admin 调 LIST 走全集（O(1) 一次查询）；user 调 LIST 需 join `agent_permissions` 表，加索引 `(tenant_id, user_id, agent_id)`。本期暂不加索引，观察 staging 性能；如 P95 > 200ms 再加。
- **C.5.1 黑盒矩阵**：12 条管理类路由 × 3 个角色 = 36 个断言；用 `pytest.mark.parametrize` 矩阵化，避免维护噩梦。
- **C.5.4 性能 smoke 阈值**：5% 是经验值；如本地 dev 跑 < 3% 但 staging > 5%，需排查是否 `users.token_version` 查询未命中索引。
- **C.6 前端工作量**：3 个前端 Story 共 3 SP，建议 1 名前端 dev 集中 1 周完成；如无前端 dev，则委托后端兼任，但前端 testing 需要 e2e（手工 + Vitest 矩阵）。

---

## Sprint D：灰度 + 文档收尾（Week 7 – Week 8）

**Sprint Goal**: 把 `auth.strict_rbac=true` 在生产按租户灰度开启；文档（CLAUDE.md / README.md / docs/AUTH.md / docs/security/rbac-matrix.md）同步更新；删除 `_ALL_PERMISSIONS` alias 和 `auth/jwt_handler.py`。

**容量**: ~4 Story Points

### Stories

| # | Story | Points | 优先级 | 依赖 | 涉及文件 |
|---|-------|--------|--------|------|----------|
| D.0 | 灰度 baseline 数据采集 + alert 阈值定义（403 计数 / 客服工单 / 黑盒绿） | 0.5 | P0 | C.5 全绿 | `docs/migrations/2026-05-19-permission-fix.md`(新)、监控 dashboard 配置 |
| D.0b | staging 模拟回滚演练（切 true → 立即切回 false，观察无中间态错误） | 0.5 | P0 | D.1.1 | manual smoke + audit log |
| D.1.1 | feature flag per-tenant 开关：`tenants.strict_rbac_enabled BOOLEAN DEFAULT FALSE` 列 + 中间件读取 | 1 | P0 | C.5 全绿 | `persistence/migrations/versions/004_tenant_strict_rbac_flag.py`(新)、`auth_middleware.py` |
| D.1.2 | 生产灰度操作手册：内部租户 → 信任客户租户 → 全量；每阶段观察 24h | 0.5 | P0 | D.0, D.0b, D.1.1 | `docs/migrations/2026-05-19-permission-fix.md` |
| D.2.1 | 更新 [backend/CLAUDE.md](../../backend/CLAUDE.md)：Authorization 章节加 RoleRegistry / strict_rbac / identity_kind / JWT claims | 0.5 | P0 | A+B+C 完成 | `backend/CLAUDE.md` |
| D.2.2 | 更新 [README.md](../../README.md)：`auth.strict_rbac` / `auth.trust_ins_base_permissions` / `DEER_FLOW_ENV` 配置项纳入 | 0.5 | P1 | 同上 | `README.md` |
| D.2.3 | 新建 `docs/AUTH.md`：完整记录角色矩阵、JWT claims、ins-base resolver、internal token 语义、装饰器调用规范、L1+L2 串行评估 | 0.5 | P1 | 同上 | `docs/AUTH.md`(新) |
| D.2.4 | 新建 `docs/security/rbac-matrix.md`：每条路由 × 每角色 allow/deny 表（来自 C.5.1 黑盒数据） | 0.5 | P1 | C.5.1 | `docs/security/rbac-matrix.md`(新) |
| D.3 | 删除 `_ALL_PERMISSIONS` backward-compat alias + `auth/jwt_handler.py` 整个文件 + 对应 `tests/test_jwt_handler_removed.py` 改为 ImportError 断言 | 0.5 | P0 | 灰度全量稳定 2 周 | `authz.py`、`auth/jwt_handler.py`(删) |
| D.4 | （视 Sprint 0 决策）补充 ins-base 自动同步：`trust_ins_base_permissions=true` 启用 + permissions[] 字段对齐 | 0-1 | P1 | S0 字段确认 | `auth/ins_base_role_resolver.py` |

### 验收标准

- [ ] 灰度 baseline 数据已采集（403 计数 / 平均 latency / 客服工单基线）
- [ ] staging 模拟回滚演练通过（无中间态错误，cache 不需要手动清理）
- [ ] 内部租户切 `strict_rbac=true` 24h 无 P0 客诉，监控指标无异常
- [ ] 信任客户租户切 24h 无 P0 客诉
- [ ] 全量切 24h 无 P0 客诉
- [ ] [backend/CLAUDE.md](../../backend/CLAUDE.md) 中能搜到 `RoleRegistry` / `strict_rbac` / `identity_kind` 三个新概念
- [ ] [README.md](../../README.md) 配置示例段落含 `auth.strict_rbac` / `auth.trust_ins_base_permissions` 字段
- [ ] `docs/AUTH.md` 与 `docs/security/rbac-matrix.md` 在 PR 中作为文档变更可被 review；前者含装饰器调用规范节
- [ ] `import app.gateway.auth.jwt_handler` 触发 `ModuleNotFoundError`（D.3 之后）
- [ ] grep `_ALL_PERMISSIONS` 在 `app/` 下无命中
- [ ] **`pytest tests/test_harness_boundary.py` 通过**

### 技术注意事项

- **D.0 baseline 采集时机**：必须在 D.1.1 启动前 24h 完成数据采集，否则没有对照基线判定灰度健康度。
- **D.0b staging 模拟回滚**：耗时 < 0.5 SP 但避免真实回滚翻车——先把内部 staging 租户的 `strict_rbac_enabled` 切 true，立刻切回 false，验证无 stale cache、AuthContext 状态恢复正常、log 无异常 stack。
- **D.1.1 per-tenant flag**：单一全局 `auth.strict_rbac` 开关上线后，再加一层 `tenants.strict_rbac_enabled` 列允许逐租户灰度。中间件优先级：tenant 列 > 全局配置。
- **D.1.2 灰度判定信号**：观察 dashboard 三个指标——(a) `audit_log` 中 403 计数同比涨 > 30% 持续 30 分钟，(b) 客服工单关键词 `权限` / `无法访问` 命中 ≥ 3 单，(c) `tests/security/test_rbac_blackbox.py` 在 staging 红 1 次。任一异常立刻把该租户 `strict_rbac_enabled` 改回 false 回滚。On-call: SRE 主、backend dev 副。
- **D.3 删除的前置条件**：必须在全量灰度稳定 2 周后再删，避免回滚路径丢失。`_ALL_PERMISSIONS` alias 在 `authz.py` 末尾保留 `_ALL_PERMISSIONS = ALL_PERMISSIONS  # deprecated alias` 一段时间，防止外部调用方遗漏。
- **D.4 视情况启用**：仅当 Sprint 0 ASM-1/2 在 D 期已被 ins-base 团队确认时，本 Story 才启用，把 `trust_ins_base_permissions=false` 切到 `true` + 补充对应 mock 测试。


## 依赖关系图

```
Sprint 0:
  S0.1 (字段对齐) → S0.2 (mock fixture) → S0.3 (启用决策)
  S0.3 → B1.1 (SP 估算确定)

Sprint A:
  A.0a → A.0 (列存在性确认 → 003 迁移)
  A.0 → C.1.1, C.1.2 (runs.tenant_id 列必须先建)
  A.1 → A.1b (RoleRegistry → 装饰器清单核对)
  A.1 → A.5b (RoleRegistry → KB 串行回归)
  A.1 → B1.1, B1.4, B2.1, C.1.1, C.2.1, C.3, C.4.1 (RoleRegistry 是所有后续 RBAC 故事的前置)
  A.0-A.5b → A.4

Sprint B1:
  B1.1 → B1.2, B1.3
  B1.4 → B1.5 → B1.6 (sentinel → tenant_id 必传 → channel 反查)
  B1.4 → B1.7, B1.8
  B1.9, B1.10 (并行，与其他 B1 故事无依赖)
  B1.1-B1.10 → B1.11

Sprint B2:
  A.1 + B1 → B2.1 → B2.2 → B2.3
  B2.1 → B2.4 (jwt_handler shim)
  B1.4 → B2.5 → B2.6 → B2.7
  B2.1-B2.7 → B2.8 → B2.9

Sprint C:
  A.0 + B2.1 → C.1.1 → C.1.2, C.1.3
  A.1 → C.2.1 → C.2.2
  A.1 → C.3
  A.1 → C.4.1 → C.4.2
  B2.1 → C.6.1 → C.6.2
  B2.2 → C.6.3
  C.1, C.2, C.3, C.4, C.6 → C.5.1, C.5.2, C.5.3, C.5.4

Sprint D:
  C.5 全绿 → D.0 (baseline) → D.1.1 → D.0b (回滚演练) → D.1.2 (灰度)
  A+B+C 完成 → D.2.1, D.2.2, D.2.3, D.2.4
  灰度全量稳定 2 周 → D.3
  S0 ASM 已确认（视情况）→ D.4
```

---

## 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| RoleRegistry 与现有路由 (resource, action) 命名不对齐导致大面积 403 | **高** | 中 | A.1b grep 全部 `@require_permission` 调用点导出清单，逐条核对；strict_rbac=false 默认回退保平安 |
| KB 既有 `KbPermissionRow` 与新 RoleRegistry 串行评估出错（L1 + L2 双闸口语义不清） | **高** | 中 | 设计 §4.1.1 明确 L1→L2 串行 + AND 关系；A.5b Story 跑既有 KB 140 个测试在 strict_rbac=true 下回归 |
| ins-base permissions[] 字段缺失，所有用户 → user 角色，超管被锁 | **高** | 中 | Sprint 0 与 ins-base 团队对齐 ASM-1~4；§4.2.2 回退路径——本地 `users.system_role` 作为唯一真相源；迁移脚本先把现有镜像账号写入本地表 |
| `check_access` 改写后历史 thread 全部 404 | **高** | 中 | B2.5 迁移脚本支持 dry-run；先打印 `user_id="default"` 行分布，人工确认后再真实 run |
| jwt_handler.py 被外部调用方依赖（IM channel SDK 注入等） | 中 | 低 | B2.4 deprecation shim 一个 sprint；D.3 删除前 grep 全仓确认无残留调用 |
| 生产灰度切 strict_rbac=true 导致 tenant_admin 突然失去某个功能 | 中 | 中 | D.1.1 per-tenant flag 让回滚精确到单租户；先内部租户跑 24h；D.0 baseline + D.0b 演练 |
| 多人并发 `PUT /admin/users/{id}/role` 出现竞态 | 低 | 低 | 复用现有 `token_version` 字段；role 改写同时 bump token_version 强制对方下次请求重新登录 |
| Alembic 003 在 PG 上 `UPDATE runs SET tenant_id = ...` 慢查询 | 中 | 低 | 加 `LIMIT 10000` 分批 + index hint；预计影响 < 100k 行 |
| internal token 的 `__internal__` sentinel 被某条新代码当成普通 user_id 写入 DB | **高** | 低 | C.1.2 写入时 assert `tenant_id is not None and user_id != INTERNAL_USER_ID`；CI 加 grep 检查；B1.5 强制 `get_internal_user(tenant_id)` 必传 |
| internal token 跨租户隐式访问（IM channel webhook 携带的 internal context 用于操作其他租户的 thread） | **高** | 中 | B1.5/B1.6/B1.7 三步守卫——`tenant_id` 必传 + chat→tenant 反查 + check_access 比对 caller_tenant_id |
| Sprint 0 字段对齐失败（ASM-1/2 未确认） | 高 | 中 | §4.2.2 回退路径不阻塞 A 期；B1.1 SP 自动从 2 调整到 1；ins-base 自动同步推迟到 D.4（视确认时机决定是否本期实现） |
| **与 PostgreSQL 存储迁移并行冲突**（Alembic 链分支起争抢） | **高** | 中 | 设计 §6.4 三种合入顺序明确决策；003 PR 必须由 PG 迁移 owner co-review；Sprint A 启动前由 PM 与 PG owner 同步合入顺序 |
| **strict_rbac=true 性能回归**（每请求多一次 token_version 查询） | 中 | 中 | C.5.4 性能 smoke 测试，回归 < 5%；超出则启用 `lru_cache(maxsize=10000, ttl=60s)`，容忍 1 分钟降权延迟 |
| **前端 role-aware 菜单未做导致 user 看到 403 入口**（影响 UX 但不影响安全） | 中 | 中 | C.6.* 三个前端 Story 闭环；如无前端 dev 资源则委托后端兼任，但需要 e2e 手工验证 |

---

## 关键技术决策

1. **可灰度优于一次切换**：`auth.strict_rbac` 全局开关 + per-tenant flag 让任何变更都可在租户粒度回滚，而不是 deploy/rollback 整个版本。
2. **DB schema 只做加法**：`runs.tenant_id` 加列允许 NULL；`threads_meta` 不加列（`check_access` 改为应用层逻辑）。strict_rbac=false 时一切兼容旧契约。
3. **`default` 字面量去重载**：把"未鉴权占位"和"内部 token 合成身份"和"行无主"三种语义彻底拆开（`DEFAULT_USER_ID` / `INTERNAL_USER_ID` / `NULL`），杜绝 C3 类越权根因。
4. **JWT 主链单一来源**：保留 `jwt.py`（pyjwt，无 cffi 依赖，部署友好），删除 `jwt_handler.py`。Bearer 头与 cookie 走同款 token，前端契约不变。
5. **角色源 DeerFlow 主、ins-base 辅**：ins-base permissions[] 仅作建议；DeerFlow 本地 `users.system_role` 是真相源。理由：避免外部权限系统抖动直接影响 DeerFlow 鉴权决策。
6. **不引入 ABAC / OPA**：所有规则用 Python `RoleDefinition` dataclass + `@require_permission` 装饰器表达，可单测、可 grep、可 review；外置策略框架的运维复杂度暂不值得。
7. **历史数据修复与配置纠错解耦**：A 期上线 `auth.strict_rbac` 开关但默认 false；B 期跑迁移脚本归属化历史数据；C 期切 dev/staging 验证；D 期生产灰度。任何阶段失败都能停在原地。

---

## Definition of Done

每个 Story 完成标准：

- [ ] 代码实现通过 Code Review（满足 [backend/CLAUDE.md](../../backend/CLAUDE.md) 格式约定）
- [ ] 单元/集成测试编写并通过；新增测试 ≥ 设计文档 §8.2 列出的数量
- [ ] `make test` 全绿；既有 `tests/test_authz.py` / `tests/test_auth_middleware.py` / `tests/test_admin.py` 继续通过
- [ ] 不引入新的安全漏洞（权限校验完整，租户上下文不漂移）
- [ ] 向后兼容：`auth.strict_rbac=false`（默认）下旧行为完全不变
- [ ] 相关文档更新到位（具体见 §D.2 stories）

每个 Sprint 完成标准：

- [ ] 所有 Story 已 close
- [ ] Sprint 目标对应的"验收标准"全部达成
- [ ] **`pytest tests/test_harness_boundary.py` 通过**（每个 Sprint 都必须验证）
- [ ] Sprint Review 演示通过

整个交付完成标准（对齐设计文档 §11）：

- [ ] 13 条诊断结论全部映射到具体 Story 并完成
- [ ] Alembic 003 已合入；SQLite/PG `upgrade head` 幂等通过；PR 由 PG 迁移 owner co-review
- [ ] 既有测试全部通过；新增测试 ≥ **27 个**（含前端 Vitest、性能 smoke、KB 串行回归、prod dump lint）
- [ ] dev 切 `auth.strict_rbac=true` 后三种角色端到端可用（user 看不到管理菜单 / tenant_admin 改 quota 被 403 / superadmin 全通）
- [ ] strict_rbac=true 下 P95 latency 回归 < 5%（C.5.4 验证）
- [ ] 前端 role-aware 菜单已生效（user 不显示 `/admin/*`；tenant_admin quota 按钮 disabled）
- [ ] HTTP 401 `token_revoked` 自动跳登录
- [ ] `auth.enabled=False + DEER_FLOW_ENV=prod` 启动 fail-fast
- [ ] ins-base 名为 `admin` + 空 permissions[] → role=user
- [ ] 用户 A thread_id 被用户 B 直接 GET → 404
- [ ] internal token 跨租户访问 thread → 404；调 `/admin/tenants` → 403
- [ ] `runs.tenant_id` 列已回填；strict_rbac=true 下 `aggregate_tokens_by_thread` 强制双键
- [ ] `RunRow.user_id != INTERNAL_USER_ID` 守卫生效（防 sentinel 入库）
- [ ] [backend/CLAUDE.md](../../backend/CLAUDE.md) / [README.md](../../README.md) / `docs/AUTH.md` / `docs/security/rbac-matrix.md` 已更新

---

## 实施顺序建议（按周）

```
Week 0:   Sprint 0 (S0.1-S0.3) — ins-base 字段对齐 + mock fixture + 启用决策（不阻塞 A 启动）
Week 1:   A.0a + A.0 + A.1 (列存在性 → Alembic 003 → RoleRegistry)
Week 2:   A.1b + A.2 + A.3 + A.4 + A.5b (装饰器清单 + role 对齐 + prod fail-fast + A 测试 + KB 串行回归)
Week 2.5: B1.1 + B1.4 + B1.9 + B1.10 (resolver 骨架 + sentinel + tenant_repo 守卫 + user.id 一致性)
Week 3:   B1.2 + B1.3 + B1.5 + B1.6 (resolver 切换 + 后台路由 + tenant_id 必传 + channel 反查)
Week 3.5: B1.7 + B1.8 + B1.11 (check_access 改写 + 后台任务 identity_kind + B1 集成测试)
Week 4:   B2.1 + B2.2 + B2.3 + B2.4 (TokenPayload 扩展 + token_version 校验 + admin role 事务 + jwt_handler shim)
Week 4.5: B2.5 + B2.6 + B2.7 (迁移脚本骨架 + 扫描范围扩展 + rollback/audit)
Week 5:   B2.8 + B2.9 (B2 集成测试 + dev strict_rbac=true 端到端回归)
Week 5.5: C.1.* + C.3 (runs 双键 + stateless 装饰器)
Week 6:   C.2.* + C.4.* (quota 路由 + LIST viewer-aware)
Week 6.5: C.6.* (前端 role-aware 菜单 + 401 处理)
Week 7:   C.5.* (端到端 + 安全黑盒 + 性能 smoke + dev/staging 切 strict_rbac=true)
Week 7.5: D.0 + D.0b + D.1.1 (baseline + 回滚演练 + per-tenant flag)
Week 8:   D.1.2 + D.2.* + D.3 + D.4 (灰度推进 + 文档收尾 + 删 alias + ins-base 同步)
```

每周结束 Demo：

- Week 0: 演示 ins-base 字段确认 doc + 4 个 mock fixture
- Week 1: 演示 Alembic 003 在 SQLite/PG 上 `upgrade head` + RoleRegistry 矩阵单测全绿
- Week 2: 演示 prod 模式 fail-fast + strict_rbac toggle 行为切换 + decorator_inventory.md 完整
- Week 2.5: 演示 ins-base mock `userName=admin` + 空 permissions[] → user 角色（不再自动 admin）
- Week 3: 演示 internal token 跨租户访问 thread → 404；channel webhook 入站反查到 tenant
- Week 3.5: 演示用户 A 的 thread → 用户 B 访问 → 404
- Week 4: 演示 JWT claims 含 role/tenant_id + admin role 改写 token_version 立刻失效旧 token
- Week 4.5: 演示迁移脚本 dry-run 输出归属分布报告（含 runs / agents 目录 / memory 全范围扫描）
- Week 5: 演示 dev strict_rbac=true 端到端三角色全通
- Week 5.5: 演示 strict_rbac=true 下 `aggregate_tokens_by_thread` 必须双键；stateless runs 移除 middleware 后仍 401
- Week 6: 演示 tenant_admin 改 quota → 403；user LIST 看到本租户子集
- Week 6.5: 演示前端 user 看不到 admin 菜单 + 401 自动跳登录
- Week 7: 演示安全黑盒矩阵（user/tenant_admin/superadmin × 12 条管理路由）全绿 + 性能 smoke 通过
- Week 7.5: 演示 staging 模拟回滚演练无中间态错误
- Week 8: 演示文档全套 + 全量灰度 + jwt_handler.py 删除

---

## 实施状态

> 实施过程中按 Story 粒度更新。每完成一个 Story 把 `[ ]` 改成 `[x]` 并补 1-2 行实测笔记（如发现的边界、被推翻的假设）。

### Sprint 0 — 待启动

| # | Story | 状态 | 备注 |
|---|-------|------|------|
| S0.1 | ins-base 字段对齐（ASM-1~4） | [ ] | EM + ins-base 团队联系人 |
| S0.2 | mock fixture 4 份 | [ ] | |
| S0.3 | trust_ins_base_permissions 启用决策 | [ ] | 影响 B1.1 SP |

### Sprint A — 待启动

| # | Story | 状态 | 备注 |
|---|-------|------|------|
| A.0a | RunRow.user_id 列存在性确认 | [ ] | |
| A.0 | Alembic 003 runs.tenant_id 加列 + 回填 + 索引 | [ ] | P0 阻塞所有 column-add 故事；PR 需 PG 迁移 owner co-review |
| A.1 | RoleRegistry + AuthContext + strict_rbac 开关 | [ ] | P0 阻塞所有 RBAC 故事 |
| A.1b | `@require_permission` 调用点清单核对 | [ ] | 防 strict_rbac=true 整路由 403 |
| A.2 | default role 对齐 Literal | [ ] | |
| A.3 | prod 模式禁止 auth.enabled=false | [ ] | |
| A.4 | A 系列单测 | [ ] | |
| A.5b | KB RBAC 串行回归（既有 140 测试 strict_rbac=true 下不破） | [ ] | L1+L2 集成边界保护 |

### Sprint B1 — 待启动

| # | Story | 状态 | 备注 |
|---|-------|------|------|
| B1.1 | InsBaseRoleResolver 骨架 | [ ] | SP 由 S0.3 决定（1 或 2） |
| B1.2 | ins-base provider 切 resolver | [ ] | |
| B1.3 | PUT /admin/users/{id}/role 后台路由 | [ ] | |
| B1.4 | INTERNAL_USER_ID + identity_kind ContextVar | [ ] | |
| B1.5 | get_internal_user 强制 tenant_id 必传 | [ ] | H4 风险闭环 |
| B1.6 | IM channel webhook 入站反查 chat→thread→tenant | [ ] | |
| B1.7 | check_access identity_kind + caller_tenant_id 参数 + default 直通分支删除 | [ ] | |
| B1.8 | 后台任务 identity_kind 传播 | [ ] | |
| B1.9 | ins-base tenant_repo 缺失 503 | [ ] | |
| B1.10 | authenticate / get_user user.id 一致性 | [ ] | |
| B1.11 | B1 集成测试组（8 个文件） | [ ] | |

### Sprint B2 — 待启动

| # | Story | 状态 | 备注 |
|---|-------|------|------|
| B2.1 | TokenPayload role/tenant_id claims | [ ] | |
| B2.2 | get_current_user_from_request token_version 校验 | [ ] | 单一信号决策 §4.4.1 |
| B2.3 | admin role 改写事务内 bump token_version | [ ] | |
| B2.4 | jwt_handler deprecation shim | [ ] | |
| B2.5 | 迁移脚本 dry-run + 归属化 | [ ] | |
| B2.6 | 迁移脚本扫描范围扩展（runs / agents / memory / uploads） | [ ] | |
| B2.7 | 迁移脚本 rollback + audit + 结构化日志 | [ ] | |
| B2.8 | B2 集成测试（5 个文件） | [ ] | |
| B2.9 | dev strict_rbac=true 端到端回归 | [ ] | |

### Sprint C — 待启动

| # | Story | 状态 | 备注 |
|---|-------|------|------|
| C.1.1 | aggregate_tokens_by_thread 双键过滤 | [ ] | |
| C.1.2 | RunRepository 写入填 tenant_id + sentinel 守卫 | [ ] | |
| C.1.3 | 路由调用方一次性补齐 | [ ] | |
| C.2.1 | update_tenant 路由拆分 (basic vs quota) | [ ] | |
| C.2.2 | strict_rbac=true 422 校验 | [ ] | |
| C.3 | runs.py stream/wait 装饰器补齐 | [ ] | |
| C.4.1 | tenant LIST 路由对 user 开放 | [ ] | |
| C.4.2 | service.list_for(viewer) viewer-aware 过滤 | [ ] | |
| **C.6.1** | **前端 useCurrentUser hook 暴露 system_role** | [ ] | |
| **C.6.2** | **前端管理菜单 / 按钮按 role 条件渲染** | [ ] | |
| **C.6.3** | **前端 401 token_revoked 自动清 cookie 跳登录** | [ ] | |
| C.5.1 | 端到端 RBAC 黑盒 | [ ] | |
| C.5.2 | thread 跨用户 + internal scope 黑盒 | [ ] | |
| C.5.3 | runs / quota / LIST 回归 + 路由装饰器覆盖率测试 | [ ] | |
| **C.5.4** | **性能 smoke：authz overhead 回归 < 5%** | [ ] | |

### Sprint D — 待启动

| # | Story | 状态 | 备注 |
|---|-------|------|------|
| D.0 | 灰度 baseline 数据采集 + alert 阈值 | [ ] | |
| D.0b | staging 模拟回滚演练 | [ ] | |
| D.1.1 | per-tenant strict_rbac flag | [ ] | |
| D.1.2 | 生产灰度操作手册 + 推进 | [ ] | |
| D.2.1 | backend/CLAUDE.md 更新 | [ ] | |
| D.2.2 | README.md 更新 | [ ] | |
| D.2.3 | docs/AUTH.md 新建 | [ ] | |
| D.2.4 | docs/security/rbac-matrix.md 新建 | [ ] | |
| D.3 | 删除 _ALL_PERMISSIONS alias + jwt_handler.py | [ ] | 需灰度全量稳定 2 周 |
| D.4 | (视情况) ins-base 自动同步启用 trust_ins_base_permissions=true | [ ] | 视 S0.3 决策 |

---

## 附录

### A. Story → 诊断 ID 反查

| 诊断 ID | 严重度 | 主题 | Sprint | Story |
|---------|--------|------|--------|-------|
| C1 | Critical | `_ALL_PERMISSIONS` 全开 | A | A.1 / A.1b / A.4 / A.5b |
| C2 | Critical | ins-base 用户名匹配 | 0 + B1 | S0.* / B1.1 / B1.2 / B1.3 |
| C3 | Critical | `user_id="default"` 越权 | B1 + B2 | B1.4 / B1.5 / B1.6 / B1.7 / B1.8 / B2.5 / B2.6 / B2.7 |
| H1 | High | 双 JWT 体系并存 | B2 | B2.1 / B2.2 / B2.3 / B2.4 |
| H2 | High | RunRow 无 tenant_id | A + C | A.0 / A.0a / C.1.1 / C.1.2 / C.1.3 |
| H3 | High | tenant_admin 改 quota | C | C.2.1 / C.2.2 |
| H4 | High | runs.py 缺装饰器 + internal token 跨租户 | B1 + C | B1.5 / B1.6 / B1.7 / C.3 / C.5.2 |
| M1 | Medium | LIST 仅 tenant_admin | C | C.4.1 / C.4.2 |
| M2 | Medium | tenant_repo=None 降级 | B1 | B1.9 |
| M3 | Medium | 默认 role "member" | A | A.2 |
| M4 | Medium | prod auth.enabled=false | A | A.3 |
| M5 | Medium | authenticate / get_user user.id 不同 | B1 | B1.10 |

### B. 新增 / 修改文件速查

新增：

- `backend/packages/harness/deerflow/persistence/migrations/versions/003_add_tenant_id_to_runs.py`
- `backend/packages/harness/deerflow/persistence/migrations/versions/004_tenant_strict_rbac_flag.py`
- `backend/packages/harness/deerflow/runtime/identity.py`
- `backend/app/gateway/auth/roles.py`
- `backend/app/gateway/auth/ins_base_role_resolver.py`
- `backend/scripts/migrate_default_user_threads.py`
- `backend/tests/test_role_registry.py`
- `backend/tests/test_strict_rbac_toggle.py`
- `backend/tests/test_require_permission_with_roles.py`
- `backend/tests/test_currentuser_default_role.py`
- `backend/tests/test_prod_auth_required.py`
- `backend/tests/test_runs_migration_backfill.py`
- `backend/tests/test_ins_base_role_resolver.py`
- `backend/tests/test_admin_user_role.py`
- `backend/tests/test_check_access_default_purge.py`
- `backend/tests/test_internal_identity_isolation.py`
- `backend/tests/test_runtime_identity_kind_propagation.py`
- `backend/tests/test_jwt_payload_role.py`
- `backend/tests/test_jwt_role_drift.py`
- `backend/tests/test_jwt_handler_removed.py`
- `backend/tests/test_ins_base_tenant_repo_required.py`
- `backend/tests/test_ins_base_user_id_consistency.py`
- `backend/tests/test_default_user_migration_script.py`
- `backend/tests/test_runs_tenant_isolation.py`
- `backend/tests/test_update_tenant_quota_role_check.py`
- `backend/tests/test_runs_stateless_decorator.py`
- `backend/tests/test_tenant_list_visibility.py`
- `backend/tests/security/test_rbac_blackbox.py`
- `backend/tests/security/test_thread_cross_user_access.py`
- `backend/tests/security/test_internal_token_scope.py`
- `docs/AUTH.md`
- `docs/security/rbac-matrix.md`
- `docs/migrations/2026-05-19-permission-fix.md`

修改：

- `backend/app/gateway/authz.py`
- `backend/app/gateway/auth_middleware.py`
- `backend/app/gateway/internal_auth.py`
- `backend/app/gateway/deps.py`
- `backend/app/gateway/app.py`
- `backend/app/gateway/auth/dependencies.py`
- `backend/app/gateway/auth/jwt.py`
- `backend/app/gateway/auth/jwt_handler.py`（先 deprecation shim，D.3 删除）
- `backend/app/gateway/auth/ins_base_provider.py`
- `backend/app/gateway/auth/repositories/sqlite.py`
- `backend/app/gateway/routers/admin.py`
- `backend/app/gateway/routers/runs.py`
- `backend/app/gateway/routers/thread_runs.py`
- `backend/app/gateway/routers/tenant_agents.py`
- `backend/app/gateway/routers/tenant_mcp_servers.py`
- `backend/app/gateway/routers/tenant_connectors.py`
- `backend/packages/harness/deerflow/runtime/user_context.py`
- `backend/packages/harness/deerflow/persistence/run/model.py`
- `backend/packages/harness/deerflow/persistence/run/sql.py`
- `backend/packages/harness/deerflow/persistence/thread_meta/sql.py`
- `backend/packages/harness/deerflow/config/auth_config.py`
- `frontend/src/components/settings/tenant-form.tsx`
- `config.yaml`
- `README.md`
- `backend/CLAUDE.md`

### C. 配置变更速查

```yaml
auth:
  strict_rbac: false               # 新增；true 时启用真正 RBAC（默认 false 灰度过渡）
  jwt_secret: "$AUTH_JWT_SECRET"   # 强化；启动 fail-fast 校验

# 环境变量
DEER_FLOW_ENV: dev                 # 新增；prod 时禁止 auth.enabled=false
```

> 所有新增字段都有保守默认值，旧 `config.yaml` 启动后行为完全不变。

### D. RBAC 矩阵（节选，完整见 `docs/security/rbac-matrix.md`）

| 路由 | resource:action | user | tenant_admin | superadmin |
|------|-----------------|------|--------------|------------|
| `GET /api/threads/{id}` | threads:read（owner_check） | 自己 | 自己 | 全部 |
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

### E. Token 主链 Claims Schema

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
