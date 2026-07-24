"""thread operation kind.

Revision ID: 0008_thread_operation_kind
Revises: 0007_scheduled_run_active_index
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_thread_operation_kind"
down_revision: str | Sequence[str] | None = "0007_scheduled_run_active_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column(
        "runs",
        sa.Column(
            "operation_kind",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'run'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "operation_kind")
