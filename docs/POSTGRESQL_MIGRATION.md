# PostgreSQL Migration Guide

DeerFlow supports migrating from SQLite/JSON/Chroma to a unified PostgreSQL backend for production deployments. This guide covers prerequisites, configuration, migration scripts, and rollback procedures.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Configuration Auto-Default](#configuration-auto-default)
- [Split Configuration Validation](#split-configuration-validation)
- [Migration Phases](#migration-phases)
  - [Phase 1: Backup](#phase-1-backup)
  - [Phase 2: SQLite to PostgreSQL](#phase-2-sqlite-to-postgresql)
  - [Phase 3: Chroma to pgvector](#phase-3-chroma-to-pgvector)
  - [Phase 4: Token Usage JSON Cleanup](#phase-4-token-usage-json-cleanup)
  - [Phase 5: Memory JSON Migration](#phase-5-memory-json-migration)
- [Rollback Procedure](#rollback-procedure)
- [Migration Runbook](#migration-runbook)

## Prerequisites

### PostgreSQL Extensions

Install these extensions before migration:

```sql
-- Required for vector embeddings (pgvector backend)
CREATE EXTENSION IF NOT EXISTS vector;

-- Required for UUID generation (used by some ORM models)
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

**Version requirements:**
- PostgreSQL 14+ (pgvector requires 14+)
- pgvector 0.5+ (for `halfvec` support in newer embedding models)

Install pgvector on common platforms:
```bash
# Ubuntu/Debian
sudo apt install postgresql-16-pgvector

# macOS (Homebrew)
brew install pgvector

# Docker
# Use image: pgvector/pgvector:pg16
```

### Python Dependencies

```bash
cd backend
uv sync --extra postgres
# Or manually:
uv add langgraph-checkpoint-postgres psycopg[binary] psycopg-pool pgvector sqlalchemy
```

## Configuration Auto-Default

When `database.backend` is set to `postgres`, DeerFlow automatically configures subsystem backends to use PostgreSQL as well — unless they are explicitly set.

| Subsystem              | Auto-defaulted value when `database.backend=postgres` | Explicit override field            |
|------------------------|-------------------------------------------------------|------------------------------------|
| `run_events.backend`   | `db`                                                  | `run_events.backend`               |
| `memory.storage_class` | `StoreMemoryStorage` (via LangGraph Store)            | `memory.storage_class`             |
| `rag.vector_store_backend` | `pgvector`                                        | `rag.vector_store_backend`         |
| `cost.storage_backend` | `postgres`                                            | `cost.storage_backend`             |

**How it works:** During `AppConfig.__init__()`, if `database.backend == "postgres"` and a subsystem field was not explicitly set in `config.yaml`, the auto-default is applied and an INFO log is emitted:

```
INFO deerflow.config: Auto-defaulting run_events.backend to 'db' (database.backend=postgres)
INFO deerflow.config: Auto-defaulting rag.vector_store_backend to 'pgvector' (database.backend=postgres)
```

If you explicitly set a subsystem to a non-PostgreSQL value (e.g., `run_events.backend: jsonl`), the auto-default is skipped and a WARNING is logged.

### Example: Full PostgreSQL config (minimal)

```yaml
database:
  backend: postgres
  postgres_url: $DATABASE_URL
```

All subsystems auto-default to PostgreSQL-backed storage.

### Example: Mixed config (explicit override)

```yaml
database:
  backend: postgres
  postgres_url: $DATABASE_URL

# Keep run events in JSONL for debugging
run_events:
  backend: jsonl
```

## Split Configuration Validation

DeerFlow validates backend consistency at startup. Behaviour depends on the environment:

### Production Mode (`DEER_FLOW_ENV=production`)

Split backends (e.g., `database.backend=postgres` but `rag.vector_store_backend=chroma`) raise a `ConfigValidationError` and **prevent startup**. The error message includes:

```
ConfigValidationError: Split storage backends detected in production.
  - database.backend=postgres but rag.vector_store_backend=chroma
  Recommendation: Set rag.vector_store_backend=pgvector (or remove the explicit
  setting to let auto-default apply).
  See: docs/POSTGRESQL_MIGRATION.md
```

### Development Mode (default, or `DEER_FLOW_ENV=development`)

Split backends log a WARNING but allow startup:

```
WARNING deerflow.config: Split storage backends detected (development mode).
  database.backend=postgres, rag.vector_store_backend=chroma
  This is acceptable for development but should be unified in production.
```

### SQLite/Memory Mode

Validation is skipped entirely when `database.backend` is `sqlite` or `memory`.

## Migration Phases

### Phase 1: Backup

Before any migration step, create full backups:

```bash
# 1. Backup SQLite database
cp .deer-flow/data/deerflow.db .deer-flow/data/deerflow.db.bak.$(date +%Y%m%d)

# 2. Backup Chroma directory
tar czf chroma-backup-$(date +%Y%m%d).tar.gz .deer-flow/chroma/

# 3. Backup JSON files (token usage + memory)
tar czf json-backup-$(date +%Y%m%d).tar.gz \
    $(find .deer-flow -name "token_usage.json") \
    $(find .deer-flow -name "memory.json")

# 4. Backup config.yaml
cp config.yaml config.yaml.bak.$(date +%Y%m%d)
```

### Phase 2: SQLite to PostgreSQL

Migrate all ORM tables (18 tables: users, tenants, threads, runs, run_events, knowledge_bases, etc.) from SQLite to PostgreSQL.

```bash
cd backend

# Dry run — show what would be migrated
python scripts/migrate_sqlite_to_postgres.py \
    --sqlite-path ../.deer-flow/data/deerflow.db \
    --postgres-url "postgresql://user:pass@host:5432/deerflow" \
    --dry-run

# Actual migration (batch size 1000, with validation)
python scripts/migrate_sqlite_to_postgres.py \
    --sqlite-path ../.deer-flow/data/deerflow.db \
    --postgres-url "postgresql://user:pass@host:5432/deerflow" \
    --batch-size 1000

# Skip validation if needed
python scripts/migrate_sqlite_to_postgres.py \
    --sqlite-path ../.deer-flow/data/deerflow.db \
    --postgres-url "postgresql://user:pass@host:5432/deerflow" \
    --skip-validation
```

**Features:**
- Idempotent: re-running skips already-migrated rows (by primary key)
- Batch processing: configurable batch size for memory efficiency
- Validation: compares row counts post-migration, exits with code 1 on mismatch
- Progress logging: `Migrated batch 1/5: 1000 rows`

### Phase 3: Chroma to pgvector

Reindex knowledge base documents from Chroma to pgvector. Each KB uses its own embedding model and dimension (KB-bound embedding).

```bash
cd backend

# Dry run — estimate tokens and cost without embedding
python scripts/reindex_rag_to_pgvector.py \
    --chroma-path ../.deer-flow/chroma \
    --postgres-url "postgresql://user:pass@host:5432/deerflow" \
    --dry-run

# Actual migration
python scripts/reindex_rag_to_pgvector.py \
    --chroma-path ../.deer-flow/chroma \
    --postgres-url "postgresql://user:pass@host:5432/deerflow" \
    --batch-size 100 \
    --rate-limit 60

# Resume after failure (skips completed KBs)
python scripts/reindex_rag_to_pgvector.py \
    --chroma-path ../.deer-flow/chroma \
    --postgres-url "postgresql://user:pass@host:5432/deerflow" \
    --resume
```

**Cost estimation (dry-run output):**

| KB Name     | Documents | Est. Tokens | Est. Cost (text-embedding-3-small) |
|-------------|-----------|-------------|-------------------------------------|
| Product FAQ | 250       | 125,000     | $0.0025                             |
| Tech Docs   | 1,200     | 600,000     | $0.0120                             |

Pricing reference (per 1M tokens):
- `text-embedding-3-small`: $0.02
- `text-embedding-3-large`: $0.13

**Features:**
- KB-bound embedding: each KB's `embedding_model` and `embedding_dim` are used
- Dimension validation: rejects mismatched embedding dimensions per KB
- Resume support: tracks completed KBs in `reindex_resume.json`
- Rate limiting: configurable batches-per-minute to avoid API rate limits
- Single KB failure isolation: one KB failure does not block others

### Phase 4: Token Usage JSON Cleanup

Audit `token_usage.json` files against ORM data (`RunRow` + `AgentUsageRow`). Archive files that match within 1% tolerance.

```bash
cd backend

# Audit only (no archival)
python scripts/cleanup_token_usage_json.py \
    --db-url "postgresql://user:pass@host:5432/deerflow" \
    --base-dir ../.deer-flow \
    --dry-run

# Audit and archive matching files
python scripts/cleanup_token_usage_json.py \
    --db-url "postgresql://user:pass@host:5432/deerflow" \
    --base-dir ../.deer-flow
```

**Output:**
```
======================================================================
TOKEN USAGE JSON CLEANUP REPORT
======================================================================
  Total JSON files scanned:     5
  Files not found (skipped):    0
  Files with matching data:     4
  Files with mismatch:          1
  Files archived:               4
----------------------------------------------------------------------

  ✓ ARCHIVED: .deer-flow/tenants/default/token_usage.json
    JSON records: 42
    JSON tokens:  125000
    ORM tokens:   125050
    Tolerance:    1.0%

  ✗ MISMATCH: .deer-flow/tenants/staging/token_usage.json
    JSON records: 10
    JSON tokens:  50000
    ORM tokens:   45000
    Tolerance:    1.0%
======================================================================
```

Mismatched files are NOT archived — they require manual review.

### Phase 5: Memory JSON Migration

Migrate `memory.json` files (per-user, per-agent) to the LangGraph Store (PostgreSQL).

```bash
cd backend

# Dry run
python scripts/migrate_memory_to_store.py \
    --postgres-url "postgresql://user:pass@host:5432/deerflow" \
    --dry-run

# Migrate with custom base directory
python scripts/migrate_memory_to_store.py \
    --postgres-url "postgresql://user:pass@host:5432/deerflow" \
    --base-dir ../.deer-flow \
    --tenant-id default
```

**Recognised file layouts:**
- `{base_dir}/memory.json` → tenant-level memory
- `{base_dir}/agents/{name}/memory.json` → tenant-level agent memory
- `{base_dir}/users/{uid}/memory.json` → per-user memory
- `{base_dir}/users/{uid}/agents/{name}/memory.json` → per-user agent memory

**Namespace scheme in Store:** `("memory", tenant_id, user_id, agent_name)` with key `"data"`.

## Rollback Procedure

If migration fails or causes issues, restore from backups:

### 1. Stop the application

```bash
# Docker
docker compose down

# Local
pkill -f "uvicorn.*deerflow"
```

### 2. Restore config

```bash
cp config.yaml.bak.YYYYMMDD config.yaml
```

### 3. Restore SQLite database

```bash
cp .deer-flow/data/deerflow.db.bak.YYYYMMDD .deer-flow/data/deerflow.db
```

### 4. Restore Chroma directory

```bash
rm -rf .deer-flow/chroma/
tar xzf chroma-backup-YYYYMMDD.tar.gz -C .deer-flow/
```

### 5. Restore JSON files

```bash
tar xzf json-backup-YYYYMMDD.tar.gz
```

### 6. Restart the application

```bash
# Docker
docker compose up -d

# Local
cd backend && uv run uvicorn deerflow.gateway:app --host 0.0.0.0 --port 8001
```

## Migration Runbook

### Pre-Migration Checklist

- [ ] PostgreSQL 14+ installed with `vector` and `pgcrypto` extensions
- [ ] Python dependencies installed (`uv sync --extra postgres`)
- [ ] `DATABASE_URL` environment variable set in `.env`
- [ ] Full backup created (SQLite, Chroma, JSON files, config.yaml)
- [ ] Maintenance window communicated to users
- [ ] Rollback procedure tested (restore from backup on staging)

### Execution Steps

1. **Set config to PostgreSQL:**
   ```yaml
   database:
     backend: postgres
     postgres_url: $DATABASE_URL
   ```

2. **Run SQLite → PostgreSQL migration:**
   ```bash
   python scripts/migrate_sqlite_to_postgres.py \
       --sqlite-path ../.deer-flow/data/deerflow.db \
       --postgres-url "$DATABASE_URL"
   ```
   - Verify: exit code 0, all table counts match

3. **Run Chroma → pgvector reindexing (dry-run first):**
   ```bash
   python scripts/reindex_rag_to_pgvector.py \
       --chroma-path ../.deer-flow/chroma \
       --postgres-url "$DATABASE_URL" \
       --dry-run
   ```
   - Verify: estimated cost is acceptable

4. **Run Chroma → pgvector reindexing:**
   ```bash
   python scripts/reindex_rag_to_pgvector.py \
       --chroma-path ../.deer-flow/chroma \
       --postgres-url "$DATABASE_URL" \
       --resume
   ```
   - Verify: all KBs report "success"

5. **Audit token usage JSON files:**
   ```bash
   python scripts/cleanup_token_usage_json.py \
       --db-url "$DATABASE_URL" \
       --base-dir ../.deer-flow \
       --dry-run
   ```
   - Investigate any mismatches before proceeding

6. **Archive matching token usage files:**
   ```bash
   python scripts/cleanup_token_usage_json.py \
       --db-url "$DATABASE_URL" \
       --base-dir ../.deer-flow
   ```

7. **Migrate memory JSON files:**
   ```bash
   python scripts/migrate_memory_to_store.py \
       --postgres-url "$DATABASE_URL" \
       --base-dir ../.deer-flow
   ```

8. **Restart the application:**
   ```bash
   docker compose up -d
   ```

### Post-Migration Validation

- [ ] Gateway starts without `ConfigValidationError`
- [ ] Existing threads load correctly (check thread list in UI)
- [ ] New messages can be sent and received
- [ ] RAG knowledge base search returns results
- [ ] Token usage dashboard shows correct data
- [ ] Memory persists across sessions
- [ ] No errors in application logs
