"""add cache token columns to runs

Revision ID: b3a7f1c4d8e2
Revises: None
Create Date: 2026-05-14

Adds cache_read_tokens and cache_creation_tokens columns to the runs table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3a7f1c4d8e2"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "runs",
        sa.Column("cache_creation_tokens", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_column("cache_creation_tokens")
        batch_op.drop_column("cache_read_tokens")
