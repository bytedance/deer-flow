"""Add the nullable LLM summary column to project_documents.

Revision ID: 0037_project_document_summaries
Revises: 0036_run_idempotency_request

The summary is a best-effort, server-generated one-line description of the
document.
Nullable with no server default and no backfill: legacy rows keep NULL, so the
bootstrap forward-compat floor is unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "0037_project_document_summaries"
down_revision: str | Sequence[str] | None = "0036_run_idempotency_request"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("project_documents", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("project_documents", "summary")
