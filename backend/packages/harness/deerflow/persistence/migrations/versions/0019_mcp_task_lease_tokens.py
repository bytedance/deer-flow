"""fence MCP task claims by per-claim lease tokens.

Revision ID: 0018_mcp_task_lease_tokens
Revises: 0017_personal_access_tokens
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

revision: str = "0019_mcp_task_lease_tokens"
down_revision: str | Sequence[str] | None = "0018_oauth_identity_pg_partial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("mcp_tasks", sa.Column("lease_token", sa.String(length=64), nullable=True))
    safe_add_column("mcp_tasks", sa.Column("notification_lease_token", sa.String(length=64), nullable=True))


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    safe_drop_column("mcp_tasks", "notification_lease_token")
    safe_drop_column("mcp_tasks", "lease_token")
