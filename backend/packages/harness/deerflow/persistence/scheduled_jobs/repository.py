"""SQL repository for the ``scheduled_jobs`` table.

All public methods take a ``user_id`` keyword argument that defaults to
``AUTO`` (resolved from the request-scoped ContextVar). This forces every
caller to either (a) let user context propagate naturally, (b) override
with an explicit ``str`` for tests / admin tools, or (c) explicitly opt
out with ``user_id=None`` for migrations. See
``deerflow.runtime.user_context.resolve_user_id``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.scheduled_jobs.model import ScheduledJobRow
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.time import coerce_datetime, coerce_iso

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _row_to_dict(row: ScheduledJobRow) -> dict[str, Any]:
    """Serialise a row to a plain dict suitable for API responses.

    Datetimes are normalised to ISO 8601 strings. ``trigger_data`` is
    passed through as-is (already JSON-shaped).
    """
    data = row.to_dict()
    for key in ("next_run_at", "last_run_at", "next_retry_at", "created_at", "updated_at"):
        value = data.get(key)
        if isinstance(value, datetime):
            data[key] = coerce_iso(value)
    return data


class ScheduledJobRepository:
    """Persistence facade for scheduled jobs.

    Construct with the shared session factory from
    ``deerflow.persistence.engine``. Do not instantiate per-request — the
    factory is cheap to share and pools connections.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex

    @staticmethod
    def new_job_id() -> str:
        """Return an id callers can use before computing job-id based schedules."""
        return ScheduledJobRepository._new_id()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_job(
        self,
        *,
        name: str,
        description: str,
        trigger_type: str,
        trigger_data: dict[str, Any],
        next_run_at: datetime,
        thread_strategy: str = "new",
        fixed_thread_id: str | None = None,
        agent_name: str | None = None,
        delete_after_run: bool = False,
        source_channel: str = "web",
        enabled: bool = True,
        job_id: str | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, Any]:
        """Insert a new scheduled job.

        ``user_id`` defaults to AUTO — resolved from the request ContextVar.
        """
        effective_uid = resolve_user_id(user_id, method_name="create_job")
        row = ScheduledJobRow(
            id=job_id or self._new_id(),
            user_id=effective_uid,
            name=name,
            description=description,
            trigger_type=trigger_type,
            trigger_data=dict(trigger_data),
            thread_strategy=thread_strategy,
            fixed_thread_id=fixed_thread_id,
            agent_name=agent_name,
            enabled=enabled,
            next_run_at=coerce_datetime(next_run_at) or _utc_now(),
            delete_after_run=delete_after_run,
            source_channel=source_channel,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _row_to_dict(row)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_job(
        self,
        job_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, Any] | None:
        """Return one job by id, scoped to ``user_id``.

        Returns ``None`` when the row does not exist or (when
        ``user_id`` is not ``None``) belongs to a different user.

        ``user_id=None`` is the admin escape hatch — returns the row
        regardless of owner (used by the scheduler, which is
        cross-user).
        """
        effective_uid = resolve_user_id(user_id, method_name="get_job")
        async with self.session_factory() as session:
            row = await session.get(ScheduledJobRow, job_id)
            if row is None:
                return None
            if effective_uid is not None and row.user_id != effective_uid:
                return None
            return _row_to_dict(row)

    async def list_jobs(
        self,
        *,
        include_disabled: bool = False,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict[str, Any]]:
        """List jobs owned by ``user_id``, newest first.

        ``user_id=None`` is the admin escape hatch — returns jobs across
        all users (no WHERE clause). Use sparingly.
        """
        effective_uid = resolve_user_id(user_id, method_name="list_jobs")
        async with self.session_factory() as session:
            stmt = select(ScheduledJobRow)
            if effective_uid is not None:
                stmt = stmt.where(ScheduledJobRow.user_id == effective_uid)
            if not include_disabled:
                stmt = stmt.where(ScheduledJobRow.enabled.is_(True))
            stmt = stmt.order_by(ScheduledJobRow.created_at.desc()).limit(limit).offset(offset)
            result = await session.execute(stmt)
            return [_row_to_dict(row) for row in result.scalars()]

    async def list_due_jobs(
        self,
        *,
        now: datetime | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return all enabled jobs with ``next_run_at <= now``.

        ⚠ **Admin scope** — does NOT filter by user_id. The scheduler runs
        across all users. Per-user isolation is enforced at execution time
        via ``set_current_user(job.user_id)`` in the executor.
        """
        cutoff = coerce_datetime(now) or _utc_now()
        async with self.session_factory() as session:
            stmt = select(ScheduledJobRow).where(ScheduledJobRow.enabled.is_(True)).where(ScheduledJobRow.next_run_at <= cutoff).order_by(ScheduledJobRow.next_run_at.asc()).limit(limit)
            result = await session.execute(stmt)
            return [_row_to_dict(row) for row in result.scalars()]

    async def list_all_enabled_jobs(self) -> list[dict[str, Any]]:
        """All enabled jobs, regardless of user. Used at scheduler startup
        to rebuild the in-memory schedule.

        ⚠ **Admin scope** — does NOT filter by user_id.
        """
        async with self.session_factory() as session:
            stmt = select(ScheduledJobRow).where(ScheduledJobRow.enabled.is_(True)).order_by(ScheduledJobRow.next_run_at.asc())
            result = await session.execute(stmt)
            return [_row_to_dict(row) for row in result.scalars()]

    async def count_enabled_jobs(
        self,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> int:
        """Count enabled jobs for ``user_id``. Used for per-user quota
        enforcement (e.g. "max 20 enabled jobs per user").

        ``user_id=None`` counts across all users (admin scope).
        """
        effective_uid = resolve_user_id(user_id, method_name="count_enabled_jobs")
        async with self.session_factory() as session:
            stmt = select(func.count()).select_from(ScheduledJobRow).where(ScheduledJobRow.enabled.is_(True))
            if effective_uid is not None:
                stmt = stmt.where(ScheduledJobRow.user_id == effective_uid)
            return int((await session.execute(stmt)).scalar() or 0)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update_scheduling_state(
        self,
        job_id: str,
        *,
        next_run_at: datetime | None = None,
        last_run_at: datetime | None = None,
        last_status: str | None = None,
        consecutive_errors: int | None = None,
        next_retry_at: datetime | None = None,
        enabled: bool | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, Any] | None:
        """Patch scheduling-state fields. ``None`` arguments are ignored.

        Returns the updated row dict, or ``None`` when the job does not
        exist / belongs to another user.
        """
        effective_uid = resolve_user_id(user_id, method_name="update_scheduling_state")
        values: dict[str, Any] = {}
        if next_run_at is not None:
            values["next_run_at"] = coerce_datetime(next_run_at)
        if last_run_at is not None:
            values["last_run_at"] = coerce_datetime(last_run_at)
        if last_status is not None:
            values["last_status"] = last_status
        if consecutive_errors is not None:
            values["consecutive_errors"] = consecutive_errors
        if next_retry_at is not None:
            values["next_retry_at"] = coerce_datetime(next_retry_at)
        if enabled is not None:
            values["enabled"] = enabled
        if not values:
            return await self.get_job(job_id, user_id=user_id)

        async with self.session_factory() as session:
            stmt = update(ScheduledJobRow).where(ScheduledJobRow.id == job_id)
            if effective_uid is not None:
                stmt = stmt.where(ScheduledJobRow.user_id == effective_uid)
            stmt = stmt.values(**values)
            await session.execute(stmt)
            await session.commit()
        return await self.get_job(job_id, user_id=user_id)

    async def update_job_spec(
        self,
        job_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        trigger_type: str | None = None,
        trigger_data: dict[str, Any] | None = None,
        next_run_at: datetime | None = None,
        thread_strategy: str | None = None,
        fixed_thread_id: str | None = None,
        agent_name: str | None = None,
        enabled: bool | None = None,
        delete_after_run: bool | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, Any] | None:
        """Patch user-editable job fields (name, trigger, etc).

        Used by the PATCH endpoint. Mutating ``trigger_type`` /
        ``trigger_data`` also recomputes ``next_run_at`` unless caller
        provides one.
        """
        effective_uid = resolve_user_id(user_id, method_name="update_job_spec")
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        if trigger_type is not None:
            values["trigger_type"] = trigger_type
        if trigger_data is not None:
            values["trigger_data"] = dict(trigger_data)
        if thread_strategy is not None:
            values["thread_strategy"] = thread_strategy
        if fixed_thread_id is not None:
            values["fixed_thread_id"] = fixed_thread_id
        if agent_name is not None:
            values["agent_name"] = agent_name
        if enabled is not None:
            values["enabled"] = enabled
        if delete_after_run is not None:
            values["delete_after_run"] = delete_after_run
        if next_run_at is not None:
            values["next_run_at"] = coerce_datetime(next_run_at)

        if not values:
            return await self.get_job(job_id, user_id=user_id)

        async with self.session_factory() as session:
            stmt = update(ScheduledJobRow).where(ScheduledJobRow.id == job_id)
            if effective_uid is not None:
                stmt = stmt.where(ScheduledJobRow.user_id == effective_uid)
            stmt = stmt.values(**values)
            await session.execute(stmt)
            await session.commit()
        return await self.get_job(job_id, user_id=user_id)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_job(
        self,
        job_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> bool:
        """Hard-delete a job. Returns True if a row was removed.

        ``user_id=None`` is the admin scope (scheduler auto-delete on
        one-shot completion).
        """
        effective_uid = resolve_user_id(user_id, method_name="delete_job")
        async with self.session_factory() as session:
            stmt = delete(ScheduledJobRow).where(ScheduledJobRow.id == job_id)
            if effective_uid is not None:
                stmt = stmt.where(ScheduledJobRow.user_id == effective_uid)
            result = await session.execute(stmt)
            await session.commit()
            return (result.rowcount or 0) > 0

    async def disable_job(
        self,
        job_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, Any] | None:
        """Soft-disable a job (set ``enabled=False``). Used when an AT job
        completes with ``delete_after_run=False``.
        """
        return await self.update_scheduling_state(job_id, enabled=False, user_id=user_id)
