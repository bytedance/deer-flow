"""Repair run-change clock schema skipped by the 0023 insertion (#5516).

``0023_run_change_seq`` was inserted between ``0022_scheduled_occurrence_seq``
and the already-shipped ``0023_user_preferences`` revision. Alembic only walks
forward from a database's stamped revision, so every database that had already
reached ``0023_user_preferences`` (or later) before the insertion treats
``0023_run_change_seq`` as an applied ancestor and never executes it. Those
databases permanently lack the ``run_change_clock`` table, the
``runs.change_seq`` column, and their indexes, and the first run-store
operation that bumps the change clock (e.g. thread deletion via
``create_thread_operation_atomic``) fails with ``no such table:
run_change_clock``. Restarting never heals it because the stamped revision is
already at or past 0023.

This revision re-applies the same idempotent DDL as ``0023_run_change_seq``
for every database that upgrades past it, restoring those skipped schemas.
Fresh and legacy databases that ran 0023 itself are untouched: every step is
guarded exactly like 0023 and no-ops on the healthy shape.

Revision ID: 0025_repair_run_change_seq
Revises: 0024_project_documents
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_repair_run_change_seq"
down_revision: str | Sequence[str] | None = "0024_project_documents"
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
