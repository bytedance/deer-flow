"""Shared, encrypted MCP OAuth tokens.

Revision ID: 0047_mcp_oauth_tokens
Revises: 0046_skill_mutations

Creates ``mcp_oauth_tokens``: one row per MCP OAuth connection that uses the
``refresh_token`` grant, keyed by ``(scope, owner_user_id, server_key)``
(``owner_user_id`` is ``''`` for deployment servers). It holds the access
token and the latest, possibly rotated, refresh token as
``DEER_FLOW_CREDENTIALS_KEY`` ciphertext, the fingerprints of the configured
token chain and of the access-token request, a ``version`` bumped on every
token write, and the refresh lease
that lets one Gateway process refresh at a time
(``deerflow.mcp.oauth_store``). Tokens used to live only in process memory,
so this revision moves no data: every connection starts from its configured
seed once, then continues from the stored chain.

``_helpers.py`` only guards columns, so the table is guarded with a fresh
inspector in both directions: an upgrade that finds the table (an interrupted
earlier attempt, or an empty-database bootstrap that already ran
``create_all``) completes, and a downgrade after the table is gone still
moves the version row.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047_mcp_oauth_tokens"
down_revision: str | Sequence[str] | None = "0046_skill_mutations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "mcp_oauth_tokens"


def _has_table() -> bool:
    return sa.inspect(op.get_bind()).has_table(_TABLE)


def upgrade() -> None:
    if _has_table():
        return
    op.create_table(
        _TABLE,
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=False),
        sa.Column("server_key", sa.String(length=255), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=True),
        sa.Column("token_request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("token_type", sa.String(length=64), nullable=True),
        sa.Column("access_expires_at", sa.Double(), nullable=True),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("refresh_lease_owner", sa.String(length=36), nullable=True),
        sa.Column("refresh_lease_until", sa.Double(), nullable=True),
        sa.Column("rotated_at", sa.Double(), nullable=True),
        sa.Column("updated_at", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("scope", "owner_user_id", "server_key", name="pk_mcp_oauth_tokens"),
    )


def downgrade() -> None:
    if _has_table():
        op.drop_table(_TABLE)
