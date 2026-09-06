"""Regression: ``bootstrap_schema`` offloads ``alembic.command.stamp`` /
``alembic.command.upgrade`` via ``asyncio.to_thread``.

The alembic commands are synchronous: they open their own engine and execute
DDL. Calling them directly on the FastAPI lifespan event loop would block --
exactly the failure mode of the issue chain that motivated the hybrid
bootstrap (sync IO on the loop = silent stalls / timeouts).

Anchor strategy
---------------

We can't run a real ``init_engine(backend="sqlite", ...)`` under the strict
Blockbuster gate without tripping on ``create_async_engine``'s own
``os.path.abspath`` (which is a pre-existing concern, not the bootstrap's).
The companion ``test_persistence_engine_sqlite.py`` covers the ``init_engine``
makedirs offload by mocking ``create_async_engine`` away entirely. That same
mocking approach would defeat the point here, because the alembic stamp /
upgrade calls in ``bootstrap_schema`` need a *real* on-disk SQLite DB to
exercise.

So this test installs a spy on ``asyncio.to_thread`` and confirms that the
two alembic entry points -- ``_stamp`` and ``_upgrade`` from
``bootstrap_schema`` -- are dispatched through it, not invoked inline. If a
future refactor inlines either call, the spy records zero invocations for
that function and the assertion fails.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

import deerflow.persistence.models  # noqa: F401
from deerflow.persistence import bootstrap as bootstrap_mod

pytestmark = pytest.mark.asyncio


@pytest.mark.allow_blocking_io
async def test_bootstrap_offloads_alembic_stamp_and_upgrade(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Stamp + upgrade must go through ``asyncio.to_thread``.

    Marked ``allow_blocking_io`` so the strict Blockbuster gate does not flag
    incidental blocking IO in test-fixture setup (engine creation paths,
    SQLite path resolution). The point of this test is the
    ``asyncio.to_thread`` wrapping invariant, which the spy below checks
    deterministically.
    """
    seen: list[str] = []

    original_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        seen.append(getattr(func, "__name__", repr(func)))
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(bootstrap_mod.asyncio, "to_thread", spy_to_thread)

    # Use a real SQLite DB so alembic actually runs stamp + upgrade.
    db_path = tmp_path / "spy.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    try:
        # Empty branch -> create_all + stamp head. ``_stamp`` must be offloaded.
        await bootstrap_mod.bootstrap_schema(engine, backend="sqlite")
        assert "_stamp" in seen, f"_stamp not offloaded; saw: {seen}"

        # Re-run -> versioned branch -> upgrade head (no-op at head). ``_upgrade`` must be offloaded.
        seen.clear()
        await bootstrap_mod.bootstrap_schema(engine, backend="sqlite")
        assert "_upgrade" in seen, f"_upgrade not offloaded; saw: {seen}"
    finally:
        await engine.dispose()
