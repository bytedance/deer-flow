# 多租户个人工作智能体统一实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 默认顺序执行，不自动派生并行智能体。

**Goal:** 在同一套空间/成员隔离模型中交付管理员开通、自助注册与团队管理，并支持个人研究报告和持续跟进。

**Architecture:** 复用原生User、认证、权限、线程、Run、MCP、Scheduler、记忆和ECS B/C。新增Workspace/Membership及相关生命周期数据，把服务端空间身份贯穿原生资源和后台任务；不以tenant替换user、不另造Agent或任务权威。

**Tech Stack:** FastAPI/Python、SQLAlchemy/Alembic/PostgreSQL、Redis、Next.js/React、现有MCP/Skill、Docker/NAS、上海Jenkins。

设计依据：[统一设计](../specs/2026-10-13-tenant-workspaces-design.md)。OpenSpec：`openspec/changes/tenant-workspaces-self-service/`。
基线48d5c3de。实施已进入M3的项目CRUD、私有与显式共享资料空间隔离；合同、迁移和离线归属基础已有定向验证，但各工作包的完整验收仍未完成。实际源码与Jenkins证据见 `docs/tenant-workspaces-progress.json`，不以计划条目代替验收。

## 用户确认后的执行顺序与可审阅交付

用户确认将“管理员管理租户”和“客户自助注册、管理团队”合为同一需求，按依赖顺序实施。两种开户入口共用账号、空间、成员和授权服务；阶段划分用于控制开发顺序，不代表只交付管理员版本。计划确认回复先整理文档；后续“完成上述计划”目标继续授权顺序实施和上海定向验证，部署仍须满足 M10–M11 门禁。

| 顺序 | 工作包 | 可审阅交付 | 进入下一阶段的依据 |
| --- | --- | --- | --- |
| 1. 租户基础与管理员管理 | M0–M3 | 入口清单、库表与迁移、管理员开通、成员权限、个人/团队空间切换、资料上传下载和会话归属 | 一个账号在两个空间分别使用资料与会话成功；跨空间列表、下载和引用被拒绝 |
| 2. 后台执行与知识隔离 | M4–M5 | 原生 B/C、定时任务、通知、记忆、检索和工具凭据携带同一空间身份 | 前端切换不改变后台任务归属；撤权后不能启动新工作、发布结果或使用已撤销连接 |
| 3. 客户自助与团队管理 | M6–M7 | 注册、邮件验证、密码恢复、团队创建、邀请、成员管理和所有权转让界面 | 浏览器跑通管理员开户与自助开户，两者调用同一服务；真实邮件验证和邀请接受成功 |
| 4. 运营与个人助理业务 | M8–M9 | 基础配额、审计、停用/关闭，以及“资料→研究→带来源报告→批准后的定期跟进” | 真实资料产生报告并完成一次更新；配额和生命周期操作有可查结果 |
| 5. 迁移与统一交付 | M10–M11 | 旧数据迁移、备份恢复、Jenkins 交付、测试与部署文档 | 版本、两库 schema 和文件归属匹配；必要隔离、撤权及恢复验收通过后才允许公开注册 |

阶段主干验证通过后推进后续功能；跨工作包的最终验收仍保持未完成，直到依赖证据齐备。先验证真实主干，再补必要边界检查，不用测试数量衡量进度。

当前记录显示 M0–M2 有部分基础实现，M3 的私有项目 CRUD 已有定向验证；私有资料上传、列表、下载和删除已在隔离环境获得真实文件证据（Jenkins #21）；共享资料 API 与旧数据私有迁移已通过 Jenkins #23，匹配版本的离线 CLI 通过 #24；线程仓库已通过 #26，线程创建/查询/修改及项目私有会话列表已通过 #28；线程文件、状态和客户端贯通仍未验收。文件路径与资料转存主干已通过 #31；下一项继续 M3 的下载发送边界、文件撤权、线程生命周期和空间切换；已有基础通过不等于完整 M3 完成。

## 顺序、检查点与边界

严格M0→M11。M3先完成单空间资料/任务主干；M4/M5补后台与知识边界；M6/M7完成两种开户及团队用户流程；M8/M9完成管理和业务；M10/M11完成迁移/发布证明。公开注册在M11前保持关闭，开发M6时仅在隔离验收环境允许。

每项按：一个有意义的失败检查→最小实现→同检查通过→受影响模块必要检查→提交。主干先于全面边界验收，不为每个字段写镜像式测试；有新的失败才扩大回归。每次提交只含该任务的文件和对应文档，不使用git add .。

所有pytest、Docker、浏览器真实后端及模型测试在上海Jenkins/ECS执行，不启动本地Docker Desktop或本地pytest。下面backend命令从云端checkout/backend运行；frontend命令从云端checkout根运行，并经过scripts/pnpm.py。本地仅文档/OpenSpec/静态检查。M7创建frontend/playwright.tenant.config.ts，后端baseURL与测试账号由Jenkins专属私有输入提供；该测试不使用page.route伪造后端。

本计划列出精确接点和新文件职责、实现合同与验收；M0入口清单决定同类路由的完整覆盖，不能把有限列举当作可以漏掉其他接口。每项开工前读所属AGENTS.md。迁移文件名必须由届时真实head生成，本文不预占revision号。

## 共享代码合同（拟新增，后续任务必须一致）

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class WorkspaceContext:
    workspace_id: str
    actor_user_id: str
    membership_version: int
    policy_version: int
```

M0定义此数据类型；M2的服务端依赖解析它。下游只接受可信调用层提供的对象，不从用户请求体反序列化成授权。授权函数合同为`authorize_resource(context, resource_workspace_id, owner_user_id, visibility, action)`；visibility仅`private`/`workspace`，返回授权结果或统一拒绝，内部每次核验有效workspace、membership及原生权限，不以字面ID相等替代数据库授权。模型不能修改任一身份字段。

M2统一开户服务合同：`provision_personal_workspace(user_id, idempotency_key)`，以及`create_team_workspace(actor, name, idempotency_key)`；事务约束确保重复请求返回同一资源。M6邮件服务：`issue_action_token(user_id, purpose, expires_at)`创建哈希记录和加密outbox，`consume_action_token(raw_token, purpose)`锁定验证并单次消费。原始令牌只能短暂留在进程内与加密邮件载荷，API日志不得包含。

最小核心用例模式（M0建立fixture，M2实现授权；不以此替代真实SQL/HTTP测试）：

```python
# Fixture seed: same user is a member of workspaces A and B;
# resource_a belongs to A and is private to that user.
def test_active_space_does_not_authorize_foreign_resource(workspace_case):
    case = workspace_case
    response = case.get_artifact(case.resource_a, selected_workspace=case.space_b)
    assert response.status_code == 404
    response = case.get_artifact(case.resource_a, selected_workspace=case.space_a)
    assert response.status_code == 200
```

`workspace_case`由M0新增`backend/tests/workspace_helpers.py`并在既有`backend/tests/conftest.py`注册fixture统一构造：两个普通账号、两个个人空间、一个团队空间，固定小文件内容；使用既有认证与独立Postgres fixture，不复制共享生产配置；`get_artifact`调用真实ASGI路由并附加选择符。M3接通前此用例应失败，M3后通过；M11复用它检查最终构建。

## 工作包

### M0：冻结入口清单与空间合同

**修改接点：**
- `backend/app/gateway/AGENTS.md`
- `backend/packages/harness/deerflow/persistence/AGENTS.md`
- `backend/tests/conftest.py`
- `frontend/AGENTS.md`

**新增文件：**
- `contracts/workspace_scope.v1.json`
- `docs/tenant-entrypoint-inventory.md`
- `backend/packages/harness/deerflow/authz/workspace.py`
- `backend/tests/test_workspace_contract.py`
- `backend/tests/workspace_helpers.py`

**实现合同：** 定义WorkspaceContext四字段及权限交集；按HTTP、SSE/WSS、PAT、IM/webhook、Scheduler、MCP、文件、记忆、知识、插件逐项列出入口、调用者和阻断策略。保留真实actor_user_id；模型输入不能构造可信上下文。

**验收结果：** 缺少/伪造空间上下文被拒绝；单用户模式保持原有行为；入口清单无未指定处理方式的运行路径。

- [ ] 1. 阅读上述模块指南及入口调用链，把该验收场景写成最小失败检查（复用共享fixture和原生身份，不mock掉授权边界）。
- [ ] 2. 在专属Jenkins工作空间运行下述定向命令，保存预期失败；依赖未就绪产生的导入错误不算业务RED证据。
- [ ] 3. 按实现合同新增/修改上述模块；涉及ORM必须同时添加迁移，涉及用户行为同步API及界面文案。每项开始先将此工作包展开为具体函数/测试的小步变更，避免凭总计划一次生成整个模块。
- [ ] 4. 重跑同一检查至通过，执行受影响模块lint/format或前端check；记录源码commit、环境及结果，不扩大到无关全套。
- [ ] 5. 自审权限、幂等和错误处理，保存回执；显式git add本任务文件后提交，再勾OpenSpec对应任务。

```bash
python -m pytest tests/test_workspace_contract.py -q
```

预期：对应主干通过；若无法证明上述验收结果则保留未完成，不能用mock成功替代物理执行或真实鉴权。

M0 dependency refinement: immutable identity and admission scrubbing are verified independently first. The real SQL/HTTP fixture cannot seed workspaces before M1 or exercise live membership before M2; build it with those foundations and keep M0 final integration acceptance unchecked until then. This does not substitute shape validation for membership authorization.

### M1：租户与成员模型、增量迁移及个人空间回填

**修改接点：**
- `backend/packages/harness/deerflow/persistence/user/model.py`
- `backend/packages/harness/deerflow/persistence/thread_meta/model.py`
- `backend/packages/harness/deerflow/persistence/run/model.py`
- `backend/packages/harness/deerflow/persistence/projects/model.py`
- `backend/packages/ecs-executor/ecs_executor/schema.py`
- `backend/packages/ecs-executor/ecs_executor/job_store.py`

**新增文件：**
- `backend/packages/harness/deerflow/persistence/workspaces/model.py`
- `backend/packages/harness/deerflow/persistence/workspaces/sql.py`
- `backend/packages/harness/deerflow/persistence/workspaces/__init__.py`
- `scripts/tenant_migration.py`
- `backend/tests/test_workspace_migration.py`

**实现合同：** 按设计表合同追加原生和executor迁移（版本在实现时按当前head生成）；资源添加workspace索引及父子一致性检查；回填已知owner个人空间，隔离无owner资源。处理本地memory store与SQL repository一致性，迁移脚本提供plan/apply/verify命令且apply要求drain及维护回执。

**验收结果：** 空库及0035/e0001隔离副本升级成功；8 runs/4 mcp_tasks/12 execution jobs等既有实际记录按清单校验保留而非硬编码业务数量；重复回填幂等，冲突记录不开放。

- [ ] 1. 阅读上述模块指南及入口调用链，把该验收场景写成最小失败检查（复用共享fixture和原生身份，不mock掉授权边界）。
- [ ] 2. 在专属Jenkins工作空间运行下述定向命令，保存预期失败；依赖未就绪产生的导入错误不算业务RED证据。
- [ ] 3. 按实现合同新增/修改上述模块；涉及ORM必须同时添加迁移，涉及用户行为同步API及界面文案。每项开始先将此工作包展开为具体函数/测试的小步变更，避免凭总计划一次生成整个模块。
- [ ] 4. 重跑同一检查至通过，执行受影响模块lint/format或前端check；记录源码commit、环境及结果，不扩大到无关全套。
- [ ] 5. 自审权限、幂等和错误处理，保存回执；显式git add本任务文件后提交，再勾OpenSpec对应任务。

```bash
python -m pytest tests/test_workspace_migration.py -q
```

预期：对应主干通过；若无法证明上述验收结果则保留未完成，不能用mock成功替代物理执行或真实鉴权。

M1 integration dependency: schema, explicit attribution, guarded phase receipts and async workspace storage precede M2. Original deployment-data inventory, physical drain/backup collectors and NAS/release verification need the M10 generation; retain those acceptance gates rather than claim foundation tests prove the deployed migration. M0 live fixture integration likewise closes with M2/M3. Functional foundations continue in dependency order while cross-package acceptance stays unchecked.

### M2：统一空间授权、成员与管理员开通API

**修改接点：**
- `backend/app/gateway/authz.py`
- `backend/app/gateway/auth_middleware.py`
- `backend/app/gateway/routers/admin_users.py`
- `backend/packages/harness/deerflow/authz/principal.py`
- `backend/packages/harness/deerflow/authz/provider.py`

**新增文件：**
- `backend/app/gateway/workspaces/service.py`
- `backend/app/gateway/workspaces/dependencies.py`
- `backend/app/gateway/routers/workspaces.py`
- `backend/app/gateway/routers/admin_workspaces.py`
- `backend/tests/test_workspace_membership.py`

**实现合同：** 实现服务端WorkspaceContext解析与成员权限；管理员开通调用统一provisioning；创建/列举/选择空间，邀请角色验证、移除/退出、owner转让；锁workspace行保持恰好一位owner。平台角色不能读取无成员关系的内容。

**验收结果：** 管理员开通空间后指定owner可登录使用；owner/admin/member遵循权限表；并发转让/退出不会失去owner；跨空间ID请求404。

- [ ] 1. 阅读上述模块指南及入口调用链，把该验收场景写成最小失败检查（复用共享fixture和原生身份，不mock掉授权边界）。
- [ ] 2. 在专属Jenkins工作空间运行下述定向命令，保存预期失败；依赖未就绪产生的导入错误不算业务RED证据。
- [ ] 3. 按实现合同新增/修改上述模块；涉及ORM必须同时添加迁移，涉及用户行为同步API及界面文案。每项开始先将此工作包展开为具体函数/测试的小步变更，避免凭总计划一次生成整个模块。
- [ ] 4. 重跑同一检查至通过，执行受影响模块lint/format或前端check；记录源码commit、环境及结果，不扩大到无关全套。
- [ ] 5. 自审权限、幂等和错误处理，保存回执；显式git add本任务文件后提交，再勾OpenSpec对应任务。

```bash
python -m pytest tests/test_workspace_membership.py -q
```

预期：对应主干通过；若无法证明上述验收结果则保留未完成，不能用mock成功替代物理执行或真实鉴权。

M2 startup integration: production create_app registers the management routers.
The native database bootstrap validates the frozen operator setting before
checkpointer/Store creation and runtime recovery. Current builds refuse enabled
mode until M3-M11 scope/release coverage is implemented; any existing team row
refuses legacy startup. This staged refusal is a safety gate, not completed
multi-tenant admission. Keep M2 final acceptance unchecked until a real operator
provisioned workspace can use the fully scoped Gateway.

### M3：原生资源、文件及客户端空间切换贯通

**修改接点：**
- `backend/app/gateway/routers/threads.py`
- `backend/app/gateway/routers/runs.py`
- `backend/app/gateway/routers/artifacts.py`
- `backend/app/gateway/routers/projects.py`
- `backend/app/gateway/routers/project_documents.py`
- `backend/packages/harness/deerflow/config/paths.py`
- `backend/packages/harness/deerflow/persistence/thread_meta/sql.py`
- `frontend/src/core/api/fetcher.ts`
- `frontend/src/core/api/api-client.ts`
- `frontend/src/core/auth/AuthProvider.tsx`

**新增文件：**
- `frontend/src/core/workspaces/api.ts`
- `frontend/src/core/workspaces/context.tsx`
- `frontend/src/components/workspace/workspace-switcher.tsx`
- `backend/tests/test_workspace_resources.py`
- `frontend/tests/unit/core/workspaces/switch.dom.test.tsx`

**实现合同：** 原生资源查询先做空间过滤再分页；文件路径/线程引用/checkpoint入口授权一致；API客户端携带选择符，SSE/WSS与下载执行同一核验；切换取消订阅并隔离query keys；默认会话私有、项目资料/报告显式共享。补齐入口清单列出的相关router与repository，禁止只改列出的示例路径。

**验收结果：** 同一用户在个人空间和团队空间各上传/提问/下载一份文件成功；切换后无旧数据闪现；未授权空间无法列举或直接读取。

- [ ] 1. 阅读上述模块指南及入口调用链，把该验收场景写成最小失败检查（复用共享fixture和原生身份，不mock掉授权边界）。
- [ ] 2. 在专属Jenkins工作空间运行下述定向命令，保存预期失败；依赖未就绪产生的导入错误不算业务RED证据。
- [ ] 3. 按实现合同新增/修改上述模块；涉及ORM必须同时添加迁移，涉及用户行为同步API及界面文案。每项开始先将此工作包展开为具体函数/测试的小步变更，避免凭总计划一次生成整个模块。
- [ ] 4. 重跑同一检查至通过，执行受影响模块lint/format或前端check；记录源码commit、环境及结果，不扩大到无关全套。
- [ ] 5. 自审权限、幂等和错误处理，保存回执；显式git add本任务文件后提交，再勾OpenSpec对应任务。

```bash
python -m pytest tests/test_workspace_resources.py -q
```

预期：对应主干通过；若无法证明上述验收结果则保留未完成，不能用mock成功替代物理执行或真实鉴权。

M3 private file checkpoint: Jenkins #20 reproduced missing persisted scope on both
native databases; #21 verified real production shelf upload/list/count/content/trash,
header/query download selectors and denial before bytes when policy changed after
response preparation, plus two legacy shelf regressions (4 passed, 22.68s). Exact
archives/source hashes live in the progress JSON. Scope-aware thread attachment,
shared ACLs, conversion/maintenance, frontend/cache and NAS/release gates remain
required; do not check the parent M3 package yet.

M3 shared file checkpoint: Jenkins #22 rejected the explicit sharing request on
both databases. #23 passed the native-auth shared file main (member read/write
denial, admin upload retaining creator, shared deletion across authors), both
legacy private-default upgrades, startup and paired-attribution generation checks,
unchanged ancestry and two native mains (11 passed, 40.55s). #24 separately passed
the actual offline paired CLI main on both databases (2 passed, 25.66s). Current
native head is 0037_project_visibility; executor remains e0002_workspace_scope.
Thread attachment/conversion/maintenance, client/cache, physical files/NAS and
release evidence remain required. Parent M3 acceptance stays unchecked.

### M4：B/C、Scheduler、通知和撤权贯通

**修改接点：**
- `backend/packages/harness/deerflow/persistence/scheduled_tasks/sql.py`
- `backend/packages/harness/deerflow/persistence/scheduled_task_runs/sql.py`
- `backend/packages/harness/deerflow/mcp/tasks/ordinary.py`
- `backend/packages/harness/deerflow/mcp/tasks/runtime.py`
- `backend/packages/ecs-executor/ecs_executor/scope.py`
- `backend/packages/ecs-executor/ecs_executor/agent_dispatch.py`
- `backend/packages/ecs-executor/ecs_executor/dependencies.py`
- `backend/packages/ecs-executor/ecs_executor/publication.py`
- `backend/packages/ecs-executor/ecs_executor/browser.py`

**新增文件：**
- `backend/tests/test_workspace_execution.py`
- `backend/tests/test_workspace_revocation.py`

**实现合同：** 空间写入可信RunContext、持久Run/MCP/occurrence/执行账与签名；验证协议版本和父子归属；claim/adopt、外部写工具、发布、续跑/通知重查成员。撤权持久outbox触发原生取消，浏览器会话撤销，未知工作继续占资源。后台不取前端active workspace。

**验收结果：** 一个空间的一次确定性C→B→C仍使用原生任务权威；切换UI空间不改变运行归属；移除成员阻止queued启动与后续发布，物理STOP未确认不释放容量。

- [ ] 1. 阅读上述模块指南及入口调用链，把该验收场景写成最小失败检查（复用共享fixture和原生身份，不mock掉授权边界）。
- [ ] 2. 在专属Jenkins工作空间运行下述定向命令，保存预期失败；依赖未就绪产生的导入错误不算业务RED证据。
- [ ] 3. 按实现合同新增/修改上述模块；涉及ORM必须同时添加迁移，涉及用户行为同步API及界面文案。每项开始先将此工作包展开为具体函数/测试的小步变更，避免凭总计划一次生成整个模块。
- [ ] 4. 重跑同一检查至通过，执行受影响模块lint/format或前端check；记录源码commit、环境及结果，不扩大到无关全套。
- [ ] 5. 自审权限、幂等和错误处理，保存回执；显式git add本任务文件后提交，再勾OpenSpec对应任务。

```bash
python -m pytest tests/test_workspace_execution.py tests/test_workspace_revocation.py -q
```

预期：对应主干通过；若无法证明上述验收结果则保留未完成，不能用mock成功替代物理执行或真实鉴权。

### M5：记忆、知识检索与工具凭据隔离

**修改接点：**
- `backend/packages/harness/deerflow/agents/memory/backends/deermem/deer_mem.py`
- `backend/app/gateway/routers/memory.py`
- `backend/app/gateway/routers/knowledge.py`
- `backend/app/gateway/routers/personal_mcp.py`
- `backend/app/gateway/routers/integrations.py`
- `backend/app/gateway/routers/plugins.py`
- `backend/app/gateway/routers/skills.py`

**新增文件：**
- `backend/app/gateway/workspaces/connections.py`
- `backend/app/gateway/workspaces/knowledge.py`
- `backend/tests/test_workspace_context_sources.py`

**实现合同：** 实现workspace_connections/knowledge_bindings，复用现有加密与provider接口；记忆事实和检索索引按空间及可见范围分区。服务器限制dataset_id和工具连接，不能客户端任意指定；不把用户私人记忆自动注入团队prompt。平台插件接口保留平台权限。空间连接吊销后旧任务无法再用。

**验收结果：** A/B各含唯一哨兵文本，直接读取、检索、prompt构建及跨线程引用均不串用；成员可用空间连接但无法读密钥；全局插件安装仍拒绝租户admin。

- [ ] 1. 阅读上述模块指南及入口调用链，把该验收场景写成最小失败检查（复用共享fixture和原生身份，不mock掉授权边界）。
- [ ] 2. 在专属Jenkins工作空间运行下述定向命令，保存预期失败；依赖未就绪产生的导入错误不算业务RED证据。
- [ ] 3. 按实现合同新增/修改上述模块；涉及ORM必须同时添加迁移，涉及用户行为同步API及界面文案。每项开始先将此工作包展开为具体函数/测试的小步变更，避免凭总计划一次生成整个模块。
- [ ] 4. 重跑同一检查至通过，执行受影响模块lint/format或前端check；记录源码commit、环境及结果，不扩大到无关全套。
- [ ] 5. 自审权限、幂等和错误处理，保存回执；显式git add本任务文件后提交，再勾OpenSpec对应任务。

```bash
python -m pytest tests/test_workspace_context_sources.py -q
```

预期：对应主干通过；若无法证明上述验收结果则保留未完成，不能用mock成功替代物理执行或真实鉴权。

### M6：自助注册、邮箱验证、邀请接受和密码恢复

**修改接点：**
- `backend/app/gateway/routers/auth.py`
- `backend/app/gateway/auth/local_provider.py`
- `backend/app/gateway/auth/models.py`
- `backend/app/gateway/auth/pat.py`
- `backend/packages/harness/deerflow/config/auth_config.py`
- `frontend/src/app/(auth)/login/page.tsx`

**新增文件：**
- `backend/app/gateway/auth/account_lifecycle.py`
- `backend/app/gateway/auth/mail_delivery.py`
- `frontend/src/app/(auth)/verify-email/page.tsx`
- `frontend/src/app/(auth)/forgot-password/page.tsx`
- `frontend/src/app/(auth)/reset-password/page.tsx`
- `frontend/src/app/(auth)/accept-invitation/page.tsx`
- `backend/tests/test_account_lifecycle.py`

**实现合同：** 扩展原生register为多租户模式pending/统一202、验证后幂等开户；统一管理员/自助provisioning；单次token哈希+加密邮件outbox；邀请绑定verified邮箱；重置递增token_version并撤销PAT；Redis分布式限流失败关闭，邮件提供方配置缺失禁止公开开户。保留单用户模式原合同。

**验收结果：** 用户真实收信验证后获得个人空间，接受团队邀请；重复/过期/错邮箱拒绝；GET预取不消费；重置后旧session/PAT失效；正常管理员开通仍可用。

- [ ] 1. 阅读上述模块指南及入口调用链，把该验收场景写成最小失败检查（复用共享fixture和原生身份，不mock掉授权边界）。
- [ ] 2. 在专属Jenkins工作空间运行下述定向命令，保存预期失败；依赖未就绪产生的导入错误不算业务RED证据。
- [ ] 3. 按实现合同新增/修改上述模块；涉及ORM必须同时添加迁移，涉及用户行为同步API及界面文案。每项开始先将此工作包展开为具体函数/测试的小步变更，避免凭总计划一次生成整个模块。
- [ ] 4. 重跑同一检查至通过，执行受影响模块lint/format或前端check；记录源码commit、环境及结果，不扩大到无关全套。
- [ ] 5. 自审权限、幂等和错误处理，保存回执；显式git add本任务文件后提交，再勾OpenSpec对应任务。

```bash
python -m pytest tests/test_account_lifecycle.py tests/test_local_registration_gate.py -q
```

预期：对应主干通过；若无法证明上述验收结果则保留未完成，不能用mock成功替代物理执行或真实鉴权。

### M7：团队管理、注册与共享资料界面

**修改接点：**
- `frontend/src/core/auth/AuthProvider.tsx`
- `frontend/src/core/auth/types.ts`
- `frontend/src/app/workspace/layout.tsx`
- `frontend/src/core/knowledge/scope-api.ts`
- `frontend/src/core/projects/api.ts`

**新增文件：**
- `frontend/src/app/workspace/team/page.tsx`
- `frontend/src/app/workspace/settings/workspace/page.tsx`
- `frontend/src/components/workspace/team/member-list.tsx`
- `frontend/src/components/workspace/team/invite-dialog.tsx`
- `frontend/tests/e2e-real-backend/workspace-onboarding.spec.ts`
- `frontend/playwright.tenant.config.ts`（新增，复用现有Playwright配置并指定真实后端baseURL与隔离账号）

**实现合同：** 实现空间创建与选择、待验证提示、邀请接受、成员操作、owner转让、共享资料选择及成员退出；空间/账号关闭、配额、审计页面在M8与真实后端一起完成，不用成功mock冒充就绪；后端错误用用户语言呈现。路由保护只是体验层，权限仍在服务端。所有新文本加入既有国际化资源，隐藏无权限操作且不缓存上一空间结果。

**验收结果：** 浏览器完成管理员开通和客户自注册两条主干，各可建立团队邀请成员；第二标签页切换不会改写第一标签页运行归属；错误不暴露内部堆栈。

- [ ] 1. 阅读上述模块指南及入口调用链，把该验收场景写成最小失败检查（复用共享fixture和原生身份，不mock掉授权边界）。
- [ ] 2. 在专属Jenkins工作空间运行下述定向命令，保存预期失败；依赖未就绪产生的导入错误不算业务RED证据。
- [ ] 3. 按实现合同新增/修改上述模块；涉及ORM必须同时添加迁移，涉及用户行为同步API及界面文案。每项开始先将此工作包展开为具体函数/测试的小步变更，避免凭总计划一次生成整个模块。
- [ ] 4. 重跑同一检查至通过，执行受影响模块lint/format或前端check；记录源码commit、环境及结果，不扩大到无关全套。
- [ ] 5. 自审权限、幂等和错误处理，保存回执；显式git add本任务文件后提交，再勾OpenSpec对应任务。

```bash
python scripts/pnpm.py exec playwright test --config=playwright.tenant.config.ts workspace-onboarding
```

预期：对应主干通过；若无法证明上述验收结果则保留未完成，不能用mock成功替代物理执行或真实鉴权。

### M8：配额、用量、审计和空间生命周期

**修改接点：**
- `backend/packages/ecs-executor/ecs_executor/scheduling.py`
- `backend/packages/harness/deerflow/persistence/run/sql.py`
- `backend/app/gateway/routers/artifacts.py`

**新增文件：**
- `backend/app/gateway/workspaces/quotas.py`
- `backend/app/gateway/workspaces/audit.py`
- `backend/app/gateway/workspaces/lifecycle.py`
- `backend/app/gateway/workspaces/outbox.py`
- `backend/tests/test_workspace_operations.py`
- `frontend/src/components/workspace/team/lifecycle-dialog.tsx`
- `frontend/src/components/workspace/team/usage-panel.tsx`

**实现合同：** 原子空间准入预留和幂等usage事件；存储上传预留、超额拒绝；审计记录脱敏actor/action/outcome；停用递增policy_version并取消，未知STOP维持suspending；关闭执行保留期和幂等purge；账户关闭先转让/关闭其团队。配置模型费用仅提示不保证币值硬上限。

**验收结果：** A达到并发/任务/存储额度不影响B；同一结果重复回报不重计；停用无新启动、恢复无自动重放；最后owner无法直接销号；保留期与清理回执可查。

- [ ] 1. 阅读上述模块指南及入口调用链，把该验收场景写成最小失败检查（复用共享fixture和原生身份，不mock掉授权边界）。
- [ ] 2. 在专属Jenkins工作空间运行下述定向命令，保存预期失败；依赖未就绪产生的导入错误不算业务RED证据。
- [ ] 3. 按实现合同新增/修改上述模块；涉及ORM必须同时添加迁移，涉及用户行为同步API及界面文案。每项开始先将此工作包展开为具体函数/测试的小步变更，避免凭总计划一次生成整个模块。
- [ ] 4. 重跑同一检查至通过，执行受影响模块lint/format或前端check；记录源码commit、环境及结果，不扩大到无关全套。
- [ ] 5. 自审权限、幂等和错误处理，保存回执；显式git add本任务文件后提交，再勾OpenSpec对应任务。

```bash
python -m pytest tests/test_workspace_operations.py -q
```

预期：对应主干通过；若无法证明上述验收结果则保留未完成，不能用mock成功替代物理执行或真实鉴权。

### M9：个人研究与定期跟进业务主干

**修改接点：**
- `frontend/src/components/workspace/scheduled-tasks`
- `backend/packages/harness/deerflow/persistence/scheduled_tasks/sql.py`

**新增文件：**
- `skills/public/personal-research/SKILL.md`
- `backend/tests/test_workspace_research_flow.py`
- `docs/tenant-workspaces-user-guide.md`

**实现合同：** 用原生Skill和项目文件实现来源可追溯报告、人工确认后定期跟进；新资料产生一次更新报告。共享报告显式发布，私有记忆不夹带。确定性接线通过后仅跑一条DeepSeek真实研究+更新，知识提供方仅验证已有一个适配，不引入新Agent或新向量库。

**验收结果：** 报告来源指向该空间真实文档及版本；更新说明新增信息；用户可以暂停；另一空间无法访问来源、报告或定时结果。

- [ ] 1. 阅读上述模块指南及入口调用链，把该验收场景写成最小失败检查（复用共享fixture和原生身份，不mock掉授权边界）。
- [ ] 2. 在专属Jenkins工作空间运行下述定向命令，保存预期失败；依赖未就绪产生的导入错误不算业务RED证据。
- [ ] 3. 按实现合同新增/修改上述模块；涉及ORM必须同时添加迁移，涉及用户行为同步API及界面文案。每项开始先将此工作包展开为具体函数/测试的小步变更，避免凭总计划一次生成整个模块。
- [ ] 4. 重跑同一检查至通过，执行受影响模块lint/format或前端check；记录源码commit、环境及结果，不扩大到无关全套。
- [ ] 5. 自审权限、幂等和错误处理，保存回执；显式git add本任务文件后提交，再勾OpenSpec对应任务。

```bash
python -m pytest tests/test_workspace_research_flow.py -q
```

预期：对应主干通过；若无法证明上述验收结果则保留未完成，不能用mock成功替代物理执行或真实鉴权。

### M10：隔离副本迁移、恢复与Jenkins交付

**修改接点：**
- `scripts/ecs_native_release.py`
- `scripts/ecs_native_release_host.py`
- `examples/ecs-native/deploy/Jenkinsfile.native-release`
- `docs/ecs-native-deployment.md`

**新增文件：**
- `scripts/tenant_release_migrate.py`
- `examples/ecs-native/deploy/Jenkinsfile.tenant-acceptance`
- `docs/tenant-workspaces-migration.md`
- `docs/tenant-workspaces-testing.md`
- `backend/tests/test_tenant_release_contract.py`

**实现合同：** 为新schema定义新版本release manifest和独立迁移阶段；drain/物理STOP/备份恢复演练→两库升级→NAS复制映射校验→匹配新协议角色启动→授权smoke。旧release继续拒绝跨schema更新。迁移先在独立DB/命名空间演练，不能覆盖历史上海验收。Jenkins只使用DeerFlow专属任务与原资源限制。

**验收结果：** 断在metadata升级后仍不放行，重入读取回执并安全继续；成套备份能恢复原镜像与数据；跨schema仅镜像回滚被拒绝；新源码/镜像/数据库版本一致。

- [ ] 1. 阅读上述模块指南及入口调用链，把该验收场景写成最小失败检查（复用共享fixture和原生身份，不mock掉授权边界）。
- [ ] 2. 在专属Jenkins工作空间运行下述定向命令，保存预期失败；依赖未就绪产生的导入错误不算业务RED证据。
- [ ] 3. 按实现合同新增/修改上述模块；涉及ORM必须同时添加迁移，涉及用户行为同步API及界面文案。每项开始先将此工作包展开为具体函数/测试的小步变更，避免凭总计划一次生成整个模块。
- [ ] 4. 重跑同一检查至通过，执行受影响模块lint/format或前端check；记录源码commit、环境及结果，不扩大到无关全套。
- [ ] 5. 自审权限、幂等和错误处理，保存回执；显式git add本任务文件后提交，再勾OpenSpec对应任务。

```bash
python -m pytest tests/test_tenant_release_contract.py -q
```

预期：对应主干通过；若无法证明上述验收结果则保留未完成，不能用mock成功替代物理执行或真实鉴权。

### M11：集中边界验收、文档与发布结论

**修改接点：**
- `README.md`
- `README_zh.md`
- `AGENTS.md`
- `backend/AGENTS.md`
- `frontend/AGENTS.md`

**新增文件：**
- `docs/tenant-workspaces-acceptance.md`

**实现合同：** 主干通过后按需求映射执行必要边界，记录真实邮件、注册、团队、研究/更新、隔离、撤权、迁移及恢复证据；逐项说明限制。更新开发指南、API文档、操作与恢复文档；OpenSpec只勾实际完成任务，实际外部开放单独显式开关。

**验收结果：** 两种开户入口及同一业务能力均通过，没有未覆盖的租户入口；失败历史保留；具备邮件配置、隔离和迁移证据后才允许公开注册。

- [ ] 1. 阅读上述模块指南及入口调用链，把该验收场景写成最小失败检查（复用共享fixture和原生身份，不mock掉授权边界）。
- [ ] 2. 在专属Jenkins工作空间运行下述定向命令，保存预期失败；依赖未就绪产生的导入错误不算业务RED证据。
- [ ] 3. 按实现合同新增/修改上述模块；涉及ORM必须同时添加迁移，涉及用户行为同步API及界面文案。每项开始先将此工作包展开为具体函数/测试的小步变更，避免凭总计划一次生成整个模块。
- [ ] 4. 重跑同一检查至通过，执行受影响模块lint/format或前端check；记录源码commit、环境及结果，不扩大到无关全套。
- [ ] 5. 自审权限、幂等和错误处理，保存回执；显式git add本任务文件后提交，再勾OpenSpec对应任务。

```bash
openspec validate tenant-workspaces-self-service --strict
```

预期：对应主干通过；若无法证明上述验收结果则保留未完成，不能用mock成功替代物理执行或真实鉴权。

## 对外API目标清单

- 复用 `/api/v1/auth/register`、`/login/local`、`/me`、`/change-password`；新增 `/verify-email`、`/resend-verification`、`/password-reset/request`、`/password-reset/confirm`、账户关闭接口。
- 新增 `/api/workspaces`、`/{id}/members`、`/{id}/invitations`、`/{id}/ownership-transfer`、`/{id}/leave`、`/{id}/close`、`/{id}/usage`、`/{id}/connections`。已有资源API保持原路径，增加可信空间解析。
- 管理端 `/api/admin/workspaces`、`/{id}/suspend`、`/{id}/restore`、`/{id}/quotas`；平台操作不获得资源内容通行证。
- 所有写接口保留原CSRF/认证保护；限流429、无有效成员403、越界对象404、owner/生命周期冲突409；公开注册/找回发送统一202。

## 发布前必须具备的配置

平台域名与HTTPS、邮件发送服务/发件域和测试收件箱、空间资源默认上限、保留期限、共享Redis、主密钥及其恢复方法。实施时先用隔离邮件接收器完成开发；真实邮件配置缺失只阻止外部注册验收，不阻止其他代码工作。不得为了取key打印现有私有配置。

## 完成定义

M0—M11全部有证据；管理员开通和自助注册同版可用；真实研究与一次更新完成；重点越权/撤权/恢复通过；发布后的版本、schema、文件归属一致。公开注册开关由操作者显式启用。付费/SSO新集成/复杂角色/生产容量承诺不计入本次。

实施进展与定向验收写入 `docs/tenant-workspaces-progress.json`。只有整个工作包的验收证据齐备才勾选对应任务；已有基础提交不等于完整交付。

## 实施工作量与拆分规则

这是跨认证、持久化、执行、文件和前端的产品改动，不能按“加注册页”的小功能估算。M0完成入口与数据清单后，再按实际改动量更新各项工期；当前不承诺固定上线日期。M3/M7/M9/M10分别提供可演示的检查点，但只有M11通过才算统一需求交付完成。

工作包不是一次大提交。M1按新表/资源归属/回填/两库协议拆小步；M3按repository/REST/流式文件/前端切换拆小步；M4按准入/claim/撤权/续跑拆小步。每个小步先明确一个可失败的行为和精确修改文件，再最小实现、定向验证、提交。不得在细化过程中把管理员或客户自助移出本次范围。

M3 private thread checkpoint: Jenkins #25 failed on missing persisted workspace in both databases. #26 passed the SQLite/PostgreSQL owner-private thread repository main, existing project/file HTTP main and three legacy thread checks (7 passed, 29.58s). Source hashes and limits are recorded in progress JSON. Thread HTTP admission, file references/checkpoint/run and client integration remain pending; no parent work-package acceptance is complete.

M3 metadata HTTP checkpoint: #27 failed at missing trusted scope on both databases; #28 passed 7 checks in 30.21s for actual native-auth thread metadata and project listing, SQL thread main and three native regressions. Persistent checkpoints, full thread lifecycle/files, Run/background and client integration remain pending. Full M3 acceptance stays unchecked.

M3 file transfer checkpoint: #29 RED at missing upload scope; #30 found a document-get signature error; #31 passed scoped actual-byte upload/attachment/promotion and two native transfer mains (6 passed, 30.99s). Source hashes and limits are in progress JSON. Artifact/query/before-send, deletion/withdrawal races, full lifecycle and physical remote mounts remain requirements; M3 stays unchecked.

M3 下载检查点：Jenkins #33 在 SQLite/PostgreSQL 实际 HTTP 主干和三项原生回归通过（5 passed，27.51s）。上传链接携带空间定位，文件/ZIP 成员在响应准备后撤权时拒绝发送；#32 RED 保留。下一项为文件删除撤权竞态，再继续完整线程生命周期与客户端；M3 不勾完成。

M3 删除检查点：#34 RED 复现撤权后响应拒绝但文件已删除；#35 GREEN（4 passed，26.75s）证明最后 SQL 授权与短文件操作受同一锁保护，撤权保留原始字节，有效权限正常删除。下一项继续会话状态/历史/目标及完整生命周期，后续客户端与物理挂载仍需验收。

M3 会话读取检查点：#38 验证原生编译图在持久化 SQLite checkpoint 关闭/重开后读取个人与团队状态、历史、目标及详情，并在跨空间或 SQL incarnation 改变时拒绝（6 passed，30.28s）；#36/#37 RED 保留。下一项为已读标记、状态/目标写入与分支/删除/压缩生命周期，再继续 Run/后台和客户端。Postgres checkpointer、跨进程/重启及 delta 验收仍需后续证据。

M3 已读标记检查点：#40 完成空间独立时钟、Run/私有父会话过滤、撤权不写标记、重复读取无变化、旧库升级保留和新回执 CLI（12 passed，54.07s）；#41 对最终异步 HTTP 排空改动复验（2 passed，30.34s）。原生当前 schema 0038，executor e0002；历史版本与回执不重写。下一项继续状态/目标写入与分支/删除/压缩；删除标记清理、活动流、Run、前端和物理发布仍需验收。

M3 native Run reads: #42 RED reproduced foreign-space disclosure in SQLite/PostgreSQL; #43 GREEN (8 passed, 21.74s). Native reads/cursors/keyset/source/batch/token reduction use matching private Run/thread workspace and live policy; required scope is captured at bootstrap. Actual withdrawal and four legacy read behaviors verified. Admission/reservations, HTTP feeds/streams, background recovery and frontend remain incomplete; M3 stays unchecked.

M3 non-run reservation checkpoint: #44 RED NULL workspace; #45 GREEN (7 passed, 21.58s). Actual SQLite/PostgreSQL native RunManager reservations persist private scope and exclude peer admission. Captured user/space/worker release survives policy withdrawal and selection changes, refuses wrong-worker and normal Run deletion, and hides foreign idempotency payloads. Three native compatibility tests retained. HTTP goal/state/new-thread behavior, cancellation/leases/recovery and normal-run M4 remain required; M3 stays unchecked.

M3 native goal/state writes: #46 RED missing scope; #47 RED new-chat allocation ordering; #48 HTTP fixture version mismatch (6 native regressions passed); #49 GREEN actual HTTP mains (2 passed, 33.24s). New goal allocation, state/title update, clear, foreign denial and SQL policy/incarnation changes preserving checkpoint IDs are verified. #48→#49 differs only in the native saver version fixture. Graph preparation stays outside final live SQL commit fencing. PostgreSQL checkpoint, cancellation/crash, full lifecycle/feed/client and M4 remain incomplete; M3 stays unchecked.

M3 write identity follow-up: #50 RED actual owner-check incarnation replacement still admitted goal write; #51 GREEN (8 passed, 34.31s), all three goal/state/clear replacement windows refused with unchanged checkpoint IDs plus both HTTP mains and six native regressions. Final source bytes match the #51 archive. Original request identity is preserved before owner-check and through final live commit; M3 full lifecycle/feed/client acceptance remains pending.

M3 checkpoint-only admission: #52 RED actual legacy checkpoint ID claimed by scoped POST thread; #53 GREEN (8 passed, 35.22s), root-only IDs refused for POST thread/new goal, subgraph-only IDs refused, no metadata or checkpoint mutation, and a real native goal committed between allocation and initialization remains intact. Six affected native creation/goal regressions passed. Durable SQLite checkpoint with both metadata dialects; mixed-version/physical inventory/restore and remaining branch/delete/compact/feed/client acceptance stay pending. M3 remains unchecked.

M3 native branches: #54 RED missing scope; #55 GREEN (8 passed, 35.34s). Actual SQLite/PostgreSQL metadata with native SQLite graph checkpoints proves private child/project ownership, exact source/child file bytes, own-only history, shared peer denial and source-incarnation replacement refusing new metadata. Six native full/delta/history/file/project regressions passed. Prepared checkpoints publish under source SQL fencing after file staging; cross-store faults and unpublished-stage reconciliation remain M4/M8/M10/M11 requirements. Delete/compact/feed/client and full M3 remain unchecked.

M3 manual compaction: #56 RED missing scope; #57 GREEN (8 passed, 36.66s). Actual native middleware/graph/SQL with deterministic model output persists summary and latest-message retention, refuses generation-span policy/incarnation changes without checkpoint writes, and refuses snapshot replacement/foreign/peer access before model calls. Six native mutation/schema/noop/failure/binding/busy regressions passed. Scoped memory/archive disabled; live model/M5 effects, delete/feed/client, fault recovery and full M3 remain pending.

M3 deletion checkpoint: #58 missing-scope RED; #59 fixture signature failure;
#60 real delete/recreate stale multipart cleanup RED; #61 both HTTP mains pass
with one stale cancellation unit entry; #62 GREEN (10 passed, 39.38s). Private
tombstones/receipts fence local cleanup, child attribution and same-ID reuse;
file publication/cleanup/unlink checks captured incarnation. Remote STOP,
unknown cleanup recovery, Run cache/background feeds, client and all remaining
M4–M11 evidence remain required. M3 stays unchecked and activation closed.
