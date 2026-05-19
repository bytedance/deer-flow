## ADDED Requirements

### Requirement: 闭环单数据模型
系统 SHALL 持久化「闭环单（Closure Ticket）」实体，作为设备问题/整改项的唯一聚合根，包含但不限于以下字段：`id`、`tenant_id`、`source_type`、`source_run_id`、`device_id`、`title`、`description`、`severity`、`priority`、`status`、`assignee_id`、`reporter_id`、`due_at`、`is_overdue`、`metadata`、`created_at`、`updated_at`、`closed_at`。

#### Scenario: 创建闭环单
- **WHEN** 服务端收到合法的创建请求（含 `tenant_id`、`source_type`、`device_id`、`title`、`severity`）
- **THEN** 系统持久化一条闭环单，初始 `status` 为 `pending`，`is_overdue` 为 `false`，`created_at` 与 `updated_at` 由服务端写入

#### Scenario: 必填字段校验
- **WHEN** 创建请求缺少 `tenant_id`、`source_type`、`device_id`、`title`、`severity` 中任一字段
- **THEN** 系统返回 422 校验错误，不创建任何记录

#### Scenario: 跨租户隔离
- **WHEN** 用户使用 tenant A 的凭证查询闭环单
- **THEN** 系统仅返回 `tenant_id == A` 的记录，绝不泄露其他租户数据

### Requirement: 来源去重
系统 SHALL 对同一来源的重复创建请求做幂等处理，避免诊断或报告 Agent 反复建单。

#### Scenario: 同源同设备重复创建
- **WHEN** Agent 以相同 `(tenant_id, source_type, source_run_id, device_id)` 再次调用创建接口
- **THEN** 系统返回已有闭环单的 `id` 与状态，不创建新记录

#### Scenario: 不同 run 视为不同来源
- **WHEN** 同设备但 `source_run_id` 不同的两次创建请求到达
- **THEN** 系统创建两张独立闭环单

### Requirement: 状态机受控迁移
闭环单 SHALL 在以下状态间按受控方式迁移：`pending → assigned → in_progress → pending_verification → closed`，并允许 `pending|assigned|in_progress → rejected`、`closed → reopened`、`pending_verification → in_progress`（验证不通过退回）。状态变更必须由服务端状态机执行，禁止外部直接修改 `status` 字段。

#### Scenario: 合法迁移
- **WHEN** 一张 `pending` 单据收到 `assign` 动作并附带合法 `assignee_id`
- **THEN** 状态变为 `assigned`，`due_at` 按 `priority` 计算并写入

#### Scenario: 非法迁移
- **WHEN** 一张 `pending` 单据收到 `close` 动作
- **THEN** 系统拒绝该操作并返回 409 冲突错误，状态保持不变

#### Scenario: 直接修改 status 被拒绝
- **WHEN** 调用方尝试通过通用更新接口直接 PATCH `status` 字段
- **THEN** 系统忽略该字段并要求改用专用的 `transition` 动作端点

#### Scenario: 验证不通过退回
- **WHEN** 一张 `pending_verification` 单据收到 `reject_verification` 动作并附带退回原因
- **THEN** 状态退回 `in_progress`，事件记录退回原因

### Requirement: 状态变更审计
系统 SHALL 为每一次状态迁移记录一条不可变的审计事件，包含 `ticket_id`、`from_status`、`to_status`、`action`、`actor_id`、`payload`、`occurred_at`。

#### Scenario: 审计事件写入
- **WHEN** 闭环单状态从 `assigned` 迁移到 `in_progress`
- **THEN** 系统写入一条审计事件，记录前后状态、动作、操作人 ID 与发生时间

#### Scenario: 审计事件不可篡改
- **WHEN** 任意调用方尝试更新或删除已写入的审计事件
- **THEN** 系统拒绝该操作并保留原记录

### Requirement: SLA 与超期识别
系统 SHALL 在闭环单进入 `assigned` 状态时按 `priority` 写入 `due_at`，并周期性扫描将 `now > due_at` 且未关闭的单据标记为 `is_overdue = true`，发布 `closure.overdue` 事件。

#### Scenario: 派单时计算 due_at
- **WHEN** 一张 `urgent` 优先级单据进入 `assigned` 状态
- **THEN** `due_at` 等于 `assigned_at + 4 小时`（按租户 SLA 配置，默认 4h）

#### Scenario: 超期标记
- **WHEN** 后台扫描发现一张 `in_progress` 单据 `due_at` 已过且未关闭
- **THEN** 系统将 `is_overdue` 置为 `true` 并发布一次 `closure.overdue` 事件

#### Scenario: 关闭后不再标超期
- **WHEN** 一张已 `closed` 的单据被扫描到
- **THEN** 系统不修改其 `is_overdue` 字段，也不发布超期事件

### Requirement: 检索查询能力
系统 SHALL 提供按 `tenant_id`、`device_id`、`status`、`assignee_id`、`source_type`、`priority`、`is_overdue`、时间窗（`created_at` / `due_at` / `closed_at`）的列表查询接口，并支持分页与排序。

#### Scenario: 按设备与状态筛选
- **WHEN** 用户请求 `device_id=D1 & status=in_progress`
- **THEN** 系统仅返回匹配条件的闭环单，并按 `due_at` 升序排序

#### Scenario: 分页
- **WHEN** 请求附带 `page=2 & page_size=20`
- **THEN** 系统返回第 21–40 条记录，并在响应中包含总数

#### Scenario: 时间窗筛选
- **WHEN** 请求附带 `closed_at_gte=2026-05-01 & closed_at_lt=2026-05-19`
- **THEN** 系统仅返回闭环时间落在该窗口内的单据

### Requirement: 权限控制
系统 SHALL 引入 `closure:read`、`closure:write`、`closure:verify` 三类权限点，分别对应查看、派单/处置、验证关闭。访问任何闭环 API 必须按权限校验。

#### Scenario: 无 read 权限
- **WHEN** 一个仅有租户登录态但无 `closure:read` 权限的用户调用列表接口
- **THEN** 系统返回 403 拒绝访问

#### Scenario: 仅 write 权限不可验证
- **WHEN** 一个具有 `closure:write` 但无 `closure:verify` 权限的用户尝试触发 `verify_close` 动作
- **THEN** 系统返回 403 并附带"需要 closure:verify 权限"错误信息

#### Scenario: 管理员默认全权限
- **WHEN** 租户管理员不显式配置任何闭环权限
- **THEN** 系统默认授予其 `read | write | verify` 三项权限
