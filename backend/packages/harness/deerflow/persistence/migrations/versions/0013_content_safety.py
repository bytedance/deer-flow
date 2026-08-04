"""Add content-safety incidents and privileged-operation audit records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_content_safety"
down_revision: str | Sequence[str] | None = "0012_skill_market"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("risk_events"):
        op.create_table(
            "risk_events",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("thread_id", sa.String(64), nullable=False),
            sa.Column("run_id", sa.String(64)),
            sa.Column("direction", sa.String(16), nullable=False),
            sa.Column("category", sa.String(64), nullable=False),
            sa.Column("severity", sa.String(16), nullable=False),
            sa.Column("rule_version", sa.String(64), nullable=False),
            sa.Column("confidence_bps", sa.Integer(), nullable=False),
            sa.Column("redacted_excerpt", sa.Text(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("resolution", sa.String(32)),
            sa.Column("resolution_reason", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True)),
        )
        op.create_index("ix_risk_events_user_id", "risk_events", ["user_id"])
        op.create_index("ix_risk_events_thread_id", "risk_events", ["thread_id"])
        op.create_index("ix_risk_events_run_id", "risk_events", ["run_id"])
        op.create_index("ix_risk_events_category", "risk_events", ["category"])
        op.create_index("ix_risk_events_severity", "risk_events", ["severity"])
        op.create_index("ix_risk_events_status", "risk_events", ["status"])
    if not inspector.has_table("admin_audit_logs"):
        op.create_table(
            "admin_audit_logs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("actor_user_id", sa.String(64)),
            sa.Column("action", sa.String(80), nullable=False),
            sa.Column("target_type", sa.String(48), nullable=False),
            sa.Column("target_id", sa.String(64), nullable=False),
            sa.Column("reason", sa.Text()),
            sa.Column("before_summary", sa.JSON(), nullable=False),
            sa.Column("after_summary", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_admin_audit_logs_actor_user_id", "admin_audit_logs", ["actor_user_id"])
        op.create_index("ix_admin_audit_logs_action", "admin_audit_logs", ["action"])
        op.create_index("ix_admin_audit_logs_target_id", "admin_audit_logs", ["target_id"])


def downgrade() -> None:
    op.drop_table("admin_audit_logs")
    op.drop_table("risk_events")
