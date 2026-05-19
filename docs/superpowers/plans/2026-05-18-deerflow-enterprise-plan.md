# DeerFlow 企业级扩展 — 开发计划

> 配套 RFC：[2026-05-18-deerflow-enterprise-rfc.md](../specs/2026-05-18-deerflow-enterprise-rfc.md)
> 日期：2026-05-18
> 计划粒度：里程碑级 / 顺序：按 RFC §1 功能优先级 / 审计：v1 同步路径 / 测试：每模块单测 + 关键集成测试

## 1. 总览

按 RFC §1 优先级切 5 个里程碑：地基 → RBAC → 审计 → 审批 → OIDC → 收尾。每个里程碑可独立交付、独立回归，里程碑之间形成单向依赖（下游可用上游产物，上游不依赖下游）。

| 里程碑 | 内容 | 主要交付物 | 进入条件 | 退出条件 |
|--------|------|-----------|---------|---------|
| **M0** | 地基 | 包结构、配置、Alembic、`PermissionProvider` 协议、中间件透传 | RFC 评审通过 | `pytest`、`test_harness_boundary` 全绿；`enterprise.enabled=false` 时行为完全不变 |
| **M1** | RBAC | RbacRepository、RbacPermissionProvider、RBAC 路由、User 模型扩展 | M0 退出 | 启用后所有现有路由 + 企业路由权限解析正确；回归不变 |
| **M2** | 审计 v1 | AuditEvent/Storage/Signer/Middleware、审计路由 | M0 退出（与 M1 可并行） | Agent 任务完成事件可查询；签名校验通过 |
| **M2.5** | **Spike 门禁** | RunManager 恢复路径可行性 + Checkpoint state 抓取契约 | M2 退出 | Spike 报告产出，决定 M3 实现路径（恢复式 vs 前端重发兜底） |
| **M3** | 审批 | Approval 模型/引擎/Checkpoint/Timeout、ApprovalGuardrailProvider、通知器、审批路由 | M1、M2、**M2.5** 退出 | 危险命令拦截 → 通知 → 批准 → Checkpoint 恢复 → 执行完成 端到端跑通 |
| **M4** | OIDC | OIDCClient、OIDCAuthProvider、auth/oidc 路由 | M1 退出 | OIDC 登录 → JIT provisioning → 角色映射 → JWT 签发 端到端跑通 |
| **M5** | 收尾 | 前端集成、文档、迁移脚本验收、回归 | M1-M4 退出 | 配置开关全矩阵回归通过；CHANGELOG 与 README 更新 |

> M2 与 M1 可并行（中间件透传与 PermissionProvider 互不依赖）。M3 必须在 M1+M2 之后，因审批要写审计、审批 GuardrailProvider 要查 User.roles 反查审批人。M4 只依赖 M1（User.roles 写路径）。

---

## 2. M0 — 地基

**目标**：建好包骨架、配置、迁移环境、最小代码改动钩子，让后续 4 个里程碑可以平行展开。

### 2.1 主要交付物

| # | 路径 | 说明 |
|---|------|------|
| M0-1 | `backend/packages/harness/deerflow/enterprise/__init__.py` | 空包占位 |
| M0-2 | `backend/packages/harness/deerflow/enterprise/config.py` | `EnterpriseConfig`、`RbacConfig`、`AuditConfig`、`ApprovalConfig`、`OIDCConfig`、`EnterpriseDatabaseConfig` Pydantic 模型（RFC §3.2）；**含 `model_validator(mode="after")` 强约束 §8.2 列出的非法/退化组合** |
| M0-3 | `backend/packages/harness/deerflow/config/app_config.py` | 新增 `enterprise: EnterpriseConfig = EnterpriseConfig()` 字段（RFC §11.1 改动 #5） |
| M0-4 | `backend/packages/harness/deerflow/enterprise/persistence/database.py` | `EnterpriseDatabase.init/close`，仅做 `SELECT 1` 探活，不调 `create_all`（RFC §8.1） |
| M0-5 | `backend/packages/harness/deerflow/enterprise/persistence/__init__.py` | **决策：复用 `deerflow.persistence.base:Base`，不新建独立 declarative_base。**所有企业 ORM 模型（M1/M2/M3 各自的）都挂到同一个 `Base.metadata` 上，让 `env.py:target_metadata = Base.metadata` 自动覆盖。理由：RFC §8.1 明确"共用同一个 Alembic 环境与 `Base.metadata`"，单 Base 比多 metadata 合并更简单 |
| M0-6 | `backend/packages/harness/deerflow/persistence/migrations/env.py` | 加入占位 import（`import deerflow.enterprise.rbac.repository` 等），让企业 ORM 模型注册到 `Base.metadata`，使 Alembic `autogenerate` 能识别企业表 |
| M0-7 | `backend/app/gateway/authz.py` | 新增 `PermissionProvider` Protocol、模块级 `_permission_provider`、`set_permission_provider()`；`_authenticate()` 中分支调用（RFC §11.3） |
| M0-8 | `backend/app/gateway/auth_middleware.py` | `dispatch()` 中**重写** `AuthContext` 构造路径：有 provider 时 `await provider.resolve_permissions(user)`，无 provider 时退回 `_ALL_PERMISSIONS`。**关键**：现状是在中间件层就用 `_ALL_PERMISSIONS` 构造 AuthContext 并写入 `request.state.auth`，`@require_permission` 看到 `auth is not None` 就不会重新解析（authz.py:254-257）→ 必须在中间件层接入 provider，否则 RBAC 形同未启用 |
| M0-9 | `backend/packages/harness/deerflow/agents/lead_agent/agent.py` | `_make_lead_agent` 顶端读 `enterprise` 配置 + 两处 `_build_middlewares(...)` 补 `custom_middlewares=`（RFC §11.4） |
| M0-10 | `backend/packages/harness/deerflow/enterprise/middlewares.py` | `get_enterprise_middlewares(config)` 工厂（M0 阶段返回空列表，由 M2 填充） |
| M0-11 | `backend/app/gateway/app.py` | `create_app()` 与 `lifespan()` 加 `if enterprise_config.enabled:` 框架（M0 阶段先留 TODO，路由由 M1-M4 各自挂） |
| M0-12 | `config.example.yaml` | 新增 `enterprise:` 段示例（RFC §3.2 完整 YAML） |
| M0-13 | `tests/test_lead_agent_middleware_order.py` | 断言 `custom_middlewares=None`/空列表/含 1 项 三种情况下整条中间件链顺序（保证 M0-9 改动不破现状） |

### 2.2 验收

- `pytest backend/tests/` 全绿
- `test_harness_boundary.py` 通过：`deerflow.enterprise.*` 无 app 层导入
- 新增 `tests/test_authz_permission_provider.py`：
  - 不注册 provider：`_authenticate()` 返回 `_ALL_PERMISSIONS`（行为不变）
  - 注册 mock provider：`AuthContext.permissions` 等于 provider 返回值
  - **反向证据 1**：mock provider 在请求处理期间被调用次数 ≥ 1（避免 `auth_middleware` 短路）
  - **反向证据 2**：`request.state.auth` 在中间件层已存在时，装饰器不会再次构造 AuthContext（覆盖 authz.py:254-257 短路路径）
  - **反向证据 3**：`internal_auth` header 分支（internal_user）下，是否绕过 provider 必须明确选择并测试
- M0-13 中间件链顺序测试通过
- `enterprise.enabled=false`（默认）下，所有原有路由、原有 Agent 链路行为零变化
- `alembic current` 可在企业环境跑通，无修订脚本时不报错

### 2.3 关键风险

| 风险 | 应对 |
|------|------|
| `authz._authenticate()` / `auth_middleware.dispatch` 改动破坏现有 401/403 行为 | 集成测试覆盖 token 有效/无效/过期/缺失四类；§2.2 反向证据测试 |
| `lead_agent` 中间件链顺序变化 | M0-13 已列入交付物 |
| Alembic 识别不到企业 ORM 模型 | M0 阶段建一张占位 `_enterprise_meta` 表（挂到复用的 `Base.metadata`）证明 autogenerate 能跑，M1 删除占位 |

---

## 3. M1 — RBAC

**目标**：让 `@require_permission` 真正生效，企业 Permission 与 legacy threads/runs 字符串共存。

### 3.1 主要交付物

| # | 路径 | 说明 |
|---|------|------|
| M1-1 | `deerflow/enterprise/rbac/models.py` | `Role`、`Permission` 枚举、`DEFAULT_ROLE_PERMISSIONS`、`LEGACY_PERMISSIONS_FOR_ROLE`（RFC §4.1） |
| M1-2 | `deerflow/enterprise/rbac/repository.py` | `RbacRepository` ABC + `SqliteRbacRepository` + `PostgresRbacRepository`；含 `roles`、`role_permissions` 表 ORM |
| M1-3 | Alembic 修订脚本 `<hash>_initial_rbac_schema.py` | 建 `roles`、`role_permissions` 表 + `users.roles TEXT DEFAULT '[]'` 列 + 现有 system_role 数据迁移到 `roles`（RFC §8.4） |
| M1-4 | `deerflow/enterprise/rbac/permission_provider.py` | `RbacPermissionProvider`：`_resolve_roles` + `resolve_permissions`（合并企业 perms + LEGACY perms，RFC §4.2） |
| M1-5 | `app/gateway/auth/models.py` | `User.system_role` `Literal` → `str`，新增 `roles: list[str]`（RFC §11.5） |
| M1-6 | `app/gateway/auth/repositories/base.py` + sqlite/pg 实现 | `get_users_by_role(role)` 方法（RFC §11.1 改动 #8）；`UserRow` 加 `roles` 列 JSON 序列化 |
| M1-7 | `app/enterprise/deps.py` | `get_enterprise_db`、`get_rbac_repo`、`get_rbac_checker` 惰性单例 |
| M1-8 | `app/enterprise/routers/rbac.py` | RFC §9.1 的 7 个路由 + `@require_permission` 装饰 |
| M1-9 | `app/gateway/app.py` | `lifespan` 中 `if enterprise_config.rbac.enabled: set_permission_provider(await get_rbac_checker())`（RFC §9.4） |

### 3.2 测试

| 测试 | 覆盖 |
|------|------|
| `test_rbac_repository.py` | CRUD、`get_role_permissions(Role)` 签名、并发写 |
| `test_rbac_permission_provider.py` | `_resolve_roles` 三条路径（roles 优先 / 回退 system_role / 默认 default_role）；`resolve_permissions` 同时返回企业 perms + LEGACY perms |
| `test_user_model_roles.py` | `User.roles` 默认空列表、`system_role` 接受任意字符串、序列化往返 |
| `test_rbac_routes.py` | 7 个路由的权限校验：admin 全通、member 部分通、未认证 401 |
| **集成** `test_legacy_routes_with_rbac.py` | 启用 RBAC 后，现有 `/api/threads/*`、`/api/runs/*` 路由对 ADMIN/MEMBER/VIEWER 角色解析正确（关键回归点）；**断言 `RbacPermissionProvider.resolve_permissions` 调用计数 ≥ 1**，证明没被 `auth_middleware` 短路绕过 |

### 3.3 验收

- `enterprise.rbac.enabled=true` 下：4 个角色对所有 RFC §9.1 路由的允/拒矩阵符合预期
- 现有 threads/runs 路由的回归测试通过
- 切回 `enterprise.rbac.enabled=false`：`_authenticate()` 走 `_ALL_PERMISSIONS`，行为退回 M0

### 3.4 风险

| 风险 | 应对 |
|------|------|
| LEGACY 映射遗漏 → 现有路由 403 | `test_legacy_routes_with_rbac.py` 必须先于代码合入 |
| `User.roles` 列迁移把已有 admin 漏掉 | Alembic 脚本支持 `--sql` 干跑预览，并写明 `op.execute("UPDATE users SET roles='[\"admin\"]' WHERE system_role='admin'")` |
| `roles.id` 与 `Role` enum 同步漂移 | repository 层用 `Role(value)` 反序列化，遇到非枚举值抛 `ValueError` 而非静默忽略 |

---

## 4. M2 — 审计 v1

**目标**：Agent 任务完成、工具调用、审批关键事件落 SQLite/PG，HMAC 签名防篡改，提供查询/导出 API。

### 4.1 主要交付物

| # | 路径 | 说明 |
|---|------|------|
| M2-1 | `deerflow/enterprise/audit/events.py` | `AuditEventType` 枚举（22 个值，RFC §5.1）、`AuditEvent` Pydantic 模型 |
| M2-2 | `deerflow/enterprise/audit/storage.py` | `AuditStorage` ABC + `SqliteAuditStorage` + `PostgresAuditStorage`；含 `query`、`count`、`verify_integrity`；`append_batch` 用 for-loop fallback |
| M2-3 | Alembic 修订脚本 `<hash>_audit_events.py` | 建 `audit_events` 表，全列索引：`(user_id, timestamp)`、`(event_type, timestamp)` |
| M2-4 | `deerflow/enterprise/audit/signer.py` | `AuditSigner.sign/verify`，HMAC-SHA256（RFC §5.3） |
| M2-5 | `deerflow/enterprise/audit/middleware.py` | `AuditMiddleware` `@Next("sandbox_audit")`，`abefore_agent`+`aafter_agent`（覆盖 STARTED+COMPLETED+ERROR 三态）+ `awrap_tool_call`，**同步** `await storage.append(event)`（RFC §5.4） |
| M2-5b | `deerflow/enterprise/audit/tool_event_map.py` | 工具名→`AuditEventType` 映射表（独立模块便于扩展）。覆盖：(1) 沙箱写入类 bash/write_file/str_replace → `SANDBOX_COMMAND_EXECUTED`；(2) MCP 工具 `mcp:{server}:{tool}` 前缀按 server 路由；(3) Community 工具 `tavily_*/jina_*/firecrawl_*` → `DATA_EXPORTED`；(4) 只读工具白名单不记录；(5) 未知工具 → `AGENT_TASK_COMPLETED` 默认；并定义 `RECORDED_TOOLS` 集合作为白名单 |
| M2-6 | `deerflow/enterprise/middlewares.py` | M0 占位的 `get_enterprise_middlewares` 填充 AuditMiddleware |
| M2-7 | `app/enterprise/routers/audit.py` | RFC §9.1 审计路由 5 个 |
| M2-8 | `app/enterprise/deps.py` | `get_audit_storage`、`get_audit_signer` 单例 |

### 4.2 测试

| 测试 | 覆盖 |
|------|------|
| `test_audit_signer.py` | sign/verify 往返、字段顺序无关性、篡改后 verify 失败 |
| `test_audit_storage_sqlite.py` | append、query 各类 filter、count、verify_integrity 全链路 |
| `test_audit_middleware.py` | `abefore_agent` 产生 STARTED；`aafter_agent` 成功产生 COMPLETED、异常路径产生 ERROR；签名落库 |
| `test_audit_tool_event_map.py` | 5 类工具映射全覆盖：bash/写文件类、MCP 前缀、community 前缀、只读白名单不记录、未知工具默认 |
| **集成** `test_audit_end_to_end.py` | 跑一个完整 lead agent，从 DB 查到对应 event 链 |
| `test_audit_routes.py` | 查询分页、导出 CSV、integrity 接口 |

### 4.3 验收

- 一次普通 Agent 调用结束后，DB 中至少有 1 条 `AGENT_TASK_COMPLETED` 事件，签名校验通过
- `GET /api/enterprise/audit/integrity` 返回 `true`；**性能 SLA**：10w 行下端到端 < 1s，或支持分页校验
- `enterprise.audit.enabled=false`：中间件不注册，零 DB 写入
- **microbenchmark**：单条 `append` 在本地 SQLite 上 P99 < 1ms；不达标升级到 §10 backlog 的 v2 队列

### 4.4 风险

| 风险 | 应对 |
|------|------|
| 同步写入拖慢 Agent | benchmark 单次 append < 1ms（SQLite 本地）；如超阈值再上 v2（在 backlog 标记） |
| `event_type` 字段漂移导致老事件无法反序列化 | `AuditEventType` 不删枚举值，仅追加 |
| 沙箱工具事件量爆炸 | `awrap_tool_call` 按工具白名单决定是否记录（细节在 M2 实现时确认） |

---

## 5. M2.5 — Spike 门禁（必经）

**目标**：在投入 M3 之前回答两个会决定 M3 整体架构的未知问题。预计 1-2 天，**不允许跳过**。

### 5.1 Spike 任务

| # | 问题 | 验证方式 | 决定 |
|---|------|---------|------|
| S1 | `RunManager` 是否支持在恢复 thread 时向后续工具调用的 metadata 注入 `_approval_id`？ | 读 `backend/packages/harness/deerflow/runtime/run_manager.py` + 写一个最小 PoC：暂停 thread → 重入 → 断言下一次 `aevaluate` 收到 `tool_input["_approval_id"]` | 支持 → M3 走 Checkpoint 恢复路径；不支持 → M3 退化为前端重发兜底（拒绝时把 `_approval_id` 返回给前端，前端在 retry 时把它放进 tool_input） |
| S2 | `GuardrailProvider.aevaluate(request)` 入参只有 `tool_name/tool_input/agent_id/thread_id`，**没有 AgentState**。Checkpoint 怎么拿到 state？ | 三选一 PoC：(a) 扩展 GuardrailProvider 协议加 `state` 入参；(b) 在 `GuardrailMiddleware` 内部从 runtime 读取 state 并通过 ContextVar 传给 provider；(c) `ApprovalGuardrailProvider` 自己实现 `awrap_tool_call` 中间件而非走 GuardrailProvider 协议 | 选定方案 → 写进 M3-8 交付物的接口契约；同时决定是否需要新增 lead_agent 改动（M0-9 是否要再加 1 行） |

### 5.2 交付物

- `docs/superpowers/spikes/2026-MM-DD-runmanager-resume.md`：S1 结论 + PoC 代码片段
- `docs/superpowers/spikes/2026-MM-DD-guardrail-state.md`：S2 三方案对比 + 选定方案 + 对 RFC §6.7、§11.1 改动清单的影响
- 如 S2 选定方案 (a) 或 (c)，**回填到 RFC** 并在本计划 §6 M3 交付物表对应更新

### 5.3 退出条件

- 两份 spike 报告评审通过
- M3 的 §6.1 交付物表根据 spike 结论修订（特别是 M3-5 Checkpoint 与 M3-8 GuardrailProvider 的契约定义）
- 如 S1 结论为"不支持且改造成本高"，**升级到决策门**：要么追加 M2.6 改造 RunManager，要么 M3 范围降级为"仅前端重发，无服务端 Checkpoint 恢复"

---

## 6. M3 — 审批

**目标**：危险命令被 GuardrailMiddleware 拦截 → 创建工单 + 保存 Checkpoint + 通知 → 审批通过后 RunManager 恢复执行；包含超时、修订闭环、多级审批。

### 6.1 主要交付物

| # | 路径 | 说明 |
|---|------|------|
| M3-1 | `deerflow/enterprise/approval/models.py` | `ApprovalStatus`、`ApprovalAction`、`ApprovalUrgency`、`Approval`、`ApprovalRule`（RFC §6.2） |
| M3-2 | `deerflow/enterprise/approval/repository.py` | `ApprovalRepository` ABC + SQLite/PG 实现，含 `record_approval_decision`、`count_approvals`、`mark_expired`、`update_checkpoint` |
| M3-3 | Alembic 修订脚本 `<hash>_approval_tables.py` | `approvals` + `approval_decisions` 表，含 `action_detail TEXT JSON`、`checkpoint TEXT JSON` |
| M3-4 | `deerflow/enterprise/approval/engine.py` | `ApprovalRuleEngine`，`_evaluate_condition` 用 `ast.parse(mode="eval")` + 白名单 walker（RFC §6.3），`_resolve_approvers` 用 M1 引入的 `get_users_by_role` |
| M3-5 | `deerflow/enterprise/approval/checkpoint.py` | `ApprovalCheckpoint.serialize_state/deserialize_state/save_suspend_point/restore`，字段白名单**对照 `ThreadState.__annotations__` 逐字段决策**（详见 §6.2 元测试）。state 来源由 M2.5 S2 spike 决定（GuardrailProvider 协议扩展 / ContextVar / 自实现 awrap_tool_call） |
| M3-6 | `deerflow/enterprise/approval/timeout.py` | `ApprovalTimeoutChecker.start/close/_check_loop` |
| M3-7 | `deerflow/enterprise/approval/notifiers/{base,web,feishu,wecom}.py` | 三个通知器实现 |
| M3-7b | `app/enterprise/webhooks/signature.py` + 路由集成 | 飞书/企微 webhook **签名校验中间件**：飞书 HMAC-SHA256 (timestamp+nonce+body+token)，企微 AES + signature 校验。所有外部回调（飞书审批卡片点击、企微消息回调）必须先过签名校验中间件才能进 `/approve` `/reject` 路由。校验前不接受任何状态变更 |
| M3-8 | `deerflow/enterprise/approval/guardrail_provider.py` | `ApprovalGuardrailProvider`（RFC §6.7）、`CompositeGuardrailProvider`（RFC §6.7 末） |
| M3-9 | `app/enterprise/routers/approval.py` | RFC §9.1 审批路由 8 个，含 `/{id}/resubmit` 修订闭环 |
| M3-10 | `app/gateway/app.py` | `lifespan` 启动 `timeout_checker.start()` / 关闭 `timeout_checker.close()` |
| M3-11 | 审批触发的恢复路径 | `/api/enterprise/approval/{id}/approve` 内调用 `RunManager` 恢复 thread，把 `_approval_id` 注入工具调用 metadata |

### 6.2 测试

| 测试 | 覆盖 |
|------|------|
| `test_approval_engine_condition.py` | 受限表达式：合法案例（`==`、`in`、`and`、`not`、括号）全通过；非法案例（`__import__`、`Call`、`Attribute`、`Subscript`、`lambda`）全抛 ValueError |
| `test_approval_checkpoint.py` | serialize→deserialize 往返；不可序列化字段（sandbox 对象）被剔除；**元测试：遍历 `ThreadState.__annotations__`，每个字段必须显式标记为 keep 或 drop**，新增 ThreadState 字段时此测试强制 fail，逼迫开发者做决策 |
| `test_webhook_signature.py` | 飞书/企微签名合法/非法/时间戳过期/重放四种分支 |
| `test_approval_timeout.py` | mock clock，超过 deadline 后 status 变 EXPIRED + 触发通知 |
| `test_approval_guardrail_provider.py` | 命中规则 → 创建工单 + return `allow=False`；`_approval_id` 已通过 → return `allow=True` |
| `test_composite_guardrail.py` | 多 provider 串联短路语义 |
| `test_approval_repository.py` | CRUD、`mark_expired` 原子性、`record_approval_decision` 多级审批计数 |
| **集成** `test_approval_e2e.py` | 配 1 条规则 → 触发 bash → 拦截 → 通知器收到 → POST `/approve` → Checkpoint 恢复 → 工具放行 → audit 落库 |

### 6.3 验收

- 端到端剧本：用户跑 `bash("rm -rf /tmp/x")` → 被拦 → 审批人在 Web 端看到工单 → 批准 → Agent 自动续跑 → DB 含 `APPROVAL_REQUESTED`/`APPROVAL_GRANTED`/`SANDBOX_COMMAND_EXECUTED` 三条审计
- 超时剧本：deadline=1s 的规则，1.5s 后 status=EXPIRED，发起人收到通知
- 修订闭环：拒绝后 POST `/resubmit`，新工单 `revision_of` 指向原工单
- `enterprise.approval.enabled=false`：GuardrailMiddleware 不挂 ApprovalGuardrailProvider，行为退回 M2

### 6.4 风险

| 风险 | 应对 |
|------|------|
| Checkpoint 序列化遗漏字段（todos/artifacts 等） | M3-5 字段白名单 + §6.2 元测试强制每个 ThreadState 字段显式决策 |
| `ast` 白名单遗漏节点导致沙箱逃逸 | 单测覆盖所有危险节点；引入新 AST 节点时必须先更新白名单 |
| webhook 回调被伪造 | M3-7b 签名校验中间件已列入交付物 |
| RunManager 恢复路径 / state 抓取 | 由 M2.5 spike 决定路径；不支持时降级为前端重发兜底 |
| 单条规则在压力下 `_resolve_approvers` 慢 | 给 `UserRepository.get_users_by_role` 加 (role, status) 复合索引 |

---

## 7. M4 — OIDC

**目标**：OIDC 登录 → callback → JIT provisioning → 角色映射 → JWT 签发；与现有本地登录并存。

### 7.1 主要交付物

| # | 路径 | 说明 |
|---|------|------|
| M4-1 | `deerflow/enterprise/auth/oidc_config.py` | `OIDCConfig`、`OIDCRoleMapping`（RFC §7.1） |
| M4-2 | `deerflow/enterprise/auth/oidc_client.py` | `OIDCClient.get_authorization_url/exchange_code/verify_id_token/_discover`（含 JWKS 缓存）（RFC §7.2） |
| M4-3 | `deerflow/enterprise/auth/role_mapper.py` | `OIDCRoleMapper.map`（RFC §7.3） |
| M4-4 | `app/enterprise/oidc_auth_adapter.py` | `OIDCAuthProvider(AuthProvider)`，三条 `_find_or_create_user` 路径（RFC §7.2） |
| M4-5 | `app/enterprise/routers/auth.py` | `/login`、`/callback`、`/discovery` 三个路由；state/nonce **写入 HttpOnly + Secure + SameSite=Lax cookie**（IdP 跨域回跳需 Lax 而非 Strict） |
| M4-6 | Alembic 修订脚本 `<hash>_oidc_links.py` | 可选 `oidc_links` 表（RFC §8.2，若复用 `users.oauth_id` 则跳过） |
| M4-7 | `app/gateway/app.py` | `lifespan` 中注册 `OIDCAuthProvider` 到现有 auth 体系 |

### 7.2 测试

| 测试 | 覆盖 |
|------|------|
| `test_oidc_client.py` | mock Discovery + JWKS + token endpoint，验签 ok/sig 不对/exp 过期/aud 不匹配/nonce 不匹配 5 种分支 |
| `test_oidc_role_mapper.py` | claim 是 str 单值、list 多值、缺失、多条命中取第一 |
| `test_oidc_auth_provider.py` | 三条 `_find_or_create_user` 路径：oauth_id 已绑、email 已绑、全新；`auto_provision=false` 时返回 None |
| **集成** `test_oidc_e2e.py` | 启动 mock IdP（如 `python-oidc-provider` 测试桩），完整跑 `/login → IdP → /callback → JWT 签发`，验证 cookie 写入 + User.roles 落库 |

### 7.3 验收

- mock IdP 下端到端登录成功，`User.roles` 被正确写入，后续受 RBAC 约束
- 现有密码登录路径完全不受影响（回归）
- state 不匹配、nonce 不匹配、code 已用 三种异常返回 401

### 7.4 风险

| 风险 | 应对 |
|------|------|
| JWKS 缓存击穿 | TTL 默认 10 分钟，刷新失败用旧值兜底 |
| nonce 跨进程不一致（多 worker 部署） | nonce 写 cookie 而非内存；session 在外部 store 时同步策略文档化 |
| `auto_provision=false` 配置下用户体验差 | callback 返回结构化错误码，前端展示「请联系管理员开通账号」 |
| IdP 不可达全员 401 | callback 加超时；前端展示"SSO 暂不可用，请用密码登录"降级提示（前提是密码登录未禁用） |

---

## 8. M5 — 收尾

**目标**：前端、配置矩阵回归、迁移脚本验收、文档。

### 8.1 主要交付物

| # | 内容 | 说明 |
|---|------|------|
| M5-1 | `frontend/src/enterprise/*` | RBAC 管理页、审计日志页、审批列表/详情页、Dashboard、OIDC 登录按钮（RFC §10） |
| M5-2 | 前端启用探测 | `GET /api/enterprise/dashboard/stats` 200/404 决定是否渲染企业入口 |
| M5-3 | `backend/scripts/migrate_enterprise.py` | 独立数据迁移脚本（admin → roles=['admin']），含 `--dry-run`（与 `migrate_user_isolation.py` 风格一致）；**幂等**：用 `WHERE roles IS NULL OR roles='[]'` 限定，避免覆盖已有值 |
| M5-3b | Alembic round-trip 测试 | 对 M1-3/M2-3/M3-3 三个修订脚本：含真实数据的库执行 `upgrade head → downgrade -1 → upgrade head` 三循环，断言数据无丢失 |
| M5-4 | 配置开关组合回归矩阵 | 见 §8.2 |
| M5-5 | `README.md` / `CLAUDE.md` 更新 | 新增企业版章节、配置说明、迁移步骤 |
| M5-6 | CHANGELOG | 列出新增 API、新增配置字段；`User.system_role` `Literal`→`str` 是**类型放宽**，不算 breaking |

### 8.2 配置开关组合回归矩阵（M5-4）

`enterprise.enabled` × 4 个子模块开关 = 32 种理论组合，按合法性分类处理：

| 类别 | 组合 | 处理 |
|------|------|------|
| 退化等价 | `enterprise.enabled=false` 时的 16 种子开关组合 | 视为等价，仅冒烟一次（应与企业版完全未引入时行为一致） |
| 合法 | `enterprise.enabled=true` + 单个子模块 `enabled=true`，其余 `false` | 各 1 个 e2e 冒烟（4 个） |
| 合法 | `enterprise.enabled=true` + 全部子模块 `enabled=true` | 1 个完整 e2e |
| **非法** | `enterprise.enabled=true` + `approval.enabled=true` + `rbac.enabled=false` | `_resolve_approvers` 因无人写过 `User.roles` 而返回空，所有审批工单永远无人能批 → `EnterpriseConfig.model_validator` **启动期 fail-fast** |
| **非法** | `enterprise.enabled=true` + `approval.enabled=true` + `audit.enabled=false` | 审批关键事件无法落审计 → 合规链断裂 → validator **fail-fast** |
| **退化警告** | `enterprise.enabled=true` + `oidc.enabled=true` + `rbac.enabled=false` | OIDC 写 `user.roles` 下游无消费者 → `EnterpriseConfig.model_validator` 产出 **warning** 但允许启动 |
| **退化警告** | `enterprise.enabled=false` 且任一子模块 `enabled=true` | validator 产出 **warning**，子模块被忽略 |

验收：上表"非法"组合启动时必须抛 `ConfigError`；"退化警告"组合启动时必须 `logger.warning(...)`；"合法"组合通过 e2e。

### 8.3 验收

- 完整 Docker Compose 起一个含企业版全功能的实例，按用户故事跑通：
  - admin 设置 member 角色
  - member 触发危险 bash → 等待审批
  - admin 批准 → bash 执行 → 审计日志可查
  - 用 OIDC mock 登录新用户 → 自动 provisioning 为 member
- 关闭 `enterprise.enabled` 后重启，所有原有 e2e 测试通过
- §8.2 所有"非法"组合启动报错，所有"退化警告"组合启动产生 warning

---

## 9. 跨里程碑约定

### 9.1 代码边界

- 所有 harness 层代码（`deerflow/enterprise/*`）不导入 `app.*`；`test_harness_boundary.py` 每个 PR 必跑
- app 层适配器（`app/enterprise/*`）可以导入 harness 与现有 app 模块

### 9.2 配置默认值与校验

- `enterprise.enabled` 默认 `false`；启用前所有子开关无意义
- 任何新增 YAML 字段必须在 `config.example.yaml` 同步示例 + 注释默认值
- `EnterpriseConfig` 必须提供 `model_validator(mode="after")`，强约束 §8.2 列出的非法 / 退化组合

### 9.3 测试组织

- 单测：`backend/tests/enterprise/test_<module>.py`，使用内存 SQLite
- 集成测试：`backend/tests/enterprise/integration/test_*.py`，启动完整 FastAPI app + mock 外部依赖
- 每个 PR 必须新增 / 修改对应测试，CI 阻塞合入
- **新增独立 CI job**：`enterprise-tests`，与现有 `tests` job 并行，失败不阻塞非企业 PR 但显式标记

### 9.4 迁移

- 任何 schema 变化必须经由 Alembic 修订脚本；禁止运行时 `create_all`
- 修订脚本必须含 `downgrade()`
- 数据迁移走 `op.execute` 或独立 script，且支持 `--dry-run`
- SQLite 上 `alter_column` 必须走 `op.batch_alter_table`（已知 SQLite 不支持 in-place ALTER）
- 迁移脚本必须**幂等**：重复运行不报错、不覆盖已修改值

### 9.5 可观测性

- 审计走独立 logger `deerflow.enterprise.audit`，不混入应用日志
- 新增 Prometheus 指标命名空间 `enterprise_*`：`enterprise_audit_append_seconds`（histogram）、`enterprise_approval_pending_total`（gauge）、`enterprise_rbac_resolve_seconds`（histogram）
- M2 验收必须含 microbenchmark：单条 `append` 在本地 SQLite 上 P99 < 1ms；超过则升级到 §10 backlog 的 v2 队列

### 9.6 文档同步

- 每个里程碑结束补一篇 `backend/docs/` 下的模块手册（可选），最少更新 `CLAUDE.md` 中的"企业模块"一节

---

## 10. 后续 Backlog（不在本计划范围）

- **审计 v2 异步队列**（RFC §5.5）：仅当 §9.5 microbenchmark 显示同步路径成为瓶颈时启动
- **企业知识库**（RFC §1）：当前借用 MCP/上传，单独立项时再做
- **Project / Tenant 维度**（RFC §4.1 注释）：当前限定单组织，未来若引入多项目隔离，按 `PROJECT_*` Permission 模式扩展
- **审批 email/SMS 通知器**（RFC §6.6）：当前仅 Web/飞书/企微
- **PostgreSQL 生产化**：当前 SQLite/PG 双实现，但生产部署、性能调优、备份策略待单独立项

---

## 11. 风险全景

| 类别 | 风险 | 缓解 |
|------|------|------|
| 架构 | PermissionProvider 注册时机错过第一个请求 | `lifespan` startup 阶段同步注册 + M0 测试用例覆盖 |
| 架构 | `auth_middleware.dispatch` 短路 → `@require_permission` 看到 `_ALL_PERMISSIONS` → RBAC 形同未启用 | M0-8 必须改写中间件中 `AuthContext` 构造路径走 provider；M1 集成测试断言 "provider 真正被调用"（mock provider 计数 > 0） |
| 架构 | Checkpoint 拿不到 AgentState（GuardrailProvider 协议无 state 入参） | M2.5 S2 spike 决策；选定方案必须回填 RFC §6.7 |
| 架构 | RunManager 不支持注入 `_approval_id` metadata | M2.5 S1 spike；不支持则 M3 范围降级为前端重发兜底 |
| 数据 | `users.roles` 列迁移误把已有 admin 漏掉 | 迁移脚本 `--dry-run` + 集成测试覆盖；脚本 idempotent |
| 数据 | Alembic downgrade 在已有数据库上丢数据 | M5-3b round-trip 测试 |
| 数据 | Checkpoint 字段白名单与 ThreadState 实际字段漂移（todos/artifacts 等被遗漏） | `test_approval_checkpoint.py` 加**元测试**：遍历 `ThreadState.__annotations__`，每个字段必须显式标记 keep/drop |
| 安全 | 受限表达式 AST 白名单漏节点 | 安全 review；每加白名单节点必须文档化原因 |
| 安全 | OIDC nonce/state 在多 worker 下不一致 | 强制走 cookie，不依赖进程内存 |
| 安全 | 飞书/企微 webhook 回调被伪造 | M3-7 必须含签名校验中间件；通过校验前不接受任何状态变更 |
| 安全 | OIDC IdP 不可达全员 401 | callback 加超时；前端降级提示密码登录（若启用） |
| 性能 | 同步审计写入拖慢 Agent | §9.5 microbenchmark；P99 > 1ms 升级到 v2 队列 |
| 性能 | `verify_integrity` 在 10w+ 行时秒级以上 | M2 验收加 SLA：10w 行 < 1s 或支持分页校验 |
| 兼容 | LEGACY 权限映射遗漏 → 现有路由 403 | M1 必须有 legacy 路由集成测试 |
| 配置 | 非法配置组合（如 approval+rbac=false）启动后业务静默坏掉 | §8.2 矩阵 + §9.2 `model_validator` fail-fast |
