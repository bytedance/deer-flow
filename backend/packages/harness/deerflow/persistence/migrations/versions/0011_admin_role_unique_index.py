"""at most one admin row: cross-process TOCTOU backstop for /initialize.

Revision ID: 0011_admin_role_unique_index
Revises: 0010_run_cancel_request
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_admin_role_unique_index"
down_revision: str | Sequence[str] | None = "0010_run_cancel_request"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Demote duplicate admins created by the pre-fix initialize TOCTOU
    # (concurrent /initialize with different emails), keeping the
    # earliest-created account (deterministic tie-break by id).
    op.execute(
        sa.text(
            """
            UPDATE users SET system_role = 'user'
            WHERE system_role = 'admin'
              AND id != (
                  SELECT id FROM users
                  WHERE system_role = 'admin'
                  ORDER BY created_at ASC, id ASC
                  LIMIT 1
              )
            """
        )
    )
    # Partial unique index: at most one row may carry system_role='admin',
    # while any number of 'user' rows remain allowed. Works on both SQLite
    # and Postgres; the index name is the same as the ORM model's, so fresh
    # (create_all) and migrated databases converge on one schema.
    op.create_index(
        "uq_users_admin_role",
        "users",
        ["system_role"],
        unique=True,
        sqlite_where=sa.text("system_role = 'admin'"),
        postgresql_where=sa.text("system_role = 'admin'"),
    )


def downgrade() -> None:
    op.drop_index("uq_users_admin_role", table_name="users")
