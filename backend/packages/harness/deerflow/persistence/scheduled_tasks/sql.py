from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.utils.time import coerce_iso

TERMINAL_TASK_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})


class ScheduledTaskRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

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
    ) -> list[dict[str, Any]]:
        lease_expires_at = now + timedelta(seconds=lease_seconds)
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
        async with self._sf() as session:
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
    ) -> None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None:
                return
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
