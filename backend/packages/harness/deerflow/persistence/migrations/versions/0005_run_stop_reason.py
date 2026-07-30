"""run stop_reason

Revision ID: 0005_run_stop_reason
Revises: 0004_run_ownership
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_run_stop_reason"
down_revision: str | Sequence[str] | None = "0004_run_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("runs", sa.Column("stop_reason", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "stop_reason")
