import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.anyio
async def test_wallet_is_unique_per_user(tmp_path):
    from deerflow.persistence.base import Base
    from deerflow.persistence.billing.model import WalletRow

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'billing.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add_all([WalletRow(user_id="user-1"), WalletRow(user_id="user-1")])
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()
