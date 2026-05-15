from __future__ import annotations

import json

from sqlalchemy import URL, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from store.persistence import MappedBase
from store.persistence.shared import close_in_order
from store.persistence.types import AppPersistence


async def build_sqlite_persistence(db_url: URL, *, echo: bool = False) -> AppPersistence:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    import store.repositories.models  # noqa: F401

    engine = create_async_engine(
        db_url,
        echo=echo,
        future=True,
        json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
        finally:
            cursor.close()

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
