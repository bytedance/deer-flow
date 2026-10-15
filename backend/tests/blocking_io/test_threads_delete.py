"""Regression anchor: deleting a thread must not block the event loop.

``DELETE /api/threads/{id}`` removes the thread's whole directory tree
(workspace, uploads, outputs). ``shutil.rmtree`` over a large workspace
stalls every other request on the Gateway loop, so the handler offloads it
via ``run_file_io``; if the removal regresses onto the event loop, the strict
Blockbuster gate raises ``BlockingError``, the handler maps it to a 500, and
this test fails.

The handler is driven through ``__wrapped__`` (past the authz decorator) so
the goal lock, the thread-operation reservation and every cleanup step run as
in production. Imports live at module scope so their file reads happen at
collection time, not on the loop under test; test-side seeding and checks are
offloaded with ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.gateway.routers import threads
from deerflow.config.paths import Paths
from deerflow.runtime.user_context import get_effective_user_id

pytestmark = pytest.mark.asyncio


class _RunManager:
    @asynccontextmanager
    async def reserve_thread_operation(self, _thread_id: str, **_kwargs):
        yield


def _seed_workspace(paths: Paths, thread_id: str, user_id: str) -> Path:
    paths.ensure_thread_dirs(thread_id, user_id=user_id)
    workspace = paths.sandbox_work_dir(thread_id, user_id=user_id)
    for index in range(20):
        (workspace / f"file-{index}.txt").write_text("content", encoding="utf-8")
    return paths.thread_dir(thread_id, user_id=user_id)


async def test_delete_thread_does_not_block_event_loop(tmp_path: Path) -> None:
    user_id = get_effective_user_id()
    # test-side setup and seeding (offloaded; not exercised on the loop)
    paths = await asyncio.to_thread(Paths, tmp_path)
    thread_dir = await asyncio.to_thread(_seed_workspace, paths, "thread-loop-delete", user_id)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(run_manager=_RunManager(), checkpointer=None)))

    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        response = await threads.delete_thread_data.__wrapped__("thread-loop-delete", request)

    assert response.success is True
    assert response.message == "Deleted local thread data for thread-loop-delete"
    assert not await asyncio.to_thread(thread_dir.exists)
