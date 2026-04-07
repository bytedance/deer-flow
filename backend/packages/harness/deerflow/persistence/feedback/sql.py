"""SQLAlchemy-backed feedback storage.

Each method acquires its own short-lived session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.feedback.model import FeedbackRow


class FeedbackRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: FeedbackRow) -> dict:
        d = row.to_dict()
        val = d.get("created_at")
        if isinstance(val, datetime):
            d["created_at"] = val.isoformat()
        return d

    async def create(
        self,
        *,
        run_id: str,
        thread_id: str,
        rating: int,
        owner_id: str | None = None,
        message_id: str | None = None,
        comment: str | None = None,
    ) -> dict:
        """Create a feedback record. rating must be +1 or -1."""
        if rating not in (1, -1):
            raise ValueError(f"rating must be +1 or -1, got {rating}")
        row = FeedbackRow(
            feedback_id=str(uuid.uuid4()),
            run_id=run_id,
            thread_id=thread_id,
            owner_id=owner_id,
            message_id=message_id,
            rating=rating,
            comment=comment,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(self, feedback_id: str) -> dict | None:
        async with self._sf() as session:
            row = await session.get(FeedbackRow, feedback_id)
            return self._row_to_dict(row) if row else None

    async def list_by_run(self, thread_id: str, run_id: str, *, limit: int = 100) -> list[dict]:
        stmt = select(FeedbackRow).where(FeedbackRow.thread_id == thread_id, FeedbackRow.run_id == run_id).order_by(FeedbackRow.created_at.asc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def list_by_thread(self, thread_id: str, *, limit: int = 100) -> list[dict]:
        stmt = select(FeedbackRow).where(FeedbackRow.thread_id == thread_id).order_by(FeedbackRow.created_at.asc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def delete(self, feedback_id: str) -> bool:
        async with self._sf() as session:
            row = await session.get(FeedbackRow, feedback_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def aggregate_by_run(self, thread_id: str, run_id: str) -> dict:
        """Aggregate feedback stats for a run using database-side counting."""
        stmt = select(
            func.count().label("total"),
            func.coalesce(func.sum(case((FeedbackRow.rating == 1, 1), else_=0)), 0).label("positive"),
            func.coalesce(func.sum(case((FeedbackRow.rating == -1, 1), else_=0)), 0).label("negative"),
        ).where(FeedbackRow.thread_id == thread_id, FeedbackRow.run_id == run_id)
        async with self._sf() as session:
            row = (await session.execute(stmt)).one()
            return {
                "run_id": run_id,
                "total": row.total,
                "positive": row.positive,
                "negative": row.negative,
            }
