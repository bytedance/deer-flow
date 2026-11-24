"""Persist single-use MCP browser authorizations and fence grant changes."""

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision = "0058_mcp_browser_oauth"
down_revision = "0057_coordination_workers"
branch_labels = None
depends_on = None

_TOKENS = "mcp_oauth_tokens"
_ATTEMPTS = "mcp_oauth_attempts"
_EXPIRY_INDEX = "ix_mcp_oauth_attempts_expires_at"


def upgrade() -> None:
    safe_add_column(_TOKENS, sa.Column("grant_epoch", sa.BigInteger, nullable=True))
    safe_add_column(_TOKENS, sa.Column("grant_context", sa.Text, nullable=True))
    if not sa.inspect(op.get_bind()).has_table(_ATTEMPTS):
        op.create_table(
            _ATTEMPTS,
            sa.Column("owner_user_id", sa.String(64), primary_key=True),
            sa.Column("server_key", sa.String(255), primary_key=True),
            sa.Column("state_digest", sa.String(64), nullable=False, unique=True),
            sa.Column("browser_digest", sa.String(64), nullable=False),
            sa.Column("config_fingerprint", sa.String(64), nullable=False),
            sa.Column("grant_epoch", sa.BigInteger(), nullable=False),
            sa.Column("grant_context", sa.Text(), nullable=False),
            sa.Column("verifier_enc", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.Double(), nullable=False),
        )
    if _EXPIRY_INDEX not in {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(_ATTEMPTS)}:
        op.create_index(_EXPIRY_INDEX, _ATTEMPTS, ["expires_at"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(_ATTEMPTS):
        op.drop_table(_ATTEMPTS)
    if sa.inspect(op.get_bind()).has_table(_TOKENS):
        # A re-upgrade must not revive grants whose epoch was dropped.
        op.execute(sa.table(_TOKENS, sa.column("scope")).delete().where(sa.column("scope") == "delegated"))
    safe_drop_column(_TOKENS, "grant_context")
    safe_drop_column(_TOKENS, "grant_epoch")
