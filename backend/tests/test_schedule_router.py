"""Behaviour tests for the scheduled-task HTTP adapter.

Driven through the handlers with a **real** `ScheduleService` over in-memory
port fakes, not a mocked service. The router's whole remaining job is protocol
translation, and half of that is turning domain errors into status codes -- a
mocked service would let those assertions pass without a domain error ever
being raised.

`__wrapped__` unwraps `@require_permission` (authorization is covered by its
own suite) while keeping `_map_domain_errors` in the call path, which is the
layer under test here.

The legacy `test_scheduled_task_router_behavior.py` remains the reference for
what this endpoint must do; every scenario it pins has a counterpart below,
plus the response-shape and error-mapping cases the old dict-returning router
could not express.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from schedule_fakes import (
    FakeRunLauncher,
    FakeThreadLookup,
    InMemoryScheduledRunRepository,
    InMemoryScheduledTaskRepository,
)

from app.gateway.routers.schedule import router as router_module
from deerflow.domain.schedule.exceptions import LaunchFailedError, ThreadBusyError
from deerflow.domain.schedule.model import RunStatus, ScheduledRun, SchedulePolicy, TaskStatus, TriggerKind
from deerflow.domain.schedule.service import ScheduleService

USER = "user-1"
OTHER_USER = "user-2"
THREAD = "thread-1"


class _User:
    def __init__(self, user_id: str | None) -> None:
        self.id = user_id


@pytest.fixture
def tasks():
    return InMemoryScheduledTaskRepository()


@pytest.fixture
def runs():
    return InMemoryScheduledRunRepository()


@pytest.fixture
def launcher():
    return FakeRunLauncher()


@pytest.fixture
def service(tasks, runs, launcher):
    return ScheduleService(
        tasks=tasks,
        runs=runs,
        launcher=launcher,
        threads=FakeThreadLookup({THREAD: USER}),
        policy=SchedulePolicy(min_once_delay_seconds=60, max_concurrent_runs=3, lease_seconds=120),
    )


@pytest.fixture
def as_user(monkeypatch):
    """Authenticate the handlers as a given user id (None = anonymous)."""

    def _apply(user_id: str | None = USER):
        async def _resolve(_request):
            return None if user_id is None else _User(user_id)

        monkeypatch.setattr(router_module, "get_optional_user_from_request", _resolve)

    _apply()
    return _apply


def _call(handler, **kwargs):
    """Invoke a route handler with authorization unwrapped."""
    return handler.__wrapped__(request=object(), **kwargs)


def _create_body(**overrides):
    defaults = dict(
        thread_id=None,
        context_mode="fresh_thread_per_run",
        title="Daily summary",
        prompt="Summarize the thread",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
    )
    return router_module.ScheduledTaskCreateRequest(**{**defaults, **overrides})


def _update_body(**fields):
    return router_module.ScheduledTaskUpdateRequest(**fields)


async def _create(service, **overrides):
    return await _call(router_module.create_scheduled_task, body=_create_body(**overrides), service=service)


class TestCreate:
    @pytest.mark.asyncio
    async def test_a_cron_task_is_created_and_rendered(self, service, as_user):
        created = await _create(service)
        assert created.title == "Daily summary"
        assert created.schedule_type == "cron"
        assert created.schedule_spec == {"cron": "0 9 * * *"}
        assert created.status == "enabled"
        assert created.next_run_at is not None

    @pytest.mark.asyncio
    async def test_the_response_carries_no_server_owned_fields(self, service, as_user):
        """The pre-migration router returned the ORM row, leaking `user_id`,
        `overlap_policy` and `assistant_id` to every client."""
        rendered = (await _create(service)).model_dump()
        assert {"user_id", "assistant_id", "overlap_policy", "lease_owner", "lease_expires_at"} & set(rendered) == set()

    @pytest.mark.asyncio
    async def test_a_fresh_thread_task_needs_no_thread_id(self, service, as_user):
        created = await _create(service, context_mode="fresh_thread_per_run", thread_id=None)
        assert created.thread_id is None

    @pytest.mark.asyncio
    async def test_reuse_thread_binds_the_thread(self, service, as_user):
        created = await _create(service, context_mode="reuse_thread", thread_id=THREAD)
        assert created.thread_id == THREAD

    @pytest.mark.asyncio
    async def test_reuse_thread_without_a_thread_id_is_422(self, service, as_user):
        with pytest.raises(HTTPException) as caught:
            await _create(service, context_mode="reuse_thread", thread_id=None)
        assert caught.value.status_code == 422

    @pytest.mark.asyncio
    async def test_reuse_of_an_unknown_thread_is_404(self, service, as_user):
        with pytest.raises(HTTPException) as caught:
            await _create(service, context_mode="reuse_thread", thread_id="thread-nope")
        assert caught.value.status_code == 404

    @pytest.mark.asyncio
    async def test_reuse_of_someone_elses_thread_is_also_404(self, service, as_user):
        """Indistinguishable from "does not exist" on purpose: telling them
        apart would let a caller probe for threads they cannot see."""
        as_user(OTHER_USER)
        with pytest.raises(HTTPException) as caught:
            await _create(service, context_mode="reuse_thread", thread_id=THREAD)
        assert caught.value.status_code == 404

    @pytest.mark.asyncio
    async def test_an_unknown_schedule_type_is_422(self, service, as_user):
        with pytest.raises(HTTPException) as caught:
            await _create(service, schedule_type="teleport")
        assert caught.value.status_code == 422

    @pytest.mark.asyncio
    async def test_a_cron_without_its_key_is_422(self, service, as_user):
        with pytest.raises(HTTPException) as caught:
            await _create(service, schedule_type="cron", schedule_spec={})
        assert caught.value.status_code == 422

    @pytest.mark.asyncio
    async def test_a_malformed_cron_is_422(self, service, as_user):
        with pytest.raises(HTTPException) as caught:
            await _create(service, schedule_type="cron", schedule_spec={"cron": "0 9 * *"})
        assert caught.value.status_code == 422

    @pytest.mark.asyncio
    async def test_an_unknown_timezone_is_422(self, service, as_user):
        with pytest.raises(HTTPException) as caught:
            await _create(service, timezone="Mars/Olympus_Mons")
        assert caught.value.status_code == 422

    @pytest.mark.asyncio
    async def test_a_once_schedule_too_close_to_now_is_422(self, service, as_user):
        """`min_once_delay_seconds` is operator policy, and it reaches the
        aggregate through SchedulePolicy rather than being re-checked here."""
        soon = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
        with pytest.raises(HTTPException) as caught:
            await _create(service, schedule_type="once", schedule_spec={"run_at": soon})
        assert caught.value.status_code == 422

    @pytest.mark.asyncio
    async def test_a_once_schedule_in_the_past_is_422(self, service, as_user):
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        with pytest.raises(HTTPException) as caught:
            await _create(service, schedule_type="once", schedule_spec={"run_at": past})
        assert caught.value.status_code == 422

    @pytest.mark.asyncio
    async def test_an_unknown_context_mode_is_422(self, service, as_user):
        with pytest.raises(HTTPException) as caught:
            await _create(service, context_mode="telepathy")
        assert caught.value.status_code == 422

    @pytest.mark.asyncio
    async def test_an_anonymous_caller_is_401(self, service, as_user):
        as_user(None)
        with pytest.raises(HTTPException) as caught:
            await _create(service)
        assert caught.value.status_code == 401


class TestRead:
    @pytest.mark.asyncio
    async def test_a_task_is_fetched_by_id(self, service, as_user):
        created = await _create(service)
        fetched = await _call(router_module.get_scheduled_task, task_id=created.id, service=service)
        assert fetched.id == created.id

    @pytest.mark.asyncio
    async def test_an_unknown_task_is_404(self, service, as_user):
        with pytest.raises(HTTPException) as caught:
            await _call(router_module.get_scheduled_task, task_id="task-nope", service=service)
        assert caught.value.status_code == 404

    @pytest.mark.asyncio
    async def test_another_users_task_is_404(self, service, as_user):
        created = await _create(service)
        as_user(OTHER_USER)
        with pytest.raises(HTTPException) as caught:
            await _call(router_module.get_scheduled_task, task_id=created.id, service=service)
        assert caught.value.status_code == 404

    @pytest.mark.asyncio
    async def test_listing_returns_the_users_tasks(self, service, as_user):
        await _create(service, title="One")
        await _create(service, title="Two")
        listed = await _call(router_module.list_scheduled_tasks, service=service)
        assert {task.title for task in listed} == {"One", "Two"}

    @pytest.mark.asyncio
    async def test_an_anonymous_listing_is_empty_not_401(self, service, as_user):
        """Unchanged from the pre-migration router: this endpoint has always
        answered an unauthenticated GET with an empty list."""
        as_user(None)
        assert await _call(router_module.list_scheduled_tasks, service=service) == []

    @pytest.mark.asyncio
    async def test_thread_listing_filters_by_thread(self, service, as_user):
        await _create(service, context_mode="reuse_thread", thread_id=THREAD, title="Bound")
        await _create(service, title="Unbound")
        listed = await _call(router_module.list_thread_scheduled_tasks, thread_id=THREAD, service=service)
        assert [task.title for task in listed] == ["Bound"]


class TestUpdate:
    @pytest.mark.asyncio
    async def test_a_title_is_updated_in_place(self, service, as_user):
        created = await _create(service)
        updated = await _call(
            router_module.update_scheduled_task,
            task_id=created.id,
            body=_update_body(title="Renamed"),
            service=service,
        )
        assert updated.title == "Renamed"
        assert updated.schedule_spec == created.schedule_spec

    @pytest.mark.asyncio
    async def test_a_schedule_spec_change_keeps_the_existing_timezone(self, service, as_user):
        """Only one of the three schedule parts was supplied; the router reads
        the task to complete the value object rather than the service being
        handed a partial one."""
        created = await _create(service, timezone="Asia/Shanghai")
        updated = await _call(
            router_module.update_scheduled_task,
            task_id=created.id,
            body=_update_body(schedule_spec={"cron": "30 2 * * *"}),
            service=service,
        )
        assert updated.schedule_spec == {"cron": "30 2 * * *"}
        assert updated.timezone == "Asia/Shanghai"

    @pytest.mark.asyncio
    async def test_a_timezone_change_keeps_the_existing_spec(self, service, as_user):
        created = await _create(service)
        updated = await _call(
            router_module.update_scheduled_task,
            task_id=created.id,
            body=_update_body(timezone="Asia/Shanghai"),
            service=service,
        )
        assert updated.schedule_spec == created.schedule_spec
        assert updated.timezone == "Asia/Shanghai"

    @pytest.mark.asyncio
    async def test_a_timezone_change_on_a_once_task_keeps_the_same_instant(self, service, as_user):
        """The `once` half of the fallback above.

        The omitted `run_at` is read straight off the current value object, and
        the stored instant is already offset-aware, so re-zoning the schedule
        must relabel it without moving it.
        """
        created = await _create(
            service,
            schedule_type="once",
            schedule_spec={"run_at": "2026-08-01T09:00:00+00:00"},
            timezone="UTC",
        )
        updated = await _call(
            router_module.update_scheduled_task,
            task_id=created.id,
            body=_update_body(timezone="Asia/Shanghai"),
            service=service,
        )
        assert updated.schedule_spec == created.schedule_spec
        assert updated.timezone == "Asia/Shanghai"
        assert updated.next_run_at == created.next_run_at

    @pytest.mark.asyncio
    async def test_a_running_task_cannot_be_updated(self, service, tasks, as_user):
        """Red line: the mutability gate lives in the aggregate now, and the
        router only maps it onto 409."""
        created = await _create(service)
        stored = await tasks.get(created.id, user_id=USER)
        await tasks.save(stored.__class__(**{**stored.__dict__, "status": TaskStatus.RUNNING}))
        with pytest.raises(HTTPException) as caught:
            await _call(
                router_module.update_scheduled_task,
                task_id=created.id,
                body=_update_body(title="Renamed"),
                service=service,
            )
        assert caught.value.status_code == 409

    @pytest.mark.asyncio
    async def test_updating_an_unknown_task_is_404(self, service, as_user):
        with pytest.raises(HTTPException) as caught:
            await _call(
                router_module.update_scheduled_task,
                task_id="task-nope",
                body=_update_body(title="Renamed"),
                service=service,
            )
        assert caught.value.status_code == 404

    @pytest.mark.asyncio
    async def test_a_malformed_new_schedule_is_422(self, service, as_user):
        created = await _create(service)
        with pytest.raises(HTTPException) as caught:
            await _call(
                router_module.update_scheduled_task,
                task_id=created.id,
                body=_update_body(schedule_spec={"cron": "0 9 * *"}),
                service=service,
            )
        assert caught.value.status_code == 422

    @pytest.mark.asyncio
    async def test_a_terminal_once_task_pushed_into_the_future_is_rearmed(self, service, tasks, as_user):
        """Red line: without re-arming, the API answers 200 with a
        `next_run_at` that can never fire, because claiming only admits
        `enabled` rows."""
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        created = await _create(service, schedule_type="once", schedule_spec={"run_at": future})
        stored = await tasks.get(created.id, user_id=USER)
        await tasks.save(stored.__class__(**{**stored.__dict__, "status": TaskStatus.FAILED}))

        later = (datetime.now(UTC) + timedelta(days=2)).isoformat()
        updated = await _call(
            router_module.update_scheduled_task,
            task_id=created.id,
            body=_update_body(schedule_spec={"run_at": later}),
            service=service,
        )
        assert updated.status == "enabled"
        assert updated.next_run_at is not None


class TestPauseResume:
    @pytest.mark.asyncio
    async def test_pause_then_resume(self, service, as_user):
        created = await _create(service)
        paused = await _call(router_module.pause_scheduled_task, task_id=created.id, service=service)
        assert paused.status == "paused"
        resumed = await _call(router_module.resume_scheduled_task, task_id=created.id, service=service)
        assert resumed.status == "enabled"

    @pytest.mark.asyncio
    async def test_pausing_a_running_task_is_409(self, service, tasks, as_user):
        created = await _create(service)
        stored = await tasks.get(created.id, user_id=USER)
        await tasks.save(stored.__class__(**{**stored.__dict__, "status": TaskStatus.RUNNING}))
        with pytest.raises(HTTPException) as caught:
            await _call(router_module.pause_scheduled_task, task_id=created.id, service=service)
        assert caught.value.status_code == 409

    @pytest.mark.asyncio
    async def test_pausing_an_unknown_task_is_404(self, service, as_user):
        with pytest.raises(HTTPException) as caught:
            await _call(router_module.pause_scheduled_task, task_id="task-nope", service=service)
        assert caught.value.status_code == 404


class TestTrigger:
    """Red line: this endpoint answers exactly 409 / 502 / 200, and the success
    body is `{"id": ..., "triggered": true}`."""

    @pytest.mark.asyncio
    async def test_a_launched_trigger_is_200_with_the_documented_body(self, service, as_user):
        created = await _create(service)
        response = await _call(router_module.trigger_scheduled_task, task_id=created.id, service=service)
        assert response.model_dump() == {"id": created.id, "triggered": True}

    @pytest.mark.asyncio
    async def test_a_busy_thread_is_409(self, service, launcher, as_user):
        created = await _create(service)
        launcher.fail_with = ThreadBusyError("thread already has an active run")
        with pytest.raises(HTTPException) as caught:
            await _call(router_module.trigger_scheduled_task, task_id=created.id, service=service)
        assert caught.value.status_code == 409

    @pytest.mark.asyncio
    async def test_an_active_run_for_the_same_task_is_409(self, service, runs, as_user):
        """The other route to a conflict: the task's single active slot is
        already taken, which the service reports without calling the launcher
        at all."""
        created = await _create(service)
        await runs.add(
            ScheduledRun(
                record_id="task-run-existing",
                task_id=created.id,
                thread_id="thread-x",
                scheduled_for=datetime.now(UTC),
                trigger=TriggerKind.SCHEDULED,
                status=RunStatus.RUNNING,
            )
        )
        with pytest.raises(HTTPException) as caught:
            await _call(router_module.trigger_scheduled_task, task_id=created.id, service=service)
        assert caught.value.status_code == 409

    @pytest.mark.asyncio
    async def test_a_launch_failure_is_502(self, service, launcher, as_user):
        """502, not 500: the failure is downstream of this API and the task
        itself is intact."""
        created = await _create(service)
        launcher.fail_with = LaunchFailedError("run backend unavailable")
        with pytest.raises(HTTPException) as caught:
            await _call(router_module.trigger_scheduled_task, task_id=created.id, service=service)
        assert caught.value.status_code == 502

    @pytest.mark.asyncio
    async def test_triggering_an_unknown_task_is_404(self, service, as_user):
        with pytest.raises(HTTPException) as caught:
            await _call(router_module.trigger_scheduled_task, task_id="task-nope", service=service)
        assert caught.value.status_code == 404

    @pytest.mark.asyncio
    async def test_a_paused_task_can_still_be_triggered(self, service, as_user):
        """Manual dispatch is deliberately allowed while paused, and leaves the
        task paused."""
        created = await _create(service)
        await _call(router_module.pause_scheduled_task, task_id=created.id, service=service)
        response = await _call(router_module.trigger_scheduled_task, task_id=created.id, service=service)
        assert response.triggered is True
        after = await _call(router_module.get_scheduled_task, task_id=created.id, service=service)
        assert after.status == "paused"


class TestDelete:
    @pytest.mark.asyncio
    async def test_a_task_is_deleted(self, service, as_user):
        created = await _create(service)
        response = await _call(router_module.delete_scheduled_task, task_id=created.id, service=service)
        assert response.model_dump() == {"id": created.id, "deleted": True}

    @pytest.mark.asyncio
    async def test_deleting_an_unknown_task_is_404(self, service, as_user):
        with pytest.raises(HTTPException) as caught:
            await _call(router_module.delete_scheduled_task, task_id="task-nope", service=service)
        assert caught.value.status_code == 404

    @pytest.mark.asyncio
    async def test_deleting_another_users_task_is_404(self, service, as_user):
        created = await _create(service)
        as_user(OTHER_USER)
        with pytest.raises(HTTPException) as caught:
            await _call(router_module.delete_scheduled_task, task_id=created.id, service=service)
        assert caught.value.status_code == 404


class TestRunHistory:
    @pytest.mark.asyncio
    async def test_runs_are_listed_for_an_owned_task(self, service, as_user):
        created = await _create(service)
        await _call(router_module.trigger_scheduled_task, task_id=created.id, service=service)
        listed = await _call(router_module.list_scheduled_task_runs, task_id=created.id, service=service)
        assert len(listed) == 1
        assert listed[0].task_id == created.id
        assert listed[0].trigger == "manual"

    @pytest.mark.asyncio
    async def test_history_of_an_unknown_task_is_404(self, service, as_user):
        with pytest.raises(HTTPException) as caught:
            await _call(router_module.list_scheduled_task_runs, task_id="task-nope", service=service)
        assert caught.value.status_code == 404

    @pytest.mark.asyncio
    async def test_history_of_another_users_task_is_404(self, service, as_user):
        """Ownership is checked on the parent task, so run history cannot be
        read sideways."""
        created = await _create(service)
        as_user(OTHER_USER)
        with pytest.raises(HTTPException) as caught:
            await _call(router_module.list_scheduled_task_runs, task_id=created.id, service=service)
        assert caught.value.status_code == 404


class TestErrorMapping:
    def test_every_mapped_error_is_a_schedule_error(self):
        from deerflow.domain.schedule.exceptions import ScheduleError

        assert all(issubclass(error, ScheduleError) for error in router_module._STATUS_BY_ERROR)

    @pytest.mark.asyncio
    async def test_an_unclassified_domain_error_is_not_swallowed(self):
        """A new domain error is a new protocol decision. Letting it through
        surfaces as a 500 that has to be classified, rather than shipping as
        whatever 4xx happened to be nearest."""
        from deerflow.domain.schedule.exceptions import ScheduleError

        class NewDomainError(ScheduleError):
            pass

        @router_module._map_domain_errors
        async def handler():
            raise NewDomainError("something new")

        with pytest.raises(NewDomainError):
            await handler()

    @pytest.mark.asyncio
    async def test_a_mapped_error_keeps_its_message_as_the_detail(self):
        from deerflow.domain.schedule.exceptions import TaskNotFoundError

        @router_module._map_domain_errors
        async def handler():
            raise TaskNotFoundError("Scheduled task not found")

        with pytest.raises(HTTPException) as caught:
            await handler()
        assert caught.value.detail == "Scheduled task not found"
