"""Domain tests for the schedule bounded context.

Deliberately synchronous and dependency-free: no pytest-asyncio, no fakes, no
IO. Everything under `deerflow.domain.schedule.model` is pure, and this file is
the proof — if a rule here ever needs a stub, the rule has leaked out of the
inner ring.

The three `status_after_*` truth tables (TestStatusAfter*) are the reason this
commit exists: those rules used to be static methods on
`app/scheduler/service.py` with no direct coverage at all, reachable only
through the service's integration tests.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from deerflow.domain.schedule.exceptions import InvalidContextModeError, InvalidScheduleError, TaskNotMutableError
from deerflow.domain.schedule.model import (
    ContextMode,
    RunStatus,
    ScheduledRun,
    ScheduledTask,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleType,
    TaskStatus,
    TriggerKind,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
NO_DELAY = SchedulePolicy(min_once_delay_seconds=0)
MIN_60 = SchedulePolicy(min_once_delay_seconds=60)


def cron_spec(expr: str = "0 9 * * *", timezone: str = "UTC") -> ScheduleSpec:
    return ScheduleSpec.cron_schedule(expr, timezone)


def once_spec(*, after_seconds: int = 3600, timezone: str = "UTC") -> ScheduleSpec:
    return ScheduleSpec.once_at(NOW + timedelta(seconds=after_seconds), timezone)


def make_task(
    *,
    schedule: ScheduleSpec | None = None,
    status: TaskStatus = TaskStatus.ENABLED,
    context_mode: ContextMode = ContextMode.FRESH_THREAD_PER_RUN,
    thread_id: str | None = None,
) -> ScheduledTask:
    return ScheduledTask(
        task_id="task-1",
        user_id="user-1",
        title="Daily summary",
        prompt="Summarize",
        schedule=schedule if schedule is not None else cron_spec(),
        status=status,
        context_mode=context_mode,
        thread_id=thread_id,
    )


# ---------------------------------------------------------------- A. ScheduleSpec invariants


class TestScheduleSpecInvariants:
    def test_unknown_timezone_is_rejected(self):
        with pytest.raises(InvalidScheduleError, match="Unknown timezone"):
            ScheduleSpec.cron_schedule("0 9 * * *", "Mars/Olympus_Mons")

    def test_cron_without_expression_is_rejected(self):
        with pytest.raises(InvalidScheduleError, match="requires schedule_spec"):
            ScheduleSpec(ScheduleType.CRON, "UTC")

    @pytest.mark.parametrize("expr", ["0 9 * *", "0 9 * * * *", "0"])
    def test_cron_must_have_exactly_five_fields(self, expr):
        with pytest.raises(InvalidScheduleError, match="exactly 5 fields"):
            ScheduleSpec.cron_schedule(expr, "UTC")

    def test_once_without_run_at_is_rejected(self):
        with pytest.raises(InvalidScheduleError, match="requires run_at"):
            ScheduleSpec(ScheduleType.ONCE, "UTC")

    def test_direct_construction_cannot_bypass_validation(self):
        """A frozen dataclass is still constructible field-by-field, so the
        rules have to live in __post_init__ rather than in the factories."""
        with pytest.raises(InvalidScheduleError, match="exactly 5 fields"):
            ScheduleSpec(ScheduleType.CRON, "UTC", cron="not-a-cron")

    def test_cron_whitespace_is_normalized_on_construction(self):
        assert ScheduleSpec(ScheduleType.CRON, "UTC", cron="  0   9  *  *  * ").cron == "0 9 * * *"

    def test_naive_run_at_is_localized_to_the_schedule_timezone(self):
        spec = ScheduleSpec.once_at(datetime(2026, 8, 1, 9, 0), "Asia/Shanghai")  # noqa: DTZ001 -- naive input is the subject
        assert spec.run_at.utcoffset() == timedelta(hours=8)
        assert spec.run_at.astimezone(UTC) == datetime(2026, 8, 1, 1, 0, tzinfo=UTC)

    def test_aware_run_at_is_left_alone(self):
        """Covers the shape the frontend submits (`zonedLocalToUtcIso`, trailing
        Z): already aware, so localization must leave it alone rather than
        reinterpreting it in the task's timezone. Parsing that spelling is
        `from_primitives`' job and is tested there."""
        run_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
        assert ScheduleSpec.once_at(run_at, "Asia/Shanghai").run_at == run_at


# ---------------------------------------------------------------- A2. from_primitives


class TestFromPrimitives:
    """The one construction path that starts from untrusted strings.

    Both boundaries -- the HTTP body and the stored JSON column -- arrive as a
    schedule type plus a loose mapping, so the rule for turning that into a
    value object lives here rather than being written out once per adapter.
    Each adapter is left with the part that is genuinely its own: which keys
    its format uses.

    Values are type-checked rather than assumed. The signature says `str |
    None` because that is the contract, but both callers read from data a
    client can influence, so a non-string has to be rejected here rather than
    reaching `datetime.fromisoformat` or the cron parser.
    """

    def test_builds_a_cron_schedule(self):
        spec = ScheduleSpec.from_primitives("cron", cron="0 9 * * *", run_at=None, timezone="Asia/Shanghai")
        assert spec.schedule_type is ScheduleType.CRON
        assert spec.cron == "0 9 * * *"
        assert spec.timezone == "Asia/Shanghai"

    def test_builds_a_once_schedule_from_an_iso_string(self):
        spec = ScheduleSpec.from_primitives("once", cron=None, run_at="2026-08-01T09:00:00", timezone="Asia/Shanghai")
        assert spec.schedule_type is ScheduleType.ONCE
        assert spec.run_at == datetime(2026, 8, 1, 1, 0, tzinfo=UTC)

    def test_a_trailing_z_run_at_is_the_same_instant(self):
        """The shape the frontend submits (`zonedLocalToUtcIso`)."""
        spec = ScheduleSpec.from_primitives("once", cron=None, run_at="2026-08-01T01:00:00Z", timezone="Asia/Shanghai")
        assert spec.run_at == datetime(2026, 8, 1, 1, 0, tzinfo=UTC)

    def test_unknown_schedule_type_is_rejected(self):
        with pytest.raises(InvalidScheduleError, match="Unsupported schedule_type"):
            ScheduleSpec.from_primitives("teleport", cron="0 9 * * *", run_at=None, timezone="UTC")

    @pytest.mark.parametrize("cron", [None, 5, ""])
    def test_cron_without_a_usable_expression_is_rejected(self, cron):
        with pytest.raises(InvalidScheduleError, match="requires schedule_spec"):
            ScheduleSpec.from_primitives("cron", cron=cron, run_at=None, timezone="UTC")

    @pytest.mark.parametrize("run_at", [None, 5])
    def test_once_without_a_string_run_at_is_rejected(self, run_at):
        with pytest.raises(InvalidScheduleError, match="requires run_at"):
            ScheduleSpec.from_primitives("once", cron=None, run_at=run_at, timezone="UTC")

    def test_an_unparseable_run_at_is_rejected(self):
        with pytest.raises(InvalidScheduleError, match="unparseable run_at"):
            ScheduleSpec.from_primitives("once", cron=None, run_at="next tuesday", timezone="UTC")

    def test_the_irrelevant_field_is_ignored(self):
        """A boundary that carries both keys must not be rejected for it."""
        spec = ScheduleSpec.from_primitives("cron", cron="0 9 * * *", run_at="2026-08-01T09:00:00", timezone="UTC")
        assert spec.run_at is None

    def test_value_rules_still_come_from_post_init(self):
        """Not re-implemented here -- this is why each adapter stays thin."""
        with pytest.raises(InvalidScheduleError, match="exactly 5 fields"):
            ScheduleSpec.from_primitives("cron", cron="0 9 * *", run_at=None, timezone="UTC")
        with pytest.raises(InvalidScheduleError, match="Unknown timezone"):
            ScheduleSpec.from_primitives("cron", cron="0 9 * * *", run_at=None, timezone="Mars/Olympus_Mons")

    def test_whitespace_in_a_cron_expression_is_normalized(self):
        spec = ScheduleSpec.from_primitives("cron", cron="  0  9 * * * ", run_at=None, timezone="UTC")
        assert spec.cron == "0 9 * * *"


# ---------------------------------------------------------------- B. next_after


class TestNextAfter:
    def test_once_in_the_future_returns_run_at(self):
        spec = once_spec(after_seconds=3600)
        assert spec.next_after(NOW) == NOW + timedelta(seconds=3600)

    def test_once_in_the_past_returns_none(self):
        spec = ScheduleSpec.once_at(NOW - timedelta(seconds=1), "UTC")
        assert spec.next_after(NOW) is None

    def test_once_exactly_now_returns_none(self):
        """`run_at > now`, not `>=` (schedules.py:44)."""
        assert ScheduleSpec.once_at(NOW, "UTC").next_after(NOW) is None

    def test_cron_returns_the_next_occurrence_in_utc(self):
        # 09:00 UTC daily; NOW is 12:00 UTC, so the next one is tomorrow.
        assert cron_spec("0 9 * * *", "UTC").next_after(NOW) == datetime(2026, 7, 28, 9, 0, tzinfo=UTC)

    def test_cron_is_evaluated_in_the_schedule_timezone(self):
        # 09:00 Shanghai == 01:00 UTC. NOW (12:00 UTC) is past today's, so the
        # answer is tomorrow 01:00 UTC -- not 09:00 UTC.
        assert cron_spec("0 9 * * *", "Asia/Shanghai").next_after(NOW) == datetime(2026, 7, 28, 1, 0, tzinfo=UTC)

    def test_cron_absorbs_a_dst_transition(self):
        """US DST starts 2026-03-08, so the same wall-clock cron maps to a
        different UTC instant on either side of it. This is what evaluating in
        the schedule's timezone buys."""
        spec = cron_spec("0 9 * * *", "America/New_York")
        before = spec.next_after(datetime(2026, 3, 7, 0, 0, tzinfo=UTC))
        after = spec.next_after(datetime(2026, 3, 9, 0, 0, tzinfo=UTC))
        assert before == datetime(2026, 3, 7, 14, 0, tzinfo=UTC)  # EST, UTC-5
        assert after == datetime(2026, 3, 9, 13, 0, tzinfo=UTC)  # EDT, UTC-4

    def test_naive_now_is_read_as_utc(self):
        spec = cron_spec("0 9 * * *", "UTC")
        assert spec.next_after(NOW.replace(tzinfo=None)) == spec.next_after(NOW)


# ---------------------------------------------------------------- C. ensure_launchable


class TestEnsureLaunchable:
    def test_once_in_the_past_is_rejected(self):
        spec = ScheduleSpec.once_at(NOW - timedelta(hours=1), "UTC")
        with pytest.raises(InvalidScheduleError, match="must be in the future"):
            spec.ensure_launchable(NOW, NO_DELAY)

    def test_once_closer_than_the_minimum_delay_is_rejected(self):
        with pytest.raises(InvalidScheduleError, match="at least 60 seconds"):
            once_spec(after_seconds=59).ensure_launchable(NOW, MIN_60)

    def test_once_exactly_at_the_minimum_delay_is_accepted(self):
        assert once_spec(after_seconds=60).ensure_launchable(NOW, MIN_60) == NOW + timedelta(seconds=60)

    def test_cron_is_never_subject_to_the_delay_floor(self):
        """router:105 / router:196 apply the floor only to `once`; a cron
        schedule whose next fire is seconds away is perfectly legal."""
        spec = cron_spec("* * * * *", "UTC")
        assert spec.ensure_launchable(NOW, MIN_60) is not None

    def test_naive_now_is_read_as_utc(self):
        """Same tolerance as next_after: a caller handing over a naive clock
        reading must not silently shift the delay floor by the local offset."""
        spec = once_spec(after_seconds=3600)
        assert spec.ensure_launchable(NOW.replace(tzinfo=None), MIN_60) == spec.ensure_launchable(NOW, MIN_60)


class TestSchedulePolicyDefaults:
    """ "Nobody configured a policy" must not invent a business constraint.

    Real values only ever arrive from the composition root (spec.py:22-25). The
    defaults being the permissive ones is what keeps an unconfigured deployment
    from silently rejecting schedules a configured one would accept -- so they
    are pinned here rather than left to whatever the dataclass happens to say.
    """

    def test_defaults_are_permissive(self):
        policy = SchedulePolicy()
        assert policy.min_once_delay_seconds == 0
        assert policy.max_concurrent_runs == 1
        assert policy.lease_seconds == 60

    def test_the_default_delay_floor_admits_an_imminent_once_schedule(self):
        """The consequence of the constant above, stated as behaviour: with no
        configured policy a one-second-away one-shot is legal."""
        assert once_spec(after_seconds=1).ensure_launchable(NOW, SchedulePolicy()) == NOW + timedelta(seconds=1)


# ---------------------------------------------------------------- D. value semantics


class TestScheduleSpecEquality:
    """A value object is its values -- two specs built from equivalent inputs
    must compare equal, because the repository relies on that to decide whether
    a schedule actually changed.

    Serialization shape (the JSON written to `scheduled_tasks.schedule_spec`)
    is deliberately NOT tested here: that mapping lives in the adapter layer,
    and so do its tests.
    """

    def test_equivalent_cron_inputs_converge(self):
        assert ScheduleSpec.cron_schedule("  0  9 * * * ", "UTC") == ScheduleSpec.cron_schedule("0 9 * * *", "UTC")

    def test_equivalent_once_inputs_converge(self):
        naive = ScheduleSpec.once_at(datetime(2026, 8, 1, 9, 0), "Asia/Shanghai")  # noqa: DTZ001 -- naive input is the subject
        aware = ScheduleSpec.once_at(datetime.fromisoformat("2026-08-01T01:00:00Z"), "Asia/Shanghai")
        assert naive == aware

    def test_timezone_is_part_of_identity(self):
        at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
        assert ScheduleSpec.once_at(at, "UTC") != ScheduleSpec.once_at(at, "Asia/Shanghai")


# ---------------------------------------------------------------- E. ScheduledTask invariants


class TestScheduledTaskInvariants:
    def test_reuse_thread_requires_a_thread(self):
        with pytest.raises(InvalidContextModeError, match="reuse_thread requires thread_id"):
            make_task(context_mode=ContextMode.REUSE_THREAD, thread_id=None)

    def test_unknown_context_mode_is_a_domain_error(self):
        """Not a bare ValueError -- the router maps the ScheduleError family
        uniformly (router:76-77 was a 422)."""
        with pytest.raises(InvalidContextModeError, match="Unsupported context_mode"):
            ScheduledTask.create(
                user_id="user-1",
                title="t",
                prompt="p",
                schedule=cron_spec(),
                context_mode="teleport",
                thread_id=None,
                now=NOW,
                policy=NO_DELAY,
            )

    def test_create_drops_thread_id_for_fresh_thread_mode(self):
        task = ScheduledTask.create(
            user_id="user-1",
            title="t",
            prompt="p",
            schedule=cron_spec(),
            context_mode=ContextMode.FRESH_THREAD_PER_RUN,
            thread_id="thread-9",
            now=NOW,
            policy=NO_DELAY,
        )
        assert task.thread_id is None

    def test_create_computes_next_run_at_and_defaults(self):
        task = ScheduledTask.create(
            user_id="user-1",
            title="t",
            prompt="p",
            schedule=cron_spec("0 9 * * *", "UTC"),
            context_mode=ContextMode.FRESH_THREAD_PER_RUN,
            thread_id=None,
            now=NOW,
            policy=NO_DELAY,
        )
        assert task.task_id.startswith("task-")
        assert task.status is TaskStatus.ENABLED
        assert task.run_count == 0
        assert task.assistant_id == "lead_agent"
        assert task.next_run_at == datetime(2026, 7, 28, 9, 0, tzinfo=UTC)

    def test_create_stamps_the_bookkeeping_timestamps_from_now(self):
        """The factory already receives the clock as a rule input; reading it
        a second time through the field defaults would give the aggregate two
        slightly different construction instants -- and the stored row a third
        if the adapter minted its own. One explicit `now`, one truth."""
        task = ScheduledTask.create(
            user_id="user-1",
            title="t",
            prompt="p",
            schedule=cron_spec("0 9 * * *", "UTC"),
            context_mode=ContextMode.FRESH_THREAD_PER_RUN,
            thread_id=None,
            now=NOW,
            policy=NO_DELAY,
        )
        assert task.created_at == NOW
        assert task.updated_at == NOW

    def test_create_rejects_a_once_schedule_inside_the_delay_floor(self):
        with pytest.raises(InvalidScheduleError, match="at least 60 seconds"):
            ScheduledTask.create(
                user_id="user-1",
                title="t",
                prompt="p",
                schedule=once_spec(after_seconds=10),
                context_mode=ContextMode.FRESH_THREAD_PER_RUN,
                thread_id=None,
                now=NOW,
                policy=MIN_60,
            )

    def test_skips_on_overlap_reflects_the_policy(self):
        assert make_task().skips_on_overlap is True


# ---------------------------------------------------------------- F. the three truth tables


class TestStatusAfterLaunch:
    @pytest.mark.parametrize(
        ("schedule", "trigger", "status", "expected"),
        [
            (once_spec(), TriggerKind.SCHEDULED, TaskStatus.RUNNING, TaskStatus.RUNNING),
            (once_spec(), TriggerKind.MANUAL, TaskStatus.ENABLED, TaskStatus.RUNNING),
            (cron_spec(), TriggerKind.MANUAL, TaskStatus.PAUSED, TaskStatus.PAUSED),
            (cron_spec(), TriggerKind.MANUAL, TaskStatus.ENABLED, TaskStatus.ENABLED),
            (cron_spec(), TriggerKind.SCHEDULED, TaskStatus.RUNNING, TaskStatus.ENABLED),
        ],
    )
    def test_truth_table(self, schedule, trigger, status, expected):
        assert make_task(schedule=schedule, status=status).status_after_launch(trigger=trigger) is expected

    def test_manual_trigger_of_paused_once_task_yields_running(self):
        """Decision-order trap: ONCE is tested before the MANUAL+PAUSED rule,
        so the paused branch never sees a once task."""
        task = make_task(schedule=once_spec(), status=TaskStatus.PAUSED)
        assert task.status_after_launch(trigger=TriggerKind.MANUAL) is TaskStatus.RUNNING


class TestStatusAfterFailure:
    @pytest.mark.parametrize(
        ("schedule", "trigger", "status", "expected"),
        [
            (once_spec(), TriggerKind.SCHEDULED, TaskStatus.RUNNING, TaskStatus.FAILED),
            (cron_spec(), TriggerKind.SCHEDULED, TaskStatus.RUNNING, TaskStatus.ENABLED),
            (cron_spec(), TriggerKind.MANUAL, TaskStatus.ENABLED, TaskStatus.ENABLED),
            (cron_spec(), TriggerKind.MANUAL, TaskStatus.PAUSED, TaskStatus.PAUSED),
        ],
    )
    def test_truth_table(self, schedule, trigger, status, expected):
        assert make_task(schedule=schedule, status=status).status_after_failure(trigger=trigger) is expected

    @pytest.mark.parametrize("status", [TaskStatus.ENABLED, TaskStatus.PAUSED])
    def test_failed_manual_trigger_of_once_task_keeps_status(self, status):
        """Decision-order trap: MANUAL is tested before ONCE, so a failed
        manual trigger cannot burn the task's single scheduled occurrence."""
        task = make_task(schedule=once_spec(), status=status)
        assert task.status_after_failure(trigger=TriggerKind.MANUAL) is status


class TestStatusAfterSkip:
    def test_once_is_failed_not_completed(self):
        assert make_task(schedule=once_spec()).status_after_skip() is TaskStatus.FAILED

    def test_cron_stays_enabled(self):
        assert make_task(schedule=cron_spec()).status_after_skip() is TaskStatus.ENABLED


class TestStatusAfterCompletion:
    @pytest.mark.parametrize("outcome", list(RunStatus))
    def test_cron_never_changes_status(self, outcome):
        assert make_task(schedule=cron_spec()).status_after_completion(outcome) is None

    @pytest.mark.parametrize(
        ("outcome", "expected"),
        [
            (RunStatus.SUCCESS, TaskStatus.COMPLETED),
            # INTERRUPTED is CANCELLED rather than FAILED: a user cancel or a
            # same-thread takeover carries no execution failure.
            (RunStatus.INTERRUPTED, TaskStatus.CANCELLED),
            (RunStatus.FAILED, TaskStatus.FAILED),
        ],
    )
    def test_once_maps_each_terminal_outcome(self, outcome, expected):
        assert make_task(schedule=once_spec()).status_after_completion(outcome) is expected


# ---------------------------------------------------------------- G. mutability gate


class TestMutabilityGate:
    def test_ensure_mutable_rejects_a_running_task(self):
        with pytest.raises(TaskNotMutableError, match="currently running"):
            make_task(status=TaskStatus.RUNNING).ensure_mutable()

    @pytest.mark.parametrize("status", [s for s in TaskStatus if s is not TaskStatus.RUNNING])
    def test_ensure_mutable_allows_every_other_status(self, status):
        make_task(status=status).ensure_mutable()

    def test_pause_and_resume_are_gated(self):
        running = make_task(status=TaskStatus.RUNNING)
        with pytest.raises(TaskNotMutableError):
            running.paused()
        with pytest.raises(TaskNotMutableError):
            running.resumed()

    def test_pause_then_resume_round_trips(self):
        task = make_task(status=TaskStatus.ENABLED)
        assert task.paused().status is TaskStatus.PAUSED
        assert task.paused().resumed().status is TaskStatus.ENABLED

    def test_transitions_do_not_mutate_the_original(self):
        task = make_task(status=TaskStatus.ENABLED)
        task.paused()
        assert task.status is TaskStatus.ENABLED

    def test_transitions_leave_updated_at_to_the_repository(self):
        """The repository stamps `updated_at` on write (task.py:54-57). A second
        clock read here would make the domain impure and a competing source of
        truth for the same column."""
        task = make_task(status=TaskStatus.ENABLED)
        assert task.paused().updated_at == task.updated_at
        assert task.paused().resumed().updated_at == task.updated_at
        assert task.with_schedule(cron_spec("0 10 * * *"), now=NOW, policy=NO_DELAY).updated_at == task.updated_at
        assert task.with_context(ContextMode.FRESH_THREAD_PER_RUN, None).updated_at == task.updated_at


# ---------------------------------------------------------------- H. with_schedule


class TestWithSchedule:
    @pytest.mark.parametrize("status", [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED])
    def test_terminal_task_is_rearmed_by_a_future_schedule(self, status):
        """claim_due only admits ENABLED rows, so leaving the terminal status
        would return a next_run_at that silently never fires (router:203-208)."""
        task = make_task(schedule=once_spec(), status=status)
        updated = task.with_schedule(once_spec(after_seconds=7200), now=NOW, policy=NO_DELAY)
        assert updated.status is TaskStatus.ENABLED
        assert updated.next_run_at == NOW + timedelta(seconds=7200)

    @pytest.mark.parametrize("status", [TaskStatus.ENABLED, TaskStatus.PAUSED])
    def test_non_terminal_status_is_preserved(self, status):
        updated = make_task(status=status).with_schedule(cron_spec("0 10 * * *"), now=NOW, policy=NO_DELAY)
        assert updated.status is status

    def test_running_task_cannot_be_rescheduled(self):
        task = make_task(status=TaskStatus.RUNNING)
        with pytest.raises(TaskNotMutableError):
            task.with_schedule(cron_spec("0 10 * * *"), now=NOW, policy=NO_DELAY)

    def test_invalid_once_schedule_propagates(self):
        task = make_task(schedule=once_spec(), status=TaskStatus.COMPLETED)
        with pytest.raises(InvalidScheduleError, match="must be in the future"):
            task.with_schedule(ScheduleSpec.once_at(NOW - timedelta(hours=1), "UTC"), now=NOW, policy=NO_DELAY)


# ---------------------------------------------------------------- I. with_context


class TestWithContext:
    def test_switching_to_fresh_thread_clears_the_thread(self):
        task = make_task(context_mode=ContextMode.REUSE_THREAD, thread_id="thread-1")
        updated = task.with_context(ContextMode.FRESH_THREAD_PER_RUN, "thread-1")
        assert updated.context_mode is ContextMode.FRESH_THREAD_PER_RUN
        assert updated.thread_id is None

    def test_switching_to_reuse_thread_without_a_thread_is_rejected(self):
        with pytest.raises(InvalidContextModeError, match="reuse_thread requires thread_id"):
            make_task().with_context(ContextMode.REUSE_THREAD, None)

    def test_switching_to_reuse_thread_keeps_the_thread(self):
        updated = make_task().with_context("reuse_thread", "thread-7")
        assert updated.context_mode is ContextMode.REUSE_THREAD
        assert updated.thread_id == "thread-7"

    def test_running_task_cannot_change_context(self):
        with pytest.raises(TaskNotMutableError):
            make_task(status=TaskStatus.RUNNING).with_context(ContextMode.FRESH_THREAD_PER_RUN, None)


# ---------------------------------------------------------------- J. execution thread


class TestResolveExecutionThread:
    def test_fresh_thread_mode_mints_a_new_thread_every_call(self):
        """Non-idempotent by design -- a dispatch must call this once and reuse
        the value for the run row, the launch, and the result."""
        task = make_task(context_mode=ContextMode.FRESH_THREAD_PER_RUN)
        assert task.resolve_execution_thread() != task.resolve_execution_thread()

    def test_reuse_thread_mode_returns_the_bound_thread(self):
        task = make_task(context_mode=ContextMode.REUSE_THREAD, thread_id="thread-1")
        assert task.resolve_execution_thread() == "thread-1"
        assert task.resolve_execution_thread() == "thread-1"

    def test_reuse_thread_with_an_empty_thread_falls_back_to_a_fresh_one(self):
        """Unreachable for new aggregates (__post_init__ forbids it) but rows
        predating that invariant can still carry this shape.

        Asserting against the fresh-thread semantics rather than against `None`:
        the fallback has to mint a real, distinct thread per call, which is what
        the fresh-thread branch means.
        """
        legacy = ScheduledTask.__new__(ScheduledTask)
        object.__setattr__(legacy, "context_mode", ContextMode.REUSE_THREAD)
        object.__setattr__(legacy, "thread_id", None)

        first = ScheduledTask.resolve_execution_thread(legacy)
        second = ScheduledTask.resolve_execution_thread(legacy)
        assert uuid.UUID(first), "a real thread id, not a placeholder"
        assert first != second, "a fresh thread per call, like FRESH_THREAD_PER_RUN"


# ---------------------------------------------------------------- K. ScheduledRun


class TestScheduledRun:
    def test_queued_run_occupies_the_active_slot(self):
        run = ScheduledRun.queued(task_id="task-1", thread_id="thread-1", scheduled_for=NOW, trigger=TriggerKind.SCHEDULED)
        assert run.status is RunStatus.QUEUED
        assert run.is_active is True
        assert run.record_id.startswith("task-run-")

    def test_skipped_tombstone_is_terminal_and_never_queued(self):
        """QUEUED falls inside uq_scheduled_task_run_active's predicate and
        would collide with the pre-existing run still holding the slot."""
        run = ScheduledRun.skipped_tombstone(task_id="task-1", thread_id="thread-1", scheduled_for=NOW, trigger=TriggerKind.SCHEDULED)
        assert run.status is RunStatus.SKIPPED
        assert run.is_active is False

    def test_each_run_gets_a_distinct_identity(self):
        first = ScheduledRun.queued(task_id="task-1", thread_id="t", scheduled_for=NOW, trigger=TriggerKind.MANUAL)
        second = ScheduledRun.queued(task_id="task-1", thread_id="t", scheduled_for=NOW, trigger=TriggerKind.MANUAL)
        assert first.record_id != second.record_id

    @pytest.mark.parametrize(
        ("status", "active"),
        [
            (RunStatus.QUEUED, True),
            (RunStatus.RUNNING, True),
            (RunStatus.SUCCESS, False),
            (RunStatus.FAILED, False),
            (RunStatus.SKIPPED, False),
            (RunStatus.INTERRUPTED, False),
        ],
    )
    def test_only_queued_and_running_occupy_the_active_slot(self, status, active):
        """Stated as behaviour over every status rather than as an equality
        against ACTIVE_RUN_STATUSES -- restating the constant proves nothing,
        since editing it would edit the assertion with it. The other half of
        this rule, that the set matches the partial unique index's predicate,
        cannot be checked from a dependency-free domain test and lives in
        test_scheduled_task_models.py.
        """
        run = replace(
            ScheduledRun.queued(task_id="task-1", thread_id="thread-1", scheduled_for=NOW, trigger=TriggerKind.SCHEDULED),
            status=status,
        )
        assert run.is_active is active
