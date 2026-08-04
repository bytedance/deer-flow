"""A corrupt stored schedule is an operator problem, not a client error.

``SqlScheduledTaskRepository._to_domain`` rebuilds the aggregate on every
read, so a row whose stored schedule no longer parses surfaces at read time.
It used to surface as ``InvalidScheduleError`` -- the same error the aggregate
raises for a *client-submitted* schedule, which the router maps to 422. That
double duty told the client "your request is wrong" about a request that was
perfectly fine, and made the row unrepairable over HTTP: PATCH reads the task
before writing, so the fix path 422'd too.

``CorruptStoredScheduleError`` splits the vocabulary: it is raised only by the
persistence adapter, and it is deliberately absent from the router's status
table so it falls through to the unclassified-500 branch -- a server-side
fault reported as one.

SQL-only: the in-memory double stores whole aggregates and cannot hold a
corrupt row, which is exactly why this file exists beside the contract suite
rather than inside it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from app.adapters.schedule.scheduled_task_repository import SqlScheduledTaskRepository
from app.gateway.routers.schedule.router import _STATUS_BY_ERROR
from deerflow.config.database_config import DatabaseConfig
from deerflow.domain.schedule.exceptions import CorruptStoredScheduleError, InvalidScheduleError
from deerflow.domain.schedule.model import ScheduledTask, SchedulePolicy, ScheduleSpec
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def repo(tmp_path) -> AsyncIterator[SqlScheduledTaskRepository]:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        sf = get_session_factory()
        assert sf is not None
        yield SqlScheduledTaskRepository(sf)
    finally:
        await close_engine()


async def _add_task(repo: SqlScheduledTaskRepository, *, title: str = "healthy") -> ScheduledTask:
    return await repo.add(
        ScheduledTask.create(
            user_id="user-1",
            title=title,
            prompt="p",
            schedule=ScheduleSpec.cron_schedule("0 9 * * *", "UTC"),
            context_mode="fresh_thread_per_run",
            thread_id=None,
            now=NOW,
            policy=SchedulePolicy(),
        )
    )


async def _corrupt(task_id: str, **columns) -> None:
    """Damage a stored row directly -- the exact shape a bug or a manual edit
    would leave behind, unreachable through the port."""
    sf = get_session_factory()
    assert sf is not None
    async with sf() as session:
        row = await session.get(ScheduledTaskRow, task_id)
        assert row is not None
        for name, value in columns.items():
            setattr(row, name, value)
        await session.commit()


class TestSingleRowReads:
    async def test_a_corrupt_schedule_raises_the_dedicated_error(self, repo):
        task = await _add_task(repo)
        await _corrupt(task.task_id, schedule_spec={})

        with pytest.raises(CorruptStoredScheduleError):
            await repo.get(task.task_id, user_id="user-1")

    async def test_the_dedicated_error_is_not_the_client_facing_one(self, repo):
        """The router maps InvalidScheduleError to 422; a corrupt row must not
        ride that mapping."""
        task = await _add_task(repo)
        await _corrupt(task.task_id, schedule_spec={})

        with pytest.raises(CorruptStoredScheduleError) as exc_info:
            await repo.get(task.task_id, user_id="user-1")
        assert not isinstance(exc_info.value, InvalidScheduleError)

    async def test_a_corrupt_context_mode_is_reported_the_same_way(self, repo):
        """Enum rebuild failures are the same fault as spec parse failures: a
        raw ValueError out of the adapter would be a technical exception
        crossing the boundary untranslated."""
        task = await _add_task(repo)
        await _corrupt(task.task_id, context_mode="not-a-mode")

        with pytest.raises(CorruptStoredScheduleError):
            await repo.get(task.task_id, user_id="user-1")


class TestListReads:
    async def test_a_corrupt_row_does_not_take_down_the_listing(self, repo):
        healthy = await _add_task(repo, title="healthy")
        broken = await _add_task(repo, title="broken")
        await _corrupt(broken.task_id, schedule_spec={})

        listed = await repo.list_by_user("user-1")

        assert [t.task_id for t in listed] == [healthy.task_id]


class TestRouterMapping:
    def test_the_corrupt_row_error_is_unclassified_on_purpose(self):
        """Absent from the status table means the router's fallthrough turns
        it into a 500 -- a new protocol decision would have to add it here
        deliberately."""
        assert CorruptStoredScheduleError not in _STATUS_BY_ERROR
