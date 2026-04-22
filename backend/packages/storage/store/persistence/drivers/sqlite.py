
from __future__ import annotations

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from store.persistence import MappedBase
from store.persistence.shared import close_in_order
from store.persistence.types import AppPersistence


async def build_sqlite_persistence(db_url: URL) -> AppPersistence:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    engine = create_async_engine(
        db_url,
        future=True,
    )

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    saver_cm = AsyncSqliteSaver.from_conn_string(db_url.database)
    checkpointer = await saver_cm.__aenter__()

    async def setup() -> None:
        # 1. LangGraph checkpoint tables
        await checkpointer.setup()

        # 2. ORM business tables
        async with engine.begin() as conn:
            await conn.run_sync(MappedBase.metadata.create_all)

    async def _close_saver() -> None:
        await saver_cm.__aexit__(None, None, None)

    async def aclose() -> None:
        await close_in_order(
            engine.dispose,
            _close_saver,
        )

    return AppPersistence(
        checkpointer=checkpointer,
        engine=engine,
        session_factory=session_factory,
        setup=setup,
        aclose=aclose,
    )
