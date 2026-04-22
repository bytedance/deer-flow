from sqlalchemy.ext.asyncio import AsyncSession

from store.repositories import (
    FeedbackRepositoryProtocol,
    RunEventRepositoryProtocol,
    RunRepositoryProtocol,
    ThreadMetaRepositoryProtocol,
)
from store.repositories.db import (
    DbFeedbackRepository,
    DbRunEventRepository,
    DbRunRepository,
    DbThreadMetaRepository,
)


def build_thread_meta_repository(session: AsyncSession) -> ThreadMetaRepositoryProtocol:
    return DbThreadMetaRepository(session)


def build_run_repository(session: AsyncSession) -> RunRepositoryProtocol:
    return DbRunRepository(session)


def build_feedback_repository(session: AsyncSession) -> FeedbackRepositoryProtocol:
    return DbFeedbackRepository(session)


def build_run_event_repository(session: AsyncSession) -> RunEventRepositoryProtocol:
    return DbRunEventRepository(session)
