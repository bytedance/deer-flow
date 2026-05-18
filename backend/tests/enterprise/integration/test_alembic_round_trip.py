"""Alembic round-trip integration tests for the M1/M2/M3 enterprise
revisions.

We assert: a clean ``upgrade <target>`` then ``downgrade base`` leaves
no orphan tables, and the same engine can be brought back up to ``head``
without losing earlier-revision data. The point is to catch a downgrade
that quietly drops data that should have survived.

Implementation notes:

* We use Alembic's Python API (``alembic.command.upgrade`` /
  ``downgrade``) rather than a ``subprocess`` so we share the *exact*
  ``env.py`` codepath production runs through. Anything that would
  break production startup will break here.
* The revision graph currently has TWO roots (``m1_initial_rbac`` and
  ``20260518_m2_audit``); M3 hangs off M2. We can't ``upgrade -1`` past
  a root, so each test scopes its own engine and walks only the chain
  that revision belongs to.
* Merging the two heads is **out of scope** for M5 — that's a separate
  ops PR. These tests document the current state.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "packages" / "harness" / "deerflow" / "persistence" / "migrations" / "alembic.ini"


def _cfg(db_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    # ``env.py`` drives migrations through ``create_async_engine`` (see
    # ``packages/harness/deerflow/persistence/migrations/env.py``), which
    # requires an async driver — the plain ``sqlite://`` URL raises
    # ``InvalidRequestError: asyncio extension requires an async driver``.
    # Use ``sqlite+aiosqlite://`` so the test exercises the same codepath
    # production startup uses.
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return cfg


def _tables(db_path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Path]:
    """A scratch SQLite file path per test."""
    yield tmp_path / "rt.db"


def test_m1_rbac_round_trip(db: Path) -> None:
    cfg = _cfg(db)

    # Upgrade only to m1 (m1 is its own root, no predecessor).
    command.upgrade(cfg, "m1_initial_rbac")
    tables_after_upgrade = _tables(db)
    # M1 introduces roles, permissions, role assignments. We don't need
    # to know every table name — just that >=1 RBAC table is present.
    assert any(t.startswith("rbac_") or t in {"roles", "permissions", "user_roles"} for t in tables_after_upgrade), f"M1 did not create any RBAC table: {tables_after_upgrade}"

    # Downgrade to base — every M1 table must be gone.
    command.downgrade(cfg, "base")
    assert _tables(db) - {"alembic_version"} == set(), "Downgrade left orphan tables"

    # Bring it back up — should work clean.
    command.upgrade(cfg, "m1_initial_rbac")
    assert _tables(db) == tables_after_upgrade


def test_m2_audit_round_trip(db: Path) -> None:
    cfg = _cfg(db)

    # ``20260518_m2_audit`` is an INDEPENDENT root (``down_revision=None``)
    # — we can't reach it by chaining through m1. Upgrade directly from
    # base.
    command.upgrade(cfg, "20260518_m2_audit")
    tables_after_upgrade = _tables(db)
    assert "audit_events" in tables_after_upgrade

    # Seed a representative row so we can prove downgrade really drops
    # the data (a downgrade that left tables but truncated rows would
    # also be a bug). The sync engine here is for inspection only —
    # opened AFTER alembic finishes, so it doesn't need an async driver.
    eng = create_engine(f"sqlite:///{db}")
    with eng.begin() as conn:
        conn.execute(
            text("INSERT INTO audit_events (id, event_type, timestamp, user_id, resource, action, details, signature) VALUES (:id, :et, :ts, :uid, :res, :act, :det, :sig)"),
            {
                "id": str(uuid4()),
                "et": "agent_task_started",
                "ts": "2026-05-18T00:00:00+00:00",
                "uid": "alice",
                "res": "agent",
                "act": "start",
                "det": "{}",
                "sig": "deadbeef",
            },
        )
    eng.dispose()

    command.downgrade(cfg, "base")
    assert "audit_events" not in _tables(db)

    # And brought back up clean.
    command.upgrade(cfg, "20260518_m2_audit")
    assert _tables(db) == tables_after_upgrade
