from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

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
