"""Tests for the composition root.

The point of extracting `build_domain_services` from the lifespan is that the
rules below become assertions. Before, "a memory backend means no service,
and the routes answer 503" was a comment inside a 180-line startup function
that no test could reach without booting the whole application.
"""

from __future__ import annotations

import pytest

from app.composition import DomainServices, build_domain_services, build_run_completion_hook, build_schedule_policy
from deerflow.config.scheduler_config import SchedulerConfig
from deerflow.domain.schedule.model import SchedulePolicy


class _StubRunStore:
    async def get(self, run_id: str):
        return None


class _StubThreadStore:
    async def check_access(self, thread_id: str, user_id: str, *, require_existing: bool = False) -> bool:
        return True


async def _launch_run(**kwargs):
    return {"run_id": "run-1", "thread_id": kwargs.get("thread_id", "thread-1")}


def _build(session_factory, scheduler_config=None) -> DomainServices:
    return build_domain_services(
        session_factory=session_factory,
        run_store=_StubRunStore(),
        thread_store=_StubThreadStore(),
        launch_run=_launch_run,
        scheduler_config=scheduler_config or SchedulerConfig(),
    )


class TestMemoryBackend:
    """`session_factory is None` is how `database.backend: memory` presents."""

    def test_no_session_factory_yields_no_services(self):
        services = _build(None)
        assert services.feedback is None
        assert services.schedule is None

    def test_it_does_not_degrade_to_an_in_memory_implementation(self):
        """Refusing is the intended behaviour: a scheduled task that silently
        vanishes on restart is worse than one the API declines to accept."""
        assert _build(None).schedule is None


class TestSqlBackend:
    def test_a_session_factory_yields_both_services(self):
        """A fake sessionmaker is enough -- wiring must not touch the database,
        which is what makes this assertable without a live engine."""
        services = _build(object())
        assert services.feedback is not None
        assert services.schedule is not None

    def test_the_two_contexts_are_wired_independently(self):
        services = _build(object())
        assert services.feedback is not services.schedule


class TestSchedulePolicy:
    def test_every_threshold_comes_from_the_operator_config(self):
        policy = build_schedule_policy(
            SchedulerConfig(
                min_once_delay_seconds=30,
                max_concurrent_runs=7,
                lease_seconds=90,
            )
        )
        assert policy == SchedulePolicy(
            min_once_delay_seconds=30,
            max_concurrent_runs=7,
            lease_seconds=90,
        )

    def test_the_domain_defaults_are_not_what_production_gets(self):
        """The domain's defaults are permissive so that "nobody configured a
        policy" invents no business constraint. Production must not inherit
        them by accident -- the config's own defaults are the real values."""
        from_config = build_schedule_policy(SchedulerConfig())
        assert from_config != SchedulePolicy()
        assert from_config.min_once_delay_seconds == SchedulerConfig().min_once_delay_seconds

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("min_once_delay_seconds", 45),
            ("max_concurrent_runs", 5),
            ("lease_seconds", 300),
        ],
    )
    def test_each_field_is_mapped_from_its_own_config_key(self, field, value):
        """Guards against two thresholds being wired from one key -- a
        transposition the type checker cannot see, since all three are ints."""
        policy = build_schedule_policy(SchedulerConfig(**{field: value}))
        assert getattr(policy, field) == value

    def test_poll_interval_is_not_part_of_the_policy(self):
        """How often to look is the poller's business, not a rule any task is
        subject to."""
        assert not hasattr(SchedulePolicy(), "poll_interval_seconds")


class TestEveryPortGetsTheRightAdapter:
    """Deliberately white-box: verifying which adapter landed in which slot is
    the entire job of a composition root, and all four are keyword arguments
    of compatible shape, so a transposition type-checks cleanly and would only
    surface as a production error.
    """

    def test_each_schedule_port_is_filled_with_its_own_adapter(self):
        from app.adapters.schedule.run_launcher import GatewayRunLauncher
        from app.adapters.schedule.scheduled_run_repository import SqlScheduledRunRepository
        from app.adapters.schedule.scheduled_task_repository import SqlScheduledTaskRepository
        from app.adapters.schedule.thread_lookup import ThreadStoreThreadLookup

        service = _build(object()).schedule
        assert isinstance(service._tasks, SqlScheduledTaskRepository)
        assert isinstance(service._runs, SqlScheduledRunRepository)
        assert isinstance(service._launcher, GatewayRunLauncher)
        assert isinstance(service._threads, ThreadStoreThreadLookup)

    def test_each_feedback_port_is_filled_with_its_own_adapter(self):
        from app.adapters.feedback.feedback_repository import SqlFeedbackRepository
        from app.adapters.feedback.run_lookup import RunStoreRunLookup

        service = _build(object()).feedback
        assert isinstance(service._repository, SqlFeedbackRepository)
        assert isinstance(service._runs, RunStoreRunLookup)

    def test_the_policy_reaches_the_service(self):
        service = _build(object(), SchedulerConfig(max_concurrent_runs=9)).schedule
        assert service._policy.max_concurrent_runs == 9


class TestRunCompletionHook:
    """The inbound half of the wiring.

    What the hook *does* with a run is asserted in
    `test_schedule_run_completion.py`; all that is left here is the assembly
    decision, which is this module's whole job.
    """

    def test_no_service_installs_no_hook(self):
        """`None` rather than a hook that always declines: with no service
        there is nothing for the runtime to call, and saying so lets it skip
        the callback entirely."""
        assert build_run_completion_hook(None) is None

    def test_a_service_is_wrapped_in_the_inbound_adapter(self):
        from app.adapters.schedule.run_completion import ScheduleRunCompletionListener

        hook = build_run_completion_hook(_build(object()).schedule)
        assert isinstance(hook, ScheduleRunCompletionListener)

    def test_the_hook_is_bound_to_the_service_it_was_given(self):
        """Deliberately white-box, for the same reason as the port assertions
        above: a hook wired to the wrong service type-checks cleanly."""
        service = _build(object()).schedule
        assert build_run_completion_hook(service)._service is service
