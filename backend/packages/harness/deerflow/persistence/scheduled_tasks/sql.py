from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)

TERMINAL_TASK_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})
_SCHEDULER_BUDGET_LOCK_KEY = 4694001


def _lease_is_alive(lease_expires_at: datetime | None, *, now: datetime, grace_seconds: int = 0) -> bool:
    if lease_expires_at is None:
        return False
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    return lease_expires_at >= now - timedelta(seconds=grace_seconds)


class ScheduledTaskRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        run_repository: RunRepository | None = None,
    ) -> None:
        self._sf = session_factory
        self._run_repository = run_repository or RunRepository(session_factory)

    @staticmethod
    def _row_to_dict(row: ScheduledTaskRow) -> dict[str, Any]:
        data = row.to_dict()
        for key in (
            "created_at",
            "updated_at",
            "next_run_at",
            "last_run_at",
            "lease_expires_at",
        ):
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

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
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        row = ScheduledTaskRow(
            id=task_id,
            user_id=user_id,
            thread_id=thread_id,
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

    async def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        stmt = select(ScheduledTaskRow).where(ScheduledTaskRow.user_id == user_id).order_by(ScheduledTaskRow.created_at.desc(), ScheduledTaskRow.id.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def update(
        self,
        task_id: str,
        *,
        user_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None or row.user_id != user_id:
                return None
            for key, value in updates.items():
                if hasattr(row, key):
                    setattr(row, key, value)
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
        global_max_concurrent_runs: int | None = None,
    ) -> list[dict[str, Any]]:
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        async with self._sf() as session:
            if global_max_concurrent_runs is not None:
                if session.get_bind().dialect.name == "postgresql":
                    await session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": _SCHEDULER_BUDGET_LOCK_KEY})
                active_runs = await session.scalar(select(func.count()).select_from(ScheduledTaskRunRow).where(ScheduledTaskRunRow.status.in_(("queued", "running"))))
                active_run_for_task = exists(
                    select(ScheduledTaskRunRow.id).where(
                        ScheduledTaskRunRow.task_id == ScheduledTaskRow.id,
                        ScheduledTaskRunRow.status.in_(("queued", "running")),
                    )
                )
                dispatch_reservations = await session.scalar(
                    select(func.count())
                    .select_from(ScheduledTaskRow)
                    .where(
                        ScheduledTaskRow.lease_owner.is_not(None),
                        ScheduledTaskRow.lease_expires_at >= now,
                        ~active_run_for_task,
                    )
                )
                active = int(active_runs or 0) + int(dispatch_reservations or 0)
                limit = min(limit, max(0, global_max_concurrent_runs - active))
            if limit <= 0:
                return []
            stmt = (
                select(ScheduledTaskRow)
                .where(
                    ScheduledTaskRow.next_run_at.is_not(None),
                    ScheduledTaskRow.next_run_at <= now,
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

    async def update_after_launch(
        self,
        task_id: str,
        *,
        status: str,
        next_run_at: datetime | None,
        last_run_at: datetime | None,
        last_run_id: str | None,
        last_thread_id: str | None,
        last_error: str | None,
        increment_run_count: bool,
        protect_terminal: bool = False,
        expected_lease_owner: str | None = None,
    ) -> bool:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id, with_for_update=True)
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
            if protect_terminal and row.status in TERMINAL_TASK_STATUSES:
                # A fast-failing run can reach handle_run_completion (which
                # finalizes a `once` task) before this launch-path write
                # commits; keep the hook's status/error and only record the
                # launch bookkeeping.
                pass
            else:
                row.status = status
                row.last_error = last_error
            row.next_run_at = next_run_at
            row.last_run_at = last_run_at
            row.last_run_id = last_run_id
            row.last_thread_id = last_thread_id
            if increment_run_count:
                row.run_count += 1
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return True

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
        stmt = (
            select(ScheduledTaskRow)
            .where(
                ScheduledTaskRow.user_id == user_id,
                ScheduledTaskRow.thread_id == thread_id,
            )
            .order_by(ScheduledTaskRow.created_at.desc(), ScheduledTaskRow.id.desc())
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def cancel_stuck_once_tasks(self, *, error: str) -> int:
        """Reconcile ``once`` tasks orphaned in ``running`` by a process crash.

        A launched ``once`` task stays ``running`` until the in-process
        completion hook moves it to a terminal status; its lease was cleared at
        launch, so the claim query's expired-lease reclaim branch never sees
        it. After a crash the hook is gone and the task would be stuck forever.
        Tasks still holding a lease are left alone — they were claimed but not
        launched, and expired-lease reclaim recovers them safely.
        """
        stmt = select(ScheduledTaskRow).where(
            ScheduledTaskRow.schedule_type == "once",
            ScheduledTaskRow.status == "running",
            ScheduledTaskRow.lease_expires_at.is_(None),
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())
            now = datetime.now(UTC)
            for row in rows:
                row.status = "cancelled"
                row.last_error = error
                row.updated_at = now
            await session.commit()
            return len(rows)

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
                        ScheduledTaskRunRow.status.in_(("queued", "running")),
                    )
                    .order_by(ScheduledTaskRunRow.created_at.desc())
                    .limit(1)
                )
                task_run = run_result.scalars().first()
                candidate = await self._find_underlying_run(session, task_run, task)
                if candidate is not None and candidate.status in {"pending", "running"}:
                    if _lease_is_alive(candidate.lease_expires_at, now=now, grace_seconds=lease_grace_seconds):
                        continue
                    # Run takeover commits in its own short transaction. If this
                    # outer commit fails, the next poll finishes task bookkeeping
                    # while the underlying run remains safely terminal.
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
                task.status = "cancelled"
                task.last_error = error
                task.updated_at = datetime.now(UTC)
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
