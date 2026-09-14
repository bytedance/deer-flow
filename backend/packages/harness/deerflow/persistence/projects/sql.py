"""SQLAlchemy-backed project repository.

Ownership discipline mirrors ``ThreadMetaRepository``: every method resolves
the caller via ``resolve_user_id(..., AUTO)`` and filters by ``user_id``;
a foreign project is indistinguishable from a missing one (callers map
``None``/``False`` to 404). ``delete`` runs the Phase-1 membership-clearing
transaction from RFC v2 §5.1 (the ``project_documents`` statement joins this
transaction in Phase 2).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.projects.model import ProjectRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)

ProjectStatus = Literal["active", "archived"]


class ProjectNotAssignableError(ValueError):
    """Raised when a thread cannot be assigned to a project.

    The project is missing, foreign to the caller, or archived — the
    atomicity rules (RFC v2 §5.2) make these indistinguishable inside the
    mutating statement, so callers get one signal and map it to 404 (explicit
    API) or a dropped key (run admission).
    """


class ProjectRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ProjectRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    async def create(
        self,
        *,
        name: str,
        instructions: str = "",
        presentation: dict | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.create")
        now = datetime.now(UTC)
        row = ProjectRow(
            id=uuid.uuid4().hex,
            user_id=resolved_user_id,
            name=name,
            instructions=instructions,
            presentation=presentation or {},
            status="active",
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(self, project_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.get")
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None:
                return None
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return None
            return self._row_to_dict(row)

    async def list(
        self,
        *,
        status: ProjectStatus | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict]:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.list")
        stmt = select(ProjectRow).order_by(ProjectRow.created_at.asc(), ProjectRow.id.asc())
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectRow.user_id == resolved_user_id)
        if status is not None:
            stmt = stmt.where(ProjectRow.status == status)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def patch(
        self,
        project_id: str,
        *,
        name: str | None = None,
        instructions: str | None = None,
        presentation: dict | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.patch")
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None or (resolved_user_id is not None and row.user_id != resolved_user_id):
                return None
            if name is not None:
                row.name = name
            if instructions is not None:
                row.instructions = instructions
            if presentation is not None:
                row.presentation = presentation
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def set_status(
        self,
        project_id: str,
        status: ProjectStatus,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        """Idempotent status flip; returns the current row or None (missing/foreign)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.set_status")
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None or (resolved_user_id is not None and row.user_id != resolved_user_id):
                return None
            row.status = status
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def delete(self, project_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> bool:
        """Delete a project and clear membership in one transaction (no filesystem work).

        Returns True when the project row was deleted; False when missing/foreign.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.delete")
        async with self._sf() as session:
            async with session.begin():
                # Lock the project row before touching it (FOR UPDATE on
                # Postgres; the clause renders nothing on SQLite). Membership
                # assignment (ThreadMetaRepository.set_project/create) takes
                # the same row lock before writing ``project_id``, so an
                # assigner either commits first and has its membership cleared
                # below, or blocks until this transaction commits and then
                # re-reads the row as gone — no dangling ``threads_meta.project_id``
                # (RFC v2 §14.14). Missing/foreign rows keep the False result.
                lock_stmt = select(ProjectRow).where(ProjectRow.id == project_id)
                if resolved_user_id is not None:
                    lock_stmt = lock_stmt.where(ProjectRow.user_id == resolved_user_id)
                locked = (await session.execute(lock_stmt.with_for_update())).scalar_one_or_none()
                if locked is None:
                    return False
                if resolved_user_id is not None:
                    await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.project_id == project_id, ThreadMetaRow.user_id == resolved_user_id).values(project_id=None, updated_at=ThreadMetaRow.__table__.c.updated_at))
                    result = await session.execute(sa_delete(ProjectRow).where(ProjectRow.id == project_id, ProjectRow.user_id == resolved_user_id))
                else:
                    await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.project_id == project_id).values(project_id=None, updated_at=ThreadMetaRow.__table__.c.updated_at))
                    result = await session.execute(sa_delete(ProjectRow).where(ProjectRow.id == project_id))
            return result.rowcount > 0
