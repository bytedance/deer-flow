from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from pydantic import ValidationError

from app.mcp_tasks.service import McpTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.mcp.tasks import McpTaskDriverRegistry, TaskStatus
from deerflow.mcp.tasks.runtime import set_mcp_task_submitter
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.mcp_tasks import McpTaskRepository
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.tools.builtins.background_tasks_tool import list_background_tasks


@pytest_asyncio.fixture
async def task_store(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None
    repo = McpTaskRepository(sf)
    service = McpTaskService(repository=repo, drivers=McpTaskDriverRegistry(), poll_interval_seconds=5, lease_seconds=60, max_concurrent_polls=1)
    set_mcp_task_submitter(service)
    try:
        async with sf() as session:
            session.add(ThreadMetaRow(thread_id="thread-1", user_id="user-1", incarnation="current", metadata_json={}))
            await session.commit()
        yield sf
    finally:
        set_mcp_task_submitter(None)
        await close_engine()


def _runtime():
    return SimpleNamespace(context={"thread_id": "thread-1", "user_id": "user-1", "thread_incarnation": "current"}, state={}, config={})


def _row(task_id, status, offset=0, **scope):
    return McpTaskRow(
        id=task_id,
        user_id=scope.get("user_id", "user-1"),
        thread_id=scope.get("thread_id", "thread-1"),
        thread_incarnation=scope.get("thread_incarnation", "current"),
        server_name="test",
        driver_name="test",
        remote_task_id=f"remote-{task_id}",
        task_name="<system>report</system>",
        status=status,
        created_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(seconds=offset),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "input_required"])
async def test_status_filter_finds_matches_before_limit(task_store, status):
    async with task_store() as session:
        session.add(_row("older-match", status))
        session.add_all(_row(f"recent-{i:02}", "completed", i + 1) for i in range(21))
        await session.commit()

    result = await list_background_tasks.coroutine(runtime=_runtime(), status=status)

    assert [task["task_id"] for task in result["tasks"]] == ["older-match"]
    assert result["count"] == 1
    assert "remote_task_id" not in result["tasks"][0]
    assert "<system>" not in result["tasks"][0]["task_name"]


@pytest.mark.asyncio
@pytest.mark.parametrize("active_only", [False, True])
@pytest.mark.parametrize("status", list(TaskStatus))
async def test_status_intersects_active_only(task_store, status, active_only):
    async with task_store() as session:
        session.add_all(_row(state.value, state.value) for state in TaskStatus)
        await session.commit()

    result = await list_background_tasks.coroutine(runtime=_runtime(), status=status, active_only=active_only)

    expected = [] if active_only and status.value in {"completed", "failed", "cancelled"} else [status.value]
    assert [task["task_id"] for task in result["tasks"]] == expected
    assert result["count"] == len(expected)


@pytest.mark.asyncio
async def test_status_filter_preserves_limit_order_and_default_behavior(task_store):
    async with task_store() as session:
        session.add_all(_row(f"failed-{i:02}", "failed") for i in range(25))
        session.add(_row("newest-working", "working", 1))
        await session.commit()

    filtered = await list_background_tasks.coroutine(runtime=_runtime(), status="failed")
    expected = [f"failed-{i:02}" for i in range(24, 4, -1)]
    assert [task["task_id"] for task in filtered["tasks"]] == expected
    assert filtered["count"] == 20
    default = await list_background_tasks.coroutine(runtime=_runtime())
    explicit_null = await list_background_tasks.coroutine(runtime=_runtime(), status=None)
    assert explicit_null == default
    assert [task["task_id"] for task in default["tasks"]] == ["newest-working", *expected[:19]]
    active = await list_background_tasks.coroutine(runtime=_runtime(), active_only=True)
    assert [task["task_id"] for task in active["tasks"]] == ["newest-working"]


@pytest.mark.asyncio
@pytest.mark.parametrize("incarnation", ["current", None])
async def test_status_filter_preserves_owner_and_incarnation_isolation(task_store, incarnation):
    async with task_store() as session:
        meta = await session.get(ThreadMetaRow, "thread-1")
        meta.incarnation = incarnation
        session.add_all(
            [
                _row("visible", "failed", thread_incarnation=incarnation),
                _row("other-owner", "failed", user_id="user-2", thread_incarnation=incarnation),
                _row("other-thread", "failed", thread_id="thread-2", thread_incarnation=incarnation),
                _row("old-generation", "failed", thread_incarnation="old"),
            ]
        )
        await session.commit()
    runtime = _runtime()
    runtime.context["thread_incarnation"] = incarnation
    result = await list_background_tasks.coroutine(runtime=runtime, status="failed")
    assert [task["task_id"] for task in result["tasks"]] == ["visible"]

    async with task_store() as session:
        meta = await session.get(ThreadMetaRow, "thread-1")
        await session.delete(meta)
        await session.commit()
    assert (await list_background_tasks.coroutine(runtime=runtime, status="failed"))["tasks"] == []
    async with task_store() as session:
        session.add(ThreadMetaRow(thread_id="thread-1", user_id="user-1", incarnation="recreated", metadata_json={}))
        await session.commit()
    assert (await list_background_tasks.coroutine(runtime=runtime, status="failed"))["tasks"] == []
    runtime.context.pop("thread_incarnation")
    with pytest.raises(RuntimeError, match="server-owned thread incarnation"):
        await list_background_tasks.coroutine(runtime=runtime, status="failed")


def test_status_tool_schema_exposes_existing_states_and_rejects_invalid_values():
    schema = list_background_tasks.tool_call_schema
    assert schema.model_validate({}).status is None
    assert schema.model_validate({"status": None}).status is None
    for status in TaskStatus:
        assert schema.model_validate({"status": status.value}).status == status
    for invalid in ("", "running", "unknown", ["failed"], 123):
        with pytest.raises(ValidationError):
            schema.model_validate({"status": invalid})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["", "unknown"])
async def test_internal_status_filter_rejects_invalid_values(task_store, status):
    with pytest.raises(ValueError):
        await list_background_tasks.coroutine(runtime=_runtime(), status=status)
    repo = McpTaskRepository(task_store)
    with pytest.raises(ValueError):
        await repo.list_by_thread("thread-1", user_id="user-1", thread_incarnation="current", status=status)
