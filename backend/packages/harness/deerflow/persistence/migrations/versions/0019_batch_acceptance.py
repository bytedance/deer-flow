"""Persist optional durable batch acceptance criteria and verdicts.

Revision ID: 0019_batch_acceptance
Revises: 0018_oauth_identity_pg_partial
"""

from __future__ import annotations

import sqlalchemy as sa

revision = "0019_batch_acceptance"
down_revision = "0018_oauth_identity_pg_partial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("subagent_batch_items", sa.Column("acceptance_criteria", sa.JSON(), nullable=True))
    safe_add_column("subagent_batch_items", sa.Column("acceptance_verdict", sa.JSON(), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("subagent_batch_items", "acceptance_verdict")
    safe_drop_column("subagent_batch_items", "acceptance_criteria")
