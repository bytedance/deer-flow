## Context

DeerFlow 当前为单进程部署模式：FastAPI Gateway (:8001) 内嵌 LangGraph Agent Runtime（通过 `RunManager` + `run_agent()` + `StreamBridge`），所有状态（会话、限流计数、StreamBridge 实例）存在于进程内存中。数据存储可选文件系统（默认）或 PostgreSQL。这在开发和小规模部署中简单高效，但不满足石油石化央企上线所需的 99.9% 可用性、完整审计追踪和自动化备份恢复。

**相关系统**：
- Nginx (:2026) 已作为统一入口，可以复用做负载均衡
- Docker Compose 已有开发部署模板，可扩展为 HA 模板
- `langgraph.json` 已定义 graph，LangGraph Server 支持独立部署 + PostgreSQL checkpointer
- 现有 `journal.py` 运行日志、`content_safety/log_storage.py`、`telemetry.py` 为审计日志提供了模块结构参考

**约束**：
- 必须兼容现有单节点开发模式 (`make dev`)
- 不能破坏现有 API 契约
- Docker 部署为主要目标环境

## Goals / Non-Goals

**Goals:**
- Gateway 无状态化，支持 2-3 副本水平扩展
- 结构化审计日志覆盖认证/授权/数据访问/Agent 运行/配置变更
- 分层备份（数据库+文件+配置），支持定时调度和异地存储

**Non-Goals:**
- Kubernetes 原生部署（留在后续迭代，本次聚焦 Docker Compose HA）
- SSO/LDAP 集成（独立需求）
- Prometheus/Grafana 可观测性（独立需求）
- 审计日志实时告警（本次仅采集和查询）

## Decisions

### D1: 会话/限流后端选择 Redis

**选择**: Redis 作为分布式会话和限流后端。
**替代方案**:
- Memcached: 无持久化，数据结构单一，不适合分布式锁
- PostgreSQL: 会话读写频繁，增加数据库负载
- 文件系统 (NFS): 高延迟，锁语义不可靠
**理由**: Redis 生态成熟，Python 客户端 (`redis-py`) 广泛使用，支持所需的所有数据结构（string、hash、sorted set for rate limit、pub/sub），且 `slowapi` 已有 Redis 后端支持。

### D2: LangGraph Server 部署模式

**选择**: LangGraph Server 作为独立容器运行，连接到共享 PostgreSQL。
**替代方案**:
- 继续内嵌在 Gateway 进程: 无法独立扩展，StreamBridge 在进程间不可传递
- 完全自定义 runner: 放弃 LangGraph 平台能力（streaming、checkpointer、cron）
**理由**: DeerFlow 已使用 `langgraph.json` 定义 graph，LangGraph Server 原生支持 PostgreSQL checkpointer 和水平扩展。Gateway 通过 `langgraph-sdk` HTTP 客户端连接 LangGraph Server，前端 SSE 连接需 Nginx sticky session 保持到同一 LangGraph 实例。

### D3: 审计日志存储

**选择**: 审计日志写入 PostgreSQL `audit_log` 表，异步批量写入以降低请求延迟。
**替代方案**:
- ELK/Loki: 引入额外基础设施，运维复杂度高
- 专用审计文件 (JSONL): 简陋，查询困难
- ClickHouse: 更适合分析型负载但引入新依赖
**理由**: PostgreSQL 已在使用，JSONB 支持灵活查询，`asyncpg` 批量插入性能足够。结构化为 `(id, ts, user_id, tenant_id, action, resource_type, resource_id, result, ip, user_agent, details JSONB)`。异步写入通过 `asyncio.Queue` + 后台 worker（参考现有 `dispatcher.py` 模式），不阻塞请求。保留策略通过定时任务清理。

### D4: 备份传输与存储

**选择**: `rclone` 处理文件增量同步到 S3/MinIO，`pg_dump` + WAL 归档处理数据库。
**替代方案**:
- `boto3` 直接上传: 需自行处理增量/重试/校验
- `pgBackRest`: 功能全但配置复杂，对当前规模过度
- Velero (K8s): 不适用 Docker Compose 部署
**理由**: `rclone` 成熟、支持 40+ 后端、内置增量同步和校验。调度使用 APScheduler（已在 `closed_loop/jobs.py` 中有模式），备份脚本以 CLI 方式运行，可被外部 cron 调用。

### D5: 健康检查端点

**选择**: 新增 `/health/live`（存活探针）和 `/health/ready`（就绪探针）。
- `/health/live`: 返回 200 当进程存活
- `/health/ready`: 返回 200 当 DB + Redis + LangGraph Server 全部可连通
**理由**: Docker/K8s 标准模式，不破坏现有 `/health` 端点。

## Risks / Trade-offs

- **[Redis 单点]**: Redis 成为新的关键依赖 → 部署 Redis Sentinel 或使用云服务托管版
- **[SSE sticky session]**: 流式响应需保持到同一后端 → Nginx `ip_hash` 或 `sticky cookie`，当后端重启时客户端需重连
- **[审计日志写入失败]**: 异步写入可能丢失关机时的缓存数据 → 优雅关闭时 drain queue，关键事件（认证失败）同步写入
- **[备份窗口]**: pg_dump 对大型数据库可能耗时 → 使用 WAL 连续归档减少全量备份频率，全量备份在低峰期执行
- **[配置新增段]**: config.yaml 变大 → 保持向后兼容，新段提供合理默认值
