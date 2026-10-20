"""Synchronous SQL repository for ``mcp_oauth_tokens`` (SQLite or PostgreSQL).

MCP OAuth headers are requested from whichever event loop runs the tool call:
the Gateway loop, a sync tool wrapper's fresh loop on a worker thread, or the
durable task runtime. The async engine is bound to the Gateway loop, so this
repository uses a synchronous session factory over the application database
(``deerflow.persistence.agents.sql.get_sync_sessionmaker``) and every call is
made through ``asyncio.to_thread``.

A refresh never holds a row lock across the token request (up to 15 s).
Instead it is claimed and fenced in single statements:

- ``claim`` takes the refresh lease with a compare-and-set: ``UPDATE ... WHERE
  version = :seen AND (refresh_lease_owner IS NULL OR refresh_lease_until <
  now)``. A peer that wrote a token since the caller's read changed
  ``version``, so the claim fails and the caller re-reads instead of
  refreshing with a consumed refresh token. A missing row is claimed by
  inserting it at version 0 with ``ON CONFLICT DO NOTHING``.
- ``write`` stores the new tokens, bumps ``version`` and clears the lease, only
  while ``refresh_lease_owner`` is still the claim's own token.
- ``release`` clears the lease under the same fence after a failed refresh.

The lease is judged against the database clock (``db_now``), never an
instance's wall clock. Outcomes come from the affected-row count, except the
insert, which counts ``RETURNING`` rows (psycopg reports rowcount -1 for ``ON
CONFLICT DO NOTHING``). Ciphertext is opaque here; encryption lives in
``deerflow.mcp.oauth_store``. Database errors propagate.
"""

from __future__ import annotations

from sqlalchemy import or_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from deerflow.persistence.channel_leases.sql import db_now
from deerflow.persistence.mcp_oauth_tokens.model import McpOAuthTokenRow, StoredMcpOAuthToken


def _dialect(session: Session) -> str:
    name = session.get_bind().dialect.name
    if name not in ("postgresql", "sqlite"):
        raise ValueError(f"Unsupported MCP OAuth token database dialect: {name}")
    return name


def _key(scope: str, owner_user_id: str, server_key: str):
    return (McpOAuthTokenRow.scope == scope, McpOAuthTokenRow.owner_user_id == owner_user_id, McpOAuthTokenRow.server_key == server_key)


class SqlMcpOAuthTokenRepository:
    """Persistence facade for ``mcp_oauth_tokens``; every call blocks, so run it off the event loop."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def get(self, scope: str, owner_user_id: str, server_key: str) -> StoredMcpOAuthToken | None:
        with self._sf() as session:
            row = session.get(McpOAuthTokenRow, (scope, owner_user_id, server_key))
            if row is None:
                return None
            return StoredMcpOAuthToken(
                config_fingerprint=row.config_fingerprint,
                access_token_enc=row.access_token_enc,
                token_type=row.token_type,
                access_expires_at=row.access_expires_at,
                refresh_token_enc=row.refresh_token_enc,
                version=int(row.version),
            )

    def claim(
        self,
        scope: str,
        owner_user_id: str,
        server_key: str,
        *,
        config_fingerprint: str,
        expected_version: int | None,
        lease_owner: str,
        lease_seconds: float,
        now: float,
    ) -> bool:
        """Take the refresh lease if the row is still at ``expected_version`` (``None``: no row yet)."""
        with self._sf() as session:
            clock = db_now(_dialect(session))
            if expected_version is None:
                insert = pg_insert if _dialect(session) == "postgresql" else sqlite_insert
                stmt = (
                    insert(McpOAuthTokenRow)
                    .values(
                        scope=scope,
                        owner_user_id=owner_user_id,
                        server_key=server_key,
                        config_fingerprint=config_fingerprint,
                        version=0,
                        refresh_lease_owner=lease_owner,
                        refresh_lease_until=clock + lease_seconds,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=[McpOAuthTokenRow.scope, McpOAuthTokenRow.owner_user_id, McpOAuthTokenRow.server_key])
                    .returning(McpOAuthTokenRow.version)
                )
                claimed = len(session.execute(stmt).all()) == 1
            else:
                stmt = (
                    update(McpOAuthTokenRow)
                    .where(
                        *_key(scope, owner_user_id, server_key),
                        McpOAuthTokenRow.version == expected_version,
                        or_(McpOAuthTokenRow.refresh_lease_owner.is_(None), McpOAuthTokenRow.refresh_lease_until < clock),
                    )
                    .values(refresh_lease_owner=lease_owner, refresh_lease_until=clock + lease_seconds)
                )
                claimed = session.execute(stmt).rowcount == 1
            session.commit()
        return claimed

    def write(
        self,
        scope: str,
        owner_user_id: str,
        server_key: str,
        *,
        lease_owner: str,
        config_fingerprint: str,
        access_token_enc: str,
        token_type: str,
        access_expires_at: float,
        refresh_token_enc: str,
        rotated: bool,
        now: float,
    ) -> bool:
        """Store a refreshed token and release the lease; ``False`` when the lease is no longer this claim's."""
        values = {
            "config_fingerprint": config_fingerprint,
            "access_token_enc": access_token_enc,
            "token_type": token_type,
            "access_expires_at": access_expires_at,
            "refresh_token_enc": refresh_token_enc,
            "version": McpOAuthTokenRow.version + 1,
            "refresh_lease_owner": None,
            "refresh_lease_until": None,
            "updated_at": now,
        }
        if rotated:
            values["rotated_at"] = now
        with self._sf() as session:
            stmt = update(McpOAuthTokenRow).where(*_key(scope, owner_user_id, server_key), McpOAuthTokenRow.refresh_lease_owner == lease_owner).values(**values)
            written = session.execute(stmt).rowcount == 1
            session.commit()
        return written

    def release(self, scope: str, owner_user_id: str, server_key: str, *, lease_owner: str) -> bool:
        """Give up a claimed lease without writing a token."""
        with self._sf() as session:
            stmt = update(McpOAuthTokenRow).where(*_key(scope, owner_user_id, server_key), McpOAuthTokenRow.refresh_lease_owner == lease_owner).values(refresh_lease_owner=None, refresh_lease_until=None)
            released = session.execute(stmt).rowcount == 1
            session.commit()
        return released
