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
- ``renew`` extends a live lease while the claim's token request runs: HTTP
  timeouts bound each I/O wait, not the whole request, so a slow response must
  not let a peer take over and resend the same refresh token.
- ``write`` stores the new tokens, bumps ``version`` and clears the lease, only
  while ``refresh_lease_owner`` is still the claim's own token.
- ``release`` clears the lease under the same fence after a failed refresh.
- ``delete_except`` drops one owner's rows for connections a saved
  configuration no longer has; their keys can never be derived again.

The lease is judged against the database clock (``db_now``), never an
instance's wall clock. Outcomes come from the affected-row count, except the
insert, which counts ``RETURNING`` rows (psycopg reports rowcount -1 for ``ON
CONFLICT DO NOTHING``). Ciphertext is opaque here; encryption lives in
``deerflow.mcp.oauth_store``. Database errors propagate.
"""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from deerflow.persistence.channel_leases.sql import db_now
from deerflow.persistence.mcp_oauth_tokens.model import McpOAuthAttemptRow, McpOAuthTokenRow, StoredMcpOAuthAttempt, StoredMcpOAuthToken


def _dialect(session: Session) -> str:
    name = session.get_bind().dialect.name
    if name not in ("postgresql", "sqlite"):
        raise ValueError(f"Unsupported MCP OAuth token database dialect: {name}")
    return name


def _key(scope: str, owner_user_id: str, server_key: str):
    return (McpOAuthTokenRow.scope == scope, McpOAuthTokenRow.owner_user_id == owner_user_id, McpOAuthTokenRow.server_key == server_key)


def _attempt_key(owner_user_id: str, server_key: str):
    return (McpOAuthAttemptRow.owner_user_id == owner_user_id, McpOAuthAttemptRow.server_key == server_key)


_CLEARED_TOKENS = {
    "access_token_enc": None,
    "token_request_fingerprint": None,
    "token_type": None,
    "access_expires_at": None,
    "refresh_token_enc": None,
    "refresh_lease_owner": None,
    "refresh_lease_until": None,
    "rotated_at": None,
}


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
                token_request_fingerprint=row.token_request_fingerprint,
                token_type=row.token_type,
                access_expires_at=row.access_expires_at,
                refresh_token_enc=row.refresh_token_enc,
                version=int(row.version),
                grant_epoch=row.grant_epoch,
                grant_context=row.grant_context,
            )

    def list_delegated_servers(self, owner_user_id: str) -> list[str]:
        """List the owner's grants, including those awaiting reconnect, without reading tokens."""
        row = McpOAuthTokenRow
        stmt = select(row.server_key).where(row.scope == "delegated", row.owner_user_id == owner_user_id, row.grant_context.is_not(None)).order_by(row.server_key)
        with self._sf() as session:
            return list(session.scalars(stmt))

    def begin_delegated(
        self,
        owner_user_id: str,
        server_key: str,
        *,
        fingerprint: str,
        state_digest: str,
        browser_digest: str,
        verifier_enc: str,
        context: str,
        ttl_seconds: int,
    ) -> int:
        """Reserve a new epoch and replace any pending attempt in one commit."""
        # Expiry cleanup acquires no grant row locks. Commit it separately so
        # it cannot deadlock with a peer replacing or disconnecting a grant.
        with self._sf() as session:
            session.execute(delete(McpOAuthAttemptRow).where(McpOAuthAttemptRow.expires_at <= db_now(_dialect(session))))
            session.commit()
        with self._sf() as session:
            dialect = _dialect(session)
            insert = pg_insert if dialect == "postgresql" else sqlite_insert
            clock = db_now(dialect)
            epoch = session.execute(
                insert(McpOAuthTokenRow)
                .values(
                    scope="delegated",
                    owner_user_id=owner_user_id,
                    server_key=server_key,
                    config_fingerprint=fingerprint,
                    grant_epoch=1,
                    updated_at=clock,
                    version=0,
                )
                .on_conflict_do_update(
                    index_elements=[McpOAuthTokenRow.scope, McpOAuthTokenRow.owner_user_id, McpOAuthTokenRow.server_key],
                    set_={
                        **_CLEARED_TOKENS,
                        "grant_epoch": McpOAuthTokenRow.grant_epoch + 1,
                        "config_fingerprint": fingerprint,
                        "grant_context": None,
                        "updated_at": clock,
                        "version": McpOAuthTokenRow.version + 1,
                    },
                )
                .returning(McpOAuthTokenRow.grant_epoch)
            ).scalar_one()
            attempt = {
                "state_digest": state_digest,
                "browser_digest": browser_digest,
                "config_fingerprint": fingerprint,
                "grant_epoch": epoch,
                "grant_context": context,
                "verifier_enc": verifier_enc,
                "expires_at": clock + ttl_seconds,
            }
            session.execute(
                insert(McpOAuthAttemptRow).values(owner_user_id=owner_user_id, server_key=server_key, **attempt).on_conflict_do_update(index_elements=[McpOAuthAttemptRow.owner_user_id, McpOAuthAttemptRow.server_key], set_=attempt)
            )
            session.commit()
            return epoch

    def consume_delegated(self, state_digest: str, *, owner_user_id: str, browser_digest: str) -> StoredMcpOAuthAttempt | None:
        """Consume the current attempt for this browser, if it has not expired.

        Beginning a new attempt or disconnecting replaces or removes this row
        in the same commit as the epoch change. Completion still checks the
        epoch because it runs after the remote token exchange.
        """
        with self._sf() as session:
            row = session.execute(
                delete(McpOAuthAttemptRow)
                .where(
                    McpOAuthAttemptRow.state_digest == state_digest,
                    McpOAuthAttemptRow.browser_digest == browser_digest,
                    McpOAuthAttemptRow.owner_user_id == owner_user_id,
                    McpOAuthAttemptRow.expires_at > db_now(_dialect(session)),
                )
                .returning(
                    McpOAuthAttemptRow.server_key,
                    McpOAuthAttemptRow.config_fingerprint,
                    McpOAuthAttemptRow.grant_epoch,
                    McpOAuthAttemptRow.grant_context,
                    McpOAuthAttemptRow.verifier_enc,
                )
            ).one_or_none()
            session.commit()
            return StoredMcpOAuthAttempt(owner_user_id, *row) if row is not None else None

    def complete_delegated(
        self,
        owner_user_id: str,
        server_key: str,
        *,
        grant_epoch: int,
        fingerprint: str,
        context: str,
        access_token_enc: str,
        access_expires_at: float | None,
        refresh_token_enc: str | None,
    ) -> bool:
        with self._sf() as session:
            stmt = (
                update(McpOAuthTokenRow)
                .where(
                    *_key("delegated", owner_user_id, server_key),
                    McpOAuthTokenRow.config_fingerprint == fingerprint,
                    McpOAuthTokenRow.grant_epoch == grant_epoch,
                    McpOAuthTokenRow.grant_context.is_(None),
                )
                .values(
                    grant_context=context,
                    access_token_enc=access_token_enc,
                    access_expires_at=access_expires_at,
                    refresh_token_enc=refresh_token_enc,
                    token_request_fingerprint=fingerprint,
                    token_type="Bearer",
                    version=McpOAuthTokenRow.version + 1,
                    updated_at=db_now(_dialect(session)),
                )
            )
            committed = session.execute(stmt).rowcount == 1
            session.commit()
            return committed

    def disconnect_delegated(
        self,
        owner_user_id: str,
        server_key: str,
        *,
        expected_epoch: int | None,
        lease_owner: str | None = None,
        access_only_version: int | None = None,
    ) -> bool:
        """Revoke the grant while retaining its epoch."""
        with self._sf() as session:
            conditions = list(_key("delegated", owner_user_id, server_key))
            values = dict(_CLEARED_TOKENS)
            if expected_epoch is not None:
                conditions.append(McpOAuthTokenRow.grant_epoch == expected_epoch)
            if lease_owner is not None:
                conditions.append(McpOAuthTokenRow.refresh_lease_owner == lease_owner)
            if access_only_version is not None:
                conditions.extend((McpOAuthTokenRow.version == access_only_version, McpOAuthTokenRow.refresh_token_enc.is_(None)))
            if lease_owner is None and access_only_version is None:
                # An explicit disconnect clears status as well as credentials.
                values["grant_context"] = None
            stmt = (
                update(McpOAuthTokenRow)
                .where(*conditions)
                .values(
                    **values,
                    grant_epoch=McpOAuthTokenRow.grant_epoch + 1,
                    version=McpOAuthTokenRow.version + 1,
                    updated_at=db_now(_dialect(session)),
                )
            )
            disconnected = session.execute(stmt).rowcount == 1
            if disconnected:
                session.execute(delete(McpOAuthAttemptRow).where(*_attempt_key(owner_user_id, server_key)))
            session.commit()
            return disconnected

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
        grant_epoch: int | None = None,
    ) -> bool:
        """Take the refresh lease if the row is still at ``expected_version`` (``None``: no row yet)."""
        with self._sf() as session:
            clock = db_now(_dialect(session))
            if expected_version is None:
                if scope == "delegated":
                    return False  # Browser grants can only be created by completing authorization.
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
                conditions = [
                    *_key(scope, owner_user_id, server_key),
                    McpOAuthTokenRow.version == expected_version,
                    or_(McpOAuthTokenRow.refresh_lease_owner.is_(None), McpOAuthTokenRow.refresh_lease_until < clock),
                ]
                if scope == "delegated":
                    if grant_epoch is None:
                        return False
                    conditions.extend((McpOAuthTokenRow.grant_epoch == grant_epoch, McpOAuthTokenRow.config_fingerprint == config_fingerprint, McpOAuthTokenRow.refresh_token_enc.is_not(None)))
                stmt = update(McpOAuthTokenRow).where(*conditions).values(refresh_lease_owner=lease_owner, refresh_lease_until=clock + lease_seconds)
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
        token_request_fingerprint: str,
        token_type: str,
        access_expires_at: float | None,
        refresh_token_enc: str,
        rotated: bool,
        now: float,
        grant_epoch: int | None = None,
    ) -> bool:
        """Store a refreshed token and release the lease; ``False`` when the lease is no longer this claim's."""
        values = {
            "config_fingerprint": config_fingerprint,
            "access_token_enc": access_token_enc,
            "token_request_fingerprint": token_request_fingerprint,
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
            conditions = [*_key(scope, owner_user_id, server_key), McpOAuthTokenRow.refresh_lease_owner == lease_owner]
            if scope == "delegated":
                if grant_epoch is None:
                    return False
                conditions.extend((McpOAuthTokenRow.grant_epoch == grant_epoch, McpOAuthTokenRow.config_fingerprint == config_fingerprint))
            stmt = update(McpOAuthTokenRow).where(*conditions).values(**values)
            written = session.execute(stmt).rowcount == 1
            session.commit()
        return written

    def renew(self, scope: str, owner_user_id: str, server_key: str, *, lease_owner: str, lease_seconds: float) -> bool:
        """Extend the claim's lease while it is still live; ``False`` once it expired or changed hands."""
        with self._sf() as session:
            clock = db_now(_dialect(session))
            stmt = update(McpOAuthTokenRow).where(*_key(scope, owner_user_id, server_key), McpOAuthTokenRow.refresh_lease_owner == lease_owner, McpOAuthTokenRow.refresh_lease_until > clock).values(refresh_lease_until=clock + lease_seconds)
            renewed = session.execute(stmt).rowcount == 1
            session.commit()
        return renewed

    def release(self, scope: str, owner_user_id: str, server_key: str, *, lease_owner: str) -> bool:
        """Give up a claimed lease without writing a token."""
        with self._sf() as session:
            stmt = update(McpOAuthTokenRow).where(*_key(scope, owner_user_id, server_key), McpOAuthTokenRow.refresh_lease_owner == lease_owner).values(refresh_lease_owner=None, refresh_lease_until=None)
            released = session.execute(stmt).rowcount == 1
            session.commit()
        return released

    def delete_except(self, scope: str, owner_user_id: str, keep_server_keys: Collection[str]) -> int:
        """Delete ``(scope, owner_user_id)``'s rows whose ``server_key`` is not kept; returns how many."""
        stmt = delete(McpOAuthTokenRow).where(McpOAuthTokenRow.scope == scope, McpOAuthTokenRow.owner_user_id == owner_user_id)
        if keep_server_keys:
            stmt = stmt.where(McpOAuthTokenRow.server_key.not_in(sorted(keep_server_keys)))
        with self._sf() as session:
            deleted = session.execute(stmt).rowcount
            session.commit()
        return int(deleted)
