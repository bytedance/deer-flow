"""threads_meta.project_id.

Revision ID: 0020_threads_meta_project_id
Revises: 0019_projects
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_threads_meta_project_id"
down_revision: str | Sequence[str] | None = "0019_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("threads_meta", sa.Column("project_id", sa.String(length=64), nullable=True))
    inspector = sa.inspect(op.get_bind())
    existing = {i["name"] for i in inspector.get_indexes("threads_meta")}
    if "ix_threads_meta_project_id" not in existing:
        op.create_index("ix_threads_meta_project_id", "threads_meta", ["project_id"])


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    inspector = sa.inspect(op.get_bind())
    existing = {i["name"] for i in inspector.get_indexes("threads_meta")}
    if "ix_threads_meta_project_id" in existing:
        op.drop_index("ix_threads_meta_project_id", table_name="threads_meta")
    safe_drop_column("threads_meta", "project_id")
