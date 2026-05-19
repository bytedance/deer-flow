## ADDED Requirements

### Requirement: 待办聚合 API
系统 SHALL 提供 `GET /api/closure/notifications/summary` 端点，返回当前用户的"待我处理 / 我创建 / 我验证"三类未闭环单据的数量与最早 `due_at`。

#### Scenario: 返回结构
- **WHEN** 已认证用户调用该接口
- **THEN** 响应体包含 `assigned_to_me`, `reported_by_me`, `to_verify_by_me` 三个聚合块，每块包含 `count`、`overdue_count`、`earliest_due_at`

#### Scenario: 跨租户隔离
- **WHEN** 用户切换租户上下文
- **THEN** 聚合结果仅包含当前租户的数据

### Requirement: 超期扫描任务
系统 SHALL 在后端启动时启动一个周期性 asyncio 任务，每 5 分钟扫描一次未关闭且 `due_at < now()` 但 `is_overdue` 仍为 `false` 的闭环单，将其标记为超期，并发布 `closure.overdue` 事件到现有事件总线（复用 `run_event` 通道）。

#### Scenario: 标记超期
- **WHEN** 扫描任务发现一张 `in_progress` 单据 `due_at` 已过期
- **THEN** 系统更新 `is_overdue=true` 并写入一条审计事件 `action=mark_overdue`，再发布 `closure.overdue` 事件

#### Scenario: 多副本去重
- **WHEN** 多副本部署下两个进程同时触发扫描
- **THEN** 系统通过 PG advisory lock 保证同一时刻仅一个进程执行扫描，另一个进程跳过本轮

#### Scenario: 任务异常自恢复
- **WHEN** 扫描任务在某轮抛出异常
- **THEN** 异常被捕获并以 ERROR 级别日志记录，任务在下一周期继续执行而不退出

### Requirement: 状态变更事件发布
状态机 SHALL 在每次状态迁移成功后发布一条领域事件到现有 `run_event` 通道，事件类型形如 `closure.<action>`，payload 至少包含 `ticket_id`、`tenant_id`、`from_status`、`to_status`、`actor_id`、`occurred_at`。

#### Scenario: 派单事件
- **WHEN** 一张单据从 `pending` 迁移到 `assigned`
- **THEN** 系统发布 `closure.assigned` 事件，订阅方（前端 SSE / 报告 Agent）可消费

#### Scenario: 关闭事件
- **WHEN** 一张单据迁移到 `closed`
- **THEN** 系统发布 `closure.closed` 事件，并附带 `verification_payload`

### Requirement: 通知规则配置
租户管理员 SHALL 能在管理后台配置每个 `priority` 等级的 SLA 时长（小时），并立即对未关闭的单据生效（仅影响未来 `due_at` 计算，不重写历史）。

#### Scenario: 修改 SLA 配置
- **WHEN** 管理员将 `urgent` SLA 从 4h 改为 2h
- **THEN** 此后新进入 `assigned` 状态的紧急单据按 2h 计算 `due_at`，已经派单的单据保持原 `due_at`

#### Scenario: 默认配置
- **WHEN** 租户未显式配置任何 SLA
- **THEN** 系统使用默认值：`urgent=4h`、`important=72h`、`normal=7d`、`observe=30d`

### Requirement: 前端实时刷新
前端 SHALL 订阅 `closure.*` 事件流，在事件到达时刷新对应列表行、详情抽屉与导航徽标，不需要用户手动刷新页面。

#### Scenario: 列表实时更新
- **WHEN** 当前正在查看列表页的用户对应的单据收到 `closure.assigned` 事件
- **THEN** 列表对应行在不重载整页的情况下更新状态、责任人、due_at 字段

#### Scenario: 抽屉实时更新
- **WHEN** 当前打开的详情抽屉对应单据收到 `closure.closed` 事件
- **THEN** 抽屉自动追加最新一条审计时间线并把状态徽章更新为 `closed`
