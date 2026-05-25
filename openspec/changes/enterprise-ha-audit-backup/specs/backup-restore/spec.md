## ADDED Requirements

### Requirement: PostgreSQL backup
系统 SHALL 支持 PostgreSQL 全量备份 (`pg_dump`) 和 WAL 连续归档。

#### Scenario: Scheduled full backup
- **WHEN** 备份调度器触发全量备份
- **THEN** 执行 `pg_dump --format=custom`，输出命名为 `deerflow-full-{timestamp}.dump`，存储到 `backup.local_dir/database/`

#### Scenario: WAL archiving
- **WHEN** PostgreSQL 生成 WAL 段文件
- **THEN** `archive_command` 将 WAL 复制到 `backup.local_dir/wal/`，`rclone` 定期同步到远程存储

#### Scenario: Backup verification
- **WHEN** 全量备份完成
- **THEN** 自动执行 `pg_restore --list` 验证备份文件完整性，失败则告警

### Requirement: File backup
系统 SHALL 使用 `rclone` 对文件数据进行增量同步到本地备份目录和远程存储 (S3/MinIO)。

#### Scenario: Incremental file sync
- **WHEN** 备份调度器触发文件备份
- **THEN** `rclone sync` 将 `DEER_FLOW_HOME/` 下的 `users/`, `report-templates/`, `skills/custom/`, `threads/` 同步到 `backup.local_dir/files/`

#### Scenario: Remote storage upload
- **WHEN** 本地备份完成
- **THEN** `rclone copy` 将本地备份目录同步到配置的 S3/MinIO bucket

#### Scenario: Backup file retention
- **WHEN** `backup.retention.daily=7`, `backup.retention.weekly=4`, `backup.retention.monthly=3`
- **THEN** 系统保留最近 7 次日备份、4 次周备份、3 次月备份，自动清理超过保留份数的旧备份

### Requirement: Config backup
配置文件 SHALL 纳入 Git 版本控制，备份调度器定期创建带时间戳的 tag。

#### Scenario: Config committed to Git
- **WHEN** `config.yaml` 或 `extensions_config.json` 被修改
- **THEN** 系统在备份时自动 commit 变更并 push 到配置的 Git 远程仓库

### Requirement: Backup scheduling
系统 SHALL 通过 `backup.schedule` 配置 crontab 风格的备份调度。

#### Scenario: Daily database backup
- **WHEN** `backup.schedule.full_db: "0 2 * * *"`（每天凌晨 2:00）
- **THEN** 每天凌晨 2:00 自动执行数据库全量备份

#### Scenario: Hourly WAL backup
- **WHEN** `backup.schedule.wal_sync: "0 * * * *"`（每小时）
- **THEN** 每小时同步 WAL 文件到远程存储

### Requirement: Point-in-time recovery
系统 SHALL 支持将数据库恢复到指定时间点。

#### Scenario: PITR to specific time
- **WHEN** 管理员执行 `make backup-restore -- --pitr "2026-05-22 14:30:00"`
- **THEN** PostgreSQL 恢复到该时间点，使用最近的全量备份 + 后续 WAL 段

#### Scenario: PITR dry-run
- **WHEN** 管理员执行 `make backup-restore -- --pitr "2026-05-22 14:30:00" --dry-run`
- **THEN** 系统模拟恢复过程，验证所有需要的 WAL 文件存在，但不修改运行中的数据库

### Requirement: Per-tenant restore
系统 SHALL 支持按租户粒度恢复数据。

#### Scenario: Restore single tenant data
- **WHEN** 管理员执行 `make backup-restore -- --tenant tenant_abc --date 2026-05-22`
- **THEN** 仅恢复该租户的 `users/`, `agents/`, `threads/`, `report-templates/` 数据

### Requirement: Restore verification
系统 SHALL 在恢复完成后自动执行验证步骤。

#### Scenario: Post-restore integrity check
- **WHEN** 恢复操作完成
- **THEN** 系统对比恢复后的文件数量、数据库行数与备份元数据中的记录，不一致时报告差异

### Requirement: Backup status monitoring
系统 SHALL 通过 `GET /api/admin/backup/status` 暴露最近备份状态。

#### Scenario: Query backup status
- **WHEN** 管理员请求 `GET /api/admin/backup/status`
- **THEN** 返回最近各类型备份的时间戳、大小、状态（success/failed/in_progress），以及下次调度时间

#### Scenario: Failed backup alert
- **WHEN** 连续两次备份失败
- **THEN** 系统在 `/api/admin/backup/status` 中标记 `alert: true`，并在 `details` 中包含最后一次错误信息
