## 1. Redis 集成

- [ ] 1.1 新增 `redis` 配置段到 `config.yaml` 和 `config.example.yaml`（url/sentinels/master_name/prefix），含默认值注释和向后兼容降级说明
- [ ] 1.2 创建 `deerflow/infra/redis.py`：连接池管理、单节点/Sentinel 模式自动选择、健康检查、连接池参数可配置
- [ ] 1.3 创建 `tests/test_redis_config.py`：配置解析测试，覆盖单节点、Sentinel、缺失配置降级三种场景
- [ ] 1.4 迁移 `slowapi` 限流后端从进程内存到 Redis（`from slowapi.extension import Limiter` → Redis backend）
- [ ] 1.5 创建 `tests/test_rate_limit_redis.py`：验证多实例间限流计数器共享 + 窗口过期
- [ ] 1.6 知识库 `IndexingDispatcher` 添加 Redis 分布式锁（`SET key NX EX`），替代进程内 `_inflight` set

## 2. Gateway 无状态化 + 多副本

- [ ] 2.1 新增 `GET /health/live` 和 `GET /health/ready` 端点到 `app/gateway/app.py`
- [ ] 2.2 创建 `tests/test_health_endpoints.py`：覆盖存活/就绪/依赖失败三种返回状态
- [ ] 2.3 创建 `docker/nginx/nginx.ha.conf`：upstream gateway 多节点 + SSE sticky session（`ip_hash`）+ 健康检查
- [ ] 2.4 更新 `docker/nginx/Dockerfile`：同时复制 `nginx.conf` 和 `nginx.ha.conf`
- [ ] 2.5 Gateway lifespan 启动时从 Redis 读取状态（会话、限流），关闭自身进程内状态初始化逻辑
- [ ] 2.6 创建 `docker-compose.ha.yml`：Gateway × 2 + Redis + PostgreSQL（可选主从）+ Nginx 路由
- [ ] 2.7 部署文档 `docs/DEPLOYMENT_HA.md`：HA 模式部署步骤、环境变量、扩缩容操作

## 3. LangGraph Server 独立部署

- [ ] 3.1 在 `docker-compose.ha.yml` 中新增 `langgraph-server` 服务，使用 `langgraph/up` 镜像，挂载 `langgraph.json` + `config.yaml` + skills 目录
- [ ] 3.2 配置 LangGraph Server 连接共享 PostgreSQL（checkpointer + store）
- [ ] 3.3 Gateway `RunManager` 添加 `LANGGRAPH_REMOTE` 模式：通过 `langgraph-sdk` 客户端调用独立 LangGraph Server，替代进程内 `run_agent()`
- [ ] 3.4 SSE stream 保持兼容：Gateway 将 LangGraph Server 的 SSE 事件透传给前端，前端无需改动

## 4. 审计日志

- [ ] 4.1 新增 `audit` 配置段到 `config.yaml`（enabled/retention_days/archive_enabled/hash_chain_enabled/queue_max_size）
- [ ] 4.2 创建 Alembic migration `003_add_audit_log.py`：`audit_log` 表（id UUID PK, ts TIMESTAMPTZ INDEXED, user_id, tenant_id, action, resource_type, resource_id, result, ip, user_agent, details JSONB, chain_hash）
- [ ] 4.3 创建 `deerflow/infra/audit.py`：`AuditLogger` 类（enqueue/mark_success/mark_failure），异步队列 + 批量写入 worker，优雅关闭 drain
- [ ] 4.4 创建 FastAPI middleware `app/gateway/middleware/audit_middleware.py`：拦截请求/响应，自动填充 user_id/tenant_id/ip/result，按路由规则分类 action
- [ ] 4.5 在关键路径手动埋点：`auth/routers/auth.py`（login/logout）, `authz.py`（permission check）, `routers/threads.py`（thread CRUD）, `routers/thread_runs.py`（run create/cancel）, `tools/builtins/`（tool execute）, `routers/tenant_mcp_servers.py`（config change）
- [ ] 4.6 创建 `app/gateway/routers/admin.py` 审计日志路由：`GET /api/admin/audit-logs`（分页查询+筛选），`GET /api/admin/audit-logs/export`（CSV/JSON 导出）
- [ ] 4.7 哈希链实现：写入时 `chain_hash = SHA-256(prev_hash || current_json)`，验证 `GET /api/admin/audit-logs/verify` 遍历计算
- [ ] 4.8 审计日志保留 + 归档定时任务（APScheduler）：到期记录导出为 JSONL.gz 到 S3/本地，然后从主表删除
- [ ] 4.9 创建 `tests/test_audit_log.py`：覆盖事件写入/查询筛选/导出格式/不可删除/哈希链验证/队列满降级/优雅关闭 drain

## 5. 备份恢复

- [ ] 5.1 新增 `backup` 配置段到 `config.yaml`（local_dir/schedule/retention/remote/s3）
- [ ] 5.2 创建 `scripts/backup_db.sh`：`pg_dump --format=custom` + WAL archive command 设置
- [ ] 5.3 创建 `scripts/backup_files.sh`：`rclone sync` 指定目录到本地备份目录 + S3 remote
- [ ] 5.4 创建 `scripts/backup_config.sh`：git commit + tag + push 远程
- [ ] 5.5 创建 `deerflow/infra/backup_scheduler.py`：APScheduler 调度器，读取配置中的 cron 表达式，调用备份脚本，记录状态到 `backup_status.json`
- [ ] 5.6 创建 `app/gateway/routers/admin.py` 备份路由：`GET /api/admin/backup/status`（最近备份状态 + 下次调度）
- [ ] 5.7 创建 `scripts/restore.sh`：支持 `--pitr` 时间点恢复 / `--tenant` 按租户恢复 / `--dry-run` 模拟

- [ ] 5.8 创建 `scripts/verify_backup.sh`：备份完整性校验（文件数量/大小对比、数据库 restore list 验证）
- [ ] 5.9 创建 `tests/test_backup_scripts.py`：覆盖 dry-run 恢复流程、备份状态报告、配置备份 git 操作、S3 上传模拟
- [ ] 5.10 恢复操作手册 `docs/BACKUP_RESTORE.md`：备份架构说明、恢复步骤（全量/PITR/按租户）、演练计划模板

## 6. 集成验证

- [ ] 6.1 创建 `tests/test_ha_integration.py`：Docker Compose HA 环境冒烟测试（多 Gateway 实例健康检查、Redis 连接、审计日志写入读出）
- [ ] 6.2 更新 `Makefile`：新增 `make ha-start` / `make ha-stop` / `make backup-now` / `make backup-restore` / `make backup-status` 命令
- [ ] 6.3 更新 `README.md` 和 `README_zh.md`：新增 HA 部署章节，添加 audit/backup 配置项说明
