"""SQLAlchemy models for tenant-scoped credit billing."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class WalletRow(Base):
    __tablename__ = "wallets"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    available_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class CreditLedgerRow(Base):
    __tablename__ = "credit_ledger"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    credit_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (UniqueConstraint("reference_type", "reference_id", "entry_type", name="uq_credit_ledger_reference_entry"),)


class PaymentOrderRow(Base):
    __tablename__ = "payment_orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    package_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_fen: Mapped[int] = mapped_column(Integer, nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_payment_orders_user_idempotency"),)


class ModelPricePolicyRow(Base):
    __tablename__ = "model_price_policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    input_fen_per_million: Mapped[int] = mapped_column(Integer, nullable=False)
    output_fen_per_million: Mapped[int] = mapped_column(Integer, nullable=False)
    cache_read_fen_per_million: Mapped[int | None] = mapped_column(Integer)
    credit_multiplier_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    max_reservation_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class UsageRecordRow(Base):
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    charged_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    price_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (Index("ix_usage_records_user_created", "user_id", "created_at"), UniqueConstraint("run_id", "model_name", name="uq_usage_records_run_model"))
