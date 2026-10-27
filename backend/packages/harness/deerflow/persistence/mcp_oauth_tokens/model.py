"""ORM model for MCP OAuth tokens shared by every Gateway instance (``mcp_oauth_tokens``).

One row per OAuth connection that uses the ``refresh_token`` grant, keyed by
``(scope, owner_user_id, server_key)``:

- ``scope='deployment'``: ``owner_user_id`` is ``''`` and ``server_key`` the
  server name in ``extensions_config.json``. The empty string stands in for
  "no owner" because primary-key columns cannot be NULL on PostgreSQL, and
  SQLite would treat NULL owners as distinct keys.
- ``scope='personal'``: ``owner_user_id`` is the owner and ``server_key`` the
  ``personal_<hash>`` runtime name (``deerflow.mcp.user_config``), so a
  personal connection never shares a row with a same-named deployment one.

The row holds only what the token endpoint returned -- the access token, its
expiry and the latest (possibly rotated) refresh token -- as
``DEER_FLOW_CREDENTIALS_KEY`` ciphertext. ``config_fingerprint`` identifies the
configured token chain (``deerflow.mcp.oauth_store.oauth_config_fingerprint``):
a row written under another fingerprint is ignored, so a changed seed wins.
``token_request_fingerprint`` identifies how the stored access token was
requested and read (``extra_token_params`` such as ``resource``, and the
response fields): a process configured differently refreshes from the stored
refresh token instead of reusing that access token.

``version`` grows by one on every token write; a refresh is claimed with a
compare-and-set on it plus the ``refresh_lease_*`` columns, so peers that read
the same expired token refresh it once. A claim before the first write leaves
a row at version 0 with no tokens. Times are epoch seconds: the lease against
the database clock, the rest from the writing instance.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import BigInteger, Double, PrimaryKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base

#: ``'deployment'`` or ``'personal'``; plain text so a new scope needs no migration.
MCP_OAUTH_TOKEN_SCOPE_LENGTH = 16
MCP_OAUTH_TOKEN_OWNER_LENGTH = 64
#: Deployment server names are operator-chosen; personal runtime names are 41 characters.
MCP_OAUTH_TOKEN_SERVER_KEY_LENGTH = 255
MCP_OAUTH_TOKEN_FINGERPRINT_LENGTH = 64
MCP_OAUTH_TOKEN_LEASE_OWNER_LENGTH = 36


class McpOAuthTokenRow(Base):
    __tablename__ = "mcp_oauth_tokens"

    scope: Mapped[str] = mapped_column(String(MCP_OAUTH_TOKEN_SCOPE_LENGTH), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(MCP_OAUTH_TOKEN_OWNER_LENGTH), nullable=False)
    server_key: Mapped[str] = mapped_column(String(MCP_OAUTH_TOKEN_SERVER_KEY_LENGTH), nullable=False)
    config_fingerprint: Mapped[str] = mapped_column(String(MCP_OAUTH_TOKEN_FINGERPRINT_LENGTH), nullable=False)
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_request_fingerprint: Mapped[str | None] = mapped_column(String(MCP_OAUTH_TOKEN_FINGERPRINT_LENGTH), nullable=True)
    token_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    access_expires_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refresh_lease_owner: Mapped[str | None] = mapped_column(String(MCP_OAUTH_TOKEN_LEASE_OWNER_LENGTH), nullable=True)
    refresh_lease_until: Mapped[float | None] = mapped_column(Double, nullable=True)
    rotated_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    updated_at: Mapped[float] = mapped_column(Double, nullable=False)

    __table_args__ = (PrimaryKeyConstraint("scope", "owner_user_id", "server_key", name="pk_mcp_oauth_tokens"),)


@dataclass(frozen=True)
class StoredMcpOAuthToken:
    """One connection's row as stored: the token columns are opaque ciphertext here."""

    config_fingerprint: str
    access_token_enc: str | None
    token_request_fingerprint: str | None
    token_type: str | None
    access_expires_at: float | None
    refresh_token_enc: str | None
    version: int
