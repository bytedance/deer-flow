## Why

The project currently uses fragmented storage across SQLite, JSON files, in-memory stores, and Chroma for different data types. This creates reliability issues, makes multi-instance deployment difficult, complicates backup/recovery, and limits operational control. Migrating to PostgreSQL as the unified primary storage will consolidate core state management, enable horizontal scaling, and simplify operations.

## What Changes

- **Unified database backend**: Migrate all structured data (users, tenants, threads, runs, knowledge bases) from SQLite to PostgreSQL
- **Runtime state consolidation**: Move LangGraph checkpointer, store, and run_events from SQLite/memory to PostgreSQL
- **Operational data migration**: Migrate feedback, token_usage, and memory from JSON files to PostgreSQL tables
- **Vector storage upgrade**: Replace Chroma with pgvector for RAG embeddings
- **Configuration consolidation**: Unify all storage configuration under `database.backend` setting
- **Dual-mode support**: Maintain SQLite support for local development while defaulting to PostgreSQL for production
- File storage (uploads, artifacts, workspaces) remains on filesystem - not migrated to database

## Capabilities

### New Capabilities
- `postgresql-storage`: PostgreSQL as primary storage backend for all core data
- `pgvector-rag`: pgvector-based vector storage for RAG embeddings
- `storage-migration`: Migration scripts and tools for SQLite → PostgreSQL transition
- `config-validation`: Startup validation to prevent configuration fragmentation

### Modified Capabilities
- `database-config`: Extend database configuration to support PostgreSQL with connection pooling
- `memory-storage`: Switch from file-based to Store-backed memory persistence
- `token-usage-tracking`: Migrate from JSON file to PostgreSQL table with proper ORM
- `run-events-persistence`: Change default from memory to database backend

## Impact

**Code affected**:
- Configuration layer: `database_config.py`, `app_config.py`, `cost_config.py`, `rag_config.py`, `memory_config.py`
- Persistence layer: New `token_usage` model/repository, formalize `pgvector` tables, update memory storage
- Runtime layer: `checkpointer/provider.py`, `store/provider.py`, `events/store/`, `memory/storage.py`, `rag/vector_store.py`
- Migration scripts: New scripts for data migration from SQLite/JSON/Chroma to PostgreSQL

**Dependencies**:
- Add PostgreSQL driver: `asyncpg`, `psycopg`
- Add vector extension: `pgvector`
- Update SQLAlchemy and Alembic configurations

**Systems affected**:
- All deployments requiring multi-instance support
- Backup and recovery procedures
- Development environment setup (PostgreSQL becomes optional for dev, required for production)
