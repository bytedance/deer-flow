"""Concurrency safety tests for ``bootstrap_schema``.

The contract: N concurrent callers against the same DB always converge to
``alembic_version == head`` without exceptions and without duplicate schema
mutations.

We model concurrency at the *async-task* level here (multiple coroutines
inside one process). SQLite is single-node by deployment, so within-process
serialisation -- which is what the per-engine ``_SQLITE_LOCKS`` entry
provides -- is the realistic boundary. Cross-process serialisation falls
through to SQLite's own write lock + ``PRAGMA busy_timeout`` plus the
idempotent revision helpers.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

import deerflow.persistence.models  # noqa: F401
from deerflow.persistence import bootstrap as bootstrap_mod
from deerflow.persistence.bootstrap import bootstrap_schema

pytestmark = pytest.mark.asyncio


HEAD = "0006_agents"


def _url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'concurrent.db').as_posix()}"


async def _alembic_version(engine) -> str | None:
    async with engine.connect() as conn:
        row = await conn.execute(sa.text("SELECT version_num FROM alembic_version"))
        return row.scalar()


async def _runs_columns(engine) -> set[str]:
    async with engine.connect() as conn:
        return await conn.run_sync(lambda c: {col["name"] for col in sa.inspect(c).get_columns("runs")})


async def test_two_concurrent_bootstrap_callers_converge(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path))
    try:
        await asyncio.gather(
            bootstrap_schema(engine, backend="sqlite"),
            bootstrap_schema(engine, backend="sqlite"),
        )
        assert await _alembic_version(engine) == HEAD
        assert "token_usage_by_model" in await _runs_columns(engine)
    finally:
        await engine.dispose()


async def test_five_concurrent_bootstrap_callers_converge(tmp_path: Path) -> None:
    engine = create_async_engine(_url(tmp_path))
    try:
        await asyncio.gather(*(bootstrap_schema(engine, backend="sqlite") for _ in range(5)))
        assert await _alembic_version(engine) == HEAD
    finally:
        await engine.dispose()


async def test_cancelled_caller_does_not_block_others(tmp_path: Path) -> None:
    """Cancelling one task mid-bootstrap must not strand the lock or the DB.

    After the cancel, a subsequent ``bootstrap_schema`` call must still reach
    head.
    """
    engine = create_async_engine(_url(tmp_path))
    try:
        task = asyncio.create_task(bootstrap_schema(engine, backend="sqlite"))
        # Give the event loop a turn so the task can start; then cancel.
        await asyncio.sleep(0)
        task.cancel()
        # Cancelled task may have raced past the lock; swallow either outcome.
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

        # Lock must be free for the next caller.
        await bootstrap_schema(engine, backend="sqlite")
        assert await _alembic_version(engine) == HEAD
    finally:
        await engine.dispose()


async def test_late_caller_after_head_is_noop(monkeypatch, tmp_path: Path) -> None:
    """When the first caller leaves the DB at head, the second observes
    'versioned' and skips create_all / stamp -- it only runs upgrade head,
    which is alembic-no-op.

    We use a monkeypatched ``_upgrade`` counter to assert the second caller's
    upgrade ran but did no real work (no new revision applied).
    """
    engine = create_async_engine(_url(tmp_path))
    try:
        # First caller: empty branch.
        await bootstrap_schema(engine, backend="sqlite")
        first_version = await _alembic_version(engine)
        assert first_version == HEAD

        upgrade_calls: list[str] = []
        original_upgrade = bootstrap_mod._upgrade

        def counting_upgrade(cfg, rev: str) -> None:
            upgrade_calls.append(rev)
            original_upgrade(cfg, rev)

        monkeypatch.setattr(bootstrap_mod, "_upgrade", counting_upgrade)

        # Second caller: versioned branch -> calls _upgrade('head').
        await bootstrap_schema(engine, backend="sqlite")
        assert upgrade_calls == ["head"]
        assert await _alembic_version(engine) == HEAD
    finally:
        await engine.dispose()


async def test_slow_upgrade_does_not_corrupt_concurrent_state(monkeypatch, tmp_path: Path) -> None:
    """Inject a delay into the upgrade path; concurrent callers must still
    converge to head with no exceptions."""
    engine = create_async_engine(_url(tmp_path))
    try:
        original_upgrade = bootstrap_mod._upgrade

        def slow_upgrade(cfg, rev: str) -> None:
            import time  # noqa: PLC0415

            time.sleep(0.2)
            original_upgrade(cfg, rev)

        monkeypatch.setattr(bootstrap_mod, "_upgrade", slow_upgrade)

        await asyncio.gather(
            bootstrap_schema(engine, backend="sqlite"),
            bootstrap_schema(engine, backend="sqlite"),
            bootstrap_schema(engine, backend="sqlite"),
        )
        assert await _alembic_version(engine) == HEAD
    finally:
        await engine.dispose()
