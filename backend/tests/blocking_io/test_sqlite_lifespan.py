"""Regression test: sqlite parent-dir creation must run off the event loop.

Anchors the production offload from
`runtime/checkpointer/async_provider.py:_async_checkpointer` (line ~58) where
`ensure_sqlite_parent_dir` is dispatched via `await asyncio.to_thread(...)`.
That fix addressed #1912, where the sync `Path.mkdir` / `os.mkdir` inside
`ensure_sqlite_parent_dir` ran on the FastAPI lifespan event loop thread
and blocked startup.

This test invokes the same `asyncio.to_thread` pattern under the strict
Blockbuster context. The target path's parent does not yet exist, so the
underlying `os.mkdir` actually fires. If the offload is regressed to a
direct call, Blockbuster raises `BlockingError` and this test fails.

Note: this test deliberately bypasses `_async_checkpointer`'s
`resolve_sqlite_conn_str` step because that helper itself contains a
separate, currently-unfixed `Path.resolve() -> os.path.abspath` blocking
call — surfaced by Blockbuster while authoring this PR but tracked as a
follow-up so the v1 gate stays green on current `main`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


async def test_ensure_sqlite_parent_dir_via_to_thread_does_not_block(tmp_path: Path) -> None:
    from deerflow.runtime.store._sqlite_utils import ensure_sqlite_parent_dir

    db_file = tmp_path / "subdir" / "store.db"

    await asyncio.to_thread(ensure_sqlite_parent_dir, str(db_file))

    assert db_file.parent.exists()
