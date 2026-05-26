## Why

DeerFlow currently uses fragmented storage across SQLite, JSON files, in-memory stores, and Chroma for different data types. This creates reliability issues, makes multi-instance deployment difficult, complicates backup/recovery, and limits operational control. Migrating to PostgreSQL as the unified primary storage will consolidate core state management, enable horizontal scaling, and simplify operations.

## What Changes

### 已完成（本提案前）

- **统一数据库配置**：`DatabaseConfig` 已支持 `memory/sqlite/postgres`，`engine.py` 已支持双模式 + WAL + Alembic 自动升级 + 自动建库
- **16 个 ORM 模型**：`users`, `tenants`, `threads_meta`, `runs`, `runs_events`, `knowledge_bases`, `knowledge_base_documents`, `index_jobs`, `kb_permissions`, `agents`, `agent_permissions`, `agent_usage`, `feedback`, `tenant_http_connectors`, `tenant_mcp_servers`, `closure_tickets`, `closure_ticket_events`, `closure_sla_configs`
- **StoreMemoryStorage**：已通过 LangGraph Store 写入
- **DbRunEventStore**：SQLAlchemy ORM 后端已实现
- **pgvector 后端**：`rag/backends/pgvector.py` 已存在（182 行）
- **Token 追踪**：已整合到 `RunRow`（per-run 字段）+ `AgentUsageRow`（per-agent 维度）

### 仍需完成

- **配置联动**：`database.backend=postgres` 时自动设置 `run_events.backend=db`、`memory.storage_class=StoreMemoryStorage`、`rag.vector_store_backend=pgvector`、`cost.storage_backend=postgres`
- **cost_config 扩展**：新增 `postgres` 选项，连接 `database.backend`
- **SQLite→PG 迁移脚本**：覆盖全部 16 个表，支持幂等和校验
- **Chroma→pgvector 迁移**：适配 KB-bound embedding（Sprint B 新增），按 KB 维度重建索引
- **token_usage.json 清理**：确认数据已落入 `AgentUsageRow`，归档遗留文件
- **memory.json→Store 迁移**：已有脚本，需验证
- **Checkpointer SQLite→PG**：通过 LangGraph 抽象层迁移
- **启动校验**：生产模式拒绝分裂配置（如 PG 数据 + JSON 成本）
- **文档**：迁移指南、配置参考、备份恢复

## Capabilities

### New Capabilities
- `config-validation`: Startup validation to prevent configuration fragmentation and auto-default subsystem backends from `database.backend`
- `storage-migration`: Migration scripts and tools for SQLite → PostgreSQL transition covering all 16 ORM tables
- `pgvector-rag`: pgvector-based vector storage for RAG embeddings with KB-bound embedding alignment

### Modified Capabilities
- `database-config`: Extend to auto-default `run_events`, `cost`, `memory`, `rag` backends when `database.backend=postgres`
- `token-usage-tracking`: Clean up legacy `token_usage.json` files; per-run and per-agent usage already in ORM
- `run-events-persistence`: Auto-default to `db` backend when `database.backend=postgres`
- `memory-storage`: Auto-default to `StoreMemoryStorage` when `database.backend=postgres`

## Impact

**Code affected**:
- Configuration layer: `database_config.py` (auto-default logic), `cost_config.py` (add postgres backend), `run_events_config.py`, `memory_config.py`, `rag_config.py`
- Migration scripts: New `scripts/migrate_sqlite_to_postgres.py` (16 tables), `scripts/reindex_rag_to_pgvector.py`, `scripts/migrate_memory_to_store.py`
- Cleanup: Archive `token_usage.json` files after validating `AgentUsageRow` data

**Dependencies**:
- PostgreSQL driver: `asyncpg` (already used)
- Vector extension: `pgvector` (backend already implemented)
- No new dependencies

**Systems affected**:
- All deployments requiring multi-instance support
- Backup and recovery procedures
- Development environment setup (PostgreSQL becomes optional for dev, required for production)
