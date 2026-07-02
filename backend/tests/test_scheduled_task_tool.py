from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from deerflow.scheduler.triggers import CronTrigger
from deerflow.tools.builtins.scheduled_task_tool import scheduled_task


async def _init_sqlite(tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'scheduled-task-tool.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return get_session_factory()


async def _cleanup():
    from deerflow.persistence.engine import close_engine

    await close_engine()


def _runtime(user_id: str, *, source_channel: str = "web"):
    return SimpleNamespace(
        context={"user_id": user_id, "source_channel": source_channel},
        tool_call_id=f"call-{user_id}",
    )


def _tool_content(command) -> str:
    return command.update["messages"][0].content


@pytest.mark.anyio
async def test_scheduled_task_tool_create_list_delete(tmp_path):
    await _init_sqlite(tmp_path)
    runtime = _runtime("alice", source_channel="im:feishu:chat:oc_123")
    try:
        created = await scheduled_task.coroutine(
            action="create",
            runtime=runtime,
            name="sleep reminder",
            when="1h",
            description="Remind me to sleep.",
            timezone="Asia/Shanghai",
        )

        created_text = _tool_content(created)
        assert "Scheduled task created." in created_text
        assert "sleep reminder" in created_text
        assert "feishu chat" in created_text

        listed = await scheduled_task.coroutine(
            action="list",
            runtime=runtime,
            timezone="Asia/Shanghai",
        )
        listed_text = _tool_content(listed)
        assert "Scheduled tasks (1 shown):" in listed_text
        assert "sleep reminder" in listed_text

        job_id = next(line.split(":", 1)[1].strip() for line in listed_text.splitlines() if line.strip().startswith("ID:"))
        deleted = await scheduled_task.coroutine(
            action="delete",
            runtime=runtime,
            job_id=job_id,
            timezone="Asia/Shanghai",
        )
        assert "Scheduled task deleted." in _tool_content(deleted)

        listed_after_delete = await scheduled_task.coroutine(action="list", runtime=runtime)
        assert "No enabled scheduled tasks found." in _tool_content(listed_after_delete)
    finally:
        await _cleanup()


@pytest.mark.anyio
async def test_scheduled_task_tool_is_user_scoped(tmp_path):
    await _init_sqlite(tmp_path)
    alice = _runtime("alice")
    bob = _runtime("bob")
    try:
        await scheduled_task.coroutine(
            action="create",
            runtime=alice,
            name="alice task",
            when="1h",
            description="Alice only.",
        )
        await scheduled_task.coroutine(
            action="create",
            runtime=bob,
            name="bob task",
            when="1h",
            description="Bob only.",
        )

        alice_list = _tool_content(await scheduled_task.coroutine(action="list", runtime=alice))
        bob_list = _tool_content(await scheduled_task.coroutine(action="list", runtime=bob))
        assert "alice task" in alice_list
        assert "bob task" not in alice_list
        assert "bob task" in bob_list
        assert "alice task" not in bob_list

        bob_job_id = next(line.split(":", 1)[1].strip() for line in bob_list.splitlines() if line.strip().startswith("ID:"))
        cross_delete = await scheduled_task.coroutine(action="delete", runtime=alice, job_id=bob_job_id)
        assert "Error: scheduled task not found" in _tool_content(cross_delete)

        bob_list_after = _tool_content(await scheduled_task.coroutine(action="list", runtime=bob))
        assert "bob task" in bob_list_after
    finally:
        await _cleanup()


@pytest.mark.anyio
async def test_scheduled_task_tool_cron_initial_stagger_uses_job_id(tmp_path, monkeypatch):
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.scheduled_jobs import ScheduledJobRepository
    from deerflow.tools.builtins import scheduled_task_tool as tool_mod

    fixed_now = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    await _init_sqlite(tmp_path)
    monkeypatch.setattr(tool_mod, "datetime", FixedDateTime)
    runtime = _runtime("alice")
    try:
        created = await scheduled_task.coroutine(
            action="create",
            runtime=runtime,
            name="hourly report",
            when="0 * * * *",
            description="Send an hourly report.",
            timezone="UTC",
        )
        assert "Scheduled task created." in _tool_content(created)

        repo = ScheduledJobRepository(get_session_factory())
        jobs = await repo.list_jobs(user_id="alice")
        assert len(jobs) == 1
        job = jobs[0]
        expected = CronTrigger("0 * * * *", tz="UTC").compute_next(None, now=fixed_now, job_id=job["id"])
        assert datetime.fromisoformat(job["next_run_at"]) == expected
    finally:
        await _cleanup()
