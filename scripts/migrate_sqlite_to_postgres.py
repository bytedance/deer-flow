"""Migrate data from SQLite to PostgreSQL for DeerFlow."""

import json
import sqlite3

import psycopg

PG_URL = "postgresql://postgres:2012dbkey@182.92.187.198:5432/deerflow"
SQLITE_MAIN = "backend/.deer-flow/data/deerflow.db"
SQLITE_CKPT = "backend/.deer-flow/checkpoints.db"

# Tables to migrate (order matters for FK constraints)
MAIN_TABLES = [
    "tenants",
    "users",
    "threads_meta",
    "runs",
    "run_events",
    "agent_usage",
    "feedback",
    "knowledge_bases",
    "knowledge_base_documents",
    "kb_permissions",
    "index_jobs",
    "agents",
    "agent_permissions",
    "closure_sla_configs",
    "closure_tickets",
    "closure_ticket_events",
    "memory_audit",
]

# Columns that are BOOLEAN in PostgreSQL (SQLite stores as 0/1)
BOOLEAN_COLUMNS = {
    "tenants": {"is_active"},
    "users": {"needs_setup"},
    "knowledge_bases": {"vector_metric_stale"},
    "agents": {"enabled"},
    "closure_tickets": {"is_overdue"},
}

# Columns that are JSON type in PostgreSQL
JSON_COLUMNS = {
    "run_events": {"event_metadata"},
    "runs": {"metadata_json", "kwargs_json"},
    "threads_meta": {"metadata_json"},
    "knowledge_base_documents": {"chunk_ids", "metadata_json"},
    "index_jobs": {"old_chunk_ids", "new_chunk_ids"},
    "agents": {"tool_groups", "skills", "mcp_servers", "tags"},
    "closure_tickets": {"extra_metadata"},
    "closure_ticket_events": {"payload"},
    "memory_audit": {"before", "after"},
}

# Tables with SERIAL id (need to reset sequence after insert)
SERIAL_TABLES = {"run_events": "run_events_id_seq", "memory_audit": "memory_audit_id_seq"}


def migrate_main_db():
    print("=" * 60)
    print("Migrating main database")
    print("=" * 60)

    sqlite_conn = sqlite3.connect(SQLITE_MAIN)
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = psycopg.connect(PG_URL, autocommit=False)

    try:
        for table in MAIN_TABLES:
            cur = sqlite_conn.cursor()
            cur.execute(f"PRAGMA table_info([{table}])")
            columns = [row["name"] for row in cur.fetchall()]
            if not columns:
                print(f"  {table}: SKIP (not found in SQLite)")
                continue

            cur.execute(f"SELECT * FROM [{table}]")
            rows = cur.fetchall()
            if not rows:
                print(f"  {table}: 0 rows (skip)")
                continue

            json_cols = JSON_COLUMNS.get(table, set())
            bool_cols = BOOLEAN_COLUMNS.get(table, set())
            placeholders = ", ".join(["%s"] * len(columns))
            col_names = ", ".join(f'"{c}"' for c in columns)
            sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})'

            pg_cur = pg_conn.cursor()
            batch = []
            for row in rows:
                values = []
                for col in columns:
                    val = row[col]
                    if col in json_cols and val is not None:
                        if isinstance(val, str):
                            val = json.loads(val)
                        val = json.dumps(val)
                    if col in bool_cols and val is not None:
                        val = bool(val)
                    values.append(val)
                batch.append(values)

            pg_cur.executemany(sql, batch)
            pg_conn.commit()

            if table in SERIAL_TABLES:
                seq = SERIAL_TABLES[table]
                pg_cur.execute(f'SELECT setval(\'{seq}\', (SELECT MAX(id) FROM "{table}"))')
                pg_conn.commit()

            print(f"  {table}: {len(rows)} rows migrated")

        print("Main database migration complete!")
    except Exception as e:
        pg_conn.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        sqlite_conn.close()
        pg_conn.close()


def migrate_checkpoints():
    print()
    print("=" * 60)
    print("Migrating checkpoint database")
    print("=" * 60)

    sqlite_conn = sqlite3.connect(SQLITE_CKPT)
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = psycopg.connect(PG_URL, autocommit=False)

    try:
        pg_cur = pg_conn.cursor()

        # Create checkpoint tables if they don't exist
        pg_cur.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                parent_checkpoint_id TEXT,
                type TEXT,
                checkpoint BYTEA,
                metadata JSONB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            )
        """)
        pg_cur.execute("""
            CREATE TABLE IF NOT EXISTS checkpoint_writes (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                channel TEXT NOT NULL,
                type TEXT,
                value BYTEA,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
            )
        """)
        pg_cur.execute("""
            CREATE TABLE IF NOT EXISTS checkpoint_store (
                prefix TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ,
                expires_at TIMESTAMPTZ,
                ttl_minutes DOUBLE PRECISION,
                PRIMARY KEY (prefix, key)
            )
        """)
        pg_conn.commit()
        print("  Checkpoint tables created in PostgreSQL")

        # Migrate checkpoints
        sc = sqlite_conn.cursor()
        sc.execute("SELECT * FROM checkpoints")
        rows = sc.fetchall()
        if rows:
            cols = ["thread_id", "checkpoint_ns", "checkpoint_id", "parent_checkpoint_id", "type", "checkpoint", "metadata"]
            sql = "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            batch = []
            for row in rows:
                metadata = row["metadata"]
                if metadata is not None:
                    if isinstance(metadata, (str, bytes)):
                        try:
                            metadata = json.loads(metadata) if isinstance(metadata, str) else json.loads(metadata.decode())
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            pass
                    metadata = json.dumps(metadata)
                batch.append([row["thread_id"], row["checkpoint_ns"], row["checkpoint_id"],
                              row["parent_checkpoint_id"], row["type"], row["checkpoint"], metadata])
            pg_cur.executemany(sql, batch)
            pg_conn.commit()
            print(f"  checkpoints: {len(rows)} rows migrated")

        # Migrate writes
        sc.execute("SELECT * FROM writes")
        rows = sc.fetchall()
        if rows:
            sql = "INSERT INTO checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            batch = []
            for row in rows:
                batch.append([row["thread_id"], row["checkpoint_ns"], row["checkpoint_id"],
                              row["task_id"], row["idx"], row["channel"], row["type"], row["value"]])
            pg_cur.executemany(sql, batch)
            pg_conn.commit()
            print(f"  checkpoint_writes: {len(rows)} rows migrated")

        # Migrate store
        sc.execute("SELECT * FROM store")
        rows = sc.fetchall()
        if rows:
            sql = "INSERT INTO checkpoint_store (prefix, key, value, created_at, updated_at, expires_at, ttl_minutes) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            batch = []
            for row in rows:
                batch.append([row["prefix"], row["key"], row["value"],
                              row["created_at"], row["updated_at"], row["expires_at"], row["ttl_minutes"]])
            pg_cur.executemany(sql, batch)
            pg_conn.commit()
            print(f"  checkpoint_store: {len(rows)} rows migrated")
        else:
            print("  checkpoint_store: 0 rows (skip)")

        print("Checkpoint migration complete!")
    except Exception as e:
        pg_conn.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    migrate_main_db()
    migrate_checkpoints()
    print()
    print("All migrations complete!")
