## Why

DeerFlow 当前为单进程部署架构，缺乏高可用（无冗余/故障转移）、完整审计追踪（运行日志有但不可检索/不可导出）和自动化备份恢复（数据全在本地文件系统，无调度/异地/恢复演练）。要在石油石化央企/国企正式上线，这三项是安全合规和数据安全的基线要求。现在补齐是因为系统已具备多租户、RBAC 等核心企业功能，基础设施短板成为上线阻塞项。

## What Changes

### 高可用
- Gateway API 从单进程升级为无状态多副本，支持 Nginx 反向代理负载均衡
- LangGraph Agent Runtime 从 Gateway 进程内嵌入拆分为独立可横向扩展的 LangGraph Server
- 引入 Redis 作为会话/限流/分布式锁的后端（替代进程内内存）
- 数据库层 PostgreSQL 主从复制（读写分离）
- 健康检查增强：就绪探针 / 存活探针

### 审计合规
- 新增审计日志基础设施：结构化审计事件（who/when/what/resource/result/ip）写入持久存储
- 覆盖范围：认证事件、权限变更、数据访问、Agent 运行、工单流转、配置修改
- 审计日志查询 API（管理端）+ 导出（CSV/JSON）
- 防篡改：审计日志只追加不可删除，可选哈希链验证
- 保留策略：可配置保留期，到期自动归档

### 备份恢复
- 分层备份策略：数据库（PostgreSQL pg_dump + WAL 连续归档）、文件（thread_data/uploads/agents/report-runs 增量同步）、配置（Git 版本控制 + 定时快照）
- 备份调度：cron-like 定时任务，可配置频率和保留份数
- 异地备份：S3/MinIO 兼容对象存储上传
- 恢复演练：dry-run 恢复验证脚本，定期自动执行
- 恢复流程：按租户/按用户粒度恢复，支持时间点恢复（PITR）

## Capabilities

### New Capabilities
- `ha-multi-replica`: Gateway 无状态化改造，多副本部署，Nginx 负载均衡，健康检查端点
- `redis-integration`: 引入 Redis 替代进程内内存状态（会话、限流计数器、分布式锁）
- `audit-log`: 结构化审计日志系统，覆盖认证/授权/数据访问/Agent 运行/配置变更，查询与导出 API
- `backup-restore`: 分层备份策略（数据库/文件/配置），定时调度，异地存储，恢复验证

### Modified Capabilities
<!-- 现有能力无需修改规格，本次为纯新增 -->

## Impact

- **后端 Gateway**: FastAPI lifespan 拆分有状态初始化（数据库连接池、Redis 客户端），中间件添加审计日志写入
- **后端 Harness**: RunManager/StreamBridge 需适配分布式环境（会话状态外移至 Redis）
- **部署**: 新增 `docker-compose.ha.yml`（Gateway × 2-3, LangGraph Server × 1-2, Redis, PostgreSQL 主从）
- **配置**: `config.yaml` 新增 `redis`, `audit`, `backup` 配置段
- **数据库迁移**: 新增 `audit_log` 表（Alembic migration）
- **依赖新增**: `redis`, `apscheduler` (backup scheduler), `boto3` (S3 upload)
- **不破坏**: 所有现有 API 兼容，单节点开发模式保持可用
