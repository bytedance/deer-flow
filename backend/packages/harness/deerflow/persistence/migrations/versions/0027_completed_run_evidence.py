"""Add explicit evidence seal and durable bounded snapshot references."""

import sqlalchemy as sa
from alembic import op

revision = "0027_completed_run_evidence"
down_revision = "0026_mcp_task_lease_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("run_events", sa.Column("content_sha256", sa.String(64), nullable=True))
    for column in (
        sa.Column("evidence_origin", sa.String(32), nullable=True),
        sa.Column("evidence_agent_id", sa.String(128), nullable=True),
        sa.Column("evidence_seal_state", sa.String(16), nullable=True),
        sa.Column("evidence_seal_error", sa.String(512), nullable=True),
        sa.Column("evidence_revision", sa.String(64), nullable=True),
        sa.Column("evidence_upper_seq", sa.BigInteger(), nullable=True),
        sa.Column("evidence_event_count", sa.BigInteger(), nullable=True),
        sa.Column("evidence_retention_revision", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    ):
        safe_add_column("runs", column)
    if "completed_run_snapshots" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "completed_run_snapshots",
            sa.Column("snapshot_ref", sa.String(64), primary_key=True),
            sa.Column("run_id", sa.String(64), nullable=False),
            sa.Column("scope_digest", sa.String(64), nullable=False),
            sa.Column("evidence_revision", sa.String(64), nullable=False),
            sa.Column("retention_revision", sa.BigInteger(), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.UniqueConstraint("run_id", "scope_digest", "evidence_revision", "retention_revision", name="uq_completed_run_snapshot_revision"),
        )
        op.create_index("ix_completed_run_snapshots_run_id", "completed_run_snapshots", ["run_id"])


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("run_events", "content_sha256")
    if "completed_run_snapshots" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("completed_run_snapshots")
    for name in ("evidence_retention_revision", "evidence_event_count", "evidence_upper_seq", "evidence_revision", "evidence_seal_error", "evidence_seal_state", "evidence_agent_id", "evidence_origin"):
        safe_drop_column("runs", name)
