"""Persist optional run settings for managed coordination tasks."""

import sqlalchemy as sa

revision = "0060_coordination_run_settings"
down_revision = "0059_coordination_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("coord_tasks", sa.Column("run_settings", sa.JSON(none_as_null=True), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("coord_tasks", "run_settings")
