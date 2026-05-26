## Why

The system has partial PostgreSQL support (DatabaseConfig, 16 ORM models, StoreMemoryStorage, DbRunEventStore, pgvector backend), but production deployments still use SQLite/JSON/Chroma fragmentation because configuration wiring and migration scripts were never completed. This blocks multi-instance deployment and enterprise adoption.

## What Changes

- Wire `database.backend=postgres` to auto-default all subsystem backends (run_events, memory, rag, cost)
- Extend `cost_config.py` to support `postgres` storage backend
- Add startup validation to reject split backend configurations in production
- Create SQLite→PostgreSQL migration script covering all 16 ORM tables with validation
- Create Chroma→pgvector reindexing script aligned with KB-bound embedding architecture
- Archive legacy `token_usage.json` files after validating ORM data parity
- Create migration runbook and rollback procedures

## Capabilities

### New Capabilities

- `config-auto-default`: When `database.backend=postgres`, automatically set `run_events.backend=db`, `memory.storage_class=StoreMemoryStorage`, `rag.vector_store_backend=pgvector`, `cost.storage_backend=postgres`
- `split-config-validation`: Startup validation that rejects split backend configurations in production mode (e.g., postgres database + json cost storage)
- `sqlite-to-postgres-migration`: Migration script covering all 16 ORM tables with idempotency, record count validation, and spot-check logic
- `chroma-to-pgvector-migration`: Reindexing script that respects KB-bound embedding model and dimension per knowledge base

### Modified Capabilities

- `cost-storage-backend`: Extend to support `postgres` as a valid `storage_backend` option (currently only `json`)

## Impact

**Code**:
- `backend/packages/harness/deerflow/config/database_config.py` (auto-default logic)
- `backend/packages/harness/deerflow/config/cost_config.py` (postgres backend)
- `backend/packages/harness/deerflow/config/app_config.py` (startup validation)
- `scripts/migrate_sqlite_to_postgres.py` (new)
- `scripts/reindex_rag_to_pgvector.py` (new)
- `scripts/migrate_memory_to_store.py` (verify existing)

**Data**:
- SQLite database files → PostgreSQL tables (16 ORM models)
- Chroma persist directory → pgvector tables (KB-bound embedding)
- `token_usage.json` files → archived (data already in `RunRow` + `AgentUsageRow`)
- `memory.json` files → LangGraph Store namespaces

**Dependencies**:
- `asyncpg` (already installed)
- `pgvector` extension (backend already implemented)
- No new dependencies

**Deployment**:
- PostgreSQL instance with `vector` and `pgcrypto` extensions
- Maintenance window for migration execution
- Rollback plan with backup snapshots
