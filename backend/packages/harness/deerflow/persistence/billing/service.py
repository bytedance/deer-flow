"""Transactional, user-scoped credit wallet operations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.billing.model import (
    CreditLedgerRow,
    ModelPricePolicyRow,
    PaymentOrderRow,
    UsageRecordRow,
    WalletRow,
)


@dataclass(frozen=True)
class WalletSnapshot:
    available_credits: int
    reserved_credits: int


@dataclass(frozen=True)
class MockPaymentResult:
    order_id: str
    provider: str
    status: str
    wallet: WalletSnapshot
    idempotent: bool


class InsufficientCredits(RuntimeError):
    def __init__(self, available_credits: int, required_credits: int) -> None:
        super().__init__("INSUFFICIENT_CREDITS")
        self.available_credits = available_credits
        self.required_credits = required_credits


class WalletService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _snapshot(row: WalletRow) -> WalletSnapshot:
        return WalletSnapshot(row.available_credits, row.reserved_credits)

    async def credit(self, user_id: str, credits: int, reference_id: str, *, reference_type: str = "credit", actor_user_id: str | None = None, reason: str | None = None) -> WalletSnapshot:
        if credits <= 0:
            raise ValueError("credits must be positive")
        async with self._sf() as session:
            async with session.begin():
                wallet = await self._get_locked_wallet(session, user_id)
                wallet.available_credits += credits
                wallet.version += 1
                session.add(CreditLedgerRow(id=uuid4().hex, user_id=user_id, entry_type="credit", credit_delta=credits, reference_type=reference_type, reference_id=reference_id, actor_user_id=actor_user_id, reason=reason))
            return self._snapshot(wallet)

    async def adjust_credits(self, user_id: str, credits: int, reference_id: str, *, actor_user_id: str, reason: str) -> WalletSnapshot:
        if credits == 0:
            raise ValueError("credits must not be zero")
        if credits > 0:
            async with self._sf() as session:
                async with session.begin():
                    wallet = await self._get_locked_wallet(session, user_id)
                    wallet.available_credits += credits
                    wallet.version += 1
                    session.add(CreditLedgerRow(id=uuid4().hex, user_id=user_id, entry_type="admin_credit", credit_delta=credits, reference_type="admin_adjustment", reference_id=reference_id, actor_user_id=actor_user_id, reason=reason))
                return self._snapshot(wallet)
        async with self._sf() as session:
            async with session.begin():
                wallet = await self._get_locked_wallet(session, user_id)
                amount = -credits
                if wallet.available_credits < amount:
                    raise InsufficientCredits(wallet.available_credits, amount)
                wallet.available_credits -= amount
                wallet.version += 1
                session.add(CreditLedgerRow(id=uuid4().hex, user_id=user_id, entry_type="admin_debit", credit_delta=credits, reference_type="admin_adjustment", reference_id=reference_id, actor_user_id=actor_user_id, reason=reason))
            return self._snapshot(wallet)

    async def create_mock_payment(
        self,
        user_id: str,
        *,
        provider: str,
        credits: int,
        idempotency_key: str,
    ) -> MockPaymentResult:
        """Create a locally-paid payment order and credit its wallet exactly once.

        The endpoint is deliberately a mock during development, but it keeps the
        same idempotency and audit boundary a real payment callback will require.
        One credit is represented as one fen until product pricing is configured.
        """
        if credits <= 0:
            raise ValueError("credits must be positive")
        async with self._sf() as session:
            async with session.begin():
                existing = await session.scalar(select(PaymentOrderRow).where(PaymentOrderRow.user_id == user_id, PaymentOrderRow.idempotency_key == idempotency_key).with_for_update())
                if existing is not None:
                    wallet = await self._get_locked_wallet(session, user_id)
                    return MockPaymentResult(existing.id, existing.provider, existing.status, self._snapshot(wallet), True)

                order = PaymentOrderRow(
                    id=uuid4().hex,
                    user_id=user_id,
                    provider=provider,
                    package_id=f"mock-{credits}",
                    amount_fen=credits,
                    credits=credits,
                    status="paid",
                    idempotency_key=idempotency_key,
                )
                wallet = await self._get_locked_wallet(session, user_id)
                wallet.available_credits += credits
                wallet.version += 1
                session.add_all(
                    [
                        order,
                        CreditLedgerRow(
                            id=uuid4().hex,
                            user_id=user_id,
                            entry_type="recharge",
                            credit_delta=credits,
                            reference_type="payment_order",
                            reference_id=order.id,
                            reason=f"mock_{provider}",
                        ),
                    ]
                )
                return MockPaymentResult(order.id, provider, "paid", self._snapshot(wallet), False)

    async def reserve_credits(self, user_id: str, run_id: str, credits: int) -> WalletSnapshot:
        if credits <= 0:
            raise ValueError("credits must be positive")
        async with self._sf() as session:
            async with session.begin():
                wallet = await self._get_locked_wallet(session, user_id)
                existing = await session.scalar(select(CreditLedgerRow).where(CreditLedgerRow.reference_type == "run", CreditLedgerRow.reference_id == run_id, CreditLedgerRow.entry_type == "reserve"))
                if existing is not None:
                    return self._snapshot(wallet)
                if wallet.available_credits < credits:
                    raise InsufficientCredits(wallet.available_credits, credits)
                wallet.available_credits -= credits
                wallet.reserved_credits += credits
                wallet.version += 1
                session.add(CreditLedgerRow(id=uuid4().hex, user_id=user_id, entry_type="reserve", credit_delta=-credits, reference_type="run", reference_id=run_id))
            return self._snapshot(wallet)

    async def reserve_for_model(self, user_id: str, run_id: str, model_name: str) -> WalletSnapshot:
        """Reserve the administrator-defined maximum cost for a configured model."""
        async with self._sf() as session:
            policy = await session.scalar(select(ModelPricePolicyRow).where(ModelPricePolicyRow.model_name == model_name, ModelPricePolicyRow.active.is_(True)).order_by(ModelPricePolicyRow.created_at.desc()).limit(1))
        if policy is None:
            raise ValueError(f"No active price policy for model {model_name}")
        return await self.reserve_credits(user_id, run_id, policy.max_reservation_credits)

    async def settle_run(self, user_id: str, run_id: str, charged_credits: int) -> WalletSnapshot:
        """Convert a run reservation into its actual charge and refund the rest."""
        if charged_credits < 0:
            raise ValueError("charged_credits must not be negative")
        async with self._sf() as session:
            async with session.begin():
                wallet = await self._get_locked_wallet(session, user_id)
                settled = await session.scalar(
                    select(CreditLedgerRow).where(
                        CreditLedgerRow.reference_type == "run",
                        CreditLedgerRow.reference_id == run_id,
                        CreditLedgerRow.entry_type == "charge",
                    )
                )
                if settled is not None:
                    return self._snapshot(wallet)
                reservation = await session.scalar(
                    select(CreditLedgerRow).where(
                        CreditLedgerRow.reference_type == "run",
                        CreditLedgerRow.reference_id == run_id,
                        CreditLedgerRow.entry_type == "reserve",
                    )
                )
                if reservation is None:
                    raise ValueError(f"run {run_id} has no reservation")
                reserved = -reservation.credit_delta
                if charged_credits > reserved:
                    charged_credits = reserved
                refund = reserved - charged_credits
                wallet.reserved_credits -= reserved
                wallet.available_credits += refund
                wallet.version += 1
                session.add_all(
                    [
                        CreditLedgerRow(id=uuid4().hex, user_id=user_id, entry_type="charge", credit_delta=-charged_credits, reference_type="run", reference_id=run_id),
                        CreditLedgerRow(id=uuid4().hex, user_id=user_id, entry_type="refund", credit_delta=refund, reference_type="run", reference_id=run_id),
                    ]
                )
            return self._snapshot(wallet)

    async def release_run_reservation(self, user_id: str, run_id: str) -> WalletSnapshot:
        """Refund a reservation when the run could not be admitted or attached."""
        return await self.settle_run(user_id, run_id, 0)

    async def settle_run_usage(self, user_id: str, run_id: str, usage_by_model: dict[str, dict[str, int]]) -> WalletSnapshot:
        """Price token usage, retain its exact price snapshot, and settle once."""
        async with self._sf() as session:
            async with session.begin():
                wallet = await self._get_locked_wallet(session, user_id)
                settled = await session.scalar(select(CreditLedgerRow).where(CreditLedgerRow.reference_type == "run", CreditLedgerRow.reference_id == run_id, CreditLedgerRow.entry_type == "charge"))
                if settled is not None:
                    return self._snapshot(wallet)

                total = 0
                for model_name, usage in usage_by_model.items():
                    policy = await session.scalar(select(ModelPricePolicyRow).where(ModelPricePolicyRow.model_name == model_name, ModelPricePolicyRow.active.is_(True)).order_by(ModelPricePolicyRow.created_at.desc()).limit(1))
                    if policy is None:
                        continue
                    input_tokens = max(0, int(usage.get("input_tokens", 0) or 0))
                    output_tokens = max(0, int(usage.get("output_tokens", 0) or 0))
                    cache_tokens = max(0, int(usage.get("cache_read_tokens", 0) or 0))
                    input_billable = max(0, input_tokens - cache_tokens)
                    cache_price = policy.cache_read_fen_per_million or policy.input_fen_per_million
                    fen = (Decimal(input_billable) * Decimal(policy.input_fen_per_million) + Decimal(output_tokens) * Decimal(policy.output_fen_per_million) + Decimal(cache_tokens) * Decimal(cache_price)) / Decimal(1_000_000)
                    charged = int((fen * Decimal(policy.credit_multiplier_bps) / Decimal(10_000)).to_integral_value(rounding=ROUND_CEILING))
                    total += charged
                    session.add(
                        UsageRecordRow(
                            id=uuid4().hex,
                            user_id=user_id,
                            run_id=run_id,
                            model_name=model_name,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            cache_read_tokens=cache_tokens,
                            charged_credits=charged,
                            price_snapshot={
                                "policy_id": policy.id,
                                "input_fen_per_million": policy.input_fen_per_million,
                                "output_fen_per_million": policy.output_fen_per_million,
                                "cache_read_fen_per_million": cache_price,
                                "credit_multiplier_bps": policy.credit_multiplier_bps,
                            },
                        )
                    )

                reservation = await session.scalar(select(CreditLedgerRow).where(CreditLedgerRow.reference_type == "run", CreditLedgerRow.reference_id == run_id, CreditLedgerRow.entry_type == "reserve"))
                if reservation is None:
                    raise ValueError(f"run {run_id} has no reservation")
                reserved = -reservation.credit_delta
                charged = min(total, reserved)
                refund = reserved - charged
                wallet.reserved_credits -= reserved
                wallet.available_credits += refund
                wallet.version += 1
                session.add_all(
                    [
                        CreditLedgerRow(id=uuid4().hex, user_id=user_id, entry_type="charge", credit_delta=-charged, reference_type="run", reference_id=run_id),
                        CreditLedgerRow(id=uuid4().hex, user_id=user_id, entry_type="refund", credit_delta=refund, reference_type="run", reference_id=run_id),
                    ]
                )
                return self._snapshot(wallet)

    async def _get_locked_wallet(self, session: AsyncSession, user_id: str) -> WalletRow:
        wallet = await session.scalar(select(WalletRow).where(WalletRow.user_id == user_id).with_for_update())
        if wallet is None:
            wallet = WalletRow(user_id=user_id)
            session.add(wallet)
            await session.flush()
        return wallet
