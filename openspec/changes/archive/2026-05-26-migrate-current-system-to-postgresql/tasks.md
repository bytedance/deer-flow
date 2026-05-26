# Tasks

## 1. Configuration Auto-Default Logic

- [x] 1.1 Add `explicitly_set` tracking to config fields: `run_events.backend`, `memory.storage_class`, `rag.vector_store_backend`, `cost.storage_backend`
- [x] 1.2 Implement `AppConfig.post_init()` method to apply auto-defaults when `database.backend=postgres`
- [x] 1.3 Add INFO logging for each auto-defaulted subsystem during startup
- [x] 1.4 Add INFO logging for explicitly configured subsystems (auto-default skipped)
- [x] 1.5 Write unit tests for auto-default logic (all subsystems auto-default, explicit override, SQLite/memory no-op)

## 2. Split Configuration Validation

- [x] 2.1 Implement `validate_config_consistency()` method in `AppConfig`
- [x] 2.2 Add environment detection via `DEER_FLOW_ENV` environment variable
- [x] 2.3 Implement production mode validation: raise `ConfigValidationError` on split backends
- [x] 2.4 Implement development mode validation: log WARNING on split backends
- [x] 2.5 Add actionable error messages with conflicting configs, recommended fix, and doc link
- [x] 2.6 Write unit tests for validation logic (production reject, dev warn, consistent pass, SQLite skip)

## 3. Cost Storage Backend Extension

- [x] 3.1 Update `CostConfig.storage_backend` field to accept `postgres` as valid value (currently only `json`)
- [x] 3.2 Add validation to reject invalid storage backend values
- [x] 3.3 Update cost middleware to use `PgUsageStorage` when `storage_backend=postgres`
- [x] 3.4 Write unit tests for postgres backend storage
- [x] 3.5 Write unit tests for invalid backend rejection

## 4. SQLite to PostgreSQL Migration Script

- [x] 4.1 Create `scripts/migrate_sqlite_to_postgres.py` with CLI argument parsing (sqlite-path, postgres-url, batch-size, skip-validation)
- [x] 4.2 Implement batch reading from SQLite (default 1000 rows per batch)
- [x] 4.3 Implement idempotent writing to PostgreSQL (skip existing rows by primary key)
- [x] 4.4 Add migration support for all 18 ORM tables
- [x] 4.5 Implement row count validation after migration (SQLite count vs PostgreSQL count)
- [x] 4.6 Add validation failure handling (exit code 1, list mismatched tables)
- [x] 4.7 Implement migration report output (tables migrated, rows per table, skipped rows, duration)
- [x] 4.8 Add progress logging for batch migration (e.g., "Migrated batch 1/5: 500 rows")
- [x] 4.9 Write integration tests for migration script (all tables, idempotency, validation, empty DB)

## 5. Chroma to pgvector Migration Script

- [x] 5.1 Create `scripts/reindex_rag_to_pgvector.py` with CLI argument parsing (chroma-path, postgres-url, batch-size, rate-limit, resume, dry-run)
- [x] 5.2 Implement KB iteration logic: fetch all knowledge bases with their `embedding_model` and `embedding_dim`
- [x] 5.3 Implement document retrieval from Chroma per KB
- [x] 5.4 Implement re-chunking using current chunking strategy (reuses Chroma documents as-is)
- [x] 5.5 Implement embedding generation using KB's configured `embedding_model`
- [x] 5.6 Add embedding dimension validation (generated dim must match KB's `embedding_dim`)
- [x] 5.7 Implement dimension mismatch handling (mark KB as failed, continue with next KB)
- [x] 5.8 Implement batch insertion into `rag_chunks` table with pgvector embeddings
- [x] 5.9 Add rate limiting between batches (configurable batches per minute)
- [x] 5.10 Implement resume support: track processed KBs, skip on re-run with `--resume` flag
- [x] 5.11 Implement single KB failure handling (log error, continue with next KB, exit code 1 for partial failure)
- [x] 5.12 Implement dry-run mode: count documents/chunks, estimate tokens and cost, no actual embedding/insertion
- [x] 5.13 Implement reindexing report output (KBs successful/failed/skipped, chunks/embeddings per KB, duration, estimated cost)
- [x] 5.14 Write integration tests for reindexing script (all KBs, dimension validation, resume, dry-run, partial failure)

## 6. Token Usage JSON Cleanup

- [x] 6.1 Implement audit logic: compare `token_usage.json` data with `RunRow` and `AgentUsageRow` ORM data
- [x] 6.2 Add tolerance check (1% difference allowed)
- [x] 6.3 Implement archival: move `token_usage.json` to `backups/token_usage.json.bak` when data matches
- [x] 6.4 Add WARNING log when data mismatch detected (skip archival, manual review required)
- [x] 6.5 Add INFO log when no JSON files found (skip migration)
- [x] 6.6 Write unit tests for audit logic (match, mismatch, no files)

## 7. Memory JSON to Store Migration Verification

- [x] 7.1 Verify existing `scripts/migrate_memory_to_store.py` works with current `StoreMemoryStorage` implementation
- [x] 7.2 Test migration with sample `memory.json` files
- [x] 7.3 Verify migrated data is accessible via `StoreMemoryStorage.load()`
- [x] 7.4 Update script documentation if needed

## 8. Testing

- [x] 8.1 Write unit tests for auto-default configuration logic (all scenarios from spec)
- [x] 8.2 Write unit tests for split configuration validation (production reject, dev warn, consistent pass, SQLite skip)
- [x] 8.3 Write integration tests for SQLite→PostgreSQL migration (all 16 tables, idempotency, validation)
- [x] 8.4 Write integration tests for Chroma→pgvector reindexing (KB-bound embedding, dimension validation, resume, dry-run)
- [ ] 8.5 Write end-to-end test: create thread with SQLite → migrate to PostgreSQL → restart → verify thread loads
- [ ] 8.6 Write end-to-end test: upload KB with Chroma → reindex to pgvector → restart → verify RAG retrieval works

## 9. Documentation

- [x] 9.1 Create `docs/POSTGRESQL_MIGRATION.md` with step-by-step migration guide (5 phases from design.md)
- [x] 9.2 Document configuration auto-default behavior and explicit override
- [x] 9.3 Document split configuration validation (production vs development mode)
- [x] 9.4 Document migration script usage (`migrate_sqlite_to_postgres.py` with examples)
- [x] 9.5 Document reindexing script usage (`reindex_rag_to_pgvector.py` with examples)
- [x] 9.6 Document rollback procedure (restore backups, revert config, restart)
- [x] 9.7 Create migration runbook for operations team (pre-migration checklist, execution steps, post-migration validation)
- [x] 9.8 Update `config.example.yaml` with PostgreSQL configuration examples and auto-default comments

## 10. Deployment Preparation

- [x] 10.1 Document PostgreSQL extension installation (`vector`, `pgcrypto`) with version requirements
- [x] 10.2 Create backup procedures for SQLite, JSON files, and Chroma directory
- [x] 10.3 Create restore procedures for rollback scenarios
- [x] 10.4 Estimate reindexing cost calculation logic (document count × avg tokens × model pricing)
- [x] 10.5 Plan maintenance window communication (notify users of downtime)
