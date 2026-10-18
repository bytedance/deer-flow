"""Persist original native Scheduler execution identity.

Historical NULL identities remain legacy; never infer scope from current UI.
"""

import sqlalchemy as sa

from deerflow.persistence.migrations._helpers import safe_add_column

revision = "0041_scheduler_workspace"
down_revision = "0040_mcp_workspace_identity"
branch_labels = None
depends_on = None


def upgrade():
    for table, columns in (
        ("scheduled_tasks", (("workspace_context_json", sa.JSON()), ("thread_incarnation", sa.String(32)), ("origin_thread_incarnation", sa.String(32)))),
        ("scheduled_task_runs", (("workspace_context_json", sa.JSON()), ("thread_incarnation", sa.String(32)))),
        ("scheduled_task_events", (("thread_incarnation", sa.String(32)),)),
    ):
        for name, kind in columns:
            safe_add_column(table, sa.Column(name, kind, nullable=True))


def downgrade():
    raise RuntimeError("Scheduler workspace authority requires restoring a matched backup generation")
