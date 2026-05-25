## ADDED Requirements

### Requirement: Audit event schema
每个审计事件 SHALL 包含以下字段：`id` (UUID), `timestamp` (UTC ISO 8601), `user_id`, `tenant_id`, `action` (enum), `resource_type` (enum), `resource_id` (nullable), `result` (success/denied/error), `ip_address`, `user_agent`, `details` (JSONB)。

#### Scenario: Successful login audit event
- **WHEN** 用户成功登录
- **THEN** 生成审计事件: `action=auth_login`, `resource_type=session`, `result=success`, `details` 包含认证方式

#### Scenario: Failed login audit event
- **WHEN** 用户登录失败（密码错误）
- **THEN** 生成审计事件: `action=auth_login`, `result=denied`, `details` 包含失败原因和尝试次数

### Requirement: Audit event coverage
审计日志 SHALL 覆盖以下操作类型：
- 认证事件: `auth_login`, `auth_logout`, `auth_token_refresh`
- 权限变更: `permission_grant`, `permission_revoke`, `role_change`
- 数据访问: `thread_read`, `thread_delete`, `artifact_read`, `knowledge_base_query`
- Agent 运行: `run_create`, `run_cancel`, `tool_execute`
- 工单流转: `ticket_create`, `ticket_transition`, `ticket_close`
- 配置修改: `config_update`, `skill_install`, `agent_fork`, `mcp_config_change`

#### Scenario: Tool execution audit
- **WHEN** Agent 调用 sandbox `bash` 工具
- **THEN** 生成审计事件: `action=tool_execute`, `resource_type=tool`, `resource_id=bash`, `details` 包含命令摘要（截断至 256 字符）

#### Scenario: Config change audit
- **WHEN** 管理员修改 `extensions_config.json` 中 MCP 服务器配置
- **THEN** 生成审计事件: `action=config_update`, `resource_type=mcp_config`, `result=success`, `details` 包含变更前后差异摘要

### Requirement: Async audit write
审计日志写入 SHALL 不阻塞 API 响应。失败 SHALL 不导致业务请求失败。

#### Scenario: Normal audit write
- **WHEN** API 请求产生审计事件
- **THEN** 事件被放入异步队列，API 响应在事件入队后立即返回（不等待持久化）

#### Scenario: Audit queue full
- **WHEN** 审计事件队列达到上限
- **THEN** 新事件被丢弃，ERROR 日志记录丢弃数量，业务请求正常处理

#### Scenario: Graceful shutdown drain
- **WHEN** Gateway 收到 SIGTERM
- **THEN** 停止接受新事件入队，等待队列中现有事件全部写入数据库后再退出（超时 10s）

### Requirement: Audit log immutability
审计日志 SHALL 只追加不可修改。系统 SHALL NOT 提供审计日志的 UPDATE 或 DELETE API。

#### Scenario: Attempt to delete audit log via API
- **WHEN** 向审计日志端点发送 DELETE 请求
- **THEN** 返回 405 Method Not Allowed

#### Scenario: Tamper detection via hash chain
- **WHEN** 启用了哈希链验证 (`audit.enable_hash_chain: true`)
- **THEN** 每条审计记录的 `chain_hash` 字段 = SHA-256(previous_chain_hash + current_record_json)，验证 API 可检测篡改

### Requirement: Audit log query API
管理员 SHALL 能通过 `GET /api/admin/audit-logs` 查询审计日志，支持时间范围、用户、操作类型、资源类型筛选，返回分页结果。

#### Scenario: Filter by time range and user
- **WHEN** `GET /api/admin/audit-logs?from=2026-05-01T00:00:00Z&to=2026-05-23T00:00:00Z&user_id=user123&page=1&page_size=50`
- **THEN** 返回该用户在指定时间范围内的审计记录，按时间倒序，附带 `total` 和 `has_more`

#### Scenario: Non-admin access denied
- **WHEN** 非 admin 用户请求 `GET /api/admin/audit-logs`
- **THEN** 返回 403 Forbidden

### Requirement: Audit log export
管理员 SHALL 能导出审计日志为 CSV 或 JSON 格式。

#### Scenario: Export as CSV
- **WHEN** `GET /api/admin/audit-logs/export?format=csv&from=2026-05-01&to=2026-05-23`
- **THEN** 返回 `Content-Type: text/csv`，文件名为 `audit-logs-2026-05-01-2026-05-23.csv`

#### Scenario: Export size limit
- **WHEN** 导出范围超过 100,000 条记录
- **THEN** 返回 400 错误，提示缩小时间范围

### Requirement: Audit log retention
系统 SHALL 根据 `audit.retention_days` 配置自动清理过期审计日志。

#### Scenario: Scheduled cleanup
- **WHEN** `audit.retention_days=365`
- **THEN** 每天凌晨 3:00 自动删除 365 天前的审计记录（归档后删除）

#### Scenario: Archive before delete
- **WHEN** `audit.archive_enabled: true` 且配置了 `audit.archive_backend: s3`
- **THEN** 删除前将过期记录导出为压缩 JSONL 文件上传到 S3
