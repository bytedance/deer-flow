"""SQL adapters for the feedback bounded context.

Secondary adapters implementing the ports declared in
``deerflow.domain.feedback.ports``. SQL/ORM vocabulary stops at this
file: methods exchange domain objects, translate ``IntegrityError`` into
domain errors, and normalize SQLite's tz-naive reads. Queries were
migrated unchanged from the legacy repository (now removed) to preserve
behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.domain.feedback.model import DuplicateFeedbackError, Feedback
from deerflow.domain.feedback.ports import FeedbackRepository, RunLookup

# Transitional: the ORM row stays in the harness until PR-N moves engine,
# models, and migrations into app/infra.
from deerflow.persistence.feedback.model import FeedbackRow


def _tz_aware(value: datetime) -> datetime:
    """SQLite drops tzinfo on read; stored values are always UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class SqlFeedbackRepository(FeedbackRepository):
    """SQL implementation of the ``FeedbackRepository`` port.

    Explicit inheritance is a readability aid only: a missing method would
    still instantiate fine (Protocol bodies are inherited), so the contract
    test suite must cover every port method.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _to_domain(row: FeedbackRow) -> Feedback:
        """ORM row -> aggregate. The only place reads are normalized."""
        return Feedback(
            feedback_id=row.feedback_id,
            run_id=row.run_id,
            thread_id=row.thread_id,
            rating=row.rating,
            user_id=row.user_id,
            message_id=row.message_id,
            comment=row.comment,
            tags=tuple(row.tags or ()),
            created_at=_tz_aware(row.created_at),
        )

    @staticmethod
    def _to_row(feedback: Feedback) -> FeedbackRow:
        """Aggregate -> ORM row. Explicit field list: new columns stay
        private until deliberately mapped here."""
        return FeedbackRow(
            feedback_id=feedback.feedback_id,
            run_id=feedback.run_id,
            thread_id=feedback.thread_id,
            user_id=feedback.user_id,
            message_id=feedback.message_id,
            rating=feedback.rating,
            comment=feedback.comment,
            tags=list(feedback.tags) or None,
            created_at=feedback.created_at,
        )

    async def save(self, feedback: Feedback) -> Feedback:
        # Migrated from legacy ``upsert``: look up by aggregate identity,
        # then update in place or insert.
        async with self._session_factory() as session:
            stmt = select(FeedbackRow).where(
                FeedbackRow.thread_id == feedback.thread_id,
                FeedbackRow.run_id == feedback.run_id,
                FeedbackRow.user_id == feedback.user_id,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is not None:
                row.rating = feedback.rating
                row.comment = feedback.comment
                row.tags = list(feedback.tags) or None
                row.created_at = feedback.created_at
            else:
                row = self._to_row(feedback)
                session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                # Two concurrent upserts can both miss the lookup and insert;
                # the loser hits the unique constraint. Translate instead of
                # leaking the driver exception (legacy code returned a 500).
                raise DuplicateFeedbackError(f"concurrent feedback upsert for run {feedback.run_id}") from exc
            await session.refresh(row)
            return self._to_domain(row)

    async def latest_per_run_in_thread(self, thread_id: str, *, user_id: str | None) -> dict[str, Feedback]:
        # Migrated from legacy ``list_by_thread_grouped``. With an ownership
        # filter the unique constraint guarantees at most one row per run.
        stmt = select(FeedbackRow).where(FeedbackRow.thread_id == thread_id)
        if user_id is not None:
            stmt = stmt.where(FeedbackRow.user_id == user_id)
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return {row.run_id: self._to_domain(row) for row in result.scalars()}

    async def latest_for_runs(self, thread_id: str, run_ids: set[str], *, user_id: str | None) -> dict[str, Feedback]:
        # Migrated from legacy ``list_by_run_ids`` (paged message list).
        if not run_ids:
            return {}
        stmt = select(FeedbackRow).where(
            FeedbackRow.thread_id == thread_id,
            FeedbackRow.run_id.in_(run_ids),
        )
        if user_id is not None:
            stmt = stmt.where(FeedbackRow.user_id == user_id)
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return {row.run_id: self._to_domain(row) for row in result.scalars()}

    async def remove_for_run(self, thread_id: str, run_id: str, *, user_id: str | None) -> bool:
        # Migrated from legacy ``delete_by_run``.
        async with self._session_factory() as session:
            stmt = select(FeedbackRow).where(
                FeedbackRow.thread_id == thread_id,
                FeedbackRow.run_id == run_id,
                FeedbackRow.user_id == user_id,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True


class RunStoreRunLookup(RunLookup):
    """Adapts the framework ``RunStore`` (wide interface) to the narrow
    ``RunLookup`` port -- reuses the existing lookup, no new SQL.

    Used by the service for run-ownership checks before writing feedback.
    """

    def __init__(self, run_store) -> None:
        self._run_store = run_store

    async def thread_of(self, run_id: str) -> str | None:
        run = await self._run_store.get(run_id)
        return run.get("thread_id") if run else None
