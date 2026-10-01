"""Cancellation target selection must cover the whole active task set (issue #6119).

``cancel_matching_task()`` used to resolve its target from
``list_tasks(active_only=True)`` with the default display page of 50 records.
A task older than the newest 50 could therefore never be cancelled by ID or by
name, and a name shared with a task outside the page looked unique instead of
ambiguous.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from app.mcp_tasks.service import McpTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.mcp.tasks import McpTaskDriverRegistry
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.mcp_tasks import McpTaskRepository
from deerflow.persistence.thread_meta.model import ThreadMetaRow

_DISPLAY_PAGE = 50


@pytest_asyncio.fixture(autouse=True)
async def _close_persistence_engine():
    yield
    await close_engine()


async def _make_repo(tmp_path) -> McpTaskRepository:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    session_factory = get_session_factory()
    assert session_factory is not None
    return McpTaskRepository(session_factory)


def _make_service(repo: McpTaskRepository) -> McpTaskService:
    return McpTaskService(
        repository=repo,
        drivers=McpTaskDriverRegistry(),
        poll_interval_seconds=5,
        lease_seconds=60,
        max_concurrent_polls=1,
        launch_notification=AsyncMock(),
        get_run=AsyncMock(return_value=None),
    )


async def _create_working_task(
    repo: McpTaskRepository,
    *,
    task_id: str,
    task_name: str,
) -> dict:
    now = datetime.now(UTC)
    async with repo._sf() as session:
        if await session.get(ThreadMetaRow, "thread-1") is None:
            session.add(
                ThreadMetaRow(
                    thread_id="thread-1",
                    incarnation=None,
                    user_id="user-1",
                    metadata_json={},
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()
    return await repo.create(
        task_id=task_id,
        user_id="user-1",
        thread_id="thread-1",
        expected_thread_incarnation=None,
        run_id="run-1",
        tool_call_id="call-1",
        server_name="reports",
        driver_name="fake",
        remote_task_id=f"remote-{task_id}",
        task_name=task_name,
        status="working",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=now,
        driver_data={"status_tool": "status"},
    )


async def _seed_active_tasks(repo: McpTaskRepository, oldest: tuple[str, str], newer_count: int, newest: tuple[str, str] | None = None) -> None:
    """Create an oldest task, *newer_count* intervening tasks, and an optional newest one."""
    await _create_working_task(repo, task_id=oldest[0], task_name=oldest[1])
    for index in range(1, newer_count + 1):
        await _create_working_task(repo, task_id=f"task-{index:03d}", task_name=f"newer report {index}")
    if newest is not None:
        await _create_working_task(repo, task_id=newest[0], task_name=newest[1])


@pytest.mark.asyncio
@pytest.mark.parametrize("selector", ["old-task", "old report"], ids=["by-id", "by-name"])
async def test_cancel_finds_active_task_beyond_display_page(tmp_path, selector):
    repo = await _make_repo(tmp_path)
    service = _make_service(repo)
    await _seed_active_tasks(repo, oldest=("old-task", "old report"), newer_count=_DISPLAY_PAGE)

    page = await service.list_tasks(thread_id="thread-1", user_id="user-1", thread_incarnation=None, active_only=True)
    assert len(page) == _DISPLAY_PAGE
    assert all(item["id"] != "old-task" for item in page)

    record = await service.cancel_matching_task(
        thread_id="thread-1",
        user_id="user-1",
        thread_incarnation=None,
        task=selector,
    )
    assert record["id"] == "old-task"
    assert record["cancel_requested_at"] is not None


@pytest.mark.asyncio
async def test_cancel_rejects_duplicate_names_across_display_page(tmp_path):
    repo = await _make_repo(tmp_path)
    service = _make_service(repo)
    await _seed_active_tasks(
        repo,
        oldest=("old-strasse-task", "Straße"),
        newer_count=_DISPLAY_PAGE - 1,
        newest=("task-050", "STRASSE"),
    )

    with pytest.raises(ValueError, match="More than one active background task"):
        await service.cancel_matching_task(
            thread_id="thread-1",
            user_id="user-1",
            thread_incarnation=None,
            task=" strasse ",
        )

    active = await service.list_tasks(thread_id="thread-1", user_id="user-1", thread_incarnation=None, active_only=True, limit=None)
    assert len(active) == _DISPLAY_PAGE + 1
    assert all(item["cancel_requested_at"] is None for item in active)


@pytest.mark.asyncio
async def test_cancel_within_display_page_still_resolves_unique_targets(tmp_path):
    repo = await _make_repo(tmp_path)
    service = _make_service(repo)
    await _create_working_task(repo, task_id="task-001", task_name="first report")
    await _create_working_task(repo, task_id="task-002", task_name="second report")

    by_id = await service.cancel_matching_task(
        thread_id="thread-1",
        user_id="user-1",
        thread_incarnation=None,
        task="task-001",
    )
    assert by_id["id"] == "task-001"

    by_name = await service.cancel_matching_task(
        thread_id="thread-1",
        user_id="user-1",
        thread_incarnation=None,
        task="second report",
    )
    assert by_name["id"] == "task-002"
