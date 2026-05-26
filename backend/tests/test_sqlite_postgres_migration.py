"""Integration tests for SQLite→PostgreSQL migration script."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from deerflow.persistence.base import Base
import deerflow.persistence.models  # noqa: F401 — import all ORM models
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.tenant.model import TenantRow


@pytest.fixture
def db_pair():
    """Create source and target SQLite databases.

    Uses in-memory databases to avoid Windows file locking issues.
    Returns (source_engine, target_engine) tuple.
    """
    source_engine = create_engine("sqlite:///:memory:", future=True)
    target_engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(source_engine)
    Base.metadata.create_all(target_engine)

    with Session(source_engine) as session:
        session.add(TenantRow(tenant_id="t1", name="Test Tenant"))
        session.add(TenantRow(tenant_id="t2", name="Second Tenant"))
        session.add(UserRow(id="u1", tenant_id="t1", email="alice@test.com"))
        session.add(UserRow(id="u2", tenant_id="t1", email="bob@test.com"))
        session.commit()

    yield source_engine, target_engine

    source_engine.dispose()
    target_engine.dispose()


@pytest.fixture
def empty_source():
    """Create an empty source database."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def empty_target():
    """Create an empty target database."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_migrate_all_tables(db_pair):
    """Migration copies all data from source to target."""
    from scripts.migrate_sqlite_to_postgres import _collect_all_models, migrate_table

    source_engine, target_engine = db_pair
    models = _collect_all_models()

    with Session(source_engine) as src_session, Session(target_engine) as tgt_session:
        for table_name, model_cls in models.items():
            report = migrate_table(src_session, tgt_session, model_cls, batch_size=100)
            if table_name in ("users", "tenants"):
                assert report.error == "", f"{table_name}: {report.error}"
                assert report.rows_migrated > 0

    with Session(target_engine) as session:
        tenants = session.execute(select(TenantRow)).scalars().all()
        assert len(tenants) == 2
        users = session.execute(select(UserRow)).scalars().all()
        assert len(users) == 2


def test_idempotent_migration(db_pair):
    """Re-running migration skips existing rows."""
    from scripts.migrate_sqlite_to_postgres import migrate_table

    source_engine, target_engine = db_pair

    with Session(source_engine) as src_session, Session(target_engine) as tgt_session:
        report1 = migrate_table(src_session, tgt_session, TenantRow, batch_size=100)
        assert report1.rows_migrated == 2
        assert report1.rows_skipped == 0

        report2 = migrate_table(src_session, tgt_session, TenantRow, batch_size=100)
        assert report2.rows_migrated == 0
        assert report2.rows_skipped == 2


def test_empty_source_database(empty_source, empty_target):
    """Migration handles empty source database gracefully."""
    from scripts.migrate_sqlite_to_postgres import _collect_all_models, migrate_table

    models = _collect_all_models()

    with Session(empty_source) as src_session, Session(empty_target) as tgt_session:
        for model_cls in models.values():
            report = migrate_table(src_session, tgt_session, model_cls, batch_size=100)
            assert report.error == ""
            assert report.rows_migrated == 0


def test_validation_passes_after_migration(db_pair):
    """Row count validation passes after successful migration."""
    from scripts.migrate_sqlite_to_postgres import _collect_all_models, migrate_table, validate_migration

    source_engine, target_engine = db_pair
    models = _collect_all_models()

    with Session(source_engine) as src_session, Session(target_engine) as tgt_session:
        for model_cls in models.values():
            migrate_table(src_session, tgt_session, model_cls, batch_size=100)

    with Session(source_engine) as src_session, Session(target_engine) as tgt_session:
        assert validate_migration(src_session, tgt_session, None)


def test_batch_processing(db_pair):
    """Large datasets are processed in batches."""
    from scripts.migrate_sqlite_to_postgres import migrate_table

    source_engine, target_engine = db_pair

    with Session(source_engine) as src_session:
        for i in range(150):
            src_session.add(UserRow(
                id=f"user_{i}",
                tenant_id="t1",
                email=f"user{i}@test.com",
            ))
        src_session.commit()

    with Session(source_engine) as src_session, Session(target_engine) as tgt_session:
        report = migrate_table(src_session, tgt_session, UserRow, batch_size=50)
        assert report.rows_migrated == 152
        assert report.error == ""
