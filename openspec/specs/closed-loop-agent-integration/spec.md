# closed-loop-agent-integration Specification

## Purpose

定义 deer-flow 内 Agent 与闭环子系统的集成契约：在 harness 中提供 builtin 工具集供 Agent 调用，并约束诊断 Agent、报告 Agent、闭环 Agent 在何种条件下创建、查询、更新、关闭闭环单。同时支持 `report_templates` 引擎在报告中以结构化区块渲染闭环单数据。

## Requirements

### Requirement: 闭环 Builtin 工具集
系统 SHALL 在 `harness/deerflow/tools/builtins` 中注册四个 builtin 工具：`create_closure_ticket`、`list_closure_tickets`、`update_closure_ticket`、`close_closure_ticket`，供 Agent 通过工具调用与闭环子系统交互。

#### Scenario: 工具注册
- **WHEN** harness 启动并加载 builtin 工具
- **THEN** 工具注册表中存在上述四个工具，且每个工具均有结构化输入 schema 与文档字符串

#### Scenario: 工具调用走服务层
- **WHEN** Agent 调用 `create_closure_ticket`
- **THEN** 工具不直接写数据库，而是委派给 `closed_loop.service`，由服务层执行租户与权限校验

#### Scenario: 工具不暴露 status 直写
- **WHEN** `update_closure_ticket` 被调用且参数包含 `status`
- **THEN** 工具忽略 `status` 字段并在返回值中提示需使用 `close_closure_ticket` 的 `action` 参数

### Requirement: 诊断结论自动建单
`fault-diagnosis*` 系列 Agent SHALL 在诊断结论的严重等级达到「重要」或「紧急」时，调用 `create_closure_ticket` 创建闭环单，`source_type` 为 `diagnosis`，`source_run_id` 为当前 run id。

#### Scenario: 严重等级达标
- **WHEN** 旋转机组诊断 Agent 输出结论中 `severity` 为 `urgent`
- **THEN** Agent 调用 `create_closure_ticket` 创建闭环单，关联当前 run，并在对话回复中告知用户已生成闭环单与其 id

#### Scenario: 严重等级未达标
- **WHEN** 诊断结论 `severity` 为 `observe`
- **THEN** Agent 不主动建单，但允许用户显式请求时再调用工具

#### Scenario: 同 run 重复触发
- **WHEN** 同一 run 内 Agent 因多轮对话第二次尝试为同设备建单
- **THEN** 工具凭幂等约束返回已有 ticket id，不创建重复单

### Requirement: 报告整改项登记
`ai-report--{daily,weekly,monthly,custom}` Agent SHALL 在报告中识别出"待整改项 / 待跟踪项"时，对每一项调用 `create_closure_ticket` 登记，`source_type` 为 `report`，并在报告正文中引用对应 ticket id。

#### Scenario: 报告生成时登记整改项
- **WHEN** 日报 Agent 在报告草稿中列出 3 条待整改项
- **THEN** Agent 对每条调用 `create_closure_ticket`，并把返回的 ticket id 写入报告对应条目的引用字段

#### Scenario: 用户撤回报告
- **WHEN** 用户在报告生成后选择不发送
- **THEN** Agent 调用 `close_closure_ticket` 以 `reject` 动作回收已登记的闭环单

### Requirement: 闭环 Agent 流程升级
`defect-closure` Agent SHALL 以闭环单为中心组织工作流：拉取待处置单据 → 引导用户选择 → 制定处置方案 → 触发 `assign` / `start` / `submit_verification` 等动作 → 在验证完成后触发 `close`。

#### Scenario: 拉取待办
- **WHEN** 用户与 `defect-closure` Agent 开启新会话
- **THEN** Agent 首先调用 `list_closure_tickets` 拉取当前用户负责或租户内 `pending` / `assigned` / `in_progress` 的单据，并以列表形式呈现

#### Scenario: 处置方案登记
- **WHEN** 用户口述了某单据的处置方案
- **THEN** Agent 调用 `update_closure_ticket` 把方案写入 `metadata.resolution_plan` 字段，状态保持不变

#### Scenario: 提交验证
- **WHEN** 用户表示处置已完成，希望提交验证
- **THEN** Agent 调用 `close_closure_ticket` 触发 `submit_verification` 动作，将状态迁移为 `pending_verification`

#### Scenario: 关闭闭环
- **WHEN** 拥有 `closure:verify` 权限的用户确认验证通过
- **THEN** Agent 调用 `close_closure_ticket` 触发 `verify_close` 动作，将状态迁移为 `closed`

### Requirement: 闭环报告 Agent 升级
`ai-report--closure` Agent SHALL 在生成闭环报告时主动调用 `list_closure_tickets` 拉取目标周期内已关闭与未关闭单据，按设备/严重等级聚合并在报告中呈现。

#### Scenario: 周期闭环报告
- **WHEN** 用户请求"上周设备闭环报告"
- **THEN** Agent 调用 `list_closure_tickets` 限定 `closed_at` 与 `created_at` 落在上周窗口的单据，并在报告中分"已闭环 / 未闭环 / 超期未闭环"三段呈现

#### Scenario: 推动关闭
- **WHEN** Agent 在报告生成过程中识别出已具备关闭条件的待验证单据
- **THEN** Agent 在报告中明确列出该单据并提示使用 `defect-closure` Agent 推动关闭，但不擅自调用 `close_closure_ticket`

### Requirement: 报告模板闭环区块
`report_templates` 引擎 SHALL 支持新的块类型 `closure_section`，模板作者可在 step 中声明该块以渲染指定筛选条件下的闭环单列表。

#### Scenario: 模板渲染闭环列表
- **WHEN** 报告模板的某 step 声明 `block_type: closure_section`，并配置 `filters: { device_ids, status, period }`
- **THEN** 渲染器调用 `closed_loop.service.list_for_report(filters)` 取数，并以表格形式渲染到报告中

#### Scenario: 无数据时降级
- **WHEN** 筛选条件下没有任何闭环单
- **THEN** 渲染器输出一条"本周期无相关闭环单"的占位文本，而不是抛出异常

#### Scenario: 兼容旧模板
- **WHEN** 老版本模板未包含 `closure_section` 块
- **THEN** 引擎完全按照旧逻辑渲染，不引入任何新行为
