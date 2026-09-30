"""Add stable changed-run discovery positions.

Revision ID: 0023_run_change_seq
Revises: 0022_scheduled_occurrence_seq
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_run_change_seq"
down_revision: str | Sequence[str] | None = "0022_scheduled_occurrence_seq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column(
        "runs",
        sa.Column("change_seq", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "run_change_clock" not in tables:
        op.create_table(
            "run_change_clock",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("value", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("runs")}
    if "ix_runs_change_seq" not in indexes:
        op.create_index("ix_runs_change_seq", "runs", ["change_seq", "run_id"])
    if "ix_runs_user_change_seq" not in indexes:
        op.create_index("ix_runs_user_change_seq", "runs", ["user_id", "change_seq", "run_id"])


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("runs")}
    if "ix_runs_user_change_seq" in indexes:
        op.drop_index("ix_runs_user_change_seq", table_name="runs")
    if "ix_runs_change_seq" in indexes:
        op.drop_index("ix_runs_change_seq", table_name="runs")
    safe_drop_column("runs", "change_seq")
    if "run_change_clock" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("run_change_clock")
