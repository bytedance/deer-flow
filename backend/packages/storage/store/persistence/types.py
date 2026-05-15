from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from langgraph.types import Checkpointer
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

AsyncSetup = Callable[[], Awaitable[None]]
AsyncClose = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class AppPersistence:
    """
    Unified runtime persistence bundle.
    """

    checkpointer: Checkpointer
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    setup: AsyncSetup
    aclose: AsyncClose
