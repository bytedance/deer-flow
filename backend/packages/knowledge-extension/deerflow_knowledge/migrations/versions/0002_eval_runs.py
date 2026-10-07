"""Evaluation and support table: kb_eval_runs.

The fork's 0017 table with the 0018 columns (is_baseline, environment) and its
partial unique index inlined (D3), renamed under the extension-owned ``kb_``
prefix (D2). The index keeps its model-declared name: it is an explicitly named
constraint in ``EvalRunRow.__table_args__``, not a derived one.

Revision ID: 0002_eval_runs
Revises: 0001_business_tables
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_eval_runs"
down_revision: str | Sequence[str] | None = "0001_business_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_eval_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("kb_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("layer1_metrics", sa.JSON(), nullable=False),
        sa.Column("layer2_metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("langfuse_trace_url", sa.String(length=512), nullable=True),
        sa.Column("baseline_diff", sa.JSON(), nullable=True),
        sa.Column("environment", sa.String(length=16), nullable=False, server_default=sa.text("'local'")),
        sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("kb_eval_runs", schema=None) as batch_op:
        batch_op.create_index("ix_kb_eval_runs_kb_id", ["kb_id"], unique=False)
        batch_op.create_index(
            "uq_eval_runs_kb_baseline",
            ["kb_id"],
            unique=True,
            sqlite_where=sa.text("is_baseline = true"),
            postgresql_where=sa.text("is_baseline = true"),
        )


def downgrade() -> None:
    with op.batch_alter_table("kb_eval_runs", schema=None) as batch_op:
        batch_op.drop_index("uq_eval_runs_kb_baseline")
        batch_op.drop_index("ix_kb_eval_runs_kb_id")
    op.drop_table("kb_eval_runs")
