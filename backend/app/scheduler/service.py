from __future__ import annotations

import asyncio
import hashlib
import logging
import socket
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from app.channels.capabilities import supports_proactive_notifications
from app.scheduler.notification_text import NOTIFICATION_LOCALES
from deerflow.persistence.channel_connections.model import ChannelConnectionRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_events import ScheduledTaskEventRepository
from deerflow.persistence.scheduled_task_runs import ActiveScheduledRunConflict, ScheduledTaskAdmissionRejected
from deerflow.persistence.scheduled_task_runs.finalization import LIFECYCLE_EVENTS, RUN_EVENT_BY_STATUS, lifecycle_anchor, lifecycle_reason
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_task_runs.sql import run_number_expression
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserPreferenceRow
from deerflow.runtime import ConflictError, RunRecord
from deerflow.scheduler.host_notes import RUN_ERROR_DELETED_WHILE_QUEUED, RUN_ERROR_INTERRUPTED, RUN_ERROR_LEASE_LOST, RUN_ERROR_PAUSED_WHILE_QUEUED, RUN_ERROR_QUEUE_TIMEOUT, RUN_ERROR_RESTARTED
from deerflow.scheduler.schedules import next_run_at
from deerflow.scheduler.stop_rule import launch_prompt
from deerflow.trace_context import ensure_trace_context
from deerflow.utils.thread_id import validate_thread_id

logger = logging.getLogger(__name__)


def _zone_is_placeholder(task: dict[str, Any]) -> bool:
    """Whether the stored "UTC" only means "no zone was needed" (timezone_source not_needed).

    A chat can save an interval task, or a one-time task whose run_at carries
    an offset, without knowing the user's zone; it stores "UTC". Those times
    are shown in the viewer's zone, so a UTC wall-clock time must not appear
    in the run conversation's title.
    """
    if task.get("timezone") != "UTC":
        return False
    if task.get("schedule_type") == "interval":
        return True
    if task.get("schedule_type") == "once":
        run_at = (task.get("schedule_spec") or {}).get("run_at")
        try:
            return isinstance(run_at, str) and datetime.fromisoformat(run_at).tzinfo is not None
        except ValueError:
            return False
    return False


def _as_utc(value: datetime | str | None) -> datetime | None:
    """A stored timestamp (ISO string from the repository, or a datetime) as aware UTC."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(f"{value[:-1]}+00:00" if value.endswith("Z") else value)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _as_utc_or_none(value: object) -> datetime | None:
    """A datetime as aware UTC; anything else (or an unusable value) is None."""
    if not isinstance(value, datetime):
        return None
    try:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _chat_event_payload(task, occurrence, event: str, *, run_number: int | None) -> dict[str, Any]:
    """Display snapshot of a lifecycle event (survives task deletion and edits).

    ``run_thread_id`` is set only when the occurrence launched a run (a skipped
    occurrence's thread was never created). ``latest_reason_code`` is the
    unmet reason of that run. Never raises for bad stored values.
    """
    title = task.title.strip() if isinstance(task.title, str) else ""
    stop_condition = getattr(task, "stop_condition", None)
    end_at = _as_utc_or_none(getattr(task, "end_at", None))
    run_status = getattr(occurrence, "status", None) if occurrence is not None else None
    launched = occurrence is not None and occurrence.run_id is not None
    # The agent that ran it (edits are refused while a run is active), so the
    # run link opens on that agent's route, not the originating chat's.
    agent = getattr(task, "assistant_id", None)
    return {
        "task_title": title or None,
        "stop_condition": stop_condition if event == "task_stopped" and isinstance(stop_condition, str) and stop_condition.strip() else None,
        "run_thread_id": occurrence.thread_id if launched else None,
        "run_agent_name": agent.strip() if launched and isinstance(agent, str) and agent.strip() else None,
        "run_number": run_number,
        "run_status": run_status,
        "latest_reason_code": occurrence.error if run_status == "unmet" and isinstance(occurrence.error, str) else None,
        "max_runs": _int_or_none(getattr(task, "max_runs", None)),
        "end_at": end_at.isoformat() if end_at is not None else None,
        "schedule_type": task.schedule_type if isinstance(task.schedule_type, str) else None,
    }


def _origin_thread_share_lock(thread_id: str):
    """``SELECT ... FOR SHARE`` on the originating chat's ``threads_meta`` row.

    The share lock makes a concurrent thread delete wait until this
    finalization commits (Postgres; SQLite already serializes writers), so the
    delete's later ``delete_by_thread`` step removes the line written here. A
    delete that committed first leaves no row to lock, and no line is written.
    """
    return select(ThreadMetaRow.thread_id).where(ThreadMetaRow.thread_id == thread_id).with_for_update(read=True)


def _event_time(task, occurrence) -> datetime:
    """When the reported transition happened (for the ``end_at`` / ``max_runs`` reason)."""
    return _as_utc_or_none(getattr(occurrence, "finished_at", None)) or _as_utc_or_none(getattr(task, "updated_at", None)) or datetime.now(UTC)


# One IM message per occurrence (or idle finish): the first event of this
# order that the transition produced. A once task's ``task_finished`` is never
# the message (its run event says the same thing), see ``_notice_event``.
_NOTICE_PRIORITY: tuple[str, ...] = ("task_stopped", "task_paused", "task_finished", "run_failed", "run_unmet", "run_completed")
NOTIFICATION_PAYLOAD_VERSION = 2


def _notice_event(task, occurrence, events: tuple[str, ...], *, now: datetime) -> tuple[str, str | None] | None:
    """The single event an IM notice reports, with its lifecycle reason (None for run events)."""
    for event in _NOTICE_PRIORITY:
        if event not in events:
            continue
        if event == "task_finished":
            reason = lifecycle_reason(task, event, now=now, occurrence=occurrence)
            if reason.startswith("once_"):
                continue
            return event, reason
        if event in LIFECYCLE_EVENTS:
            return event, lifecycle_reason(task, event, now=now, occurrence=occurrence)
        return event, None
    return None


def _idle_notice_key(task_id: str, anchor: str) -> str:
    """Outbox ``task_run_id`` of a finish without an occurrence (fits the 64-char column).

    Derived from the lifecycle anchor, so re-running ``complete_if_ended`` for
    the same end dedupes, and page-created tasks (no event row) get one too.
    """
    digest = hashlib.sha256(f"{task_id}\x00{anchor}".encode()).hexdigest()
    return f"idle:{digest[:48]}"


def _notice_payload(task, occurrence, event: str, reason: str | None, *, locale: str | None) -> dict[str, Any]:
    """Payload v2 of an IM notice (rendered by ``app.scheduler.notification_text``).

    No thread or run ids: notices carry no links. ``task_id`` stays for
    diagnostics only. Never raises for bad stored values.
    """
    title = task.title.strip() if isinstance(task.title, str) else ""
    run_status = getattr(occurrence, "status", None) if occurrence is not None else None
    occurrence_error = getattr(occurrence, "error", None) if occurrence is not None else None
    unmet_reason = occurrence_error if run_status == "unmet" and isinstance(occurrence_error, str) else None
    payload: dict[str, Any] = {
        "payload_version": NOTIFICATION_PAYLOAD_VERSION,
        "task_id": task.id,
        "task_title": title or None,
        "locale": locale,
        "reason_code": unmet_reason if event == "run_unmet" else reason,
        "latest_reason_code": unmet_reason,
        "run_status": run_status if isinstance(run_status, str) else None,
    }
    verdict = getattr(occurrence, "goal_verdict", None) if occurrence is not None else None
    if run_status == "success" and getattr(occurrence, "goal_objective", None) is not None and isinstance(verdict, dict) and verdict.get("satisfied") is True:
        # Present only when a goal was met; True when it relied on an assumption.
        payload["relied_on_assumption"] = verdict.get("relied_on_assumption") is True
    stop_condition = getattr(task, "stop_condition", None)
    if event == "task_stopped" and isinstance(stop_condition, str) and stop_condition.strip():
        payload["stop_condition"] = stop_condition
    if event == "task_finished":
        payload["max_runs"] = _int_or_none(getattr(task, "max_runs", None))
    return payload


# Shared so the active-row fast path and the atomic-admission conflict path
# return byte-identical outcomes for the same active-occurrence condition.
_ACTIVE_RUN_CONFLICT_ERROR = "task already has an active run"
# A manual trigger whose task changed between read and admission. The REST
# trigger and the chat trial map this exact outcome error to ``task_changed``.
TASK_CHANGED_ERROR = "scheduled task changed before trigger admission"
_RESTART_RECOVERY_ERROR = RUN_ERROR_RESTARTED
_LEASE_RECOVERY_ERROR = RUN_ERROR_LEASE_LOST
_QUEUE_TIMEOUT_ERROR = RUN_ERROR_QUEUE_TIMEOUT


class ScheduledTaskService:
    def __init__(
        self,
        *,
        task_repo,
        task_run_repo,
        launch_run,
        poll_interval_seconds: int,
        lease_seconds: int,
        max_concurrent_runs: int,
        max_concurrent_runs_per_user: int = 0,
        queue_timeout_seconds: int = 3600,
        multi_instance: bool = False,
        run_lease_grace_seconds: int = 10,
        connection_repo=None,
        notification_repo=None,
        own_stop_available: bool | None = None,
    ) -> None:
        self._task_repo = task_repo
        self._task_run_repo = task_run_repo
        self._launch_run = launch_run
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._max_concurrent_runs = max_concurrent_runs
        # Per-owner cap on launching/running rows (0 = off). It never exceeds
        # the global cap, so with the defaults (3 global, 2 per owner) one
        # owner always leaves a slot for everyone else.
        self._max_concurrent_runs_per_user = min(max_concurrent_runs_per_user, max_concurrent_runs) if max_concurrent_runs_per_user > 0 else 0
        self._queue_timeout_seconds = queue_timeout_seconds
        self._multi_instance = multi_instance
        self._run_lease_grace_seconds = run_lease_grace_seconds
        # Notification outbox wiring (issue #4254): both repos must be present
        # for IM notices. The finalization observer stages them in the outcome's
        # transaction (it reads bindings in that session); the delivery worker
        # sends. Either being None sends no IM notices.
        self._connection_repo = connection_repo
        self._notification_repo = notification_repo
        # Whether scheduled runs get stop_scheduled_task (scheduler.tool_enabled).
        # Decides how a launch phrases the user's stop rule (stop_rule.launch_prompt).
        # None (production) reads the live config at each launch, the same source
        # the run itself uses to grant the tool; a bool is a fixed test override.
        self._own_stop_available = own_stop_available
        self._lease_owner = f"{socket.gethostname()}:{uuid.uuid4().hex}"
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._skip_next_lease_reconciliation = False
        self._install_finalization_observers()

    async def _can_stop_itself(self) -> bool:
        """Whether the launched run will be given stop_scheduled_task.

        Read per launch from the live config, like ``start_run`` (which decides
        whether the run gets the tool) and ``/api/features``, so a config reload
        never tells a run to call a tool it does not have.
        """
        if self._own_stop_available is not None:
            return self._own_stop_available
        from deerflow.config.app_config import get_app_config
        from deerflow.scheduler.runtime import scheduler_tools_enabled

        try:
            return scheduler_tools_enabled(await asyncio.to_thread(get_app_config))
        except Exception:
            logger.warning("Could not read the scheduler tool setting; phrasing the stop rule without the tool", exc_info=True)
            return False

    @property
    def is_running(self) -> bool:
        """Whether this process's poller is running (automatic runs fire here)."""
        return self._task is not None and not self._task.done()

    def _install_finalization_observers(self) -> None:
        # Always installed: chat events need no outbox. The IM step checks the
        # outbox wiring at call time, so a detached outbox keeps chat events.
        for repository in (self._task_repo, self._task_run_repo):
            register = getattr(repository, "set_finalization_observer", None)
            if callable(register):
                register(self._on_finalization)

    async def _on_finalization(self, session, task, occurrence, *, events: tuple[str, ...]) -> None:
        """Stage lifecycle obligations in the transaction that finalizes them.

        Called by ``finalize_occurrence`` and ``finish_task_at_end_condition``
        under the parent lock, before their commit, so every row written here
        commits or rolls back with the state change it reports (also during
        crash and lease recovery). ``occurrence`` is None for an idle finish.

        1. A manual trial drops only its ``run_*`` events (the user is watching
           it); lifecycle events are one-time transitions and are kept.
        2. Lifecycle events become rows for the originating chat.
        3. One IM notice per occurrence (only while the outbox is wired).

        Lookups never raise for bad data (see ``_record_chat_events``); only
        database errors propagate, because swallowing them would break the
        same-transaction guarantee.
        """
        if occurrence is not None and occurrence.trigger == "manual":
            events = tuple(event for event in events if event not in RUN_EVENT_BY_STATUS.values())
        lifecycle = tuple(event for event in events if event in LIFECYCLE_EVENTS)
        if lifecycle:
            await self._record_chat_events(session, task, occurrence, lifecycle)
        if self._notification_repo is not None and self._connection_repo is not None:
            await self._enqueue_notice(session, task, occurrence, events)

    async def _record_chat_events(self, session, task, occurrence, events: tuple[str, ...]) -> None:
        """Write one display-only event row per lifecycle event for the originating chat.

        Page-created tasks have no originating chat, and a deleted chat gets no
        new rows. Bad stored data falls back (blank title -> None, unreadable
        end time -> ``max_runs`` / ``seq:`` anchor, missing run -> None).
        """
        origin_thread_id = getattr(task, "origin_thread_id", None)
        if not isinstance(origin_thread_id, str) or not origin_thread_id:
            return
        if await session.scalar(_origin_thread_share_lock(origin_thread_id)) is None:
            return
        now = _event_time(task, occurrence)
        anchor = lifecycle_anchor(task, occurrence, now=now)
        after_run_id = await session.scalar(select(RunRow.run_id).where(RunRow.thread_id == origin_thread_id, RunRow.operation_kind == "run").order_by(RunRow.created_at.desc(), RunRow.run_id.desc()).limit(1))
        run_number = None
        if occurrence is not None:
            value = await session.scalar(select(run_number_expression(ScheduledTaskRunRow)).where(ScheduledTaskRunRow.id == occurrence.id))
            run_number = _int_or_none(value)
        for event in events:
            reason = lifecycle_reason(task, event, now=now, occurrence=occurrence)
            await ScheduledTaskEventRepository.record_in_session(
                session,
                user_id=task.user_id,
                task_id=task.id,
                thread_id=origin_thread_id,
                occurrence_id=occurrence.id if occurrence is not None else None,
                anchor=anchor,
                event=event,
                reason_code=reason,
                after_run_id=after_run_id,
                payload=_chat_event_payload(task, occurrence, event, run_number=run_number),
            )

    async def _enqueue_notice(self, session, task, occurrence, events: tuple[str, ...]) -> None:
        """Stage the occurrence's one IM notice for each push-capable binding of the owner.

        Rows are deduplicated on ``(task_run_id, event, provider, target)``,
        so recovery re-finalizing nothing (``finalize_occurrence`` returns
        False) and a replayed idle finish (same anchor) add nothing. Providers
        without proactive push get no row. Plain manual trials reach here
        without run events and send nothing; interrupted runs have no event.
        """
        now = _event_time(task, occurrence)
        selected = _notice_event(task, occurrence, events, now=now)
        if selected is None:
            return
        event, reason = selected
        bindings = [
            binding
            for binding in await session.scalars(select(ChannelConnectionRow).where(ChannelConnectionRow.owner_user_id == task.user_id, ChannelConnectionRow.status == "connected"))
            if binding.provider and binding.external_account_id and supports_proactive_notifications(binding.provider)
        ]
        if not bindings:
            return
        payload = _notice_payload(task, occurrence, event, reason, locale=await self._owner_locale(session, task.user_id))
        task_run_id = occurrence.id if occurrence is not None else _idle_notice_key(task.id, lifecycle_anchor(task, occurrence, now=now))
        for binding in bindings:
            await self._notification_repo.enqueue_in_session(
                session,
                task_id=task.id,
                task_run_id=task_run_id,
                run_id=occurrence.run_id if occurrence is not None else None,
                event=event,
                provider=binding.provider,
                target=binding.external_account_id,
                owner_user_id=task.user_id,
                payload=payload,
            )

    @staticmethod
    async def _owner_locale(session, user_id: str) -> str | None:
        """The owner's UI language preference, or None (= ``channel_connections.notification_locale``).

        A missing, invalid or unreadable stored value falls back instead of
        raising (liveness rule: the observer must not wedge recovery). Database
        errors still propagate.
        """
        try:
            value = await session.scalar(select(UserPreferenceRow.value).where(UserPreferenceRow.user_id == user_id, UserPreferenceRow.key == "locale"))
        except (ValueError, TypeError, KeyError):
            # Undecodable stored JSON (json.JSONDecodeError is a ValueError).
            return None
        return value if isinstance(value, str) and value in NOTIFICATION_LOCALES else None

    def detach_notification_outbox(self) -> None:
        """Stop enqueueing run notifications (issue #4254).

        The Gateway calls this when the delivery side cannot start, so the outbox
        does not fill with rows nothing will send.
        """
        self._connection_repo = None
        self._notification_repo = None
        self._install_finalization_observers()

    async def run_once(self, *, now: datetime) -> None:
        if self._multi_instance:
            if self._skip_next_lease_reconciliation:
                self._skip_next_lease_reconciliation = False
            else:
                await self._reconcile_active_state(now=now)
        else:
            await self._task_run_repo.recover_expired_launch_claims(
                error=_LEASE_RECOVERY_ERROR,
                now=now,
            )
        await self._expire_waiting_runs(now=now)
        await self._drain_queue(now=now)
        # Admission and execution capacity are separate. Due occurrences are
        # persisted even when all execution slots are busy; claim_queued_run()
        # applies the global launch budget under the database lock.
        claimed = await self._task_repo.claim_due_tasks(
            now=now,
            lease_owner=self._lease_owner,
            lease_seconds=self._lease_seconds,
            limit=self._max_concurrent_runs,
        )
        for task in claimed:
            await self.dispatch_task(task, now=now, trigger="scheduled")

    @staticmethod
    def _is_overlap_conflict(exc: Exception) -> bool:
        if isinstance(exc, ConflictError):
            return True
        return isinstance(exc, HTTPException) and exc.status_code == 409

    @staticmethod
    def _task_status_for_failure(task: dict[str, Any], *, trigger: str) -> str:
        if trigger == "manual":
            # A failed manual trigger must not consume the task's scheduled
            # future: a `once` task with run_at still ahead would otherwise be
            # flipped to "failed" and never claimed again.
            return task.get("status") or "enabled"
        if task["schedule_type"] == "once":
            return "failed"
        return "enabled"

    @staticmethod
    def _task_status_for_launch(task: dict[str, Any], *, trigger: str) -> str:
        # The task-level status to write once _launch_run has produced a live
        # run. A `once` task stays "running" until handle_run_completion
        # observes the real terminal outcome; declaring "completed" at launch
        # would stick if the run fails or the process dies (startup
        # reconciliation is cancel_stuck_once_tasks).
        if task["schedule_type"] == "once":
            return "running"
        if trigger == "manual" and task.get("status") == "paused":
            return "paused"
        return "enabled"

    async def dispatch_task(
        self,
        task: dict[str, Any],
        *,
        now: datetime,
        trigger: str,
    ) -> dict[str, Any]:
        end_check = getattr(self._task_repo, "complete_if_ended", None)
        if trigger == "scheduled" and callable(end_check) and await end_check(task["id"], user_id=task.get("user_id"), now=now):
            return {"outcome": "completed", "task_run_id": None, "run_id": None, "thread_id": task.get("thread_id"), "error": None}
        expected_lease_owner = self._lease_owner if trigger == "scheduled" else None
        execution_thread_id = task.get("thread_id")
        if task.get("context_mode") == "fresh_thread_per_run" or execution_thread_id is None:
            execution_thread_id = str(uuid.uuid4())
        try:
            validate_thread_id(execution_thread_id)
        except ValueError as exc:
            # Rows persisted before the thread-id contract was centralized may
            # hold IDs that were valid then (dots, unlimited length) but fail
            # the canonical pattern now. Route through the normal failure
            # bookkeeping instead of raising: an uncaught ValueError here would
            # surface as HTTP 500 on manual trigger and, in the poller, abort
            # the rest of the claimed batch every cycle while the task itself
            # is never marked with last_error.
            task_status = self._task_status_for_failure(task, trigger=trigger)
            await self._task_repo.update_after_launch(
                task["id"],
                status=task_status,
                next_run_at=next_run_at(
                    task["schedule_type"],
                    task["schedule_spec"],
                    task["timezone"],
                    now=now,
                ),
                last_run_at=now,
                last_run_id=None,
                last_thread_id=execution_thread_id,
                last_error=str(exc),
                increment_run_count=False,
                expected_lease_owner=expected_lease_owner,
            )
            return {
                "outcome": "failed",
                "task_run_id": None,
                "run_id": None,
                "thread_id": execution_thread_id,
                "error": str(exc),
            }
        active = await self._task_run_repo.get_active_run(task["id"])
        if active is not None:
            if trigger == "scheduled":
                await self._release_admission_lease(task, trigger=trigger)
            return self._existing_active_result(active, execution_thread_id, trigger=trigger)

        task_run_id = f"task-run-{uuid.uuid4().hex}"
        try:
            await self._task_run_repo.create(
                run_record_id=task_run_id,
                task_id=task["id"],
                thread_id=execution_thread_id,
                scheduled_for=now,
                trigger=trigger,
                status="queued",
                coordinate_with_task=True,
                expected_task_user_id=task.get("user_id"),
                expected_task_status=task.get("status") if trigger == "manual" else None,
                expected_task_updated_at=task.get("updated_at") if trigger == "manual" else None,
                expected_task_lease_owner=self._lease_owner if trigger == "scheduled" else None,
                release_task_lease_status="enabled" if trigger == "scheduled" else None,
            )
        except ActiveScheduledRunConflict:
            active = await self._task_run_repo.get_active_run(task["id"])
            if trigger == "scheduled":
                await self._release_admission_lease(task, trigger=trigger)
            if active is None:
                return self._active_run_conflict_result(execution_thread_id)
            return self._existing_active_result(active, execution_thread_id, trigger=trigger)
        except ScheduledTaskAdmissionRejected as exc:
            if exc.reason == "ended":
                return {"outcome": "completed", "task_run_id": None, "run_id": None, "thread_id": execution_thread_id, "error": None}
            if exc.reason == "not_found":
                return {
                    "outcome": "not_found",
                    "task_run_id": None,
                    "run_id": None,
                    "thread_id": execution_thread_id,
                    "error": "scheduled task no longer exists",
                }
            return {
                "outcome": "conflict",
                "task_run_id": None,
                "run_id": None,
                "thread_id": execution_thread_id,
                "error": TASK_CHANGED_ERROR,
            }

        # Scheduled admission inserted the queue row and released its parent
        # lease in one transaction. Manual admission verified that this task
        # snapshot was still current under the same parent lock.
        queued = {
            "id": task_run_id,
            "task_id": task["id"],
            "thread_id": execution_thread_id,
            "trigger": trigger,
        }
        return await self._attempt_queued_run(task, queued, now=now)

    async def _release_admission_lease(self, task: dict[str, Any], *, trigger: str) -> None:
        status = "enabled" if trigger == "scheduled" else (task.get("status") or "enabled")
        await self._task_repo.release_dispatch_lease(
            task["id"],
            expected_lease_owner=self._lease_owner if trigger == "scheduled" else None,
            status=status,
        )

    async def _attempt_queued_run(
        self,
        task: dict[str, Any],
        queued: dict[str, Any],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        """Turn one queued occurrence into a live run under its own trace scope.

        The poller is a non-HTTP entry point, so no ``TraceMiddleware`` has
        bound anything: each occurrence opens its own scope rather than
        sharing one id across a whole poll cycle. A manual trigger arrives
        inside a Gateway request and keeps that request's trace instead, so
        the launched run stays correlated with the call that asked for it.
        """
        with ensure_trace_context():
            return await self._launch_queued_occurrence(task, queued, now=now)

    async def _launch_queued_occurrence(
        self,
        task: dict[str, Any],
        queued: dict[str, Any],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        task_run_id = queued["id"]
        execution_thread_id = queued["thread_id"]
        trigger = queued["trigger"]
        claimed = await self._task_run_repo.claim_queued_run(
            task_run_id,
            lease_owner=self._lease_owner,
            now=now,
            lease_seconds=self._lease_seconds,
            global_max_concurrent_runs=self._max_concurrent_runs,
            per_user_max_concurrent_runs=self._max_concurrent_runs_per_user,
        )
        if claimed is None:
            return self._queued_result(task_run_id, execution_thread_id)

        # Track whether _launch_run has produced a live run. A bookkeeping
        # failure after launch must retain the non-terminal slot so a later
        # poll cannot start the same occurrence twice.
        launched_run_id: str | None = None
        launched_thread_id: str | None = None
        launch_succeeded = False
        try:
            # Goals, notes, the stop rule and the previous-run reference apply
            # to every task, whether a chat or the tasks page created it.
            metadata = {"scheduled_task_id": task["id"], "scheduled_task_run_id": task_run_id, "scheduled_trigger": trigger, "scheduled_context_mode": task.get("context_mode")}
            if task.get("origin_thread_id") is not None:
                metadata["scheduled_tool_created"] = True  # informational only
            # The stop rule is composed only here, never stored in the prompt.
            prompt = launch_prompt(task["prompt"], task.get("stop_condition"), can_stop=await self._can_stop_itself())
            notes = task.get("standing_notes") or []
            if notes:
                prompt += "\n\n<standing_notes>\n" + "\n".join(f"- {note}" for note in notes) + "\n</standing_notes>"
            if task.get("goal_objective") is not None:
                metadata["scheduled_goal_objective"] = task["goal_objective"]
            previous_lookup = getattr(self._task_run_repo, "previous_occurrence", None)
            if task.get("context_mode") == "fresh_thread_per_run" and task["schedule_type"] != "once" and callable(previous_lookup):
                previous = await previous_lookup(task["id"], before_task_run_id=task_run_id)
                if previous is not None and previous.get("thread_id") != execution_thread_id:
                    metadata["scheduled_previous_thread_id"] = previous["thread_id"]
            origin, title = await self._launch_provenance(task, queued, now=now)
            result = await self._launch_run(
                thread_id=execution_thread_id,
                assistant_id=task.get("assistant_id"),
                prompt=prompt,
                owner_user_id=task.get("user_id"),
                metadata=metadata,
                origin=origin,
                title=title,
            )
            launch_succeeded = True
            launched_run_id = result["run_id"]
            launched_thread_id = result["thread_id"]
            next_at = next_run_at(
                task["schedule_type"],
                task["schedule_spec"],
                task["timezone"],
                now=now,
            )
            task_status = self._task_status_for_launch(task, trigger=trigger)
            await self._record_launched_run(
                task_run_id=task_run_id,
                task_id=task["id"],
                run_id=launched_run_id,
                started_at=now,
            )
            await self._task_repo.update_after_launch(
                task["id"],
                status=task_status,
                next_run_at=next_at,
                last_run_at=now,
                last_run_id=launched_run_id,
                last_thread_id=launched_thread_id,
                last_error=None,
                increment_run_count=True,
                task_run_id=task_run_id,
                # Same race as the run-row write above: a fast-failing run's
                # completion hook may have already finalized a `once` task.
                protect_terminal=True,
            )
            return {
                "outcome": "launched",
                "task_run_id": task_run_id,
                "run_id": launched_run_id,
                "thread_id": launched_thread_id,
                "error": None,
            }
        except Exception as exc:
            if not launch_succeeded and self._is_overlap_conflict(exc):
                await self._task_run_repo.requeue_claimed_run(
                    task_run_id,
                    lease_owner=self._lease_owner,
                    error=str(exc),
                )
                return self._queued_result(task_run_id, execution_thread_id, error=str(exc))

            next_at = next_run_at(
                task["schedule_type"],
                task["schedule_spec"],
                task["timezone"],
                now=now,
            )

            if launch_succeeded:
                # _launch_run succeeded, so a run is live even though
                # post-launch bookkeeping raised. Keep the task-run row
                # "running" so it keeps holding the task's single active slot
                # (preventing a duplicate launch on the next dispatch) and
                # persist the run_id on the parent task for recovery /
                # reconciliation / cancellation. These writes are best-effort:
                # if the DB is still down the row stays "queued" -- still
                # active, still holding the slot -- so we log and still report
                # the run as launched so callers know a run is in flight.
                task_status = self._task_status_for_launch(task, trigger=trigger)
                try:
                    await self._record_launched_run(
                        task_run_id=task_run_id,
                        task_id=task["id"],
                        run_id=launched_run_id,
                        started_at=now,
                    )
                except Exception:
                    logger.exception(
                        "Scheduled task-run %s: post-launch bookkeeping failed; run %s is still live (task %s)",
                        task_run_id,
                        launched_run_id,
                        task["id"],
                    )
                try:
                    await self._task_repo.update_after_launch(
                        task["id"],
                        status=task_status,
                        next_run_at=next_at,
                        last_run_at=now,
                        last_run_id=launched_run_id,
                        last_thread_id=launched_thread_id,
                        # The bookkeeping exception is an infrastructure-level
                        # transient, not a run-level failure: the run launched
                        # and is still in flight. Clear last_error like the
                        # success path so the task list does not show an error
                        # on a task whose run is actively running; the real
                        # terminal outcome is written by handle_run_completion.
                        # The transient itself is logged above.
                        last_error=None,
                        increment_run_count=True,
                        task_run_id=task_run_id,
                        protect_terminal=True,
                    )
                except Exception:
                    logger.exception(
                        "Scheduled task %s: post-launch update failed; run %s is still live",
                        task["id"],
                        launched_run_id,
                    )
                return {
                    "outcome": "launched",
                    "task_run_id": task_run_id,
                    "run_id": launched_run_id,
                    "thread_id": launched_thread_id,
                    "error": str(exc),
                }

            # _launch_run itself failed (or a step before it did): no live run
            # was created, so it is safe to release the active slot.
            finalized = await self._task_run_repo.fail_launching_run(
                task_run_id,
                task_id=task["id"],
                lease_owner=self._lease_owner,
                error=str(exc),
                now=now,
            )
            if not finalized:
                logger.warning(
                    "Scheduled task-run %s lost its launch claim before failure bookkeeping; leaving recovery-owned state unchanged",
                    task_run_id,
                )
                return self._queued_result(task_run_id, execution_thread_id, error=str(exc))
            return {
                "outcome": "failed",
                "task_run_id": task_run_id,
                "run_id": None,
                "thread_id": execution_thread_id,
                "error": str(exc),
            }

    async def _launch_provenance(self, task: dict[str, Any], queued: dict[str, Any], *, now: datetime) -> tuple[dict[str, Any], str | None]:
        """What the run thread shows about this launch, and its title.

        ``origin`` carries the user-language parts (instructions, stop
        condition, notes) so the run thread never has to show the launched
        text, which also holds host-written English. The run number is the
        one the run row shows once the launch is accounted.
        """
        trigger = queued["trigger"]
        scheduled_for = _as_utc(queued.get("scheduled_for")) if trigger == "scheduled" else None
        scheduled_for = scheduled_for or now
        run_number = None
        number_lookup = getattr(self._task_run_repo, "run_number", None)
        if trigger == "scheduled" and callable(number_lookup):
            try:
                run_number = await number_lookup(queued["id"])
            except Exception:
                logger.warning("Scheduled task-run %s: run number lookup failed", queued["id"], exc_info=True)
        origin = {
            "task_id": task["id"],
            "task_run_id": queued["id"],
            "trigger": trigger,
            "run_number": run_number,
            "scheduled_for": scheduled_for.isoformat(),
            "timezone": task["timezone"],
            "schedule_type": task.get("schedule_type"),
            "task_title": task.get("title") or "",
            "instructions": task["prompt"],
            "stop_condition": task.get("stop_condition"),
            "standing_notes": list(task.get("standing_notes") or []),
        }
        title = None
        if task.get("context_mode") == "fresh_thread_per_run":
            title = origin["task_title"][:80]
            if not _zone_is_placeholder(task):
                title = f"{title} · {scheduled_for.astimezone(ZoneInfo(task['timezone'])):%m-%d %H:%M}"
            elif run_number is not None:
                # No zone the reader would recognise: name the run, not a UTC time.
                title = f"{title} · #{run_number}"
        return origin, title

    async def _record_launched_run(
        self,
        *,
        task_run_id: str,
        task_id: str,
        run_id: str,
        started_at: datetime,
    ) -> None:
        updated = await self._task_run_repo.update_status(
            task_run_id,
            status="running",
            run_id=run_id,
            started_at=started_at,
            protect_terminal=True,
            expected_lease_owner=self._lease_owner,
        )
        if updated:
            return
        reconciled = await self._task_run_repo.reconcile_launched_run(
            task_run_id,
            task_id=task_id,
            run_id=run_id,
            started_at=started_at,
        )
        if not reconciled:
            logger.error(
                "Scheduled task-run %s launched durable run %s but could not restore its occurrence association",
                task_run_id,
                run_id,
            )

    def _active_run_conflict_result(self, thread_id: str) -> dict[str, Any]:
        """Manual-trigger response when the task already has an active run.

        Nothing was scheduled to happen, so no run-history row is recorded; the
        router maps this to a 409.
        """
        return {
            "outcome": "conflict",
            "task_run_id": None,
            "run_id": None,
            "thread_id": thread_id,
            "error": _ACTIVE_RUN_CONFLICT_ERROR,
        }

    def _existing_active_result(
        self,
        active: dict[str, Any],
        thread_id: str,
        *,
        trigger: str,
    ) -> dict[str, Any]:
        if active["status"] == "queued":
            # No new occurrence was admitted; the caller reports the waiting one.
            return self._queued_result(active["id"], active["thread_id"], existing=True)
        return self._active_run_conflict_result(thread_id)

    @staticmethod
    def _queued_result(
        task_run_id: str,
        thread_id: str,
        *,
        error: str | None = None,
        existing: bool = False,
    ) -> dict[str, Any]:
        return {
            "outcome": "queued",
            "task_run_id": task_run_id,
            "run_id": None,
            "thread_id": thread_id,
            "error": error,
            "existing": existing,
        }

    async def _drain_queue(self, *, now: datetime) -> None:
        queued_rows = await self._task_run_repo.list_queued_runs(
            limit=max(16, self._max_concurrent_runs * 4),
            per_user_max_concurrent_runs=self._max_concurrent_runs_per_user,
        )
        for queued in queued_rows:
            await self._task_repo.release_queued_admission_lease(queued["task_id"])
            task = await self._task_repo.get_internal(queued["task_id"])
            if task is None:
                await self._task_run_repo.update_status(
                    queued["id"],
                    status="interrupted",
                    error=RUN_ERROR_DELETED_WHILE_QUEUED,
                    finished_at=now,
                )
                continue
            # Pausing suppresses automatic occurrences, but a manual trigger is
            # an explicit request and has always been allowed to run without
            # resuming the schedule. A later pause still cancels an already
            # queued manual row atomically in pause_with_queue_cancellation().
            if task.get("status") == "paused" and queued["trigger"] != "manual":
                await self._task_run_repo.update_status(
                    queued["id"],
                    status="interrupted",
                    error=RUN_ERROR_PAUSED_WHILE_QUEUED,
                    finished_at=now,
                )
                continue
            await self._attempt_queued_run(task, queued, now=now)

    async def _expire_waiting_runs(self, *, now: datetime) -> None:
        await self._task_run_repo.expire_queued_runs(
            created_before=now - timedelta(seconds=self._queue_timeout_seconds),
            error=_QUEUE_TIMEOUT_ERROR,
            now=now,
        )

    async def handle_run_completion(self, record: RunRecord) -> None:
        metadata = record.metadata or {}
        task_id = metadata.get("scheduled_task_id")
        task_run_id = metadata.get("scheduled_task_run_id")
        user_id = record.user_id
        if not isinstance(task_id, str) or not isinstance(task_run_id, str) or not user_id:
            return

        terminal_status: Literal["success", "failed", "interrupted", "unmet"] | None
        if record.status.value == "success":
            terminal_status = "success"
            error = None
            verdict = getattr(record, "goal_verdict", None)
            if metadata.get("scheduled_goal_objective") is not None and (not isinstance(verdict, dict) or verdict.get("satisfied") is not True):
                terminal_status = "unmet"
                error = (verdict.get("stand_down_reason") if isinstance(verdict, dict) else None) or "no_verdict"
        elif record.status.value == "interrupted":
            # Distinct from "failed": an interrupt (user cancel, same-thread
            # takeover) carries no error and is not an execution failure.
            terminal_status = "interrupted"
            error = record.error or RUN_ERROR_INTERRUPTED
        elif record.status.value in {"error", "timeout"}:
            terminal_status = "failed"
            error = record.error
        else:
            terminal_status = None
            error = record.error
        if terminal_status is None:
            return

        completion_kwargs = {}
        if metadata.get("scheduled_goal_objective") is not None:
            completion_kwargs["goal_verdict"] = getattr(record, "goal_verdict", None)
        # The outcome and its notices (chat event, IM outbox row) commit in one
        # transaction: the finalization observer stages them. A completion
        # that recorded nothing (another run's occurrence, already finalized
        # by recovery) announces nothing.
        await self._task_repo.complete_run(
            task_id,
            user_id=user_id,
            task_run_id=task_run_id,
            run_id=record.run_id,
            status=terminal_status,
            error=error,
            finished_at=datetime.now(UTC),
            **completion_kwargs,
        )

    async def start(self) -> None:
        if self._task is not None:
            return
        restart_error = _RESTART_RECOVERY_ERROR
        if self._multi_instance:
            await self._reconcile_active_state(now=datetime.now(UTC))
            self._skip_next_lease_reconciliation = True
        else:
            # This destructive sweep is safe only while Gateway lifespan awaits
            # start(): no request or poll admission can create a run owned by
            # this process yet. Complete occurrence -> parent recovery before
            # returning; moving either pass into run_once() can interrupt live
            # work or race manual admission.
            try:
                stale = await self._task_run_repo.mark_stale_active_runs(error=restart_error)
                if stale:
                    logger.warning("Marked %d stale scheduled task run(s) as interrupted after restart", stale)
            except Exception:
                logger.exception("Failed to sweep stale scheduled task runs at startup")
                raise
            try:
                # The run rows above are only half the story: a launched `once`
                # task is parked in "running" until the (now dead) completion hook
                # would have finalized it.
                stuck = await self._task_repo.cancel_stuck_once_tasks(error=restart_error)
                if stuck:
                    logger.warning("Reconciled %d stuck once task(s) after restart", stuck)
            except Exception:
                logger.exception("Failed to reconcile stuck once tasks at startup")
                raise
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def _reconcile_active_state(self, *, now: datetime) -> None:
        error = _LEASE_RECOVERY_ERROR
        try:
            stale = await self._task_run_repo.reconcile_active_runs(
                error=error,
                now=now,
                lease_grace_seconds=self._run_lease_grace_seconds,
            )
            if stale:
                logger.warning("Marked %d stale scheduled task run(s) as interrupted after lease reconciliation", stale)
        except Exception:
            logger.exception("Failed to reconcile scheduled task runs with leases")
        try:
            stuck = await self._task_repo.reconcile_stuck_once_tasks(
                error=error,
                now=now,
                lease_grace_seconds=self._run_lease_grace_seconds,
            )
            if stuck:
                logger.warning("Reconciled %d stuck once task(s) after lease reconciliation", stuck)
        except Exception:
            logger.exception("Failed to reconcile once tasks with leases")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once(now=datetime.now(UTC))
            except Exception:
                # A transient DB error (e.g. SQLite "database is locked") must
                # not kill the poller task for the rest of the process life.
                logger.exception("Scheduled task poll failed; retrying next interval")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except TimeoutError:
                continue
