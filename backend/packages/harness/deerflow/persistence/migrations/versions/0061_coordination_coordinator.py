"""Store the Coordinator mode and accepted decisions."""

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision = "0061_coordination_coordinator"
down_revision = "0060_coordination_run_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    safe_add_column("coord_tasks", sa.Column("coordinator", sa.Boolean(), nullable=True))
    safe_add_column("coord_executions", sa.Column("decision", sa.JSON(), nullable=True))
    safe_add_column("coord_executions", sa.Column("result_text", sa.Text(), nullable=True))


def downgrade() -> None:
    safe_drop_column("coord_executions", "result_text")
    safe_drop_column("coord_executions", "decision")
    safe_drop_column("coord_tasks", "coordinator")
