import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.anyio
async def test_reserve_rejects_insufficient_balance(tmp_path):
    from deerflow.persistence.base import Base
    from deerflow.persistence.billing.service import InsufficientCredits, WalletService

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wallet.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        service = WalletService(async_sessionmaker(engine, expire_on_commit=False))
        await service.credit("user-1", 10, "seed")
        with pytest.raises(InsufficientCredits) as exc_info:
            await service.reserve_credits("user-1", "run-1", 11)
        assert exc_info.value.available_credits == 10
        assert exc_info.value.required_credits == 11
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_reserve_moves_credits_and_is_idempotent(tmp_path):
    from deerflow.persistence.base import Base
    from deerflow.persistence.billing.service import WalletService

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wallet.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        service = WalletService(async_sessionmaker(engine, expire_on_commit=False))
        await service.credit("user-1", 10, "seed")
        first = await service.reserve_credits("user-1", "run-1", 6)
        second = await service.reserve_credits("user-1", "run-1", 6)
        assert first.available_credits == 4
        assert first.reserved_credits == 6
        assert second == first
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_settlement_charges_actual_usage_and_releases_unused_credits(tmp_path):
    from deerflow.persistence.base import Base
    from deerflow.persistence.billing.service import WalletService

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wallet.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        service = WalletService(async_sessionmaker(engine, expire_on_commit=False))
        await service.credit("user-1", 10, "seed")
        await service.reserve_credits("user-1", "run-1", 6)
        wallet = await service.settle_run("user-1", "run-1", 4)
        assert wallet.available_credits == 6
        assert wallet.reserved_credits == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_credit_reference_type_is_preserved_for_payment_idempotency(tmp_path):
    from sqlalchemy import select

    from deerflow.persistence.base import Base
    from deerflow.persistence.billing.model import CreditLedgerRow
    from deerflow.persistence.billing.service import WalletService

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wallet.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        await WalletService(session_factory).credit("user-1", 100, "order-1", reference_type="recharge")
        async with session_factory() as session:
            row = await session.scalar(select(CreditLedgerRow).where(CreditLedgerRow.reference_id == "order-1"))
        assert row is not None
        assert row.reference_type == "recharge"
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_mock_payment_is_idempotent_and_records_an_order(tmp_path):
    from sqlalchemy import select

    from deerflow.persistence.base import Base
    from deerflow.persistence.billing.model import PaymentOrderRow
    from deerflow.persistence.billing.service import WalletService

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wallet.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        service = WalletService(session_factory)
        created = await service.create_mock_payment("user-1", provider="wechat", credits=100, idempotency_key="idempotency-1")
        retried = await service.create_mock_payment("user-1", provider="wechat", credits=100, idempotency_key="idempotency-1")
        assert created.wallet.available_credits == 100
        assert retried.wallet.available_credits == 100
        assert retried.idempotent is True
        assert retried.order_id == created.order_id
        async with session_factory() as session:
            orders = list((await session.scalars(select(PaymentOrderRow))).all())
        assert len(orders) == 1
        assert orders[0].status == "paid"
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_usage_settlement_persists_price_snapshot(tmp_path):
    from sqlalchemy import select

    from deerflow.persistence.base import Base
    from deerflow.persistence.billing.model import ModelPricePolicyRow, UsageRecordRow
    from deerflow.persistence.billing.service import WalletService

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wallet.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add(
                ModelPricePolicyRow(
                    id="policy-1",
                    model_name="test-model",
                    input_fen_per_million=1,
                    output_fen_per_million=1,
                    cache_read_fen_per_million=1,
                    credit_multiplier_bps=10000,
                    max_reservation_credits=20,
                )
            )
            await session.commit()
        service = WalletService(session_factory)
        await service.credit("user-1", 20, "seed")
        await service.reserve_credits("user-1", "run-1", 20)
        wallet = await service.settle_run_usage("user-1", "run-1", {"test-model": {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 100_000}})
        assert wallet.available_credits == 18
        assert wallet.reserved_credits == 0
        async with session_factory() as session:
            record = await session.scalar(select(UsageRecordRow))
        assert record is not None
        assert record.charged_credits == 2
        assert record.price_snapshot["policy_id"] == "policy-1"
    finally:
        await engine.dispose()
