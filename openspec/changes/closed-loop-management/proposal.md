## Why

设备运维当前存在「断点」：故障诊断 Agent 输出诊断结论后，整改是否落地、何时关闭、效果如何，缺乏统一的数字化跟踪载体；日报/周报里识别出的整改项也无法回流到下一周期复核。结果是发现归发现、整改归整改，问题易反复、责任不清、无 SLA 可考核。

本期通过引入「闭环管理」核心域，把诊断结论、巡检发现、报告整改项统一抽象为「闭环单（Closure Ticket）」并以状态机驱动其生命周期，实现「发现 → 派单 → 处置 → 验证 → 归档」全链路在线，并与现有 `fault-diagnosis` / `ai-report--*` 系列 Agent 双向打通。

## What Changes

- 新增「闭环单」核心数据域：统一描述设备缺陷/异常/整改项，覆盖来源、严重等级、责任人、状态、SLA、验证依据、关联报告/诊断 run。
- 新增闭环单状态机与流转 API：`pending → assigned → in_progress → pending_verification → closed`（含 `rejected` / `reopened` 旁支）。
- 新增 Agent/Tool 集成：诊断结论达到阈值时由 `fault-diagnosis*` 通过工具自动建单；报告（日/周/月/自定义）中的整改项由 `ai-report--*` 通过工具登记追踪项；闭环报告 Agent (`ai-report--closure`) 自动汇总待关闭单据。
- 新增前端工作台「闭环管理」模块：列表 / 看板 / 详情 / 处置抽屉 / 验证表单。
- 新增超期与待办通知：基于 SLA 的超期标记、待办聚合、推送钩子（first-class，但只对接现有事件总线，不引入新通知通道）。
- **BREAKING**：`defect-closure` Agent 的工作流由仅 prompt 描述升级为基于闭环单的工具驱动流程，旧的纯对话式记单方式不再保证可追溯。

## Capabilities

### New Capabilities
- `closed-loop-tickets`: 闭环单的数据模型、状态机、来源/关联、SLA、检索查询能力。
- `closed-loop-agent-integration`: 诊断/报告 Agent 通过工具创建、查询、更新、关闭闭环单的接入契约（builtins tools + agent SOUL 约定）。
- `closed-loop-workspace`: 前端工作台的闭环单列表、看板、详情、处置与验证交互。
- `closed-loop-notifications`: 待办聚合、超期识别与推送规则（基于现有事件总线，不引入新渠道）。

### Modified Capabilities
*（无现有 capability 的 spec 在 `openspec/specs/` 中需要修改；现有 `defect-closure` 与 `ai-report--closure` Agent 仅有 SOUL.md，无独立 spec，行为变更在 `closed-loop-agent-integration` 中以约定形式表达。）*

## Impact

- 后端
  - 新增 `backend/packages/harness/deerflow/persistence/models/closure_ticket.py`（SQLAlchemy 模型）+ Alembic 迁移。
  - 新增 `backend/packages/harness/deerflow/closed_loop/` 子包（service / state machine / repository / events）。
  - 新增 `backend/app/gateway/routers/closure_tickets.py` REST 路由，挂到现有 FastAPI app。
  - 新增 builtin tools：`create_closure_ticket` / `update_closure_ticket` / `list_closure_tickets` / `close_closure_ticket`，注册到 `tools/builtins/`。
- Agent
  - 更新 `agents/builtin/defect-closure/SOUL.md` + `config.yaml`：新增对闭环单工具的依赖与流程约束。
  - 更新 `agents/builtin/ai-report--closure/SOUL.md`：从纯报告生成升级为「拉取待闭环单 + 生成报告 + 推动关闭」。
  - 更新 `agents/builtin/fault-diagnosis*/SOUL.md`：诊断结论严重等级达到阈值时，调用 `create_closure_ticket`。
  - 更新 `agents/builtin/ai-report--{daily,weekly,monthly,custom}/SOUL.md`：报告中识别出的整改项通过工具登记。
- 前端
  - 新增 `frontend/src/app/workspace/closed-loop/` 路由与页面。
  - 新增 `frontend/src/components/workspace/closed-loop/` 组件群（list / kanban / detail-drawer / verify-form）。
  - 在 `workspace-nav-chat-list.tsx` 等入口处增加「闭环管理」导航。
  - 新增 API client：`frontend/src/core/closed-loop/`。
- 跨切关注点
  - 权限：闭环单读/写遵循现有 tenant + role 模型，新增 `closure:read` / `closure:write` / `closure:verify` 三个权限点。
  - 事件：复用 run_event 通道发布闭环状态变更事件。
  - 报告模板：在 `report_templates` schema 中扩展 `closure_section` 区块类型，让模板可直接渲染闭环单列表（属于 `closed-loop-agent-integration` 的延伸约定，不改动 `report_templates` 引擎核心契约）。
