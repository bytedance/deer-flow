"""Add tenant-scoped credit billing tables."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column

revision: str = "0011_billing"
down_revision: str | Sequence[str] | None = "0010_run_cancel_request"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    safe_add_column("users", sa.Column("is_frozen", sa.Boolean(), nullable=False, server_default=sa.false()))
    inspector = sa.inspect(bind)
    if not inspector.has_table("wallets"):
        op.create_table(
            "wallets",
            sa.Column("user_id", sa.String(64), primary_key=True),
            sa.Column("available_credits", sa.Integer(), nullable=False),
            sa.Column("reserved_credits", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if not inspector.has_table("credit_ledger"):
        op.create_table(
            "credit_ledger",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("entry_type", sa.String(32), nullable=False),
            sa.Column("credit_delta", sa.Integer(), nullable=False),
            sa.Column("reference_type", sa.String(32), nullable=False),
            sa.Column("reference_id", sa.String(64), nullable=False),
            sa.Column("reason", sa.Text()),
            sa.Column("actor_user_id", sa.String(64)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("reference_type", "reference_id", "entry_type", name="uq_credit_ledger_reference_entry"),
        )
        op.create_index("ix_credit_ledger_user_id", "credit_ledger", ["user_id"])
    if not inspector.has_table("payment_orders"):
        op.create_table(
            "payment_orders",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("provider", sa.String(16), nullable=False),
            sa.Column("package_id", sa.String(64), nullable=False),
            sa.Column("amount_fen", sa.Integer(), nullable=False),
            sa.Column("credits", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("idempotency_key", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("user_id", "idempotency_key", name="uq_payment_orders_user_idempotency"),
        )
    if not inspector.has_table("model_price_policies"):
        op.create_table(
            "model_price_policies",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("model_name", sa.String(128), nullable=False),
            sa.Column("input_fen_per_million", sa.Integer(), nullable=False),
            sa.Column("output_fen_per_million", sa.Integer(), nullable=False),
            sa.Column("cache_read_fen_per_million", sa.Integer()),
            sa.Column("credit_multiplier_bps", sa.Integer(), nullable=False),
            sa.Column("max_reservation_credits", sa.Integer(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_model_price_policies_model_name", "model_price_policies", ["model_name"])
    if not inspector.has_table("usage_records"):
        op.create_table(
            "usage_records",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("run_id", sa.String(64), nullable=False),
            sa.Column("model_name", sa.String(128), nullable=False),
            sa.Column("input_tokens", sa.Integer(), nullable=False),
            sa.Column("output_tokens", sa.Integer(), nullable=False),
            sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
            sa.Column("charged_credits", sa.Integer(), nullable=False),
            sa.Column("price_snapshot", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("run_id", "model_name", name="uq_usage_records_run_model"),
        )
        op.create_index("ix_usage_records_user_created", "usage_records", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_usage_records_user_created", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_index("ix_model_price_policies_model_name", table_name="model_price_policies")
    op.drop_table("model_price_policies")
    op.drop_table("payment_orders")
    op.drop_index("ix_credit_ledger_user_id", table_name="credit_ledger")
    op.drop_table("credit_ledger")
    op.drop_table("wallets")
