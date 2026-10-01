"""Verify cancellation target selection and ambiguity beyond list limits with the real repository."""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import update

from app.mcp_tasks.service import McpTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.mcp.tasks import McpTaskDriverRegistry
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.mcp_tasks import McpTaskRepository
from deerflow.persistence.mcp_tasks.model import McpTaskRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow

SCOPE = {"user_id": "user-1", "thread_id": "thread-1", "thread_incarnation": "inc-1"}


@pytest_asyncio.fixture
async def tasks(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None
    now = datetime.now(UTC)
    async with sf() as session:
        session.add(ThreadMetaRow(thread_id="thread-1", user_id="user-1", incarnation="inc-1", metadata_json={}, created_at=now, updated_at=now))
        await session.commit()
    repo = McpTaskRepository(sf)
    service = McpTaskService(repository=repo, drivers=McpTaskDriverRegistry(), poll_interval_seconds=5, lease_seconds=120, max_concurrent_polls=3)
    try:
        yield repo, service
    finally:
        await close_engine()


async def create_task(repo, task_id, name, *, status="working"):
    return await repo.create(
        task_id=task_id,
        user_id="user-1",
        thread_id="thread-1",
        expected_thread_incarnation="inc-1",
        run_id=None,
        tool_call_id=None,
        server_name="reports",
        driver_name="fake",
        remote_task_id=f"remote-{task_id}",
        task_name=name,
        status=status,
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("selector", ["old-task", "old report"])
async def test_cancel_finds_active_task_beyond_display_page(tasks, selector):
    repo, service = tasks
    await create_task(repo, "old-task", "old report")
    for i in range(50):
        await create_task(repo, f"new-{i}", f"new report {i}")
    assert "old-task" not in {row["id"] for row in await service.list_tasks(**SCOPE, active_only=True)}

    selected = await service.cancel_matching_task(**SCOPE, task=selector)

    assert selected["id"] == "old-task"
    assert selected["status"] == "working"
    assert selected["cancel_requested_at"] is not None
    persisted = await repo.get("old-task", **SCOPE)
    assert persisted["cancel_requested_at"] == selected["cancel_requested_at"]


@pytest.mark.asyncio
async def test_cancel_rejects_duplicate_names_across_display_page(tasks):
    repo, service = tasks
    await create_task(repo, "old-task", "Straße")
    for i in range(49):
        await create_task(repo, f"new-{i}", f"new report {i}")
    await create_task(repo, "newest", "STRASSE")

    with pytest.raises(ValueError, match=r"More than one active background task matches; cancel by task ID \(conflicting names: (Straße, STRASSE|STRASSE, Straße)\)"):
        await service.cancel_matching_task(**SCOPE, task=" strasse ")

    for task_id in ("old-task", "newest"):
        assert (await repo.get(task_id, **SCOPE))["cancel_requested_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("name,selector", [("Straße", " STRASSE "), ("Σςσ", "σσσ"), ("İ", "i\u0307"), ("Report", "report")])
async def test_cancel_preserves_unicode_casefold(tasks, name, selector):
    repo, service = tasks
    await create_task(repo, "task-1", name)
    result = await service.cancel_matching_task(**SCOPE, task=selector)
    assert result["id"] == "task-1"
    assert "task_name_key" not in result


@pytest.mark.asyncio
async def test_exact_id_disambiguates_a_name_collision(tasks):
    repo, service = tasks
    await create_task(repo, "chosen-id", "report")
    await create_task(repo, "other-id", "chosen-id")
    result = await service.cancel_matching_task(**SCOPE, task="chosen-id")
    assert result["id"] == "chosen-id"
    assert (await repo.get("other-id", **SCOPE))["cancel_requested_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 2, 51])
async def test_omitted_selector_requires_exactly_one_active_task(tasks, count):
    repo, service = tasks
    for i in range(count):
        await create_task(repo, f"task-{i}", "report")
    if count == 1:
        assert (await service.cancel_matching_task(**SCOPE))["id"] == "task-0"
    else:
        with pytest.raises(LookupError if count == 0 else ValueError):
            await service.cancel_matching_task(**SCOPE)
        assert all(row["cancel_requested_at"] is None for row in await service.list_tasks(**SCOPE, limit=100))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
@pytest.mark.parametrize("selector", ["old-task", "report"])
async def test_terminal_tasks_are_not_cancellation_targets(tasks, status, selector):
    repo, service = tasks
    await create_task(repo, "old-task", "report", status=status)
    with pytest.raises(LookupError):
        await service.cancel_matching_task(**SCOPE, task=selector)
    assert (await repo.get("old-task", **SCOPE))["cancel_requested_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [{"user_id": "other-user"}, {"thread_id": "other-thread"}, {"thread_incarnation": "old-inc"}, {"thread_incarnation": None}])
@pytest.mark.parametrize("selector", ["task-1", "report"])
async def test_cancel_respects_trusted_scope(tasks, override, selector):
    repo, service = tasks
    await create_task(repo, "task-1", "report")
    with pytest.raises(LookupError):
        await service.cancel_matching_task(**(SCOPE | override), task=selector)
    assert (await repo.get("task-1", **SCOPE))["cancel_requested_at"] is None


@pytest.mark.asyncio
async def test_name_uniqueness_ignores_stale_incarnations(tasks):
    repo, service = tasks
    await create_task(repo, "old-task", "report")
    async with repo._sf() as session:
        await session.execute(update(McpTaskRow).where(McpTaskRow.id == "old-task").values(thread_incarnation="old-inc"))
        await session.commit()
    await create_task(repo, "new-task", "report")
    assert (await service.cancel_matching_task(**SCOPE, task="report"))["id"] == "new-task"


@pytest.mark.asyncio
async def test_query_returns_only_enough_matches_to_detect_ambiguity(tasks):
    repo, _service = tasks
    for i in range(3):
        await create_task(repo, f"task-{i}", "report")
    matches = await repo.find_active_matches(**SCOPE, task="report")
    assert len(matches) == 2


@pytest.mark.asyncio
async def test_stored_name_whitespace_is_not_silently_normalized(tasks):
    repo, service = tasks
    await create_task(repo, "task-1", " report ")
    with pytest.raises(LookupError):
        await service.cancel_matching_task(**SCOPE, task="report")


@pytest.mark.asyncio
async def test_legacy_null_incarnation_can_select_owned_task(tasks):
    repo, service = tasks
    await create_task(repo, "task-1", "report")
    async with repo._sf() as session:
        await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == "thread-1").values(incarnation=None))
        await session.execute(update(McpTaskRow).where(McpTaskRow.id == "task-1").values(thread_incarnation=None))
        await session.commit()
    assert (await service.cancel_matching_task(**(SCOPE | {"thread_incarnation": None}), task="report"))["id"] == "task-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["completed", "deleted", "recreated"])
async def test_selection_rechecks_lifecycle_when_persisting_request(tasks, monkeypatch, change):
    repo, service = tasks
    await create_task(repo, "task-1", "report")
    request_cancel = repo.request_cancel

    async def race(task_id, **kwargs):
        async with repo._sf() as session:
            if change == "completed":
                await session.execute(update(McpTaskRow).where(McpTaskRow.id == task_id).values(status="completed"))
            elif change == "deleted":
                await session.delete(await session.get(McpTaskRow, task_id))
            else:
                await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == "thread-1").values(incarnation="inc-2"))
            await session.commit()
        return await request_cancel(task_id, **kwargs)

    monkeypatch.setattr(repo, "request_cancel", race)
    if change == "completed":
        result = await service.cancel_matching_task(**SCOPE, task="report")
        assert result["status"] == "completed"
        assert result["cancel_requested_at"] is None
    else:
        with pytest.raises(LookupError, match="no longer exists"):
            await service.cancel_matching_task(**SCOPE, task="report")
