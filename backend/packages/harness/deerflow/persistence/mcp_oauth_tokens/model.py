"""ORM model for MCP OAuth tokens shared by every Gateway instance (``mcp_oauth_tokens``).

One row per OAuth connection with persisted credentials, keyed by
``(scope, owner_user_id, server_key)``:

- ``scope='deployment'``: ``owner_user_id`` is ``''`` and ``server_key`` the
  server name in ``extensions_config.json``. The empty string stands in for
  "no owner" because primary-key columns cannot be NULL on PostgreSQL, and
  SQLite would treat NULL owners as distinct keys.
- ``scope='personal'``: ``owner_user_id`` is the owner and ``server_key`` the
  ``personal_<hash>`` runtime name (``deerflow.mcp.user_config``), so a
  personal connection never shares a row with a same-named deployment one.
- ``scope='delegated'``: one browser grant per user and deployment server.
  Its grant epoch changes on connect/disconnect and fences late writes.

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

from sqlalchemy import BigInteger, Double, Index, PrimaryKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base

#: ``'deployment'``, ``'personal'`` or ``'delegated'``.
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
    grant_epoch: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    grant_context: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    grant_epoch: int | None
    grant_context: str | None


class McpOAuthAttemptRow(Base):
    """Short-lived browser authorization, stored until one callback claims it."""

    __tablename__ = "mcp_oauth_attempts"

    owner_user_id: Mapped[str] = mapped_column(String(MCP_OAUTH_TOKEN_OWNER_LENGTH), primary_key=True)
    server_key: Mapped[str] = mapped_column(String(MCP_OAUTH_TOKEN_SERVER_KEY_LENGTH), primary_key=True)
    state_digest: Mapped[str] = mapped_column(String(64), unique=True)
    browser_digest: Mapped[str] = mapped_column(String(64))
    config_fingerprint: Mapped[str] = mapped_column(String(MCP_OAUTH_TOKEN_FINGERPRINT_LENGTH))
    grant_epoch: Mapped[int] = mapped_column(BigInteger)
    grant_context: Mapped[str] = mapped_column(Text)
    verifier_enc: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[float] = mapped_column(Double)

    __table_args__ = (Index("ix_mcp_oauth_attempts_expires_at", "expires_at"),)


@dataclass(frozen=True)
class StoredMcpOAuthAttempt:
    owner_user_id: str
    server_key: str
    config_fingerprint: str
    grant_epoch: int
    grant_context: str
    verifier_enc: str
