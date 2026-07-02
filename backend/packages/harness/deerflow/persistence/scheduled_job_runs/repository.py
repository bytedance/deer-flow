"""SQL repository for the ``scheduled_job_runs`` table.

The repository trusts that the caller has already validated ``user_id``
against the parent job (which is enforced by ``ScheduledJobRepository``).
``user_id`` is stored on the run row at creation time and used in
subsequent list queries to avoid joins.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.scheduled_job_runs.model import ScheduledJobRunRow
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.time import coerce_datetime, coerce_iso

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _row_to_dict(row: ScheduledJobRunRow) -> dict[str, Any]:
    data = row.to_dict()
    for key in ("started_at", "finished_at"):
        value = data.get(key)
        if isinstance(value, datetime):
            data[key] = coerce_iso(value)
    return data


class ScheduledJobRunRepository:
    """Persistence facade for scheduled job execution history."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex

    async def create_run(
        self,
        *,
        job_id: str,
        user_id: str,
        thread_id: str,
        status: str = "running",
        started_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Begin a new run record. ``user_id`` is required — the caller
        must have it in hand (from the parent job row, not the ContextVar,
        because the scheduler runs across users).
        """
        row = ScheduledJobRunRow(
            id=self._new_id(),
            job_id=job_id,
            user_id=user_id,
            thread_id=thread_id,
            status=status,
            started_at=coerce_datetime(started_at) or _utc_now(),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _row_to_dict(row)

    async def mark_terminal(
        self,
        run_id: str,
        *,
        status: str,
        error_msg: str | None = None,
        token_usage: int | None = None,
        duration_ms: int | None = None,
        finished_at: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Flip a run from ``running`` to a terminal status and stamp
        ``finished_at``. ``status`` must be one of ``ok`` / ``error`` /
        ``skipped`` / ``timeout``.
        """
        values: dict[str, Any] = {
            "status": status,
            "finished_at": coerce_datetime(finished_at) or _utc_now(),
        }
        if error_msg is not None:
            values["error_msg"] = error_msg
        if token_usage is not None:
            values["token_usage"] = int(token_usage)
        if duration_ms is not None:
            values["duration_ms"] = int(duration_ms)

        async with self.session_factory() as session:
            await session.execute(update(ScheduledJobRunRow).where(ScheduledJobRunRow.id == run_id).values(**values))
            await session.commit()
            row = await session.get(ScheduledJobRunRow, run_id)
            return _row_to_dict(row) if row else None

    async def list_runs_for_job(
        self,
        job_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict[str, Any]]:
        """List execution history for one job, scoped to ``user_id``.

        ``user_id`` defaults to AUTO and must match the run row's
        ``user_id`` field. Pass ``None`` for admin scope (across users).
        """
        effective_uid = resolve_user_id(user_id, method_name="list_runs_for_job")
        async with self.session_factory() as session:
            stmt = select(ScheduledJobRunRow).where(ScheduledJobRunRow.job_id == job_id)
            if effective_uid is not None:
                stmt = stmt.where(ScheduledJobRunRow.user_id == effective_uid)
            stmt = stmt.order_by(ScheduledJobRunRow.started_at.desc()).limit(limit).offset(offset)
            result = await session.execute(stmt)
            return [_row_to_dict(row) for row in result.scalars()]

    async def list_recent_runs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict[str, Any]]:
        """List recent runs across all of the user's jobs, newest first.

        ``user_id=None`` returns runs across all users (admin scope).
        """
        effective_uid = resolve_user_id(user_id, method_name="list_recent_runs")
        async with self.session_factory() as session:
            stmt = select(ScheduledJobRunRow)
            if effective_uid is not None:
                stmt = stmt.where(ScheduledJobRunRow.user_id == effective_uid)
            stmt = stmt.order_by(ScheduledJobRunRow.started_at.desc()).limit(limit).offset(offset)
            result = await session.execute(stmt)
            return [_row_to_dict(row) for row in result.scalars()]

    async def sum_token_usage_since(
        self,
        *,
        since: datetime,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> int:
        """Sum token usage for ``user_id`` since ``since``. Used for
        per-user daily quota checks.

        ``user_id=None`` sums across all users (admin scope).
        """
        effective_uid = resolve_user_id(user_id, method_name="sum_token_usage_since")
        async with self.session_factory() as session:
            stmt = select(func.coalesce(func.sum(ScheduledJobRunRow.token_usage), 0)).where(ScheduledJobRunRow.started_at >= coerce_datetime(since))
            if effective_uid is not None:
                stmt = stmt.where(ScheduledJobRunRow.user_id == effective_uid)
            return int((await session.execute(stmt)).scalar() or 0)
