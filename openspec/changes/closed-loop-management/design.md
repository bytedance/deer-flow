## Context

DeerFlow 当前的设备运维链路由若干 Agent 组成：`fault-diagnosis*` 输出诊断结论、`monitoring-analysis` 给出运行评估、`ai-report--*` 系列生成日/周/月/自定义报告，`defect-closure` Agent 负责"缺陷闭环"。然而落到数据层面只有 thread/run 维度的对话记录与报告 artifact，没有以"设备问题/整改项"为中心的稳定实体；问题状态、责任人、SLA、验证依据散落在文字里，跨周期复核与超期识别无法机器化执行。

本次设计要解决的是把"闭环"从一组对话约定升级为一等公民的领域模型，并保证：
- 多个 Agent（诊断、报告、闭环 Agent）以**工具调用**而非自然语言协议来读写闭环数据，避免漂移。
- 现有 `harness/deerflow` 后端、FastAPI Gateway、Next.js workspace 三层都能各司其职。
- 与 `report_templates`、`run_event`、tenant/role/auth 等现有基础设施兼容，不引入新的运行时或存储。

主要约束：
- 后端持久化使用 SQLAlchemy + Alembic；新表必须按租户隔离（`tenant_id`）。
- 前端工作台基于 Next.js App Router + 现有 workspace 布局；导航通过 `workspace-nav-chat-list.tsx` 入口扩展。
- Agent 改动尽量保持向后兼容，旧对话不应因为新工具的存在而失败。
- 不新增第三方依赖（消息队列、外部任务调度）。

## Goals / Non-Goals

**Goals:**
- 提供一个跨 Agent、跨报告周期可被引用的「闭环单」实体（`ClosureTicket`）。
- 提供清晰的状态机和受控的状态迁移 API，所有状态变化可审计、可回放。
- 提供 Agent-friendly 的工具集，让 `fault-diagnosis*`、`ai-report--*`、`defect-closure` 通过工具完成绝大部分操作。
- 提供 workspace UI，让人工角色可以接单、处置、验证、回退、归档。
- 提供 SLA/超期/待办聚合能力，可被前端和 Agent 同时消费。
- 与 `report_templates` 集成：模板渲染时可拉取闭环单作为表格/列表块。

**Non-Goals:**
- 不实现复杂的工单流程引擎（多级会签、并行分支、动态表单设计器）——状态机为线性 + 少量旁支，足以覆盖本期需求。
- 不引入新的消息推送渠道（短信/邮件/微信），仅复用现有 `run_event` 与前端轮询/SSE。
- 不替换现有的 `defect-closure` Agent，仅升级其工作流。
- 不改动报告模板引擎核心契约；闭环区块以"扩展块类型"形式叠加，不破坏现有模板。
- 本期不实现移动端原生 UI，移动响应式由现有 workspace 布局承担。

## Decisions

### D1. 单表 + JSONB 字段 vs 多表关联

**选择**：闭环单使用单表 `closure_tickets` + JSONB `metadata` 字段承载来源/关联信息，通过若干索引列（`source_type`、`source_run_id`、`device_id`、`status`、`priority`、`due_at`）保证查询性能。

**理由**：
- 来源类型多样（诊断 run、巡检、报告 run、人工），多表关联会造成大量 LEFT JOIN，且各来源字段差异大。
- JSONB 在 PostgreSQL 上有原生索引，足以支持本期检索；后续若某来源需要重型查询再做物化视图。
- 与 `run_event` 表当前的设计风格一致（事件主表 + JSONB payload），团队心智成本低。

**备选**：每种来源一张关联表（`closure_diagnosis_links` / `closure_report_links` 等）。被否的原因：扩展新来源需要 schema 迁移，违背"工具一次接入即可"的目标。

### D2. 状态机：显式枚举 + 服务端集中校验

**选择**：定义 `ClosureStatus` 枚举：`pending | assigned | in_progress | pending_verification | closed | rejected | reopened`。所有状态迁移走 `closed_loop.state_machine.transition(ticket, action, actor, payload)`，禁止 Agent/前端直接 PATCH `status` 字段。

**理由**：
- 集中式校验避免 Agent 误操作（比如直接从 `pending` 跳到 `closed`）。
- 每次迁移自动写入 `closure_ticket_events` 审计表，便于复盘。
- 易于在 `transition` 内挂钩 SLA 计算、`run_event` 发布、通知触发。

**备选**：纯 CRUD + 业务层用断言检查。被否的原因：前期容易绕过、后期审计困难。

### D3. Agent 集成：四个 builtin tools，单一职责

**选择**：

| Tool | 作用 | 主要调用方 |
|------|------|-----------|
| `create_closure_ticket` | 由发现源（诊断/报告/巡检）创建一张闭环单 | `fault-diagnosis*`、`ai-report--{daily,weekly,monthly,custom}` |
| `list_closure_tickets` | 按设备/状态/责任人/时间窗检索 | `ai-report--closure`、`defect-closure` |
| `update_closure_ticket` | 受控字段更新（处置方案、责任人、备注、附件） | `defect-closure` |
| `close_closure_ticket` | 触发关闭/重开/拒绝等终态迁移 | `defect-closure`、`ai-report--closure` |

每个工具都内置租户/权限校验，且 `update`/`close` 两个工具不允许直接写 `status`，状态变化只能通过专用 `action` 参数。

**理由**：
- 工具粒度匹配语义动作，减少 Agent 学习成本。
- 与现有 `report_template_runtime_tools` 的拆分风格一致。
- 状态机校验在 service 层强制，工具层只是包装。

**备选**：单一巨型工具 `manage_closure_ticket`。被否的原因：参数空间膨胀、Agent 容易调用错误动作。

### D4. 报告模板集成：扩展块类型 `closure_section`

**选择**：在 `report_templates/schema.py` 中允许 `step` 节点声明 `block_type: closure_section`，运行时由 `step_renderer` 调用 `closed_loop.service.list_for_report(period, devices, ...)` 拉取数据并渲染表格/列表。

**理由**：
- 复用现有模板调度，避免在报告 Agent 内重复实现"按设备聚合待闭环单"的逻辑。
- 模板版本化机制天然适配"不同班组/项目要看不同维度"。

**备选**：在每个 `ai-report--*` Agent 的 SOUL 里写 prompt 让其自行调用 `list_closure_tickets`。被否的原因：每个报告 Agent 都要重复实现，且无法在不改 Agent 的前提下变更视觉样式。

### D5. 前端：列表 + 看板双视图，处置走抽屉

**选择**：默认列表视图（密集信息、可批量），提供按状态分列的看板视图（拖拽暂不实现，本期仅展示）。处置和验证均走右侧抽屉表单，不跳页。

**理由**：
- 与 workspace 现有的"主区 + 抽屉"风格一致（参考 agent-detail、knowledge-base-detail）。
- 列表/看板复用同一份 query hook，状态机推动 UI 状态。

### D6. 待办与超期：服务端计算，前端只展示

**选择**：`due_at` 由状态机在进入 `assigned` 时按 `priority` 写入；超期由后台轮询任务每 5 分钟扫描一次置 `is_overdue=true` 并发布 `closure.overdue` 事件。前端通过现有事件流刷新徽标。

**理由**：
- 前端不应承担时间判定，避免时区/时钟漂移导致显示与服务端不一致。
- 事件驱动让 Agent（如 `ai-report--closure`）也可以在事件发生时主动汇总。

**备选**：使用外部 cron / Celery。被否的原因：本仓库目前没有这些组件，引入成本高。改用 FastAPI startup 起一个 asyncio task；后续如需扩展再迁移。

### D7. 权限模型

**选择**：新增 `closure:read`、`closure:write`、`closure:verify` 三个权限点，分别对应"查看"、"派单/处置"、"验证关闭"。现有租户管理员默认获得全部三项；普通成员默认仅 `read`。

**理由**：
- 验证关闭与处置应分人执行（典型现场两班分离需求）。
- 与现有 RBAC 风格一致（细粒度、显式授予）。

## Risks / Trade-offs

- **[Risk] Agent 工具调用错误（如重复建单）** → Mitigation：`create_closure_ticket` 在 `source_type + source_run_id + device_id` 上加唯一约束，重复建单返回已有 ticket 的 id。
- **[Risk] 状态机与现实流程脱节** → Mitigation：状态枚举刻意保持精简，复杂流程通过备注/附件而非新增状态承载；后续若必须扩展，新增态需经 spec 修订流程。
- **[Risk] JSONB metadata 字段失控** → Mitigation：在 `service` 层定义 `metadata` 的 Pydantic schema，按 `source_type` 校验；不通过校验直接拒绝写入。
- **[Risk] 后台轮询任务在多副本部署下重复执行** → Mitigation：使用 PG advisory lock 包裹超期扫描；如未来切换到容器多副本，再切到分布式锁/调度器。
- **[Trade-off] 不引入流程引擎** → 取舍：换来的是简单可演进的状态机；如果未来需要并行任务、会签，需要专门 spec 替换本设计。
- **[Trade-off] 报告模板的闭环区块直接读 service** → 与"模板纯渲染"原则有一点冲突；通过把数据获取限定在 `closure_section` 这一块类型内，保持模板 DSL 整体只读特性。

## Migration Plan

1. **Schema 落库**：发布 Alembic 迁移创建 `closure_tickets` + `closure_ticket_events`，灰度环境先跑、确认无问题再到生产。
2. **后端服务上线**：闭环 service + REST 路由 + 工具注册；此时无 Agent 调用，仅 UI 可读写，便于 QA 闭环测试。
3. **Agent 升级**：先升级 `defect-closure`（自身改动）→ 再升级 `ai-report--closure`（消费方）→ 最后升级 `fault-diagnosis*` / `ai-report--{daily,weekly,monthly,custom}`（生产方）。每步可独立回滚（仅回退 SOUL.md / config.yaml）。
4. **前端发布**：workspace 新增「闭环管理」入口，feature flag 控制（`NEXT_PUBLIC_CLOSED_LOOP_ENABLED`），便于按租户开放。
5. **回滚策略**：
   - 数据层：迁移设计为可向前兼容，回滚仅回退 Alembic（前端隐藏入口即可，不丢数据）。
   - Agent 层：保留旧 SOUL.md 在 git 历史中，降级时直接 revert。
   - 前端层：feature flag 关闭即对用户不可见。

## Open Questions

- **OQ1**：跨租户的设备故障是否需要"问题模板库"复用历史处置方案？本期暂不实现，留待 `closed-loop-knowledge` 后续 change。
- **OQ2**：闭环单是否要支持子任务/拆单？短期看缺陷可在 `metadata.subtasks` 内承载，无需专门 schema；长期视使用反馈再决定。
- **OQ3**：超期 SLA 的具体阈值（紧急 4h / 重要 72h / 一般 7d / 观察 30d）需运维侧确认；本期先按此默认值落库，租户可在 admin 内调整。
