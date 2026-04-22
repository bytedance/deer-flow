from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory = getattr(request.app.state.persistence, "session_factory", None)
    if factory is None:
        raise HTTPException(status_code=503, detail="Database session factory not available")
    return factory


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Open a session without auto-commit. Use for read-only endpoints."""
    session_factory = _get_session_factory(request)
    async with session_factory() as session:
        yield session


async def get_db_session_transaction(request: Request) -> AsyncIterator[AsyncSession]:
    """Open a session and commit on success, rollback on error."""
    session_factory = _get_session_factory(request)
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


CurrentSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentSessionTransaction = Annotated[AsyncSession, Depends(get_db_session_transaction)]
