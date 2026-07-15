"""evaluation persistence tables.

Revision ID: 0005_evaluations
Revises: 0004_run_ownership
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_evaluations"
down_revision: str | Sequence[str] | None = "0004_run_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "eval_runs" not in existing:
        op.create_table(
            "eval_runs",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("owner_id", sa.String(length=64), nullable=False),
            sa.Column("idempotency_key", sa.String(length=128), nullable=True),
            sa.Column("suite_name", sa.String(length=255), nullable=False),
            sa.Column("suite_version", sa.String(length=64), nullable=True),
            sa.Column("suite_digest", sa.String(length=128), nullable=False),
            sa.Column("suite_snapshot", sa.JSON(), nullable=False),
            sa.Column("environment_fingerprint_json", sa.JSON(), nullable=False),
            sa.Column("config_json", sa.JSON(), nullable=False),
            sa.Column("variants_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("total_items", sa.Integer(), nullable=False),
            sa.Column("completed_items", sa.Integer(), nullable=False),
            sa.Column("summary_json", sa.JSON(), nullable=False),
            sa.Column("effect_summary_json", sa.JSON(), nullable=False),
            sa.Column("comparison_json", sa.JSON(), nullable=False),
            sa.Column("report_json", sa.JSON(), nullable=False),
            sa.Column("report_markdown", sa.Text(), nullable=True),
            sa.Column("infrastructure_gate", sa.String(length=20), nullable=False),
            sa.Column("trace_export", sa.String(length=32), nullable=False),
            sa.Column("trace_sync_status", sa.String(length=20), nullable=False),
            sa.Column("lease_owner", sa.String(length=128), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("cancellation_reason", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_eval_runs_owner_idempotency_key"),
        )
        with op.batch_alter_table("eval_runs", schema=None) as batch_op:
            batch_op.create_index("idx_eval_runs_claim", ["status", "lease_expires_at", "created_at"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_runs_lease_expires_at"), ["lease_expires_at"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_runs_owner_id"), ["owner_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_runs_status"), ["status"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_runs_suite_digest"), ["suite_digest"], unique=False)

    if "eval_run_items" not in existing:
        op.create_table(
            "eval_run_items",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("eval_run_id", sa.String(length=64), nullable=False),
            sa.Column("suite_item_id", sa.String(length=255), nullable=False),
            sa.Column("variant_id", sa.String(length=128), nullable=False),
            sa.Column("sample_index", sa.Integer(), nullable=False),
            sa.Column("execution_key", sa.String(length=512), nullable=False),
            sa.Column("paired_item_id", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("selected_attempt_id", sa.String(length=64), nullable=True),
            sa.Column("selected_attempt_index", sa.Integer(), nullable=True),
            sa.Column("thread_id", sa.String(length=64), nullable=True),
            sa.Column("run_id", sa.String(length=64), nullable=True),
            sa.Column("workspace_path", sa.Text(), nullable=True),
            sa.Column("checks_json", sa.JSON(), nullable=False),
            sa.Column("check_results_json", sa.JSON(), nullable=False),
            sa.Column("metrics_json", sa.JSON(), nullable=False),
            sa.Column("comparison_json", sa.JSON(), nullable=False),
            sa.Column("run_event_summary_json", sa.JSON(), nullable=False),
            sa.Column("failure_kind", sa.String(length=32), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("trace_sync_status", sa.String(length=20), nullable=False),
            sa.Column("langsmith_dataset_id", sa.String(length=128), nullable=True),
            sa.Column("langsmith_example_id", sa.String(length=128), nullable=True),
            sa.Column("langsmith_trace_url", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["eval_run_id"], ["eval_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "eval_run_id",
                "suite_item_id",
                "variant_id",
                "sample_index",
                name="uq_eval_items_run_suite_variant_sample",
            ),
            sa.UniqueConstraint("eval_run_id", "execution_key", name="uq_eval_items_run_execution_key"),
        )
        with op.batch_alter_table("eval_run_items", schema=None) as batch_op:
            batch_op.create_index("idx_eval_items_run_status", ["eval_run_id", "status"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_run_items_eval_run_id"), ["eval_run_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_run_items_run_id"), ["run_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_run_items_status"), ["status"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_run_items_suite_item_id"), ["suite_item_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_run_items_thread_id"), ["thread_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_run_items_variant_id"), ["variant_id"], unique=False)

    if "eval_item_attempts" not in existing:
        op.create_table(
            "eval_item_attempts",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("eval_run_id", sa.String(length=64), nullable=False),
            sa.Column("eval_run_item_id", sa.String(length=64), nullable=False),
            sa.Column("attempt_index", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("thread_id", sa.String(length=64), nullable=True),
            sa.Column("run_id", sa.String(length=64), nullable=True),
            sa.Column("workspace_path", sa.Text(), nullable=True),
            sa.Column("checks_json", sa.JSON(), nullable=False),
            sa.Column("check_results_json", sa.JSON(), nullable=False),
            sa.Column("metrics_json", sa.JSON(), nullable=False),
            sa.Column("comparison_json", sa.JSON(), nullable=False),
            sa.Column("run_event_summary_json", sa.JSON(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("failure_kind", sa.String(length=32), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("trace_sync_status", sa.String(length=20), nullable=False),
            sa.Column("langsmith_trace_url", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["eval_run_id"], ["eval_runs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["eval_run_item_id"], ["eval_run_items.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("eval_run_item_id", "attempt_index", name="uq_eval_attempts_item_attempt_index"),
        )
        with op.batch_alter_table("eval_item_attempts", schema=None) as batch_op:
            batch_op.create_index("idx_eval_attempts_item_status", ["eval_run_item_id", "status"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_item_attempts_eval_run_id"), ["eval_run_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_item_attempts_eval_run_item_id"), ["eval_run_item_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_item_attempts_run_id"), ["run_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_item_attempts_status"), ["status"], unique=False)
            batch_op.create_index(batch_op.f("ix_eval_item_attempts_thread_id"), ["thread_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("eval_item_attempts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_eval_item_attempts_thread_id"))
        batch_op.drop_index(batch_op.f("ix_eval_item_attempts_status"))
        batch_op.drop_index(batch_op.f("ix_eval_item_attempts_run_id"))
        batch_op.drop_index(batch_op.f("ix_eval_item_attempts_eval_run_item_id"))
        batch_op.drop_index(batch_op.f("ix_eval_item_attempts_eval_run_id"))
        batch_op.drop_index("idx_eval_attempts_item_status")
    op.drop_table("eval_item_attempts")

    with op.batch_alter_table("eval_run_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_eval_run_items_variant_id"))
        batch_op.drop_index(batch_op.f("ix_eval_run_items_thread_id"))
        batch_op.drop_index(batch_op.f("ix_eval_run_items_suite_item_id"))
        batch_op.drop_index(batch_op.f("ix_eval_run_items_status"))
        batch_op.drop_index(batch_op.f("ix_eval_run_items_run_id"))
        batch_op.drop_index(batch_op.f("ix_eval_run_items_eval_run_id"))
        batch_op.drop_index("idx_eval_items_run_status")
    op.drop_table("eval_run_items")

    with op.batch_alter_table("eval_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_eval_runs_suite_digest"))
        batch_op.drop_index(batch_op.f("ix_eval_runs_status"))
        batch_op.drop_index(batch_op.f("ix_eval_runs_owner_id"))
        batch_op.drop_index(batch_op.f("ix_eval_runs_lease_expires_at"))
        batch_op.drop_index("idx_eval_runs_claim")
    op.drop_table("eval_runs")
