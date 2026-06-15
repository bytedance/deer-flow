## 1. Phase 1: 配置框架 + 健康检查 + Worker ID (multi-worker-mode)

- [x] 1.1 新增 `DeploymentConfig` 数据类：字段 `mode: Literal["single_worker", "multi_worker"] = "single_worker"`，在 `AppConfig` 中添加 `deployment: DeploymentConfig` 字段
- [x] 1.2 实现 `DEER_FLOW_MULTI_WORKER=1` 环境变量支持：在 `AppConfig.from_file()` 中读取环境变量，等效于 `deployment.mode: multi_worker`
- [x] 1.3 扩展 `_apply_database_defaults()` 方法：在现有逻辑中新增 multi-worker 分支。当 `deployment.mode: multi_worker` 时，覆盖以下 4 个非 database 子系统（现有方法已覆盖 memory/rag/cost/run_events，无需重复）：
  - `stream_bridge.type` → `redis`
  - `rate_limit.backend` → `redis`
  - `indexing.dispatcher_mode` → `queue`
  - `im.coordination_mode` → `redis`

  确保与现有 `database.backend=postgres` 自动覆盖逻辑不冲突（multi-worker 分支在 postgres 分支之后执行）
- [x] 1.4 实现 multi-worker 模式启动验证：模式激活时检查 PostgreSQL 和 Redis 连通性，不可达则 fail-fast 并输出清晰错误信息
- [x] 1.5 实现 `DEER_FLOW_DEV_MODE=1` 环境变量：设置时强制所有后端为 memory/chroma/json/file，并输出 WARNING 日志
- [x] 1.6 实现 worker_id 日志传播：生成 8 位短 UUID 作为 `WORKER_ID`，通过 `logging.Filter` 注入所有日志记录，格式为 `timestamp [worker_id] LEVEL module: message`
- [x] 1.7 增强健康检查端点（位于 `backend/app/gateway/app.py:800` 现有 `/health` 端点附近）：新增 `/health/ready` 和 `/health/live` 两个独立端点。`/health/ready` 检查 PostgreSQL (`SELECT 1`)、Redis (`PING`)、向量库连接，超时 5 秒，结果缓存 10 秒。保留原有 `/health` 端点兼容性
- [x] 1.8 创建 `GET /health/live` 端点（位于 `backend/app/gateway/app.py`）：仅返回 `{"status": "alive"}`，**不缓存**，不检查外部依赖
- [x] 1.9 实现健康检查 Prometheus 指标：`health_check_total{backend, status}` 计数器
- [x] 1.10 更新 `config.example.yaml`：添加 `deployment.mode` 配置项及注释，添加 `DEER_FLOW_DEV_MODE` 和 `DEER_FLOW_MULTI_WORKER` 说明
- [x] 1.11 添加配置框架单元测试：验证 mode 覆盖逻辑、显式配置优先级、dev mode 回退、与 `_apply_database_defaults` 的交互
- [x] 1.12 添加健康检查端点单元测试（mock 后端连接）

## 2. Phase 2: Agent Memory 乐观合并 (agent-memory-postgres)

- [x] 2.1 在 memory updater 层实现乐观合并函数 `_merge_facts(current, incoming)`：按内容 key（casefold，与现有 `_fact_content_key()` 一致）去重，合并已有 facts 和新增 facts
- [x] 2.2 在 memory updater 的所有 save 调用链中集成乐观合并：先调用 `storage.load()` 读取当前数据，合并后再调用 `storage.save()` 写入。需覆盖所有保存路径：
  - `_finalize_update()`（updater.py:507，LLM 更新主路径）
  - `_save_memory_to_file()`（updater.py:51，fact CRUD 操作路径）
  - `import_memory_data()`（updater.py:66，手动导入路径）
  - 异步保存路径（如有 `async_save` 调用）
- [x] 2.3 确认 multi-worker 模式下 `get_memory_storage()` 返回 `StoreMemoryStorage`：当 `database.backend=postgres` 时，现有逻辑已自动选择 `StoreMemoryStorage`（app_config.py:324），无需额外修改。只需验证在 multi-worker 模式下行为正确
- [x] 2.4 为 `FileMemoryStorage` 添加文件锁：使用 `filelock` 库（跨平台）在 `save()` 中加锁，防止多进程并发写损坏（如意外启动多个实例指向同一数据目录）。注意：进程内线程同步已由现有 `cache_lock` (RLock) 处理，filelock 仅用于进程间互斥
- [x] 2.5 添加乐观合并单元测试：验证 facts 去重、并发合并、空数据场景
- [x] 2.6 添加跨 worker 可见性集成测试（需要真实 PostgreSQL）：Worker A 写入记忆，Worker B 读取验证可见性
- [x] 2.7 添加 FileMemoryStorage 文件锁测试：验证并发 save 不损坏数据

## 3. Phase 3: KB 索引队列改造 (kb-indexing-queue)

- [x] 3.1 创建 Alembic 迁移脚本：在 `index_jobs` 表添加 `worker_id` (VARCHAR, nullable) 和 `retry_count` (INT, default 0, not null) 列。注意：`started_at` 列已存在于模型中（model.py:95），无需添加
- [x] 3.2 在 `IndexingDispatcher` 中新增 `queue` 模式：`_claim_job()` 方法使用 `SELECT ... FROM index_jobs WHERE status='pending' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED` 抢占任务
- [x] 3.3 实现 `_claim_job()` 方法：更新 `status='running'`、`worker_id=<uuid>`、`started_at=now()`，返回 job 或 None
- [x] 3.4 实现 stale job 回收：`_reclaim_stale_jobs()` 将超时（`started_at` 超过 `job_timeout_seconds`）且 `status='running'` 的 job 重置为 `pending`，递增 `retry_count`
- [x] 3.5 实现 max retries 逻辑：`retry_count >= max_retries` 的 job 标记为 `status='failed'`
- [x] 3.6 添加配置项：`indexing.dispatcher_mode`（`"local"` / `"queue"`）、`indexing.job_timeout_seconds`（默认 300）、`indexing.max_retries`（默认 3）
- [x] 3.7 为每个 dispatcher worker 生成 UUID `worker_id`，在进程启动时生成（`uuid.uuid4().hex[:12]`），生命周期为进程存续期，不做持久化
- [x] 3.8 添加 KB 索引队列单元测试（mock DB）：抢占竞争、stale 回收、max retries
- [x] 3.9 添加 KB 索引队列集成测试（需要真实 PostgreSQL）：2 个 dispatcher 竞争同一 job

## 4. Phase 4: IM 渠道协调 (im-channel-coordination)

- [x] 4.1 创建 `IMChannelLock` 类在 `backend/app/channels/coordination.py`：封装 Redis 分布式锁，使用 Lua 脚本实现原子操作
- [x] 4.2 实现 `IMChannelLock.acquire()` Lua 脚本：`SET deerflow:im_lock:{channel} {worker_id} NX EX 30`（原子获取锁）
- [x] 4.3 实现 `IMChannelLock.renew()` Lua 脚本：
  ```lua
  if redis.call("GET", KEYS[1]) == ARGV[1] then
      return redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[2])
  end
  return 0
  ```
  仅当 value 匹配 worker_id 时才续期，防止覆盖其他 worker 的锁
- [x] 4.4 实现 `IMChannelLock.release()` Lua 脚本：
  ```lua
  if redis.call("GET", KEYS[1]) == ARGV[1] then
      return redis.call("DEL", KEYS[1])
  end
  return 0
  ```
  仅当 value 匹配时才删除
- [x] 4.5 实现锁续期定时器：每 TTL/3 秒（默认 10 秒）调用 `renew()`，锁丢失时停止续期
- [x] 4.6 修改各 IM 渠道（飞书、微信、WeCom、钉钉、Telegram、**Slack、Discord**）的启动逻辑：启动时尝试获锁，获锁成功才启动消费循环，未获锁则跳过该渠道
- [x] 4.7 在 graceful shutdown（SIGTERM handler）中释放所有持有的 IM 锁
- [x] 4.8 实现 webhook 去重：`Redis SET deerflow:webhook_dedup:{channel}:{message_id} NX EX 300`，重复消息返回 HTTP 200 不处理
- [x] 4.9 添加配置项 `im.coordination_mode`（`"redis"` / `"none"`），multi-worker 模式默认 `"redis"`
- [x] 4.10 添加 `IMChannelLock` 单元测试（mock Redis）：获锁、续期（验证 ownership check）、释放（验证 ownership check）、竞争
- [x] 4.11 添加 webhook 去重单元测试

## 5. Phase 5: 部署配置 + 连接池 (deployment)

- [x] 5.1 调整 PostgreSQL 连接池大小：多 worker 模式下 checkpointer async 连接池 `max_size` 从 5 提升到 10（async_provider.py:79），Store 连接池保持现有 `max_size=10`（async_provider.py:76,152; provider.py:88），App ORM `pool_size` 从 5 提升到 10（`max_overflow` 保持 5，database_config.py:73-79）
- [x] 5.2 配置 PostgreSQL `max_connections`：docker-compose 中 PostgreSQL 启动参数增加 `-c max_connections=250`，确保 4 workers × ~50 connections 不超限
- [x] 5.3 更新 `docker-compose.yml`：确保 PostgreSQL 和 Redis 作为依赖服务启动
- [x] 5.4 创建 `docker-compose.dev.yml`：为开发环境提供 PostgreSQL + Redis 容器，设置 `DEER_FLOW_DEV_MODE=1`
- [x] 5.5 更新 `docker/nginx/nginx.conf`：添加 sticky session 配置，使用 `map` 从 URI path 提取 thread_id：
  ```nginx
  map $uri $thread_id {
      ~^/api/threads/(?<tid>[^/]+) $tid;
      default "";
  }
  upstream gateway {
      hash $thread_id consistent;
  }
  ```
  当 `$thread_id` 为空时（非 thread 相关请求如 `/api/models`），nginx 自动降级为 round-robin。注意：当 stream_bridge 使用 Redis 时，sticky session 为优化项而非必需，可改用 `least_conn` 替代
- [x] 5.6 更新 `docker/nginx/nginx.local.conf`：同上
- [x] 5.7 更新 `backend/packages/harness/pyproject.toml`：确认 `redis[hiredis]`、`psycopg[binary]`、`pgvector`、`filelock` 依赖可用
- [x] 5.8 实现 graceful HTTP drain：SIGTERM 后等待正在处理的 HTTP 请求完成（最长 30 秒），再退出进程
- [x] 5.9 创建迁移文档 `docs/MULTI_WORKER_MIGRATION.md`：从单 worker 升级到多 worker 的步骤、回滚步骤、注意事项
- [x] 5.10 更新 `config.example.yaml` 中的 `config_version`（bump）
- [x] 5.11 在 `app_config.py` 中添加配置版本检查增强：`config_version` 过时时输出升级提示（已有基础实现，扩展检查 deployment 段）

## 6. 集成测试与验证

- [x] 6.1 创建多 worker 集成测试：启动 2 个 worker，验证同一 thread 的消息在 worker 间一致
- [x] 6.2 创建 SSE 多 worker 测试：验证 Redis stream bridge 跨 worker 事件传递
- [x] 6.3 创建 Agent Memory 多 worker 测试：Worker A 写入记忆，Worker B 读取验证可见性；验证乐观合并（两 worker 并发写入不同 facts）
- [x] 6.4 创建 KB 索引竞争测试：2 个 worker 同时有 pending job，验证只有一个处理
- [x] 6.5 创建 IM 锁竞争测试：2 个 worker 竞争同一 channel，验证单实例消费；验证锁过期后另一 worker 接管
- [x] 6.6 创建配置降级测试：`DEER_FLOW_DEV_MODE=1` 下验证所有后端回退到 memory/file
- [x] 6.7 创建配置覆盖优先级测试：`deployment.mode: multi_worker` + `database.backend: memory` 验证显式配置优先
- [x] 6.8 创建 worker_id 日志测试：验证多 worker 下日志包含正确的 worker_id
