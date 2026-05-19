## 1. Configuration Layer

- [ ] 1.1 Add startup configuration validation to reject split backend configurations in production mode
- [ ] 1.2 Implement auto-default logic: when `database.backend=postgres`, auto-set `run_events.backend=db`, `memory.storage_class=StoreMemoryStorage`, `rag.vector_store_backend=pgvector`
- [ ] 1.3 Add deprecation warnings for standalone `checkpointer` configuration section
- [ ] 1.4 Update `DatabaseConfig` to validate PostgreSQL URL format and required extensions
- [ ] 1.5 Add configuration validation error messages with actionable guidance
- [ ] 1.6 Update `config.example.yaml` with PostgreSQL configuration examples

## 2. Database Schema and Models

- [ ] 2.1 Create `TokenUsage` ORM model with fields: `id`, `tenant_id`, `user_id`, `thread_id`, `run_id`, `model_name`, `input_tokens`, `output_tokens`, `total_tokens`, `cost_usd`, `created_at`
- [ ] 2.2 Create Alembic migration for `token_usage` table with indexes on `(tenant_id, created_at)`, `(thread_id, created_at)`, `(user_id, created_at)`
- [ ] 2.3 Create `rag_chunks` table schema with pgvector extension: `id`, `tenant_id`, `collection`, `document_id`, `chunk_id`, `content`, `metadata`, `embedding`, `created_at`
- [ ] 2.4 Create Alembic migration for `rag_chunks` table with HNSW/IVFFlat index on `embedding` column and indexes on `(tenant_id, collection)` and `metadata` JSONB
- [ ] 2.5 Verify all existing ORM models (users, tenants, threads_meta, runs, knowledge_bases, knowledge_base_documents) work with PostgreSQL

## 3. Repository Layer

- [ ] 3.1 Create `TokenUsageRepository` with methods: `create()`, `get_by_thread()`, `get_by_user()`, `aggregate_by_tenant()`, `aggregate_by_date_range()`
- [ ] 3.2 Update `memory/storage.py` to default to `StoreMemoryStorage` when `database.backend=postgres`
- [ ] 3.3 Verify `FeedbackRepository` works correctly with PostgreSQL (already implemented)
- [ ] 3.4 Update `rag/backends/pgvector.py` to use formal `rag_chunks` table instead of runtime DDL
- [ ] 3.5 Add connection pool management and monitoring for PostgreSQL

## 4. Runtime Layer

- [ ] 4.1 Update `runtime/checkpointer/provider.py` to automatically follow `database.backend` setting
- [ ] 4.2 Update `runtime/store/provider.py` to automatically follow `database.backend` setting
- [ ] 4.3 Update `runtime/events/store/__init__.py` to default to `db` backend when `database.backend=postgres`
- [ ] 4.4 Update `cost/*` middleware to use `TokenUsageRepository` instead of JSON file when `cost.storage_backend=postgres`
- [ ] 4.5 Update `rag/vector_store.py` to use pgvector backend when `rag.vector_store_backend=pgvector`

## 5. Migration Scripts

- [ ] 5.1 Create `scripts/migrate_sqlite_to_postgres.py` to migrate business tables (users, tenants, threads_meta, runs, knowledge_bases, knowledge_base_documents)
- [ ] 5.2 Add record count validation and spot-check logic to SQLite→PostgreSQL migration script
- [ ] 5.3 Make SQLite→PostgreSQL migration script idempotent (skip existing records, update changed records)
- [ ] 5.4 Create `scripts/migrate_checkpointer_sqlite_to_postgres.py` using LangGraph abstraction layer
- [ ] 5.5 Create `scripts/migrate_memory_to_store.py` to migrate `memory.json` files to LangGraph Store namespaces
- [ ] 5.6 Create `scripts/migrate_token_usage_json_to_postgres.py` to migrate `token_usage.json` to PostgreSQL table
- [ ] 5.7 Create `scripts/reindex_rag_to_pgvector.py` to rebuild vector embeddings from source documents
- [ ] 5.8 Add batch processing and rate limiting to reindexing script
- [ ] 5.9 Add validation logic to reindexing script (chunk count, spot-check retrieval)

## 6. Testing

- [ ] 6.1 Add unit tests for `TokenUsageRepository` CRUD operations
- [ ] 6.2 Add unit tests for configuration validation logic
- [ ] 6.3 Add unit tests for auto-default configuration logic
- [ ] 6.4 Add integration tests for PostgreSQL backend initialization
- [ ] 6.5 Add integration tests for checkpointer/store PostgreSQL backend
- [ ] 6.6 Add integration tests for pgvector vector search
- [ ] 6.7 Add integration tests for memory Store-backed storage
- [ ] 6.8 Add migration script tests (idempotency, validation)
- [ ] 6.9 Add end-to-end test: create thread → restart with PostgreSQL → verify thread loads
- [ ] 6.10 Add end-to-end test: upload knowledge base → reindex to pgvector → verify retrieval

## 7. Documentation

- [ ] 7.1 Update `docs/CONFIGURATION.md` with PostgreSQL configuration guide
- [ ] 7.2 Create `docs/POSTGRESQL_MIGRATION.md` with step-by-step migration guide
- [ ] 7.3 Update `docs/ARCHITECTURE.md` to reflect PostgreSQL as primary storage
- [ ] 7.4 Update `README.md` with PostgreSQL setup instructions
- [ ] 7.5 Create migration runbook for operations team
- [ ] 7.6 Document rollback procedure in migration guide
- [ ] 7.7 Update `config.example.yaml` comments to explain PostgreSQL vs SQLite modes

## 8. Deployment Preparation

- [ ] 8.1 Create PostgreSQL provisioning scripts for production environment
- [ ] 8.2 Document PostgreSQL extension installation (`vector`, `pgcrypto`)
- [ ] 8.3 Create backup and restore procedures for PostgreSQL
- [ ] 8.4 Estimate vector reindexing cost (document count × embedding cost)
- [ ] 8.5 Plan maintenance window for production migration
- [ ] 8.6 Prepare rollback plan with backup snapshots
- [ ] 8.7 Create monitoring dashboards for PostgreSQL connection pool, query performance, table sizes

## 9. Phase 1: Structured Business Tables Migration

- [ ] 9.1 Provision PostgreSQL instance and install extensions
- [ ] 9.2 Run Alembic migrations to create tables in PostgreSQL
- [ ] 9.3 Backup SQLite database files
- [ ] 9.4 Execute `migrate_sqlite_to_postgres.py` script
- [ ] 9.5 Validate record counts match between SQLite and PostgreSQL
- [ ] 9.6 Update `config.yaml`: set `database.backend=postgres`
- [ ] 9.7 Restart services and verify threads load correctly

## 10. Phase 2: Runtime State Migration

- [ ] 10.1 Backup JSON files (`token_usage.json`, `memory.json`)
- [ ] 10.2 Execute `migrate_checkpointer_sqlite_to_postgres.py` script
- [ ] 10.3 Execute `migrate_memory_to_store.py` script
- [ ] 10.4 Execute `migrate_token_usage_json_to_postgres.py` script
- [ ] 10.5 Update `config.yaml`: set `run_events.backend=db`, `memory.storage_class=StoreMemoryStorage`
- [ ] 10.6 Restart services and verify thread history, memory injection, run events persistence

## 11. Phase 3: Vector Storage Migration

- [ ] 11.1 Run Alembic migration to create `rag_chunks` table with pgvector extension
- [ ] 11.2 Backup Chroma persist directory
- [ ] 11.3 Execute `reindex_rag_to_pgvector.py` script
- [ ] 11.4 Validate chunk count matches expected
- [ ] 11.5 Spot-check retrieval results against Chroma baseline
- [ ] 11.6 Update `config.yaml`: set `rag.vector_store_backend=pgvector`
- [ ] 11.7 Restart services and verify RAG retrieval works correctly

## 12. Phase 4: Cleanup and Monitoring

- [ ] 12.1 Monitor PostgreSQL system for 24-48 hours
- [ ] 12.2 Archive old SQLite files to `backups/` directory
- [ ] 12.3 Archive old JSON files to `backups/` directory
- [ ] 12.4 Archive Chroma directory to `backups/` directory
- [ ] 12.5 Update deployment documentation
- [ ] 12.6 Remove deprecation warnings after one release cycle
- [ ] 12.7 Implement retention policies for `run_events` and `token_usage` tables
