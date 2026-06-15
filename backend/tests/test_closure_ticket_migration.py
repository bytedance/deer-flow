"""Migration lifecycle tests for the closure_tickets schema (alembic 002).

Project convention: ``Base.metadata.create_all`` provisions the baseline schema
on engine init; alembic migrations carry only incremental changes. So these
tests:

1. Create all baseline tables via ``Base.metadata.create_all``.
2. Stamp alembic at 001 (the prior head).
3. Apply 002 (our new migration) and assert closure tables + SLA seed land.
4. Downgrade back to 001 and assert closure tables disappear.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from deerflow.persistence.base import Base
from deerflow.persistence.models import ClosureSlaConfigRow, ClosureTicketEventRow, ClosureTicketRow  # noqa: F401 — register tables on Base.metadata

_HARNESS_ROOT = Path(__file__).resolve().parents[1] / "packages" / "harness" / "deerflow"
_ALEMBIC_DIR = _HARNESS_ROOT / "persistence" / "migrations"


def _make_alembic_config(db_url: str) -> Config:
    cfg = Config(str(_ALEMBIC_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _create_baseline(sync_url: str) -> None:
    """Create the full ORM-defined baseline schema, then drop our closure tables.

    This mirrors the production startup path (``Base.metadata.create_all`` happens
    before alembic upgrade), but removes the closure tables we want migration 002
    to create so the migration has work to do.
    """
    engine = create_engine(sync_url)
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS closure_ticket_events"))
            conn.execute(text("DROP TABLE IF EXISTS closure_tickets"))
            conn.execute(text("DROP TABLE IF EXISTS closure_sla_configs"))
    finally:
        engine.dispose()


def _table_names(sync_url: str) -> set[str]:
    engine = create_engine(sync_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.fixture()
def sqlite_urls(tmp_path):
    db_path = tmp_path / "closure_migration.db"
    sync_url = f"sqlite:///{db_path}"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    return sync_url, async_url


def test_upgrade_creates_closure_tables(sqlite_urls):
    sync_url, async_url = sqlite_urls
    _create_baseline(sync_url)

    cfg = _make_alembic_config(async_url)
    command.stamp(cfg, "001")
    command.upgrade(cfg, "002")

    tables = _table_names(sync_url)
    assert "closure_tickets" in tables
    assert "closure_ticket_events" in tables
    assert "closure_sla_configs" in tables


def test_upgrade_seeds_default_sla(sqlite_urls):
    sync_url, async_url = sqlite_urls
    _create_baseline(sync_url)

    cfg = _make_alembic_config(async_url)
    command.stamp(cfg, "001")
    command.upgrade(cfg, "002")

    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT priority, sla_hours FROM closure_sla_configs "
                    "WHERE tenant_id = '__default__' ORDER BY priority"
                )
            ).all()
    finally:
        engine.dispose()

    seeded = {priority: hours for priority, hours in rows}
    assert seeded == {
        "important": 72,
        "normal": 7 * 24,
        "observe": 30 * 24,
        "urgent": 4,
    }


def test_downgrade_drops_closure_tables(sqlite_urls):
    sync_url, async_url = sqlite_urls
    _create_baseline(sync_url)

    cfg = _make_alembic_config(async_url)
    command.stamp(cfg, "001")
    command.upgrade(cfg, "002")
    assert "closure_tickets" in _table_names(sync_url)

    command.downgrade(cfg, "001")

    tables = _table_names(sync_url)
    assert "closure_tickets" not in tables
    assert "closure_ticket_events" not in tables
    assert "closure_sla_configs" not in tables


def test_unique_constraint_enforced(sqlite_urls):
    """The (tenant_id, source_type, source_run_id, device_id) idempotency key must hold."""
    sync_url, async_url = sqlite_urls
    _create_baseline(sync_url)

    cfg = _make_alembic_config(async_url)
    command.stamp(cfg, "001")
    command.upgrade(cfg, "002")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO closure_tickets "
                    "(id, tenant_id, title, status, priority, created_by, source_type, "
                    "source_run_id, device_id, extra_metadata, is_overdue, created_at, updated_at) "
                    "VALUES ('t1', 'tenant-a', 'first', 'pending', 'urgent', 'u1', 'diagnosis', "
                    "'run-1', 'dev-1', '{}', 0, '2026-05-19 00:00:00', '2026-05-19 00:00:00')"
                )
            )
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO closure_tickets "
                        "(id, tenant_id, title, status, priority, created_by, source_type, "
                        "source_run_id, device_id, extra_metadata, is_overdue, created_at, updated_at) "
                        "VALUES ('t2', 'tenant-a', 'dup', 'pending', 'urgent', 'u1', 'diagnosis', "
                        "'run-1', 'dev-1', '{}', 0, '2026-05-19 00:00:00', '2026-05-19 00:00:00')"
                    )
                )
    finally:
        engine.dispose()
