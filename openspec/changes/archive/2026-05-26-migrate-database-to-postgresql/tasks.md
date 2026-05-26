# Tasks: migrate-database-to-postgresql

> Streamlined on 2026-05-26: removed already-completed work (DatabaseConfig, 16 ORM models, StoreMemoryStorage, DbRunEventStore, pgvector backend, token usage in RunRow/AgentUsageRow). Focus on config wiring + migration scripts + cleanup.

---

## 1. Configuration Layer

- [ ] 1.1 Add auto-default logic in `database_config.py`: when `database.backend=postgres`, set `run_events.backend=db`, `memory.storage_class=StoreMemoryStorage`, `rag.vector_store_backend=pgvector`, `cost.storage_backend=postgres`
- [ ] 1.2 Update `cost_config.py` to add `postgres` as a valid `storage_backend` option
- [ ] 1.3 Add startup validation: reject split backend configs in production mode (e.g., `database.backend=postgres` + `cost.storage_backend=json`)
- [ ] 1.4 Add deprecation warning for standalone `checkpointer` section when `database` section is also present

---

## 2. Migration Scripts

- [ ] 2.1 Create `scripts/migrate_sqlite_to_postgres.py` to migrate all 16 ORM tables (users, tenants, threads_meta, runs, run_events, knowledge_bases, knowledge_base_documents, index_jobs, kb_permissions, agents, agent_permissions, agent_usage, feedback, tenant_http_connectors, tenant_mcp_servers, closure_tickets, closure_ticket_events, closure_sla_configs)
- [ ] 2.2 Add record count validation and spot-check logic to SQLite→PostgreSQL migration script
- [ ] 2.3 Make SQLite→PostgreSQL migration script idempotent (skip existing records, update changed records)
- [ ] 2.4 Create `scripts/migrate_checkpointer_sqlite_to_postgres.py` using LangGraph abstraction layer
- [ ] 2.5 Verify `scripts/migrate_memory_to_store.py` (already exists) works correctly with current StoreMemoryStorage
- [ ] 2.6 Create `scripts/reindex_rag_to_pgvector.py` aligned with KB-bound embedding architecture (Sprint B): iterate knowledge bases, use per-KB `embedding_model` + `embedding_dim`, insert into `rag_chunks` table
- [ ] 2.7 Add batch processing and rate limiting to reindexing script
- [ ] 2.8 Add validation logic to reindexing script (chunk count, spot-check retrieval)

---

## 3. Cleanup

- [ ] 3.1 Audit existing `token_usage.json` files (3 locations: backend/.deer-flow/, backend/.deer-flow/tenants/zm/, backend/.deer-flow/tenants/390567939692036096/)
- [ ] 3.2 Verify `AgentUsageRow` and `RunRow` contain equivalent data before archiving `token_usage.json`
- [ ] 3.3 Archive legacy `token_usage.json` files to `backups/` directory
- [ ] 3.4 Archive SQLite database files to `backups/` after successful migration
- [ ] 3.5 Archive Chroma persist directory to `backups/` after successful pgvector migration

---

## 4. Testing

- [ ] 4.1 Add unit tests for auto-default configuration logic
- [ ] 4.2 Add unit tests for startup validation (reject split backends)
- [ ] 4.3 Add integration tests for SQLite→PostgreSQL migration script (all 16 tables)
- [ ] 4.4 Add integration tests for pgvector reindexing with KB-bound embedding
- [ ] 4.5 Add end-to-end test: create thread → restart with PostgreSQL → verify thread loads
- [ ] 4.6 Add end-to-end test: upload knowledge base → reindex to pgvector → verify retrieval

---

## 5. Documentation

- [ ] 5.1 Create `docs/POSTGRESQL_MIGRATION.md` with step-by-step migration guide covering all 16 tables
- [ ] 5.2 Update `config.example.yaml` with PostgreSQL configuration examples and auto-default behavior
- [ ] 5.3 Document rollback procedure in migration guide
- [ ] 5.4 Create migration runbook for operations team

---

## 6. Deployment Preparation

- [ ] 6.1 Document PostgreSQL extension installation (`vector`, `pgcrypto`)
- [ ] 6.2 Create backup and restore procedures for PostgreSQL
- [ ] 6.3 Estimate vector reindexing cost (document count × embedding cost)
- [ ] 6.4 Plan maintenance window for production migration

---

## Summary

- **Total tasks**: 27 (down from 81)
- **Estimated effort**: 2-3 weeks (down from 6-8 weeks)
- **Key savings**: DatabaseConfig already done, 16 ORM models already exist, no need to create TokenUsage table (RunRow + AgentUsageRow cover it), StoreMemoryStorage and DbRunEventStore already implemented, pgvector backend already exists
