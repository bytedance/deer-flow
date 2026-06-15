## Why

DeerFlow 当前默认配置（InMemorySaver + SQLite + ChromaDB + 文件存储）将所有状态锁定在单进程内，无法水平扩展。随着并发用户增长，需要多 worker 部署来分摊 LLM 调用和 Agent 执行的负载。但多 worker 下，进程间状态不共享导致：线程丢失、SSE 断流、记忆读写冲突、成本统计不一致。本方案为现有系统提供**可选的多 worker 部署能力**，在不改变现有默认行为的前提下，让用户通过配置切换到共享后端。

## What Changes

- **多 Worker 模式开关**：新增 `DEER_FLOW_MULTI_WORKER=1` 环境变量（或 `deployment.mode: multi_worker` 配置），启用时所有有状态组件自动切换到共享后端（PostgreSQL + Redis）
- **保持默认不变**：现有用户的 `config.yaml` 行为完全不变（memory/sqlite/chroma/json），零破坏性升级
- **Agent Memory 跨 Worker 共享**：multi-worker 模式下复用现有 `StoreMemoryStorage` + PostgreSQL BaseStore，在 memory updater 层实现乐观合并策略防止并发写入丢失 facts
- **Cost Storage 默认联动**：多 worker 模式下自动切换到 PostgreSQL 后端（已有实现）
- **KB 索引队列**：新增 PostgreSQL `FOR UPDATE SKIP LOCKED` 竞争消费模式，替代进程内 `asyncio.create_task`
- **IM 渠道协调**：Redis 分布式锁（Lua 脚本原子操作）保证多 worker 下 webhook/轮询单实例消费
- **健康检查增强**：新增 `/health/ready` 端点，报告 PostgreSQL/Redis/向量库连接状态
- **Nginx sticky session**：多 worker 模式下提供 `hash $arg_thread_id consistent` 配置选项

## Capabilities

### New Capabilities

- `multi-worker-mode`：多 Worker 部署模式开关，启用时自动切换所有有状态组件到共享后端，不改变现有默认行为
- `agent-memory-postgres`：Agent Memory 跨 worker 共享（复用 StoreMemoryStorage + PostgreSQL BaseStore），含应用层乐观合并策略防止并发写入丢失
- `kb-indexing-queue`：KB 索引任务的外部队列实现（PostgreSQL FOR UPDATE SKIP LOCKED），支持多 worker 下任务不重复执行
- `im-channel-coordination`：IM 渠道（飞书/微信/WeCom/钉钉/Telegram/Slack/Discord）在多 worker 下的消费协调机制（Redis Lua 脚本锁），确保 webhook/轮询只被一个 worker 处理
- `multi-worker-health-probe`：增强的健康检查端点，报告各共享后端连接状态，供编排系统使用

### Modified Capabilities

- `sqlite-to-postgres-migration`：迁移脚本需要增加迁移后验证步骤，确保 PostgreSQL 后端所有表数据完整
- `cost-storage-backend`：多 worker 模式下自动切换 PostgreSQL 后端

## Impact

- **配置兼容性**：完全向后兼容。不设置 `DEER_FLOW_MULTI_WORKER=1` 时行为与现有完全一致
- **依赖变更**：多 worker 模式下需要 `redis[hiredis]`、`psycopg`、`pgvector`、`filelock`
- **部署变更**：多 worker 部署时 docker-compose 需要 PostgreSQL 和 Redis 服务
- **代码变更**：
  - `backend/packages/harness/deerflow/config/` — 新增 deployment.mode 配置
  - `backend/packages/harness/deerflow/agents/memory/updater.py` — 新增乐观合并逻辑
  - `backend/packages/harness/deerflow/knowledge_base/dispatcher.py` — 新增 queue 模式
  - `backend/app/channels/` — 新增消费协调逻辑
  - `backend/app/gateway/app.py` — 健康检查端点增强
  - `docker/` — compose 和 nginx 配置更新
- **数据库变更**：`index_jobs` 表新增 `worker_id`、`retry_count` 列
- **测试**：新增多 worker 集成测试（模拟 2+ worker 并发读写同一 thread）
