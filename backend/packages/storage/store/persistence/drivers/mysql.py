from __future__ import annotations

from sqlalchemy import URL
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from store.persistence import MappedBase
from store.persistence.shared import close_in_order
from store.persistence.types import AppPersistence


def _validate_mysql_driver(db_url: str) -> str:
    url = make_url(db_url)
    driver = url.get_driver_name()

    if driver not in {"aiomysql", "asyncmy"}:
        raise ValueError(
            "MySQL persistence requires async SQLAlchemy driver "
            f"(aiomysql/asyncmy), got: {driver!r}"
        )
    return driver


async def build_mysql_persistence(db_url: URL) -> AppPersistence:
    _validate_mysql_driver(db_url)

    from langgraph.checkpoint.mysql.aio import AIOMySQLSaver

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

    saver_cm = AIOMySQLSaver.from_conn_string(db_url)
    checkpointer = await saver_cm.__aenter__()

    async def setup() -> None:
        # 1. LangGraph checkpoint tables / migrations
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
