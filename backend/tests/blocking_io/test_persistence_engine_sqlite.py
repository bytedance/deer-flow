"""Regression test: persistence-engine sqlite dir setup must run off the loop.

Anchors the production offload in `persistence/engine.py:init_engine`, where the
SQLite data directory is created with `os.makedirs`. `init_engine` runs on the
FastAPI lifespan event loop, so a sync `os.makedirs` (a stat + mkdir syscall)
there blocks startup — the same class of bug fixed for the checkpointer's
`ensure_sqlite_parent_dir` in #1912 (see `test_sqlite_lifespan.py`).

This invokes the production `init_engine(backend="sqlite", ...)` under the strict
Blockbuster context with a `sqlite_dir` that does not yet exist, so `os.makedirs`
actually runs. The async engine/session machinery is mocked out so the only host
filesystem operation under test is the directory creation; if it regresses to run
directly on the event loop, Blockbuster raises `BlockingError` and this fails.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-import so `init_engine`'s lazy ``import deerflow.persistence.models`` is a
# cached no-op rather than a file read under the strict gate.
import deerflow.persistence.models  # noqa: E402,F401
from deerflow.persistence import engine as engine_mod  # noqa: E402

pytestmark = pytest.mark.asyncio


def _noop_listens_for(*_args, **_kwargs):
    """Decorator factory that registers nothing (mock engine has no real events)."""

    def _decorator(fn):
        return fn

    return _decorator


async def test_init_engine_sqlite_dir_setup_does_not_block_event_loop(tmp_path: Path) -> None:
    data_dir = tmp_path / "newsubdir"  # does not exist yet -> os.makedirs runs
    db_file = data_dir / "app.db"

    mock_conn = AsyncMock()
    begin_ctx = AsyncMock()
    begin_ctx.__aenter__.return_value = mock_conn
    begin_ctx.__aexit__.return_value = False
    mock_engine = MagicMock()
    mock_engine.begin.return_value = begin_ctx
    mock_engine.dispose = AsyncMock()

    with (
        patch.object(engine_mod, "create_async_engine", return_value=mock_engine),
        patch.object(engine_mod, "async_sessionmaker", return_value=MagicMock()),
        patch("sqlalchemy.event.listens_for", _noop_listens_for),
    ):
        await engine_mod.init_engine(
            backend="sqlite",
            url=f"sqlite+aiosqlite:///{db_file}",
            sqlite_dir=str(data_dir),
        )
        assert data_dir.exists()

    await engine_mod.close_engine()
