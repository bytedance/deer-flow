"""Generalize notification_deliveries source columns for runtime IM notifications.

Revision ID: 0043_runtime_im_notices
Revises: 0042_channel_leases
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043_runtime_im_notices"
down_revision: str | Sequence[str] | None = "0042_channel_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "notification_deliveries"
_OLD_UQ = "uq_notification_delivery_run_event_target"
_NEW_UQ = "uq_notification_delivery_source_event_target"
_SOURCE_KEY_IX = "ix_notification_deliveries_source_key"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return

    columns = {col["name"]: col for col in inspector.get_columns(_TABLE)}
    if "source_kind" not in columns or "source_key" not in columns:
        with op.batch_alter_table(_TABLE) as batch:
            if "source_kind" not in columns:
                batch.add_column(sa.Column("source_kind", sa.String(length=32), nullable=True))
            if "source_key" not in columns:
                batch.add_column(sa.Column("source_key", sa.String(length=128), nullable=True))

    bind.execute(sa.text("UPDATE notification_deliveries SET source_kind = COALESCE(source_kind, 'scheduled_task'),     source_key = COALESCE(source_key, task_run_id, run_id, id) WHERE source_kind IS NULL OR source_key IS NULL"))

    inspector = sa.inspect(bind)
    columns = {col["name"]: col for col in inspector.get_columns(_TABLE)}
    unique_constraints = {uc["name"] for uc in inspector.get_unique_constraints(_TABLE) if uc.get("name")}
    indexes = {idx["name"] for idx in inspector.get_indexes(_TABLE) if idx.get("name")}

    needs_batch = columns["source_kind"]["nullable"] or columns["source_key"]["nullable"] or not columns["task_id"]["nullable"] or not columns["task_run_id"]["nullable"] or _OLD_UQ in unique_constraints or _NEW_UQ not in unique_constraints
    if needs_batch:
        with op.batch_alter_table(_TABLE) as batch:
            if _OLD_UQ in unique_constraints:
                batch.drop_constraint(_OLD_UQ, type_="unique")
            batch.alter_column(
                "source_kind",
                existing_type=sa.String(length=32),
                nullable=False,
                server_default=None,
            )
            batch.alter_column(
                "source_key",
                existing_type=sa.String(length=128),
                nullable=False,
                server_default=None,
            )
            batch.alter_column(
                "task_id",
                existing_type=sa.String(length=64),
                nullable=True,
            )
            batch.alter_column(
                "task_run_id",
                existing_type=sa.String(length=64),
                nullable=True,
            )
            if _NEW_UQ not in unique_constraints:
                batch.create_unique_constraint(
                    _NEW_UQ,
                    ["source_kind", "source_key", "event", "provider", "target"],
                )

    inspector = sa.inspect(bind)
    indexes = {idx["name"] for idx in inspector.get_indexes(_TABLE) if idx.get("name")}
    if _SOURCE_KEY_IX not in indexes:
        op.create_index(_SOURCE_KEY_IX, _TABLE, ["source_key"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return

    bind.execute(sa.text("DELETE FROM notification_deliveries WHERE task_id IS NULL OR task_run_id IS NULL"))

    indexes = {idx["name"] for idx in inspector.get_indexes(_TABLE) if idx.get("name")}
    if _SOURCE_KEY_IX in indexes:
        op.drop_index(_SOURCE_KEY_IX, table_name=_TABLE)

    inspector = sa.inspect(bind)
    columns = {col["name"]: col for col in inspector.get_columns(_TABLE)}
    unique_constraints = {uc["name"] for uc in inspector.get_unique_constraints(_TABLE) if uc.get("name")}

    with op.batch_alter_table(_TABLE) as batch:
        if _NEW_UQ in unique_constraints:
            batch.drop_constraint(_NEW_UQ, type_="unique")
        if "task_id" in columns:
            batch.alter_column(
                "task_id",
                existing_type=sa.String(length=64),
                nullable=False,
            )
        if "task_run_id" in columns:
            batch.alter_column(
                "task_run_id",
                existing_type=sa.String(length=64),
                nullable=False,
            )
        if _OLD_UQ not in unique_constraints:
            batch.create_unique_constraint(
                _OLD_UQ,
                ["task_run_id", "event", "provider", "target"],
            )
        if "source_key" in columns:
            batch.drop_column("source_key")
        if "source_kind" in columns:
            batch.drop_column("source_kind")
