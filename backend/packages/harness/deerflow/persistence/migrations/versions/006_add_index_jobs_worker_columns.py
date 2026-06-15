"""Add worker_id and retry_count to index_jobs for multi-worker queue

Revision ID: 006
Revises: 005
Create Date: 2026-06-13

"""

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("index_jobs", sa.Column("worker_id", sa.String(64), nullable=True))
    op.add_column("index_jobs", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("index_jobs", "retry_count")
    op.drop_column("index_jobs", "worker_id")
