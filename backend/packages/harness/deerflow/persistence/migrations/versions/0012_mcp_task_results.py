"""bounded MCP task result fields.

Revision ID: 0012_mcp_task_results
Revises: 0011_mcp_tasks
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "0012_mcp_task_results"
down_revision: str | Sequence[str] | None = "0011_mcp_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column(
        "mcp_tasks",
        sa.Column("result_preview", sa.Text(), nullable=True),
    )
    safe_add_column(
        "mcp_tasks",
        sa.Column(
            "result_truncated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    safe_add_column(
        "mcp_tasks",
        sa.Column("result_artifact", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("mcp_tasks", "result_artifact")
    safe_drop_column("mcp_tasks", "result_truncated")
    safe_drop_column("mcp_tasks", "result_preview")
