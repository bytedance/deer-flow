"""Regression test for the Postgres bootstrap advisory-lock protection.

Managed Postgres (RDS, Cloud SQL, Supabase) defaults
``idle_in_transaction_session_timeout`` to 1-10 minutes. If the lock-holding
connection sits idle while ``asyncio.to_thread(_upgrade, ...)`` runs alembic
on a different pooled connection longer than that, the host kills the idle
session and the advisory lock is **silently released** -- defeating the
cross-process mutex. ``_postgres_lock`` issues
``SET LOCAL idle_in_transaction_session_timeout = 0`` immediately on the
lock-holding connection to neutralise that kill for the lifetime of the
transaction.

This test pins:

1. The ``SET LOCAL`` is emitted at all (no silent regression).
2. It runs **before** ``pg_advisory_lock`` -- otherwise a slow lock acquire
   on a heavily-contended cluster would itself be vulnerable.
3. The ``pg_advisory_unlock`` still fires on the way out (the new SQL must
   not break the release path).

We mock the engine instead of standing up a real Postgres because the only
behaviour worth pinning here is the SQL execution order; the timeout's
runtime effect is Postgres's contract, not ours.
"""

from __future__ import annotations

import pytest

from deerflow.persistence import bootstrap as bootstrap_mod


class _FakeAsyncConn:
    """Async-context-manager stand-in for SQLAlchemy's ``AsyncConnection``.

    Records every ``execute(stmt, params)`` so the test can assert SQL order.
    """

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict | None]] = []

    async def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))
        return None

    async def __aenter__(self) -> _FakeAsyncConn:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        return None


class _FakeAsyncEngine:
    def __init__(self) -> None:
        self.conn = _FakeAsyncConn()

    def connect(self) -> _FakeAsyncConn:
        return self.conn


@pytest.mark.asyncio
async def test_postgres_lock_disables_idle_in_transaction_kill_before_locking() -> None:
    engine = _FakeAsyncEngine()

    async with bootstrap_mod._postgres_lock(engine):  # type: ignore[arg-type]
        pass

    sqls = [stmt for stmt, _ in engine.conn.executed]

    # 1. SET LOCAL fires.
    set_local_idx = next(
        (i for i, s in enumerate(sqls) if "set local idle_in_transaction_session_timeout" in s.lower()),
        None,
    )
    assert set_local_idx is not None, f"SET LOCAL never executed; saw: {sqls}"
    assert "0" in sqls[set_local_idx], f"SET LOCAL did not target value 0: {sqls[set_local_idx]!r}"

    # 2. SET LOCAL precedes pg_advisory_lock.
    lock_idx = next((i for i, s in enumerate(sqls) if "pg_advisory_lock" in s), None)
    assert lock_idx is not None, f"pg_advisory_lock never executed; saw: {sqls}"
    assert set_local_idx < lock_idx, f"SET LOCAL must run before pg_advisory_lock; got order {sqls}"

    # 3. pg_advisory_unlock still fires on exit.
    assert any("pg_advisory_unlock" in s for s in sqls), f"pg_advisory_unlock missing; saw: {sqls}"


@pytest.mark.asyncio
async def test_postgres_lock_releases_even_if_body_raises() -> None:
    """Defence-in-depth: the SET LOCAL addition must not regress the
    existing finally-block contract that releases the lock on body errors."""
    engine = _FakeAsyncEngine()

    with pytest.raises(RuntimeError, match="boom"):
        async with bootstrap_mod._postgres_lock(engine):  # type: ignore[arg-type]
            raise RuntimeError("boom")

    sqls = [stmt for stmt, _ in engine.conn.executed]
    assert any("pg_advisory_unlock" in s for s in sqls), f"unlock missing after body error; saw: {sqls}"
