## Context

DeerFlow currently uses a fragmented storage architecture:
- **SQLite** for structured business data (users, tenants, threads, runs, knowledge bases)
- **JSON files** for operational data (token_usage.json, memory.json, feedback.json)
- **In-memory stores** for run_events (lost on restart)
- **Chroma** for RAG vector embeddings
- **Filesystem** for uploads, artifacts, and workspaces

This fragmentation creates several problems:
1. Multi-instance deployments cannot share state consistently
2. Backup/recovery requires coordinating multiple storage systems
3. Operational queries (cost tracking, audit logs) are difficult
4. Some data (run_events) is lost on restart

The codebase already has partial PostgreSQL support:
- `DatabaseConfig` supports `memory`, `sqlite`, and `postgres` backends
- LangGraph checkpointer/store can use PostgreSQL
- `FeedbackRepository` already uses SQL
- `pgvector` backend exists but isn't default
- `StoreMemoryStorage` can write to LangGraph Store

The migration consolidates these partial implementations into a unified PostgreSQL-first architecture.

**Stakeholders**: DevOps (deployment), Backend team (implementation), Users (no visible changes expected)

**Constraints**:
- Must support both SQLite (dev) and PostgreSQL (prod) modes
- Cannot require downtime for multi-hour migrations
- Must preserve all existing data
- File storage (uploads/artifacts) stays on filesystem

## Goals / Non-Goals

**Goals:**
1. PostgreSQL becomes the authoritative storage for all core structured and runtime state
2. Multi-instance deployments share consistent state without local disk dependencies
3. Single backup/restore procedure covers all critical data
4. Configuration consolidates under `database.backend` setting
5. Migration is phased, testable, and rollback-capable
6. SQLite remains supported for local development

**Non-Goals:**
1. Not migrating file storage (uploads, artifacts, workspaces) into PostgreSQL
2. Not redesigning multi-tenancy isolation model
3. Not changing RAG product capabilities (only storage backend)
4. Not supporting hot-swap between SQLite and PostgreSQL during runtime
5. Not maintaining long-term dual-write to both backends
6. Not requiring online migration of all historical data (offline scripts acceptable)

## Decisions

### Decision 1: Configuration Consolidation
**Choice**: Use `database.backend` as the single source of truth for storage mode selection.

**Rationale**: 
- Current fragmentation has different subsystems reading different config sections
- `checkpointer`, `run_events`, `cost`, `memory`, `rag` each had independent backend settings
- This led to "split brain" configurations (e.g., PostgreSQL for business data but JSON for costs)

**Alternatives considered**:
- Keep independent config sections → Rejected: perpetuates fragmentation
- Force PostgreSQL-only → Rejected: breaks local dev workflow

**Implementation**:
- Deprecate standalone `checkpointer` config section (keep for backward compat)
- When `database.backend=postgres`, auto-default:
  - `run_events.backend = db`
  - `cost.storage_backend = postgres`
  - `memory.storage_class = StoreMemoryStorage`
  - `rag.vector_store_backend = pgvector`
- Add startup validation to reject split configurations in production mode

### Decision 2: Dual-Mode Support (SQLite + PostgreSQL)
**Choice**: Support both backends through configuration, but switching requires restart/redeploy.

**Rationale**:
- Local development benefits from zero-dependency SQLite
- Production requires PostgreSQL for multi-instance consistency
- Hot-swapping storage backends mid-flight is architecturally complex and error-prone

**Alternatives considered**:
- PostgreSQL-only → Rejected: raises dev environment barrier
- Hot-swap support → Rejected: requires dual-write architecture, high complexity
- Long-term dual-write → Rejected: consistency guarantees become difficult

**Implementation**:
- `database.backend` selects mode at startup
- Migration scripts handle one-time data transfer
- Rollback requires restore from backup + config change + restart

### Decision 3: Token Usage as Formal ORM Table
**Choice**: Replace `PgUsageStorage` prototype with proper ORM model + Alembic migration.

**Rationale**:
- Current `PgUsageStorage` uses raw `psycopg` with runtime DDL and JSON fallback
- Not integrated with Alembic schema versioning
- Difficult to query, aggregate, or enforce retention policies

**Alternatives considered**:
- Keep JSON file → Rejected: doesn't solve multi-instance problem
- Keep prototype → Rejected: technical debt, no schema versioning

**Implementation**:
- New `TokenUsage` ORM model with fields: `tenant_id`, `user_id`, `thread_id`, `run_id`, `model_name`, `input_tokens`, `output_tokens`, `total_tokens`, `cost_usd`, `created_at`
- Alembic migration to create table
- `TokenUsageRepository` for CRUD operations
- One-time migration script: `token_usage.json` → PostgreSQL table

### Decision 4: Memory Storage via LangGraph Store
**Choice**: Use `StoreMemoryStorage` (already implemented) instead of creating a separate `memory` table.

**Rationale**:
- `StoreMemoryStorage` already writes to LangGraph Store
- Store backend automatically follows `database.backend` setting
- Avoids creating yet another table when Store provides namespace isolation

**Alternatives considered**:
- New `memory` ORM table → Rejected: duplicates Store functionality
- Keep file-based → Rejected: doesn't solve multi-instance problem

**Implementation**:
- Default to `StoreMemoryStorage` when `database.backend=postgres`
- Migration script: `memory.json` → Store namespace per user/agent
- File-based storage remains fallback for SQLite mode

### Decision 5: RAG Vector Storage with pgvector
**Choice**: Migrate from Chroma to pgvector, rebuild indexes from source documents.

**Rationale**:
- Chroma adds another persistence system to manage
- Multi-instance deployments need shared vector storage
- Backup/restore should cover vectors alongside metadata
- pgvector integrates with existing PostgreSQL infrastructure

**Alternatives considered**:
- Keep Chroma → Rejected: perpetuates storage fragmentation
- Copy Chroma files → Rejected: Chroma internal format is not portable
- Separate vector database (Pinecone, Weaviate) → Rejected: adds external dependency

**Implementation**:
- Formalize `rag_chunks` table with pgvector extension
- Alembic migration for table + HNSW/IVFFlat indexes
- Reindex all knowledge base documents from source content
- Migration validates chunk count and spot-checks retrieval results

### Decision 6: Run Events Default to Database
**Choice**: Change `run_events.backend` default from `memory` to `db` when using PostgreSQL.

**Rationale**:
- Current memory backend loses all events on restart
- Audit, debugging, and analytics require persistent event history
- `db` backend already implemented in `runtime/events/store/db.py`

**Alternatives considered**:
- Keep memory default → Rejected: loses critical operational data
- JSONL file → Rejected: doesn't solve multi-instance problem

**Implementation**:
- Auto-default to `db` when `database.backend=postgres`
- No migration needed (historical memory-only events are already lost)

### Decision 7: Phased Migration Strategy
**Choice**: Migrate in phases: config → structured data → runtime state → vectors → cleanup.

**Rationale**:
- All-at-once migration is high-risk and difficult to test
- Phased approach allows validation at each step
- Rollback is easier if issues are caught early

**Phases**:
1. **Phase 0**: Prepare PostgreSQL instance, install extensions, test connectivity
2. **Phase 1**: Migrate structured business tables (users, tenants, threads, runs, knowledge bases)
3. **Phase 2**: Migrate runtime state (checkpointer, store, run_events, memory, token_usage)
4. **Phase 3**: Migrate vector storage (reindex to pgvector)
5. **Phase 4**: Cleanup (deprecate old files, update docs)

**Alternatives considered**:
- Big-bang migration → Rejected: too risky, hard to rollback
- Gradual dual-write → Rejected: consistency complexity

## Risks / Trade-offs

### Risk 1: Configuration Fragmentation Persists
**Risk**: Developers might still configure split backends (e.g., PostgreSQL for data but JSON for costs).

**Mitigation**:
- Add startup validation that rejects split configurations in production mode
- Emit deprecation warnings for old config sections
- Update documentation to emphasize `database.backend` as primary control

### Risk 2: Checkpointer Migration Complexity
**Risk**: LangGraph checkpointer tables are managed by the library, not Alembic. Schema differences between SQLite and PostgreSQL could cause issues.

**Mitigation**:
- Use LangGraph's abstraction layer for migration (read from SQLite checkpointer, write to PostgreSQL checkpointer)
- If schema versions match, consider table-level copy as optimization
- Test migration on staging environment first
- Maintain maintenance window for production migration

### Risk 3: Vector Migration Cost
**Risk**: Reindexing all documents to pgvector may consume significant embedding API tokens and time.

**Mitigation**:
- Estimate cost before migration (document count × embedding model cost)
- Batch reindexing to control rate limits
- Consider caching embeddings during migration if source documents haven't changed
- Validate chunk count and spot-check retrieval quality after migration

### Risk 4: High-Volume Table Growth
**Risk**: `run_events` and `token_usage` tables could grow rapidly in production.

**Mitigation**:
- Implement retention policies (e.g., archive events older than 90 days)
- Add indexes on `(tenant_id, created_at DESC)` for efficient queries
- Consider table partitioning for future scalability
- Monitor table sizes and query performance

### Risk 5: Local Development Barrier
**Risk**: Requiring PostgreSQL for all development could slow down onboarding and testing.

**Mitigation**:
- Keep SQLite as default for `database.backend` in dev mode
- Document PostgreSQL setup for developers who need to test multi-instance features
- CI tests should cover both SQLite and PostgreSQL modes

### Risk 6: Rollback Data Loss
**Risk**: If migration fails and we rollback to SQLite, any new data written to PostgreSQL during testing is lost.

**Mitigation**:
- Announce maintenance window before migration
- Stop writes during migration
- Keep SQLite/JSON/Chroma snapshots until PostgreSQL is validated
- Test rollback procedure in staging environment

## Migration Plan

### Pre-Migration Checklist
1. Provision PostgreSQL 15+ instance
2. Install extensions: `vector`, `pgcrypto`
3. Create database and user with appropriate permissions
4. Test connectivity from application servers
5. Backup all existing data:
   - SQLite database files
   - `feedback.json`, `token_usage.json`, `memory.json`
   - Chroma persist directory
6. Estimate vector reindexing cost (document count × embedding cost)

### Phase 1: Structured Business Tables
**Duration**: ~1-2 hours (depends on data volume)

1. Stop writes (announce maintenance window)
2. Run Alembic migrations on PostgreSQL to create tables
3. Execute `scripts/migrate_sqlite_to_postgres.py`:
   - Migrate: users, tenants, threads_meta, runs, knowledge_bases, knowledge_base_documents
   - Validate record counts match
   - Spot-check sample records
4. Update config: `database.backend = postgres`
5. Restart services
6. Verify: threads load, new conversations work

### Phase 2: Runtime State
**Duration**: ~2-4 hours (depends on checkpointer size)

1. Stop writes
2. Execute migration scripts:
   - `scripts/migrate_checkpointer_sqlite_to_postgres.py` (via LangGraph abstraction)
   - `scripts/migrate_memory_to_store.py` (memory.json → Store)
   - `scripts/migrate_token_usage_json_to_postgres.py`
3. Update config:
   - `run_events.backend = db`
   - `memory.storage_class = StoreMemoryStorage`
4. Restart services
5. Verify: thread history loads, memory injects, run events persist

### Phase 3: Vector Storage
**Duration**: ~4-8 hours (depends on document count and embedding rate limits)

1. Run Alembic migration to create `rag_chunks` table with pgvector extension
2. Execute `scripts/reindex_rag_to_pgvector.py`:
   - For each knowledge base document:
     - Re-chunk content
     - Generate embeddings
     - Insert into `rag_chunks` table
   - Batch processing with rate limiting
3. Update config: `rag.vector_store_backend = pgvector`
4. Restart services
5. Verify:
   - Chunk count matches expected
   - Spot-check retrieval results against Chroma baseline
   - Test search quality with sample queries

### Phase 4: Cleanup
**Duration**: ~1 hour

1. Verify PostgreSQL system is stable (monitor for 24-48 hours)
2. Archive old files (don't delete yet):
   - Move SQLite files to `backups/`
   - Move JSON files to `backups/`
   - Move Chroma directory to `backups/`
3. Update documentation:
   - Deployment guide
   - Configuration reference
   - Backup/restore procedures
4. Remove deprecation warnings after one release cycle

### Rollback Procedure
**If migration fails**:

1. Stop all writes immediately
2. Restore from backups:
   - Copy SQLite files back
   - Copy JSON files back
   - Copy Chroma directory back
3. Revert config:
   - `database.backend = sqlite`
   - `run_events.backend = memory`
   - `memory.storage_class = FileMemoryStorage`
   - `rag.vector_store_backend = chroma`
4. Restart services
5. Verify: threads load, conversations work, RAG retrieval works
6. Preserve PostgreSQL data for post-mortem analysis (don't drop database)

## Open Questions

1. **Retention policies**: What is the retention period for `run_events` and `token_usage`? Should we implement automatic archival?
   - **Recommendation**: Start with 90-day retention, implement archival in Phase 2

2. **Connection pooling**: What are the optimal pool sizes for different deployment scales?
   - **Recommendation**: Start with `pool_size=20`, monitor connection usage, adjust based on load

3. **Content safety logs**: Should `content_safety_logs.json` be migrated to PostgreSQL in this phase?
   - **Recommendation**: Defer to Phase 2 (optional), focus on core state first

4. **Embedding caching**: Should we cache embeddings during migration to avoid re-generating for unchanged documents?
   - **Recommendation**: Yes, if source document content hash matches, reuse existing embedding

5. **Multi-database setup**: Should we use separate PostgreSQL databases for different concerns (app data, vectors, events)?
   - **Recommendation**: Start with single database for simplicity, consider separation later if needed
