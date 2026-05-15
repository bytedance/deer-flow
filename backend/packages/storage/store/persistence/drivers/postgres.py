from __future__ import annotations

import json

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from store.persistence import MappedBase
from store.persistence.shared import close_in_order
from store.persistence.types import AppPersistence


def _checkpoint_conn_string(db_url: URL) -> str:
    return db_url.set(drivername="postgresql").render_as_string(hide_password=False)


async def build_postgres_persistence(db_url: URL, *, echo: bool = False, pool_size: int = 5) -> AppPersistence:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    import store.repositories.models  # noqa: F401

    engine = create_async_engine(
        db_url,
        echo=echo,
        future=True,
        pool_pre_ping=True,
        pool_size=pool_size,
        json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),
    )

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    saver_cm = AsyncPostgresSaver.from_conn_string(_checkpoint_conn_string(db_url))
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
