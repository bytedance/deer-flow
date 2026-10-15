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
2. It runs **before** the lock is acquired -- otherwise a slow lock acquire
   on a heavily-contended cluster would itself be vulnerable.
3. The ``pg_advisory_unlock`` still fires on the way out (the new SQL must
   not break the release path).

It also pins that waiting for a peer's migration is not cut short by the app
engine's asyncpg ``command_timeout``: acquisition polls the non-blocking
``pg_try_advisory_lock`` so no single statement outlives that deadline.

We mock the engine instead of standing up a real Postgres because the only
behaviour worth pinning here is the SQL execution order; the timeout's
runtime effect is Postgres's contract, not ours. The one exception drives
Gateway startup (``init_engine_from_config``) against a live server and is opt-in via
``DEERFLOW_TEST_POSTGRES_URL``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import DropSchema

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence import bootstrap as bootstrap_mod
from deerflow.persistence.engine import close_engine, get_engine, init_engine_from_config

POSTGRES_URL = os.getenv("DEERFLOW_TEST_POSTGRES_URL")


class _FakeResult:
    def __init__(self, value: object = None) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value


class _FakeAsyncConn:
    """Async-context-manager stand-in for SQLAlchemy's ``AsyncConnection``.

    Records every ``execute(stmt, params)`` so the test can assert SQL order.
    The advisory lock is always free, so ``pg_try_advisory_lock`` succeeds.
    """

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict | None]] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append((sql, params))
        return _FakeResult(True if "pg_try_advisory_lock" in sql else None)

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

    # 2. SET LOCAL precedes the lock acquire.
    lock_idx = next((i for i, s in enumerate(sqls) if "pg_try_advisory_lock" in s), None)
    assert lock_idx is not None, f"pg_try_advisory_lock never executed; saw: {sqls}"
    assert set_local_idx < lock_idx, f"SET LOCAL must run before pg_try_advisory_lock; got order {sqls}"

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


class _BlockingUnlockConn(_FakeAsyncConn):
    def __init__(self) -> None:
        super().__init__()
        self.unlock_started = asyncio.Event()
        self.allow_unlock = asyncio.Event()
        self.unlock_finished = asyncio.Event()

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append((sql, params))
        if "pg_advisory_unlock" in sql:
            self.unlock_started.set()
            await self.allow_unlock.wait()
            self.unlock_finished.set()
        return _FakeResult(True if "pg_try_advisory_lock" in sql else None)


class _BlockingUnlockEngine:
    def __init__(self) -> None:
        self.conn = _BlockingUnlockConn()

    def connect(self) -> _BlockingUnlockConn:
        return self.conn


@pytest.mark.asyncio
async def test_postgres_lock_drains_unlock_across_repeated_cancellation() -> None:
    engine = _BlockingUnlockEngine()
    entered = asyncio.Event()
    hold_body = asyncio.Event()

    async def owner() -> None:
        async with bootstrap_mod._postgres_lock(engine):  # type: ignore[arg-type]
            entered.set()
            await hold_body.wait()

    task = asyncio.create_task(owner())
    await asyncio.wait_for(entered.wait(), timeout=1)

    task.cancel()
    await asyncio.wait_for(engine.conn.unlock_started.wait(), timeout=1)

    try:
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "bootstrap returned before advisory unlock finished"
        assert not engine.conn.unlock_finished.is_set()

        engine.conn.allow_unlock.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert engine.conn.unlock_finished.is_set()
    finally:
        engine.conn.allow_unlock.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class _ContendedLockConn(_FakeAsyncConn):
    """A peer instance holds the bootstrap lock until ``peer_done`` is set.

    Every statement runs under ``command_timeout``, the way asyncpg applies the
    connection default to statements that pass no explicit timeout, so a
    blocking ``pg_advisory_lock`` that outlives it raises ``TimeoutError``.
    """

    def __init__(self, command_timeout: float) -> None:
        super().__init__()
        self.command_timeout = command_timeout
        self.peer_done = asyncio.Event()

    async def execute(self, stmt, params=None):
        return await asyncio.wait_for(self._execute(str(stmt), params), timeout=self.command_timeout)

    async def _execute(self, sql: str, params: dict | None) -> _FakeResult:
        self.executed.append((sql, params))
        if "pg_try_advisory_lock" in sql:
            return _FakeResult(self.peer_done.is_set())
        if "pg_advisory_lock" in sql:
            await self.peer_done.wait()
        return _FakeResult()


class _ContendedLockEngine:
    def __init__(self, command_timeout: float) -> None:
        self.conn = _ContendedLockConn(command_timeout)

    def connect(self) -> _ContendedLockConn:
        return self.conn


@pytest.mark.asyncio
async def test_postgres_lock_outwaits_command_timeout_while_a_peer_migrates(monkeypatch, caplog) -> None:
    monkeypatch.setattr(bootstrap_mod, "_PG_LOCK_POLL_INTERVAL_SECONDS", 0.01)
    engine = _ContendedLockEngine(command_timeout=0.05)
    acquired = asyncio.Event()

    async def bootstrap() -> None:
        async with bootstrap_mod._postgres_lock(engine):  # type: ignore[arg-type]
            acquired.set()

    with caplog.at_level(logging.INFO, logger=bootstrap_mod.__name__):
        task = asyncio.create_task(bootstrap())
        try:
            # The peer's migration outlasts command_timeout several times over.
            await asyncio.sleep(0.25)
            assert not task.done(), f"bootstrap stopped waiting while the peer held the lock: {task.exception()!r}"

            engine.conn.peer_done.set()
            await asyncio.wait_for(task, timeout=1)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    assert acquired.is_set()
    sqls = [stmt for stmt, _ in engine.conn.executed]
    assert sum("pg_try_advisory_lock" in s for s in sqls) > 2, f"expected repeated polls; saw: {sqls}"
    assert any("pg_advisory_unlock" in s for s in sqls), f"unlock missing; saw: {sqls}"
    waiting_logs = [r for r in caplog.records if "held by another instance" in r.getMessage()]
    assert len(waiting_logs) == 1, "the wait should be logged once, not on every poll"


@pytest.mark.skipif(not POSTGRES_URL, reason="set DEERFLOW_TEST_POSTGRES_URL to run the live PostgreSQL bootstrap-lock test")
@pytest.mark.asyncio
async def test_init_engine_outwaits_command_timeout_on_live_postgres(monkeypatch) -> None:
    """Gateway startup waits out a peer's migration that outlasts ``command_timeout``."""
    monkeypatch.setattr(bootstrap_mod, "_PG_LOCK_POLL_INTERVAL_SECONDS", 0.1)
    schema = f"deerflow_test_{uuid.uuid4().hex[:12]}"
    db_config = DatabaseConfig(backend="postgres", postgres_url=POSTGRES_URL or "", postgres_schema=schema, command_timeout=1)
    peer = create_async_engine(db_config.app_sqlalchemy_url)
    try:
        async with peer.connect() as peer_conn:
            await peer_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": bootstrap_mod._PG_LOCK_KEY})
            task = asyncio.create_task(init_engine_from_config(db_config))
            try:
                # The peer's migration outlasts command_timeout more than twice over.
                await asyncio.sleep(2.5)
                assert not task.done(), f"startup stopped waiting while the peer held the lock: {task.exception()!r}"
            finally:
                await peer_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": bootstrap_mod._PG_LOCK_KEY})
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=60)
            await task

        engine = get_engine()
        assert engine is not None
        async with engine.connect() as conn:
            revision = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
        assert revision
    finally:
        await close_engine()
        async with peer.begin() as conn:
            await conn.execute(DropSchema(schema, cascade=True, if_exists=True))
        await peer.dispose()
