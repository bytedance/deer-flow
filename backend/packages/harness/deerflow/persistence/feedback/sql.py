"""SQLAlchemy-backed feedback storage.

Each method acquires its own short-lived session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.feedback.model import FeedbackRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.persistence.workspaces.scope import lock_resource_scope, resolve_resource_scope
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.time import coerce_iso


class FeedbackRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, workspace_required: bool = False) -> None:
        self._sf = session_factory
        self._workspace_required = workspace_required

    def _scope(self, user_id):
        return resolve_resource_scope(None, user_id, required=self._workspace_required)

    def _read_scope(self, stmt, user_id):
        context = self._scope(user_id)
        if user_id is not None:
            stmt = stmt.where(FeedbackRow.user_id == user_id)
        if context is not None:
            parent = ThreadMetaRepository._owned_scope(select(ThreadMetaRow.thread_id).where(ThreadMetaRow.thread_id == FeedbackRow.thread_id), user_id, context).correlate(FeedbackRow).exists()
            run = (
                select(RunRow.run_id)
                .where(RunRow.run_id == FeedbackRow.run_id, RunRow.thread_id == FeedbackRow.thread_id, RunRow.user_id == user_id, RunRow.workspace_id == context.workspace_id, RunRow.operation_kind == "run")
                .correlate(FeedbackRow)
                .exists()
            )
            stmt = stmt.where(parent, run)
        return stmt

    def _write_scope(self, user_id, incarnation):
        context = self._scope(user_id)
        if context is not None and (not isinstance(incarnation, str) or not incarnation):
            raise WorkspaceAccessDenied("feedback writes require captured thread identity")
        return context

    async def _lock_run(self, session, thread_id, run_id, user_id, context, incarnation):
        if context is None:
            return
        await lock_resource_scope(session, context)
        thread = await session.scalar(ThreadMetaRepository._owned_scope(select(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id), user_id, context).with_for_update())
        if thread is None or thread.incarnation != incarnation:
            raise WorkspaceAccessDenied("feedback thread changed before commit")
        run = await session.scalar(
            select(RunRow.run_id).where(RunRow.run_id == run_id, RunRow.thread_id == thread_id, RunRow.user_id == user_id, RunRow.workspace_id == context.workspace_id, RunRow.operation_kind == "run").with_for_update()
        )
        if run is None:
            raise WorkspaceAccessDenied("feedback run is unavailable")

    @staticmethod
    def _row_to_dict(row: FeedbackRow) -> dict:
        d = row.to_dict()
        val = d.get("created_at")
        if isinstance(val, datetime):
            # SQLite drops tzinfo on read; normalize via ``coerce_iso`` so output is always tz-aware.
            d["created_at"] = coerce_iso(val)
        return d

    async def create(
        self,
        *,
        run_id: str,
        thread_id: str,
        rating: int,
        user_id: str | None | _AutoSentinel = AUTO,
        message_id: str | None = None,
        comment: str | None = None,
        incarnation: str | None = None,
    ) -> dict:
        """Create a feedback record. rating must be +1 or -1."""
        if rating not in (1, -1):
            raise ValueError(f"rating must be +1 or -1, got {rating}")
        resolved_user_id = resolve_user_id(user_id, method_name="FeedbackRepository.create")
        context = self._write_scope(resolved_user_id, incarnation)
        row = FeedbackRow(
            feedback_id=str(uuid.uuid4()),
            run_id=run_id,
            thread_id=thread_id,
            user_id=resolved_user_id,
            message_id=message_id,
            rating=rating,
            comment=comment,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            await self._lock_run(session, thread_id, run_id, resolved_user_id, context, incarnation)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(
        self,
        feedback_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        resolved_user_id = resolve_user_id(user_id, method_name="FeedbackRepository.get")
        async with self._sf() as session:
            row = await session.scalar(self._read_scope(select(FeedbackRow).where(FeedbackRow.feedback_id == feedback_id), resolved_user_id))
            if row is None:
                return None
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return None
            return self._row_to_dict(row)

    async def list_by_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        limit: int = 100,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict]:
        resolved_user_id = resolve_user_id(user_id, method_name="FeedbackRepository.list_by_run")
        stmt = select(FeedbackRow).where(FeedbackRow.thread_id == thread_id, FeedbackRow.run_id == run_id)
        stmt = self._read_scope(stmt, resolved_user_id)
        stmt = stmt.order_by(FeedbackRow.created_at.asc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def list_by_thread(
        self,
        thread_id: str,
        *,
        limit: int = 100,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict]:
        resolved_user_id = resolve_user_id(user_id, method_name="FeedbackRepository.list_by_thread")
        stmt = select(FeedbackRow).where(FeedbackRow.thread_id == thread_id)
        stmt = self._read_scope(stmt, resolved_user_id)
        stmt = stmt.order_by(FeedbackRow.created_at.asc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def delete(
        self,
        feedback_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
        incarnation: str | None = None,
    ) -> bool:
        resolved_user_id = resolve_user_id(user_id, method_name="FeedbackRepository.delete")
        context = self._write_scope(resolved_user_id, incarnation)
        # Locator discovery is read-only and separate from the short writer
        # transaction (including SQLite BEGIN IMMEDIATE).
        async with self._sf() as discovery:
            candidate = (await discovery.execute(self._read_scope(select(FeedbackRow.thread_id, FeedbackRow.run_id).where(FeedbackRow.feedback_id == feedback_id), resolved_user_id))).one_or_none()
        if candidate is None:
            return False
        async with self._sf() as session:
            await self._lock_run(session, candidate.thread_id, candidate.run_id, resolved_user_id, context, incarnation)
            stmt = self._read_scope(select(FeedbackRow).where(FeedbackRow.feedback_id == feedback_id, FeedbackRow.thread_id == candidate.thread_id, FeedbackRow.run_id == candidate.run_id), resolved_user_id)
            row = await session.scalar(stmt.with_for_update())
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def upsert(
        self,
        *,
        run_id: str,
        thread_id: str,
        rating: int,
        user_id: str | None | _AutoSentinel = AUTO,
        comment: str | None = None,
        incarnation: str | None = None,
    ) -> dict:
        """Create or update feedback for (thread_id, run_id, user_id). rating must be +1 or -1."""
        if rating not in (1, -1):
            raise ValueError(f"rating must be +1 or -1, got {rating}")
        resolved_user_id = resolve_user_id(user_id, method_name="FeedbackRepository.upsert")
        context = self._write_scope(resolved_user_id, incarnation)
        async with self._sf() as session:
            await self._lock_run(session, thread_id, run_id, resolved_user_id, context, incarnation)
            stmt = select(FeedbackRow).where(
                FeedbackRow.thread_id == thread_id,
                FeedbackRow.run_id == run_id,
                FeedbackRow.user_id == resolved_user_id,
            )
            result = await session.execute(stmt.with_for_update())
            row = result.scalar_one_or_none()
            if row is not None:
                row.rating = rating
                row.comment = comment
                row.created_at = datetime.now(UTC)
            else:
                row = FeedbackRow(
                    feedback_id=str(uuid.uuid4()),
                    run_id=run_id,
                    thread_id=thread_id,
                    user_id=resolved_user_id,
                    rating=rating,
                    comment=comment,
                    created_at=datetime.now(UTC),
                )
                session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def delete_by_run(
        self,
        *,
        thread_id: str,
        run_id: str,
        user_id: str | None | _AutoSentinel = AUTO,
        incarnation: str | None = None,
    ) -> bool:
        """Delete the current user's feedback for a run. Returns True if a record was deleted."""
        resolved_user_id = resolve_user_id(user_id, method_name="FeedbackRepository.delete_by_run")
        context = self._write_scope(resolved_user_id, incarnation)
        async with self._sf() as session:
            await self._lock_run(session, thread_id, run_id, resolved_user_id, context, incarnation)
            stmt = select(FeedbackRow).where(
                FeedbackRow.thread_id == thread_id,
                FeedbackRow.run_id == run_id,
                FeedbackRow.user_id == resolved_user_id,
            )
            result = await session.execute(stmt.with_for_update())
            row = result.scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def delete_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> int:
        """Delete the owner's feedback for every run of a thread.

        ``user_id`` keeps the repository's three-state convention: ``AUTO``
        resolves the request context, an explicit id scopes the delete to that
        owner, and ``None`` removes every owner's rows (migration/CLI callers).
        """
        resolved_user_id = resolve_user_id(user_id, method_name="FeedbackRepository.delete_by_thread")
        if self._scope(resolved_user_id) is not None:
            raise WorkspaceAccessDenied("workspace bulk cleanup requires the canonical thread deletion receipt")

        conditions = [FeedbackRow.thread_id == thread_id]
        if resolved_user_id is not None:
            conditions.append(FeedbackRow.user_id == resolved_user_id)

        async with self._sf() as session:
            count = await session.scalar(select(func.count()).select_from(FeedbackRow).where(*conditions)) or 0
            if count:
                await session.execute(delete(FeedbackRow).where(*conditions))
            await session.commit()
            return count

    async def list_by_thread_grouped(
        self,
        thread_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, dict]:
        """Return feedback grouped by run_id for a thread: {run_id: feedback_dict}.

        With an explicit ``None`` user id (unfiltered reads) several users may
        hold feedback on the same run, so order deterministically — the
        per-run collapse below keeps the last row per ``run_id``, i.e. the
        most recently written feedback (``created_at`` is refreshed on
        update), with ``feedback_id`` breaking ties.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="FeedbackRepository.list_by_thread_grouped")
        stmt = select(FeedbackRow).where(FeedbackRow.thread_id == thread_id)
        stmt = self._read_scope(stmt, resolved_user_id)
        stmt = stmt.order_by(FeedbackRow.created_at.asc(), FeedbackRow.feedback_id.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return {row.run_id: self._row_to_dict(row) for row in result.scalars()}

    async def list_by_run_ids(
        self,
        thread_id: str,
        run_ids: set[str],
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, dict]:
        """Return feedback for only the selected runs in one thread.

        Same deterministic ordering as :meth:`list_by_thread_grouped`: with an
        explicit ``None`` user id the per-run collapse keeps the most recently
        written feedback (``created_at`` is refreshed on update), ties broken
        by ``feedback_id``.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="FeedbackRepository.list_by_run_ids")
        self._scope(resolved_user_id)
        if not run_ids:
            return {}
        stmt = select(FeedbackRow).where(
            FeedbackRow.thread_id == thread_id,
            FeedbackRow.run_id.in_(run_ids),
        )
        stmt = self._read_scope(stmt, resolved_user_id)
        stmt = stmt.order_by(FeedbackRow.created_at.asc(), FeedbackRow.feedback_id.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return {row.run_id: self._row_to_dict(row) for row in result.scalars()}

    async def aggregate_by_run(self, thread_id: str, run_id: str, *, user_id: str | None | _AutoSentinel = None) -> dict:
        """Count visible feedback; unbound default preserves native all-owner stats."""
        resolved_user_id = resolve_user_id(user_id, method_name="FeedbackRepository.aggregate_by_run")
        stmt = select(
            func.count().label("total"),
            func.coalesce(func.sum(case((FeedbackRow.rating == 1, 1), else_=0)), 0).label("positive"),
            func.coalesce(func.sum(case((FeedbackRow.rating == -1, 1), else_=0)), 0).label("negative"),
        ).where(FeedbackRow.thread_id == thread_id, FeedbackRow.run_id == run_id)
        stmt = self._read_scope(stmt, resolved_user_id)
        async with self._sf() as session:
            row = (await session.execute(stmt)).one()
            return {
                "run_id": run_id,
                "total": row.total,
                "positive": row.positive,
                "negative": row.negative,
            }
