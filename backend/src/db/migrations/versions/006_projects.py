"""Add projects table and project_id to threads.

Revision ID: 006
Revises: 005
Create Date: 2026-03-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("project_id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "name", name="uq_projects_user_name"),
    )
    op.create_index("idx_projects_user_id", "projects", ["user_id"])

    op.add_column("threads", sa.Column("project_id", sa.String(32), nullable=True))
    op.create_index("idx_threads_project_id", "threads", ["project_id"])


def downgrade() -> None:
    op.drop_index("idx_threads_project_id", table_name="threads")
    op.drop_column("threads", "project_id")
    op.drop_index("idx_projects_user_id", table_name="projects")
    op.drop_table("projects")
