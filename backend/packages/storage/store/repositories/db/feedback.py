from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from store.repositories.contracts.feedback import Feedback, FeedbackAggregate, FeedbackCreate, FeedbackRepositoryProtocol
from store.repositories.models.feedback import Feedback as FeedbackModel


def _to_feedback(m: FeedbackModel) -> Feedback:
    return Feedback(
        feedback_id=m.feedback_id,
        run_id=m.run_id,
        thread_id=m.thread_id,
        rating=m.rating,
        user_id=m.user_id,
        message_id=m.message_id,
        comment=m.comment,
        created_time=m.created_time,
    )


class DbFeedbackRepository(FeedbackRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_feedback(self, data: FeedbackCreate) -> Feedback:
        if data.rating not in (1, -1):
            raise ValueError(f"rating must be +1 or -1, got {data.rating}")
        model = FeedbackModel(
            feedback_id=data.feedback_id,
            run_id=data.run_id,
            thread_id=data.thread_id,
            rating=data.rating,
            user_id=data.user_id,
            message_id=data.message_id,
            comment=data.comment,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_feedback(model)

    async def upsert_feedback(self, data: FeedbackCreate) -> Feedback:
        if data.rating not in (1, -1):
            raise ValueError(f"rating must be +1 or -1, got {data.rating}")

        result = await self._session.execute(
            select(FeedbackModel).where(
                FeedbackModel.thread_id == data.thread_id,
                FeedbackModel.run_id == data.run_id,
                FeedbackModel.user_id == data.user_id,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return await self.create_feedback(data)

        model.rating = data.rating
        model.message_id = data.message_id
        model.comment = data.comment
        model.created_time = datetime.now(UTC)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_feedback(model)

    async def get_feedback(self, feedback_id: str) -> Feedback | None:
        result = await self._session.execute(select(FeedbackModel).where(FeedbackModel.feedback_id == feedback_id))
        model = result.scalar_one_or_none()
        return _to_feedback(model) if model else None

    async def list_feedback_by_run(
        self,
        run_id: str,
        *,
        thread_id: str | None = None,
        user_id: str | None = None,
        limit: int | None = None,
    ) -> list[Feedback]:
        stmt = select(FeedbackModel).where(FeedbackModel.run_id == run_id)
        if thread_id is not None:
            stmt = stmt.where(FeedbackModel.thread_id == thread_id)
        if user_id is not None:
            stmt = stmt.where(FeedbackModel.user_id == user_id)
        stmt = stmt.order_by(FeedbackModel.created_time.desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [_to_feedback(m) for m in result.scalars().all()]

    async def list_feedback_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        limit: int | None = None,
    ) -> list[Feedback]:
        stmt = select(FeedbackModel).where(FeedbackModel.thread_id == thread_id)
        if user_id is not None:
            stmt = stmt.where(FeedbackModel.user_id == user_id)
        stmt = stmt.order_by(FeedbackModel.created_time.desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [_to_feedback(m) for m in result.scalars().all()]

    async def delete_feedback(self, feedback_id: str) -> bool:
        existing = await self.get_feedback(feedback_id)
        if existing is None:
            return False
        await self._session.execute(delete(FeedbackModel).where(FeedbackModel.feedback_id == feedback_id))
        return True

    async def delete_feedback_by_run(self, thread_id: str, run_id: str, *, user_id: str | None = None) -> bool:
        stmt = select(FeedbackModel).where(
            FeedbackModel.thread_id == thread_id,
            FeedbackModel.run_id == run_id,
        )
        if user_id is not None:
            stmt = stmt.where(FeedbackModel.user_id == user_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return False
        await self._session.delete(model)
        return True

    async def aggregate_feedback_by_run(self, thread_id: str, run_id: str) -> FeedbackAggregate:
        stmt = select(
            func.count().label("total"),
            func.coalesce(func.sum(case((FeedbackModel.rating == 1, 1), else_=0)), 0).label("positive"),
            func.coalesce(func.sum(case((FeedbackModel.rating == -1, 1), else_=0)), 0).label("negative"),
        ).where(FeedbackModel.thread_id == thread_id, FeedbackModel.run_id == run_id)
        row = (await self._session.execute(stmt)).one()
        return {
            "run_id": run_id,
            "total": int(row.total),
            "positive": int(row.positive),
            "negative": int(row.negative),
        }
