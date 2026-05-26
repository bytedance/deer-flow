#!/usr/bin/env python
"""Migrate data from SQLite to PostgreSQL.

Reads all ORM tables from a SQLite database and writes them to PostgreSQL
in batches. Idempotent: re-running skips rows that already exist (by PK).

Usage:
    python scripts/migrate_sqlite_to_postgres.py \
        --sqlite-path /path/to/deerflow.db \
        --postgres-url postgresql://user:pass@host:5432/deerflow

Options:
    --batch-size N       Rows per batch (default: 1000)
    --skip-validation    Skip post-migration row count checks
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _collect_all_models():
    """Import all ORM models and return (table_name -> ORM class) mapping."""
    from deerflow.persistence.models import (
        ClosureSlaConfigRow,
        ClosureTicketEventRow,
        ClosureTicketRow,
        FeedbackRow,
        IndexJobRow,
        KnowledgeBaseDocumentRow,
        KnowledgeBaseRow,
        RunEventRow,
        RunRow,
        TenantRow,
        ThreadMetaRow,
        UserRow,
    )
    from deerflow.persistence.agent.model import AgentPermissionRow, AgentRow
    from deerflow.persistence.agent.usage_model import AgentUsageRow
    from deerflow.persistence.http_connector.model import TenantHttpConnectorRow
    from deerflow.persistence.knowledge_base.model import KbPermissionRow
    from deerflow.persistence.mcp_server.model import TenantMcpServerRow

    models = [
        UserRow,
        TenantRow,
        ThreadMetaRow,
        RunRow,
        RunEventRow,
        KnowledgeBaseRow,
        KnowledgeBaseDocumentRow,
        KbPermissionRow,
        IndexJobRow,
        AgentRow,
        AgentPermissionRow,
        AgentUsageRow,
        FeedbackRow,
        TenantHttpConnectorRow,
        TenantMcpServerRow,
        ClosureTicketRow,
        ClosureTicketEventRow,
        ClosureSlaConfigRow,
    ]
    return {m.__tablename__: m for m in models}


@dataclass
class TableReport:
    """Migration result for a single table."""

    table_name: str
    sqlite_rows: int = 0
    postgres_rows_before: int = 0
    rows_migrated: int = 0
    rows_skipped: int = 0
    postgres_rows_after: int = 0
    duration_sec: float = 0.0
    error: str = ""


@dataclass
class MigrationReport:
    """Overall migration report."""

    tables: list[TableReport] = field(default_factory=list)
    total_duration_sec: float = 0.0

    def print_report(self) -> None:
        """Print a human-readable migration report."""
        print("\n" + "=" * 80)
        print("MIGRATION REPORT")
        print("=" * 80)
        total_migrated = 0
        total_skipped = 0
        errors = 0
        for t in self.tables:
            status = "✓" if not t.error else "✗"
            print(f"  {status} {t.table_name:<30} {t.sqlite_rows:>6} rows  "
                  f"(migrated: {t.rows_migrated}, skipped: {t.rows_skipped}, "
                  f"{t.duration_sec:.1f}s)")
            if t.error:
                print(f"    ERROR: {t.error}")
                errors += 1
            total_migrated += t.rows_migrated
            total_skipped += t.rows_skipped

        print("-" * 80)
        print(f"  Total: {len(self.tables)} tables, "
              f"{total_migrated} rows migrated, {total_skipped} skipped, "
              f"{errors} errors, {self.total_duration_sec:.1f}s")
        print("=" * 80 + "\n")


def _get_primary_key(model_cls) -> str:
    """Return the primary key column name for a model class."""
    mapper = inspect(model_cls)
    pk_cols = mapper.primary_key
    if len(pk_cols) != 1:
        raise ValueError(f"{model_cls.__name__} has {len(pk_cols)} PK columns; expected 1")
    return pk_cols[0].key


def migrate_table(
    sqlite_session: Session,
    pg_session: Session,
    model_cls,
    batch_size: int,
) -> TableReport:
    """Migrate a single table from SQLite to PostgreSQL.

    Idempotent: rows with existing PKs are skipped.
    """
    table_name = model_cls.__tablename__
    report = TableReport(table_name=table_name)
    start = time.monotonic()

    try:
        pk_col = _get_primary_key(model_cls)
    except ValueError as e:
        report.error = str(e)
        report.duration_sec = time.monotonic() - start
        return report

    # Check if table exists in source database
    sqlite_engine = sqlite_session.get_bind()
    inspector = inspect(sqlite_engine)
    if table_name not in inspector.get_table_names():
        logger.info("  %s: table does not exist in source, skipping", table_name)
        report.duration_sec = time.monotonic() - start
        return report

    try:
        report.sqlite_rows = sqlite_session.execute(
            select(model_cls)
        ).scalars().all().__len__()

        report.postgres_rows_before = pg_session.execute(
            select(model_cls)
        ).scalars().all().__len__()

        existing_pks = {
            getattr(row, pk_col)
            for row in pg_session.execute(select(model_cls)).scalars().all()
        }

        sqlite_rows = sqlite_session.execute(select(model_cls)).scalars().all()
        rows_to_insert = [
            row for row in sqlite_rows if getattr(row, pk_col) not in existing_pks
        ]
        report.rows_skipped = len(sqlite_rows) - len(rows_to_insert)

        if not rows_to_insert:
            logger.info("  %s: nothing to migrate (%d rows exist)", table_name, report.rows_skipped)
            report.postgres_rows_after = report.postgres_rows_before
            report.duration_sec = time.monotonic() - start
            return report

        total_batches = (len(rows_to_insert) + batch_size - 1) // batch_size
        for i in range(0, len(rows_to_insert), batch_size):
            batch = rows_to_insert[i:i + batch_size]
            batch_num = i // batch_size + 1
            logger.info("  %s: migrating batch %d/%d (%d rows)",
                        table_name, batch_num, total_batches, len(batch))

            row_dicts = []
            for row in batch:
                d = {c.key: getattr(row, c.key) for c in inspect(model_cls).mapper.column_attrs}
                row_dicts.append(d)

            pg_session.execute(model_cls.__table__.insert(), row_dicts)
            report.rows_migrated += len(batch)

        pg_session.commit()
        report.postgres_rows_after = pg_session.execute(
            select(model_cls)
        ).scalars().all().__len__()

    except Exception as e:
        pg_session.rollback()
        report.error = str(e)
        logger.exception("  %s: migration failed", table_name)

    report.duration_sec = time.monotonic() - start
    return report


def validate_migration(
    sqlite_session: Session,
    pg_session: Session,
    report: MigrationReport,
) -> bool:
    """Compare row counts between SQLite and PostgreSQL.

    Returns True if all tables match.
    """
    models = _collect_all_models()
    mismatches = []

    sqlite_engine = sqlite_session.get_bind()
    sqlite_inspector = inspect(sqlite_engine)
    sqlite_tables = set(sqlite_inspector.get_table_names())

    for table_name, model_cls in models.items():
        # Skip tables that don't exist in source
        if table_name not in sqlite_tables:
            continue

        sqlite_count = sqlite_session.execute(select(model_cls)).scalars().all().__len__()
        pg_count = pg_session.execute(select(model_cls)).scalars().all().__len__()

        if sqlite_count != pg_count:
            mismatches.append((table_name, sqlite_count, pg_count))

    if mismatches:
        logger.error("Validation failed: row count mismatches")
        for table, sqlite_count, pg_count in mismatches:
            logger.error("  %s: SQLite=%d, PostgreSQL=%d", table, sqlite_count, pg_count)
        return False

    logger.info("Validation passed: all %d tables match", len(sqlite_tables))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate SQLite to PostgreSQL")
    parser.add_argument("--sqlite-path", required=True, help="Path to SQLite database file")
    parser.add_argument("--postgres-url", required=True, help="PostgreSQL connection URL")
    parser.add_argument("--batch-size", type=int, default=1000, help="Rows per batch (default: 1000)")
    parser.add_argument("--skip-validation", action="store_true", help="Skip post-migration row count checks")
    args = parser.parse_args()

    sqlite_url = f"sqlite:///{args.sqlite_path}"
    sqlite_engine = create_engine(sqlite_url, future=True)
    pg_engine = create_engine(args.postgres_url, future=True)

    models = _collect_all_models()
    logger.info("Found %d ORM models to migrate", len(models))

    overall_start = time.monotonic()
    report = MigrationReport()

    with Session(sqlite_engine) as sqlite_session, Session(pg_engine) as pg_session:
        for table_name, model_cls in models.items():
            logger.info("Migrating %s...", table_name)
            table_report = migrate_table(sqlite_session, pg_session, model_cls, args.batch_size)
            report.tables.append(table_report)

    report.total_duration_sec = time.monotonic() - overall_start
    report.print_report()

    if not args.skip_validation:
        logger.info("Running post-migration validation...")
        with Session(sqlite_engine) as sqlite_session, Session(pg_engine) as pg_session:
            if not validate_migration(sqlite_session, pg_session, report):
                return 1

    errors = sum(1 for t in report.tables if t.error)
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
