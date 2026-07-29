"""Secondary adapter (owned persistence) -- the feedback table in SQL.

Implements ``FeedbackRepository`` from ``deerflow.domain.feedback.ports``.
This context owns the ``feedback`` table and writes its own queries, so
SQL/ORM vocabulary stops at this file: methods exchange domain objects,
translate ``IntegrityError`` into domain errors, and normalize SQLite's
tz-naive reads. Queries were migrated unchanged from the legacy repository
(now removed) to preserve behavior.

Sibling adapter: ``run_lookup.py`` serves the same context but owns no
table and writes no SQL -- see its docstring for why that distinction is
worth keeping visible.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.domain.feedback.exceptions import DuplicateFeedbackError
from deerflow.domain.feedback.model import Feedback
from deerflow.domain.feedback.ports import FeedbackRepository

# Transitional: the ORM row stays in the harness until PR-N moves engine,
# models, and migrations into app/adapters.
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
            comment=row.comment,
            tags=tuple(row.tags or ()),
            created_at=_tz_aware(row.created_at),
        )

    @staticmethod
    def _apply(row: FeedbackRow, feedback: Feedback) -> None:
        """Aggregate -> ORM row, in place. One explicit field list serves
        BOTH write paths (insert and update), so a new field cannot be
        stored on insert yet silently dropped on update. ``feedback_id``
        is deliberately absent: the surrogate key is fixed at insert and
        an upsert keeps the existing identity (see the port contract).
        Explicit field list rather than ``**asdict()``: new fields stay
        private until deliberately mapped here."""
        row.thread_id = feedback.thread_id
        row.run_id = feedback.run_id
        row.user_id = feedback.user_id
        row.rating = feedback.rating
        row.comment = feedback.comment
        row.tags = list(feedback.tags) or None
        row.created_at = feedback.created_at

    async def save(self, feedback: Feedback) -> Feedback:
        # Migrated from legacy ``upsert``: look up by aggregate identity,
        # then apply the aggregate onto the existing or a fresh row. The
        # identity fields are rewritten with equal values on update --
        # idempotent, and the price of a single field list.
        async with self._session_factory() as session:
            stmt = select(FeedbackRow).where(
                FeedbackRow.thread_id == feedback.thread_id,
                FeedbackRow.run_id == feedback.run_id,
                FeedbackRow.user_id == feedback.user_id,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                row = FeedbackRow(feedback_id=feedback.feedback_id)
                session.add(row)
            self._apply(row, feedback)
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
