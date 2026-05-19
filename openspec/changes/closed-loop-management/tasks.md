## 1. 数据层与迁移

- [ ] 1.1 在 `backend/packages/harness/deerflow/persistence/models/closure_ticket.py` 新增 `ClosureTicket` 与 `ClosureTicketEvent` 两个 SQLAlchemy 模型，包含必要列、索引与唯一约束 `(tenant_id, source_type, source_run_id, device_id)`
- [ ] 1.2 在 `persistence/migrations/versions/` 新增 alembic 迁移：建表、建索引、播种默认 SLA 配置（urgent=4h / important=72h / normal=7d / observe=30d）
- [ ] 1.3 在 `persistence/models/__init__.py` 暴露新模型，确保 alembic autogenerate 可见
- [ ] 1.4 编写迁移正/反向回滚测试（`alembic upgrade` + `alembic downgrade` 在 sqlite + postgres 两种后端下均可通过）

## 2. 闭环领域服务

- [ ] 2.1 新建 `backend/packages/harness/deerflow/closed_loop/` 子包，包含 `__init__.py`、`schemas.py`、`repository.py`、`state_machine.py`、`service.py`、`events.py`
- [ ] 2.2 在 `schemas.py` 用 Pydantic 定义请求/响应 DTO 与 `metadata` 按 `source_type` 的 discriminated union schema
- [ ] 2.3 在 `state_machine.py` 实现状态枚举 `ClosureStatus`、动作枚举 `ClosureAction`，以及 `transition(ticket, action, actor, payload)` 校验函数
- [ ] 2.4 在 `repository.py` 实现 CRUD 与受筛选条件控制的 `list(...)`，统一返回分页结果
- [ ] 2.5 在 `service.py` 实现 `create_ticket / get_ticket / list_tickets / update_ticket / transition / list_for_report` 高层 API，所有 API 在入口处做租户与权限校验
- [ ] 2.6 在 `events.py` 实现"状态迁移成功后"复用 `run_event` 通道发布 `closure.<action>` 事件的封装
- [ ] 2.7 引入 `closure:read | closure:write | closure:verify` 三个权限点的常量，注入到现有 RBAC 注册表
- [ ] 2.8 单元测试覆盖：状态机所有合法/非法迁移、幂等去重、租户隔离、权限校验、SLA `due_at` 计算

## 3. Gateway REST 路由

- [ ] 3.1 新增 `backend/app/gateway/routers/closure_tickets.py`：`POST /api/closure/tickets`、`GET /api/closure/tickets`、`GET /api/closure/tickets/{id}`、`PATCH /api/closure/tickets/{id}`（不接受 `status` 字段）、`POST /api/closure/tickets/{id}/transition`
- [ ] 3.2 在 `closure_tickets.py` 实现 `GET /api/closure/notifications/summary` 待办聚合接口
- [ ] 3.3 在 FastAPI app 主入口注册新路由，复用现有 `auth` 依赖并按权限点分别守卫
- [ ] 3.4 路由级别集成测试：覆盖正/反路径、403、409、422、分页与时间窗筛选

## 4. 后台超期扫描任务

- [ ] 4.1 在 `closed_loop/jobs.py` 实现每 5 分钟一次的 asyncio 周期任务，使用 PG advisory lock 防止多副本重复扫描
- [ ] 4.2 在 FastAPI startup 钩子中启动该任务，shutdown 钩子中优雅停止
- [ ] 4.3 扫描循环异常捕获并以 ERROR 级别日志记录，确保下一周期继续执行
- [ ] 4.4 集成测试：注入若干过期单据，运行一轮扫描后断言 `is_overdue` 与 `closure.overdue` 事件被正确写入

## 5. Builtin 工具

- [ ] 5.1 在 `harness/deerflow/tools/builtins/closure_ticket_tools.py` 实现 `create_closure_ticket` / `list_closure_tickets` / `update_closure_ticket` / `close_closure_ticket` 四个工具，全部委派给 `closed_loop.service`
- [ ] 5.2 在 builtin 工具注册表中注册新工具，并在 `update_closure_ticket` 中显式忽略 `status` 字段并返回提示
- [ ] 5.3 工具级单元测试：参数 schema 校验、幂等返回、状态直写被拒、租户/权限错误正确传播

## 6. 报告模板闭环区块

- [ ] 6.1 在 `report_templates/schema.py` 中扩展 step 节点，允许 `block_type: closure_section` 与对应 `filters` 配置
- [ ] 6.2 在 `report_templates/runtime/step_renderer.py` 中分发 `closure_section` 到新增的渲染函数，由其调用 `closed_loop.service.list_for_report`
- [ ] 6.3 渲染器无数据时输出占位文本，旧模板（无该块类型）保持完全无变化
- [ ] 6.4 在 `validator.py` 中校验 `closure_section` 的 filters 结构
- [ ] 6.5 报告模板渲染测试：包含 `closure_section` 的模板能正确渲染表格；旧模板回归测试通过

## 7. Agent SOUL 与 config 升级

- [ ] 7.1 更新 `agents/builtin/defect-closure/SOUL.md`：以闭环单为中心组织工作流（拉取→处置→提交验证→关闭）；同时在 `config.yaml` 中加入新工具依赖
- [ ] 7.2 更新 `agents/builtin/ai-report--closure/SOUL.md`：接入 `list_closure_tickets`，并按"已闭环 / 未闭环 / 超期未闭环"分段
- [ ] 7.3 更新 `agents/builtin/fault-diagnosis*/SOUL.md` 与 `config.yaml`：严重等级达标时调用 `create_closure_ticket`，并在回复中告知 ticket id
- [ ] 7.4 更新 `agents/builtin/ai-report--{daily,weekly,monthly,custom}/SOUL.md` 与 `config.yaml`：识别整改项时调用 `create_closure_ticket`，撤回时调用 `close_closure_ticket(reject)`
- [ ] 7.5 在 `agents/builtin/report-templates/` 中给关键模板示例附上 `closure_section` 用法示范

## 8. 前端 API 与状态层

- [ ] 8.1 新增 `frontend/src/core/closed-loop/types.ts` 与 `client.ts`，封装列表、详情、迁移、汇总四个端点
- [ ] 8.2 实现按筛选条件的 hooks（`useClosureTickets`、`useClosureTicket`、`useClosureSummary`）以及乐观更新逻辑
- [ ] 8.3 接入现有事件流，订阅 `closure.*` 事件并触发 hooks 缓存失效

## 9. 前端工作台 UI

- [ ] 9.1 新增路由 `frontend/src/app/workspace/closed-loop/page.tsx`，受 feature flag 与 `closure:read` 权限守卫
- [ ] 9.2 新增 `frontend/src/components/workspace/closed-loop/closure-list.tsx`：表格、筛选条、URL query 同步、超期高亮
- [ ] 9.3 新增 `closure-kanban.tsx`：按状态分列的只读看板视图
- [ ] 9.4 新增 `closure-detail-drawer.tsx`：完整字段、来源跳转链接、时间线（倒序）
- [ ] 9.5 新增 `closure-action-form.tsx`：按当前状态机可执行动作动态渲染表单（派单 / 开始 / 提交验证 / 验证关闭 / 退回）并接入权限校验
- [ ] 9.6 在 `workspace-nav-chat-list.tsx`（或对应导航文件）增加「闭环管理」入口，附带未关闭 / 超期数量徽标
- [ ] 9.7 视图切换、抽屉路由、表单错误提示等的组件级测试

## 10. E2E 与发布

- [ ] 10.1 编写 Playwright E2E：诊断 Agent 触发建单 → 在工作台派单 → 处置 → 提交验证 → 验证关闭，全链路通过
- [ ] 10.2 编写 Playwright E2E：日报 Agent 登记整改项 → 整改项出现在闭环列表 → 上周报告中可见整改追踪段落
- [ ] 10.3 在 `docs/` 下补充使用文档（仅当用户后续显式要求时再创建）；本期默认不写新文档
- [ ] 10.4 灰度发布检查清单：迁移已跑、feature flag 已下发到目标租户、Agent SOUL 已更新、监控指标（`closure.overdue` / `closure.closed`）面板已就绪
- [ ] 10.5 演练回滚：禁用 feature flag → revert Agent SOUL → 确认旧链路功能正常
