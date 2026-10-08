from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs.finalization import FinalizationObserver, automatic_runs_used, end_condition_reached, finalize_occurrence, finish_task_at_end_condition, is_host_pause_marker, utc
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_task_runs.projection import account_launch, can_project
from deerflow.persistence.scheduled_tasks.model import ACTIVE_RUN_STATUSES, LIVE_TASK_STATUSES, ONCE_TASK_STATUS_BY_RUN_STATUS, TERMINAL_RUN_STATUSES, TERMINAL_TASK_STATUSES, ScheduledTaskRow
from deerflow.scheduler.host_notes import RUN_ERROR_END_REACHED
from deerflow.utils.goal_objective import normalize_goal_objective
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)


class ScheduledTaskQuotaExceeded(ValueError):
    """A tool-created task would exceed its owner's live schedule quota."""

    def __init__(self) -> None:
        super().__init__("at most 20 live conversation-created scheduled tasks per user")


class ScheduledTaskLimitsExhausted(ValueError):
    """Reactivation would start a task whose safety cap is already used up.

    ``limit`` is ``"end_at"`` when the end time has passed, else ``"max_runs"``.
    Raising ``max_runs`` or moving ``end_at`` in the same update avoids it.
    """

    def __init__(self, *, limit: str, used: int, max_runs: int | None, end_at: str | None) -> None:
        self.limit = limit
        self.used = used
        self.max_runs = max_runs
        self.end_at = end_at
        super().__init__(f"scheduled task safety cap reached ({limit})")


class ActiveScheduledTaskMutationConflict(Exception):
    """A user mutation raced an admitted scheduled-task occurrence."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"scheduled task has an active {status} occurrence")


def _lease_is_alive(lease_expires_at: datetime | None, *, now: datetime, grace_seconds: int = 0) -> bool:
    if lease_expires_at is None:
        return False
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    return lease_expires_at >= now - timedelta(seconds=grace_seconds)


# Task columns that ``_row_to_dict`` serializes as ISO strings and that every
# write path must coerce back (``_coerce_datetime``) before binding.
_TIMESTAMP_KEYS = frozenset({"created_at", "updated_at", "next_run_at", "last_run_at", "lease_expires_at", "end_at"})


def _coerce_datetime(value: datetime | str | None) -> datetime | None:
    """Convert serialized task timestamps back before binding DateTime fields."""
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            text = value
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"invalid scheduled task timestamp: {value!r}") from exc
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    raise TypeError(f"scheduled task timestamp must be datetime, str, or None: {type(value).__name__}")


class ScheduledTaskRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        run_repository: RunRepository | None = None,
    ) -> None:
        self._sf = session_factory
        self._run_repository = run_repository or RunRepository(session_factory)
        self._finalization_observer: FinalizationObserver | None = None

    def set_finalization_observer(self, callback: FinalizationObserver | None) -> None:
        self._finalization_observer = callback

    @staticmethod
    def _row_to_dict(row: ScheduledTaskRow) -> dict[str, Any]:
        data = row.to_dict(exclude={"last_occurrence_seq", "unmet_streak_after_seq"})
        for key in _TIMESTAMP_KEYS:
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

    @staticmethod
    async def _lock_task(session: AsyncSession, task_id: str) -> ScheduledTaskRow | None:
        # Match scheduled-run admission on SQLite, where FOR UPDATE is ignored:
        # acquire the database writer before checking the child occurrence.
        if session.get_bind().dialect.name == "sqlite":
            await session.execute(update(ScheduledTaskRow).where(ScheduledTaskRow.id == task_id).values(updated_at=ScheduledTaskRow.updated_at))
        return await session.get(ScheduledTaskRow, task_id, with_for_update=True)

    @staticmethod
    async def _serialize_owner_quota(session: AsyncSession, user_id: str) -> None:
        dialect = session.get_bind().dialect.name
        if dialect == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))
        elif dialect == "postgresql":
            digest = hashlib.sha256(f"scheduler-conversation-quota\x00{user_id}".encode()).digest()
            key = int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    @staticmethod
    async def _check_owner_quota(session: AsyncSession, user_id: str) -> None:
        count = await session.scalar(select(func.count()).select_from(ScheduledTaskRow).where(ScheduledTaskRow.user_id == user_id, ScheduledTaskRow.origin_thread_id.is_not(None), ScheduledTaskRow.status.in_(LIVE_TASK_STATUSES)))
        if int(count or 0) >= 20:
            raise ScheduledTaskQuotaExceeded()

    async def create(
        self,
        *,
        task_id: str,
        user_id: str,
        thread_id: str | None,
        context_mode: str,
        assistant_id: str | None,
        title: str,
        prompt: str,
        schedule_type: str,
        schedule_spec: dict[str, Any],
        timezone: str,
        next_run_at: datetime | None,
        origin_thread_id: str | None = None,
        goal_objective: str | None = None,
        max_runs: int | None = None,
        end_at: datetime | str | None = None,
        standing_notes: list[str] | None = None,
        stop_condition: str | None = None,
    ) -> dict[str, Any]:
        if goal_objective is not None:
            normalize_goal_objective(goal_objective)
        if goal_objective is not None and context_mode != "fresh_thread_per_run":
            raise ValueError("goal-backed schedules require fresh_thread_per_run")
        if max_runs is not None and (not isinstance(max_runs, int) or isinstance(max_runs, bool) or max_runs < 1):
            raise ValueError("max_runs must be a positive integer")
        if standing_notes is not None and (len(standing_notes) > 10 or any(not isinstance(note, str) or not note.strip() or len(note) > 500 for note in standing_notes)):
            raise ValueError("standing notes allow at most 10 nonempty notes of 500 characters")
        now = datetime.now(UTC)
        row = ScheduledTaskRow(
            id=task_id,
            user_id=user_id,
            thread_id=thread_id,
            origin_thread_id=origin_thread_id,
            goal_objective=goal_objective,
            stop_condition=stop_condition,
            max_runs=max_runs,
            end_at=_coerce_datetime(end_at),
            standing_notes=list(standing_notes) if standing_notes is not None else None,
            context_mode=context_mode,
            assistant_id=assistant_id,
            title=title,
            prompt=prompt,
            schedule_type=schedule_type,
            schedule_spec=schedule_spec,
            timezone=timezone,
            next_run_at=next_run_at,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            if origin_thread_id is not None:
                await self._serialize_owner_quota(session, user_id)
                await self._check_owner_quota(session, user_id)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(self, task_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None or row.user_id != user_id:
                return None
            return self._row_to_dict(row)

    async def get_internal(self, task_id: str) -> dict[str, Any] | None:
        """Load a task for the internal queue worker without an auth boundary."""
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            return self._row_to_dict(row) if row is not None else None

    async def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        stmt = select(ScheduledTaskRow).where(ScheduledTaskRow.user_id == user_id).order_by(ScheduledTaskRow.created_at.desc(), ScheduledTaskRow.id.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def get_active_run_status(self, task_id: str) -> str | None:
        stmt = (
            select(ScheduledTaskRunRow.status)
            .where(
                ScheduledTaskRunRow.task_id == task_id,
                ScheduledTaskRunRow.status.in_(("queued", "launching", "running")),
            )
            .limit(1)
        )
        async with self._sf() as session:
            return (await session.execute(stmt)).scalars().first()

    async def active_run_status_for(self, task_ids: Sequence[str]) -> dict[str, str]:
        """Most advanced active occurrence status per task, in one query.

        A recurring task's own ``status`` is ``enabled`` while its occurrence
        runs, so "is something running or waiting" must come from here.
        """
        ids = list(dict.fromkeys(task_ids))
        if not ids:
            return {}
        stmt = select(ScheduledTaskRunRow.task_id, ScheduledTaskRunRow.status).where(ScheduledTaskRunRow.task_id.in_(ids), ScheduledTaskRunRow.status.in_(("queued", "launching", "running")))
        rank = {"queued": 0, "launching": 1, "running": 2}
        result: dict[str, str] = {}
        async with self._sf() as session:
            for task_id, status in (await session.execute(stmt)).all():
                if task_id not in result or rank[status] > rank[result[task_id]]:
                    result[task_id] = status
        return result

    async def automatic_runs_used_for(self, task_ids: Sequence[str]) -> dict[str, int]:
        """Launched automatic runs per task (the ``max_runs`` unit); missing ids map to 0."""
        ids = list(dict.fromkeys(task_ids))
        if not ids:
            return {}
        stmt = select(ScheduledTaskRunRow.task_id, func.count()).where(ScheduledTaskRunRow.task_id.in_(ids), ScheduledTaskRunRow.trigger == "scheduled", ScheduledTaskRunRow.launch_accounted.is_(True)).group_by(ScheduledTaskRunRow.task_id)
        async with self._sf() as session:
            counts = {task_id: int(count) for task_id, count in (await session.execute(stmt)).all()}
        return {task_id: counts.get(task_id, 0) for task_id in ids}

    async def pause_with_queue_cancellation(
        self,
        task_id: str,
        *,
        user_id: str,
        error: str,
        now: datetime,
    ) -> str:
        """Pause a task and cancel its waiting occurrence in one transaction.

        Returns ``"paused"``, ``"not_found"``, ``"executing"`` (an occurrence is
        launching or running) or ``"finished"`` (a completed, failed or
        cancelled task has no schedule left to pause; Resume reactivates it).
        """
        async with self._sf() as session:
            task = await self._lock_task(session, task_id)
            if task is None or task.user_id != user_id:
                await session.rollback()
                return "not_found"
            if task.status in TERMINAL_TASK_STATUSES:
                await session.rollback()
                return "finished"
            run = (
                (
                    await session.execute(
                        select(ScheduledTaskRunRow)
                        .where(
                            ScheduledTaskRunRow.task_id == task_id,
                            ScheduledTaskRunRow.status.in_(("queued", "launching", "running")),
                        )
                        .limit(1)
                        .with_for_update()
                    )
                )
                .scalars()
                .first()
            )
            if run is not None and run.status in {"launching", "running"}:
                await session.rollback()
                return "executing"
            if run is not None:
                run.status = "interrupted"
                run.error = error
                run.finished_at = now
                run.lease_owner = None
                run.lease_expires_at = None
            task.status = "paused"
            task.lease_owner = None
            task.lease_expires_at = None
            task.updated_at = now
            await session.commit()
            return "paused"

    async def delete_with_queue_cancellation(
        self,
        task_id: str,
        *,
        user_id: str,
        error: str,
        now: datetime,
    ) -> str:
        """Delete a task only before queue execution begins."""
        async with self._sf() as session:
            task = await self._lock_task(session, task_id)
            if task is None or task.user_id != user_id:
                await session.rollback()
                return "not_found"
            run = (
                (
                    await session.execute(
                        select(ScheduledTaskRunRow)
                        .where(
                            ScheduledTaskRunRow.task_id == task_id,
                            ScheduledTaskRunRow.status.in_(("queued", "launching", "running")),
                        )
                        .limit(1)
                        .with_for_update()
                    )
                )
                .scalars()
                .first()
            )
            if run is not None and run.status in {"launching", "running"}:
                await session.rollback()
                return "executing"
            if run is not None:
                run.status = "interrupted"
                run.error = error
                run.finished_at = now
                run.lease_owner = None
                run.lease_expires_at = None
            await session.delete(task)
            await session.commit()
            return "deleted"

    async def update(
        self,
        task_id: str,
        *,
        user_id: str,
        updates: dict[str, Any],
        require_mutable: bool = False,
    ) -> dict[str, Any] | None:
        if updates.get("goal_objective") is not None:
            normalize_goal_objective(updates["goal_objective"])
        async with self._sf() as session:
            quota_transition = False
            if updates.get("status") in LIVE_TASK_STATUSES:
                # Read only the provenance first, without an ORM identity-map
                # snapshot. Acquire the owner mutex before the parent lock so
                # create and terminal reactivation share one admission order.
                origin = await session.scalar(select(ScheduledTaskRow.origin_thread_id).where(ScheduledTaskRow.id == task_id, ScheduledTaskRow.user_id == user_id))
                if origin is not None:
                    await self._serialize_owner_quota(session, user_id)
                    quota_transition = True
            definition_changed = bool({"context_mode", "goal_objective", "prompt", "stop_condition"} & updates.keys())
            reactivation_requested = updates.get("status") == "enabled"
            row = await self._lock_task(session, task_id) if require_mutable or quota_transition or definition_changed or reactivation_requested else await session.get(ScheduledTaskRow, task_id)
            if row is None or row.user_id != user_id:
                return None
            reactivating = reactivation_requested and row.status != "enabled"
            # A goal, instruction or stop-rule change starts a new unmet count:
            # every occurrence so far was judged against the old definition
            # (edits require no active occurrence). Resume does not move it.
            moves_boundary = any(key in updates and updates[key] != getattr(row, key) for key in ("goal_objective", "prompt", "stop_condition"))
            effective_goal = updates.get("goal_objective", row.goal_objective)
            effective_context = updates.get("context_mode", row.context_mode)
            if effective_goal is not None and effective_context != "fresh_thread_per_run":
                raise ValueError("goal-backed schedules require fresh_thread_per_run")
            if quota_transition and row.origin_thread_id is not None and row.status in TERMINAL_TASK_STATUSES:
                await self._check_owner_quota(session, user_id)
            if require_mutable:
                if row.status == "running":
                    await session.rollback()
                    raise ActiveScheduledTaskMutationConflict("running")
                active_status = await session.scalar(
                    select(ScheduledTaskRunRow.status)
                    .where(
                        ScheduledTaskRunRow.task_id == task_id,
                        ScheduledTaskRunRow.status.in_(("queued", "launching", "running")),
                    )
                    .limit(1)
                )
                if active_status is not None:
                    await session.rollback()
                    raise ActiveScheduledTaskMutationConflict(active_status)
            for key, value in updates.items():
                if hasattr(row, key):
                    # Callers pass timestamps back in the serialized form
                    # ``_row_to_dict`` returned (the PATCH route reuses an
                    # interval task's ``next_run_at`` unchanged); bind datetimes.
                    setattr(row, key, _coerce_datetime(value) if key in _TIMESTAMP_KEYS else value)
            if moves_boundary:
                row.unmet_streak_after_seq = row.last_occurrence_seq
            if reactivating:
                # Single choke point for every reactivation (REST resume, PATCH
                # re-arm, chat update/resume). Renewal fields were applied
                # above, so raising max_runs or moving end_at in the same
                # request passes; history and run_count stay untouched.
                now = datetime.now(UTC)
                if await end_condition_reached(session, row, now=now):
                    used = await automatic_runs_used(session, row.id)
                    end_at = row.end_at
                    limit = "end_at" if end_at is not None and utc(end_at) <= now else "max_runs"
                    max_runs = row.max_runs
                    await session.rollback()
                    raise ScheduledTaskLimitsExhausted(limit=limit, used=used, max_runs=max_runs, end_at=coerce_iso(utc(end_at)) if end_at is not None else None)
                if is_host_pause_marker(row.last_error):
                    # As on resume: a later manual pause must not read as
                    # "Paused by agent" or "Auto-paused".
                    row.last_error = None
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def delete(self, task_id: str, *, user_id: str) -> bool:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None or row.user_id != user_id:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def claim_due_tasks(
        self,
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        async with self._sf() as session:
            active_run_for_task = exists(
                select(ScheduledTaskRunRow.id).where(
                    ScheduledTaskRunRow.task_id == ScheduledTaskRow.id,
                    ScheduledTaskRunRow.status.in_(("queued", "launching", "running")),
                )
            )
            if limit <= 0:
                return []
            stmt = (
                select(ScheduledTaskRow)
                .where(
                    ScheduledTaskRow.next_run_at.is_not(None),
                    ScheduledTaskRow.next_run_at <= now,
                    ~active_run_for_task,
                    or_(
                        and_(
                            ScheduledTaskRow.status == "enabled",
                            or_(
                                ScheduledTaskRow.lease_expires_at.is_(None),
                                ScheduledTaskRow.lease_expires_at < now,
                            ),
                        ),
                        # A task stuck in "running" with an expired lease means the
                        # claiming process died between claim and dispatch; it must
                        # stay reclaimable or the task is dead forever.
                        and_(
                            ScheduledTaskRow.status == "running",
                            ScheduledTaskRow.lease_expires_at.is_not(None),
                            ScheduledTaskRow.lease_expires_at < now,
                        ),
                    ),
                )
                .order_by(ScheduledTaskRow.next_run_at.asc(), ScheduledTaskRow.id.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            rows = list(result.scalars())
            for row in rows:
                row.lease_owner = lease_owner
                row.lease_expires_at = lease_expires_at
                row.status = "running"
                row.updated_at = datetime.now(UTC)
            await session.commit()
            return [self._row_to_dict(row) for row in rows]

    async def release_dispatch_lease(
        self,
        task_id: str,
        *,
        expected_lease_owner: str | None,
        status: str,
    ) -> bool:
        """Release the short due-task claim after its occurrence is queued.

        The lease-owner guard is only as fresh as the row it reads, so the
        read takes the writer first (``_lock_task``): on SQLite a plain
        ``SELECT`` sees a pre-pause snapshot, and the unconditional
        ``row.status = status`` below would then write the caller's
        ``"enabled"`` over a pause that had already committed.
        """
        async with self._sf() as session:
            row = await self._lock_task(session, task_id)
            if row is None:
                return False
            if expected_lease_owner is not None and row.lease_owner != expected_lease_owner:
                await session.rollback()
                return False
            row.status = status
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def release_queued_admission_lease(self, task_id: str) -> bool:
        """Recover a crash after queue insert but before parent-lease release."""
        async with self._sf() as session:
            task = await self._lock_task(session, task_id)
            if task is None or task.status != "running" or task.lease_owner is None:
                await session.rollback()
                return False
            queued = await session.scalar(
                select(ScheduledTaskRunRow).where(
                    ScheduledTaskRunRow.task_id == task_id,
                    ScheduledTaskRunRow.status == "queued",
                )
            )
            if queued is None or not can_project(task, queued):
                await session.rollback()
                return False
            task.status = "enabled"
            task.lease_owner = None
            task.lease_expires_at = None
            task.updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def update_after_launch(
        self,
        task_id: str,
        *,
        status: str,
        next_run_at: datetime | str | None,
        last_run_at: datetime | str | None,
        last_run_id: str | None,
        last_thread_id: str | None,
        last_error: str | None,
        increment_run_count: bool,
        protect_terminal: bool = False,
        expected_lease_owner: str | None = None,
        task_run_id: str | None = None,
    ) -> bool:
        async with self._sf() as session:
            row = await self._lock_task(session, task_id)
            if row is None:
                return False
            if expected_lease_owner is not None and row.lease_owner != expected_lease_owner:
                logger.warning(
                    "Fenced stale scheduled-task update for task %s: expected lease owner %s, current owner %s",
                    task_id,
                    expected_lease_owner,
                    row.lease_owner,
                )
                await session.rollback()
                return False
            occurrence = None
            if task_run_id is not None:
                occurrence = await session.get(ScheduledTaskRunRow, task_run_id, with_for_update=True)
                if occurrence is None or occurrence.task_id != task_id or occurrence.run_id not in (None, last_run_id):
                    logger.warning(
                        "Fenced stale scheduled-task launch update for task %s: occurrence %s does not belong to run %s",
                        task_id,
                        task_run_id,
                        last_run_id,
                    )
                    await session.rollback()
                    return False
            elif last_run_id is not None:
                # Preserve direct repository callers that identify the launch
                # by its durable run id rather than its occurrence id.
                occurrence = await session.scalar(select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.task_id == task_id, ScheduledTaskRunRow.run_id == last_run_id).with_for_update())
            should_increment_run_count = increment_run_count and (last_run_id is None or row.last_run_id != last_run_id)
            if occurrence is not None:
                if increment_run_count and last_run_id is not None:
                    account_launch(row, occurrence, last_run_id)
                should_increment_run_count = False
                if not can_project(row, occurrence):
                    await session.commit()
                    return True
            if protect_terminal and (row.status in TERMINAL_TASK_STATUSES or (occurrence is not None and occurrence.status in TERMINAL_RUN_STATUSES)):
                # A fast-failing run can reach handle_run_completion (which
                # finalizes a `once` task) before this launch-path write
                # commits. Cron parents stay enabled even after completion,
                # so also protect the terminal occurrence's status/error.
                pass
            else:
                # A trial on a task the host paused keeps its pause reason.
                keep_pause_marker = occurrence is not None and occurrence.trigger == "manual" and row.status == "paused" and status == "paused" and is_host_pause_marker(row.last_error)
                row.status = status
                if not keep_pause_marker:
                    row.last_error = last_error
            row.next_run_at = _coerce_datetime(next_run_at)
            row.last_run_at = _coerce_datetime(last_run_at)
            row.last_run_id = last_run_id
            row.last_thread_id = last_thread_id
            if should_increment_run_count:
                row.run_count += 1
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def complete_run(
        self,
        task_id: str,
        *,
        user_id: str,
        task_run_id: str,
        run_id: str,
        status: str,
        error: str | None,
        finished_at: datetime,
        goal_verdict: dict[str, Any] | None = None,
    ) -> bool:
        """Commit occurrence completion, accounting and eligible parent outcome."""
        if status not in TERMINAL_RUN_STATUSES:
            raise ValueError(f"unsupported terminal occurrence status: {status!r}")
        async with self._sf() as session:
            task = await self._lock_task(session, task_id)
            occurrence = await session.get(ScheduledTaskRunRow, task_run_id, with_for_update=True)
            if occurrence is None or occurrence.task_id != task_id or occurrence.run_id not in (None, run_id) or (task is not None and task.user_id != user_id):
                await session.rollback()
                return False
            accepted = await finalize_occurrence(session, task, occurrence, status=status, error=error, finished_at=finished_at, run_id=run_id, goal_verdict=goal_verdict, observer=self._finalization_observer)
            await session.commit()
            return accepted

    async def claim_dispatch_lease(
        self,
        task_id: str,
        *,
        lease_owner: str,
        now: datetime,
        lease_seconds: int,
    ) -> dict[str, Any] | None:
        """Reserve the short pre-launch window for a manual dispatch."""
        stmt = (
            select(ScheduledTaskRow)
            .where(
                ScheduledTaskRow.id == task_id,
                or_(
                    ScheduledTaskRow.lease_expires_at.is_(None),
                    ScheduledTaskRow.lease_expires_at < now,
                ),
            )
            .with_for_update(skip_locked=True)
        )
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            if row is None:
                return None
            row.lease_owner = lease_owner
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def list_by_user_and_thread(self, user_id: str, thread_id: str) -> list[dict[str, Any]]:
        """Tasks related to a conversation: created in it, running in it, or one of its runs.

        Each dict gains ``thread_relation`` (``origin`` / ``reuse`` / ``run``) and,
        for ``run``, ``thread_run``: the latest occurrence of that task in the thread.
        """
        ran_in_thread = exists(select(ScheduledTaskRunRow.id).where(ScheduledTaskRunRow.task_id == ScheduledTaskRow.id, ScheduledTaskRunRow.thread_id == thread_id))
        stmt = (
            select(ScheduledTaskRow)
            .where(
                ScheduledTaskRow.user_id == user_id,
                or_(ScheduledTaskRow.thread_id == thread_id, ScheduledTaskRow.origin_thread_id == thread_id, ran_in_thread),
            )
            .order_by(ScheduledTaskRow.created_at.desc(), ScheduledTaskRow.id.desc())
        )
        async with self._sf() as session:
            rows = list((await session.execute(stmt)).scalars())
            items: list[dict[str, Any]] = []
            for row in rows:
                data = self._row_to_dict(row)
                if row.origin_thread_id == thread_id:
                    data["thread_relation"], data["thread_run"] = "origin", None
                elif row.thread_id == thread_id:
                    data["thread_relation"], data["thread_run"] = "reuse", None
                else:
                    data["thread_relation"] = "run"
                    data["thread_run"] = await self._latest_thread_run(session, row.id, thread_id)
                items.append(data)
            return items

    @staticmethod
    async def _latest_thread_run(session: AsyncSession, task_id: str, thread_id: str) -> dict[str, Any] | None:
        from deerflow.persistence.scheduled_task_runs.sql import run_number_expression

        number = run_number_expression(ScheduledTaskRunRow)
        stmt = (
            select(ScheduledTaskRunRow.trigger, ScheduledTaskRunRow.scheduled_for, ScheduledTaskRunRow.status, number)
            .where(ScheduledTaskRunRow.task_id == task_id, ScheduledTaskRunRow.thread_id == thread_id)
            .order_by(ScheduledTaskRunRow.occurrence_seq.desc().nulls_last(), ScheduledTaskRunRow.created_at.desc(), ScheduledTaskRunRow.id.desc())
            .limit(1)
        )
        found = (await session.execute(stmt)).first()
        if found is None:
            return None
        trigger, scheduled_for, status, run_number = found
        return {"run_number": int(run_number) if run_number is not None else None, "trigger": trigger, "scheduled_for": coerce_iso(utc(scheduled_for)), "status": status}

    async def list_by_origin_thread(self, user_id: str, origin_thread_id: str) -> list[dict[str, Any]]:
        async with self._sf() as session:
            rows = await session.execute(select(ScheduledTaskRow).where(ScheduledTaskRow.user_id == user_id, ScheduledTaskRow.origin_thread_id == origin_thread_id).order_by(ScheduledTaskRow.created_at.desc(), ScheduledTaskRow.id.desc()))
            return [self._row_to_dict(row) for row in rows.scalars()]

    async def list_manageable_from_thread(self, user_id: str, thread_id: str) -> list[dict[str, Any]]:
        """Tasks a conversation may manage: created in it, or whose run it is."""
        ran_in_thread = exists(select(ScheduledTaskRunRow.id).where(ScheduledTaskRunRow.task_id == ScheduledTaskRow.id, ScheduledTaskRunRow.thread_id == thread_id))
        stmt = select(ScheduledTaskRow).where(ScheduledTaskRow.user_id == user_id, or_(ScheduledTaskRow.origin_thread_id == thread_id, ran_in_thread)).order_by(ScheduledTaskRow.created_at.desc(), ScheduledTaskRow.id.desc())
        async with self._sf() as session:
            return [self._row_to_dict(row) for row in (await session.execute(stmt)).scalars()]

    async def append_standing_note(self, task_id: str, *, user_id: str, note: str, origin_thread_id: str | None = None) -> dict[str, Any] | None:
        """Append one standing note; ``origin_thread_id`` additionally scopes the task when given."""
        if not isinstance(note, str) or not note.strip() or len(note) > 500:
            raise ValueError("a standing note must contain 1 to 500 characters")
        async with self._sf() as session:
            task = await self._lock_task(session, task_id)
            if task is None or task.user_id != user_id or (origin_thread_id is not None and task.origin_thread_id != origin_thread_id):
                return None
            active = await session.scalar(select(ScheduledTaskRunRow.status).where(ScheduledTaskRunRow.task_id == task_id, ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES)).limit(1))
            if active is not None or task.status == "running":
                raise ActiveScheduledTaskMutationConflict(active or "running")
            notes = list(task.standing_notes or [])
            if len(notes) >= 10:
                raise ValueError("at most 10 standing notes per scheduled task")
            task.standing_notes = notes + [note]
            # New notes change what later runs are told; restart the unmet count.
            task.unmet_streak_after_seq = task.last_occurrence_seq
            task.updated_at = datetime.now(UTC)
            await session.commit()
            return self._row_to_dict(task)

    async def complete_if_ended(self, task_id: str, *, user_id: str | None = None, now: datetime, scheduled_only: bool = True) -> bool:
        """Return true when an automatic dispatch must stop at a durable limit.

        Ended waiting work is cancelled; executing work keeps its slot until
        first-terminal completion. Manual trial admission can opt out entirely.
        """
        if not scheduled_only:
            return False
        async with self._sf() as session:
            task = await self._lock_task(session, task_id)
            if task is None or (user_id is not None and task.user_id != user_id):
                return False
            if not await end_condition_reached(session, task, now=now):
                return False
            active = await session.scalar(select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.task_id == task_id, ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES)).with_for_update())
            if active is not None and active.status in {"launching", "running"}:
                # Completion owns the lifecycle while work is already executing.
                return True
            if active is not None and active.trigger == "scheduled":
                # Skipping the waiting row finishes the task and emits there;
                # the helper below then only clears the lease.
                await finalize_occurrence(session, task, active, status="skipped", error=RUN_ERROR_END_REACHED, finished_at=now, run_id=None, observer=self._finalization_observer)
            # No queued row (or a queued manual trial): an idle finish.
            await finish_task_at_end_condition(session, task, occurrence=None, now=now, observer=self._finalization_observer)
            await session.commit()
            return True

    @staticmethod
    async def _fetch_latest_run(session: AsyncSession, task_id: str) -> ScheduledTaskRunRow | None:
        """Return the latest ``scheduled_task_runs`` row for a task (no status filter).

        The caller must not hold a pre-lock snapshot of this row; the outcome
        used for finalization must come from a fresh read.  ``populate_existing``
        bypasses the session identity map so a concurrently committed status is
        read back fresh.

        Once any sequenced row exists, the parent-locked ``occurrence_seq`` is
        the only recency key and the highest sequence wins: caller clocks never
        reorder sequenced rows, and unsequenced rows (legacy history or an
        admission by a pre-upgrade writer) are not consulted, matching the
        ``can_project`` rule applied by every other parent write.  Only a task
        whose history is entirely unsequenced keeps the previous timestamp
        ordering.
        """
        base = select(ScheduledTaskRunRow).where(ScheduledTaskRunRow.task_id == task_id)
        sequenced_stmt = base.where(ScheduledTaskRunRow.occurrence_seq.is_not(None)).order_by(ScheduledTaskRunRow.occurrence_seq.desc()).limit(1).execution_options(populate_existing=True)
        sequenced = (await session.execute(sequenced_stmt)).scalars().first()
        if sequenced is not None:
            return sequenced
        legacy_stmt = (
            base.order_by(
                ScheduledTaskRunRow.created_at.desc(),
                ScheduledTaskRunRow.scheduled_for.desc(),
                ScheduledTaskRunRow.id.desc(),
            )
            .limit(1)
            .execution_options(populate_existing=True)
        )
        return (await session.execute(legacy_stmt)).scalars().first()

    @staticmethod
    async def _has_active_occurrence(session: AsyncSession, task_id: str) -> bool:
        """True while any occurrence row of the task is queued/launching/running.

        ``uq_scheduled_task_run_active`` allows one such row per task, so a live
        row is the newest admission regardless of its caller clock or whether
        it carries a sequence.
        """
        stmt = (
            select(ScheduledTaskRunRow.id)
            .where(
                ScheduledTaskRunRow.task_id == task_id,
                ScheduledTaskRunRow.status.in_(ACTIVE_RUN_STATUSES),
            )
            .limit(1)
        )
        return (await session.execute(stmt)).scalars().first() is not None

    @staticmethod
    def _finalise_once_task_from_run(
        task_row: ScheduledTaskRow,
        run_row: ScheduledTaskRunRow | None,
        *,
        error: str,
        now: datetime,
    ) -> bool:
        """Finalise a stuck ``once`` task parent to match its latest run outcome.

        success -> completed, failed -> failed, interrupted -> cancelled,
        skipped -> cancelled (no work performed).  An active occurrence
        (queued/launching/running) is left untouched — a concurrent completion
        or a later recovery pass will finalize it once the run reaches a
        terminal state.  When there is no run row at all the parent keeps
        the original generic cancellation.

        Returns ``True`` if the parent was finalised, ``False`` for an active
        occurrence that must be retried by a later recovery pass.
        """
        if run_row is not None and run_row.status in TERMINAL_RUN_STATUSES:
            task_row.status = ONCE_TASK_STATUS_BY_RUN_STATUS[run_row.status]
            if run_row.status == "success":
                task_row.last_error = None
            elif run_row.status == "interrupted":
                task_row.last_error = run_row.error or error
            else:
                task_row.last_error = run_row.error
            task_row.updated_at = now
            return True
        if run_row is not None and run_row.status in ACTIVE_RUN_STATUSES:
            # Active occurrence — leave the parent unchanged.  A concurrent
            # completion or a later recovery pass will finalize it.
            return False
        # No run row, or an unrecognised legacy status — generic cancel.
        task_row.status = "cancelled"
        task_row.last_error = error
        task_row.updated_at = now
        return True

    async def cancel_stuck_once_tasks(self, *, error: str) -> int:
        """Reconcile ``once`` tasks orphaned in ``running`` by a process crash.

        A launched ``once`` task stays ``running`` until the in-process
        completion hook moves it to a terminal status; its lease was cleared at
        launch, so the claim query's expired-lease reclaim branch never sees
        it. After a crash the hook is gone and the task would be stuck forever.
        Tasks still holding a lease are left alone — they were claimed but not
        launched, and expired-lease reclaim recovers them safely.

        Outcome-aware: for each stuck task, looks up the latest
        ``scheduled_task_runs`` row.  If the run already reached a terminal
        status the parent task is finalised to match (``success`` →
        ``completed``, ``failed`` → ``failed``, ``interrupted`` →
        ``cancelled``, ``skipped`` → ``cancelled``).  While any occurrence
        row is still active (queued/launching/running), sequenced or not, the
        parent is left untouched: ``uq_scheduled_task_run_active`` makes that
        row the task's newest admission.  Tasks whose latest run row is absent
        receive the generic cancellation.
        """
        stmt = select(ScheduledTaskRow.id).where(
            ScheduledTaskRow.schedule_type == "once",
            ScheduledTaskRow.status == "running",
            ScheduledTaskRow.lease_expires_at.is_(None),
        )
        async with self._sf() as session:
            task_ids = list((await session.execute(stmt)).scalars())
            if not task_ids:
                return 0
            now = datetime.now(UTC)
            reconciled = 0
            for task_id in task_ids:
                # Row lock (no SQLite writer emulation, so the race regressions
                # can still commit concurrently): on Postgres this serialises
                # against admission, which locks the parent before inserting a
                # queued occurrence, so no live row can appear between the
                # probe below and this commit.
                task_row = await session.get(ScheduledTaskRow, task_id, with_for_update=True)
                if task_row is None or task_row.status != "running" or task_row.lease_expires_at is not None:
                    continue
                run_row = await self._fetch_latest_run(session, task_id)
                if await self._has_active_occurrence(session, task_id):
                    # The live row is the newest admission whatever its clock or
                    # sequence; its own completion, or a later pass once it is
                    # terminal, owns the parent.
                    continue
                if run_row is not None and not can_project(task_row, run_row):
                    # Same eligibility rule as every other parent write: a row
                    # that cannot project leaves the parent untouched.
                    continue
                if self._finalise_once_task_from_run(task_row, run_row, error=error, now=now):
                    reconciled += 1
            await session.commit()
            return reconciled

    async def reconcile_stuck_once_tasks(
        self,
        *,
        error: str,
        now: datetime,
        lease_grace_seconds: int = 10,
    ) -> int:
        """Cancel once tasks only after their underlying run is no longer live."""
        async with self._sf() as session:
            result = await session.execute(
                select(ScheduledTaskRow.id).where(
                    ScheduledTaskRow.schedule_type == "once",
                    ScheduledTaskRow.status == "running",
                )
            )
            task_ids = list(result.scalars())
            cancelled = 0
            for task_id in task_ids:
                task = await session.get(ScheduledTaskRow, task_id, with_for_update=True)
                if task is None or task.status != "running":
                    continue
                if _lease_is_alive(task.lease_expires_at, now=now, grace_seconds=0):
                    continue
                run_result = await session.execute(
                    select(ScheduledTaskRunRow)
                    .where(
                        ScheduledTaskRunRow.task_id == task.id,
                        ScheduledTaskRunRow.status.in_(("queued", "launching", "running")),
                    )
                    .order_by(ScheduledTaskRunRow.created_at.desc())
                    .limit(1)
                )
                task_run = run_result.scalars().first()
                candidate = await self._find_underlying_run(session, task_run, task)
                if candidate is not None and candidate.status in {"pending", "running"}:
                    if _lease_is_alive(candidate.lease_expires_at, now=now, grace_seconds=lease_grace_seconds):
                        continue
                    # Run takeover commits the durable RunRow in its own short
                    # transaction.  Its occurrence projection may remain active
                    # until reconcile_active_runs runs, so this pass can defer the
                    # parent and let the next poll finish task bookkeeping.
                    claimed = await self._run_repository.claim_for_takeover(
                        candidate.run_id,
                        grace_seconds=lease_grace_seconds,
                        error=error,
                        stop_reason="scheduled_task_orphan_recovered",
                    )
                    if not claimed:
                        refreshed = await self._run_repository.get(candidate.run_id, user_id=None)
                        if refreshed is not None and refreshed.get("status") in {"pending", "running"}:
                            continue
                # Finalise from the latest scheduled_task_run (unconditional lookup).
                # Filtering by terminal status only could exclude a newer skipped
                # or active row, causing us to finalise based on an older run.
                run_row = await self._fetch_latest_run(session, task.id)
                if await self._has_active_occurrence(session, task.id):
                    # Any live occurrence, sequenced or not, is the newest
                    # admission; reconcile_active_runs terminalises it once its
                    # durable run is gone and the next pass finalises the parent.
                    continue
                if run_row is not None and not can_project(task, run_row):
                    # Same eligibility rule as every other parent write.
                    continue
                if self._finalise_once_task_from_run(task, run_row, error=error, now=now):
                    cancelled += 1
            await session.commit()
            return cancelled

    @staticmethod
    async def _find_underlying_run(session: AsyncSession, task_run: ScheduledTaskRunRow | None, task: ScheduledTaskRow) -> RunRow | None:
        run_ids = [candidate for candidate in (task_run.run_id if task_run is not None else None, task.last_run_id) if candidate]
        for run_id in dict.fromkeys(run_ids):
            candidate = await session.get(RunRow, run_id)
            if candidate is None:
                continue
            linked_task_run_id = (candidate.metadata_json or {}).get("scheduled_task_run_id")
            if task_run is None or linked_task_run_id is None or linked_task_run_id == task_run.id:
                return candidate

        metadata_filter = RunRow.metadata_json["scheduled_task_id"].as_string() == task.id
        if task_run is not None:
            metadata_filter = RunRow.metadata_json["scheduled_task_run_id"].as_string() == task_run.id
        result = await session.execute(select(RunRow).where(metadata_filter).order_by(RunRow.created_at.desc()).limit(1))
        return result.scalars().first()
