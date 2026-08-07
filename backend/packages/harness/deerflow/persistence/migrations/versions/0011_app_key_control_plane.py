"""add App-Key control-plane tables.

Revision ID: 0011_app_key_control_plane
Revises: 0010_run_cancel_request
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_app_key_control_plane"
down_revision: str | Sequence[str] | None = "0010_run_cancel_request"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("app_profiles"):
        return
    op.create_table(
        "app_profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "app_credentials",
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("app_id", sa.String(64), sa.ForeignKey("app_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_app_credentials_app_id", "app_credentials", ["app_id"])
    op.create_index("idx_app_credentials_active", "app_credentials", ["key_hash", "revoked_at"])
    op.create_table(
        "app_capabilities",
        sa.Column("app_id", sa.String(64), sa.ForeignKey("app_profiles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("capability", sa.String(32), primary_key=True),
        sa.Column("value", sa.String(128), primary_key=True),
    )
    op.create_table(
        "app_key_audits",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("app_id", sa.String(64)),
        sa.Column("key_hash", sa.String(64)),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_app_key_audits_app_id", "app_key_audits", ["app_id"])


def downgrade() -> None:
    op.drop_table("app_key_audits")
    op.drop_table("app_capabilities")
    op.drop_table("app_credentials")
    op.drop_table("app_profiles")
