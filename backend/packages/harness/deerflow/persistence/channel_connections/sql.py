"""SQL repository for user-owned IM channel connections."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.channel_connections.model import (
    ChannelConnectionRow,
    ChannelConversationRow,
    ChannelCredentialRow,
    ChannelOAuthStateRow,
)
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)


class ChannelCredentialCipher:
    """Encrypts provider credentials before they are persisted."""

    def __init__(self, fernet: Fernet) -> None:
        self._fernet = fernet

    @classmethod
    def from_key(cls, key: str) -> ChannelCredentialCipher:
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        return cls(Fernet(base64.urlsafe_b64encode(digest)))

    def encrypt_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        return "fernet:v1:" + self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        token = value.removeprefix("fernet:v1:")
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")


class ChannelConnectionRepository:
    """Persistence facade for channel connections, credentials, and conversations."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        cipher: ChannelCredentialCipher | None = None,
    ) -> None:
        self.session_factory = session_factory
        self._cipher = cipher

    async def close(self) -> None:
        from deerflow.persistence.engine import close_engine

        await close_engine()

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex

    @staticmethod
    def _normalize_optional_identity(value: str | None) -> str:
        return value or ""

    @staticmethod
    def _coerce_datetime(value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)

    def _encrypt_optional_secret(self, value: str | None) -> str | None:
        if value is None:
            return None
        if self._cipher is None:
            raise RuntimeError("channel connection encryption key is required")
        return self._cipher.encrypt_text(value)

    @staticmethod
    def _connection_to_dict(row: ChannelConnectionRow) -> dict[str, Any]:
        data = row.to_dict()
        data["external_account_id"] = data["external_account_id"] or None
        data["workspace_id"] = data["workspace_id"] or None
        data["scopes"] = data.pop("scopes_json") or []
        data["capabilities"] = data.pop("capabilities_json") or {}
        data["metadata"] = data.pop("metadata_json") or {}
        for key in ("created_at", "updated_at", "last_seen_at", "last_error_at"):
            value = data.get(key)
            if isinstance(value, datetime):
                data[key] = coerce_iso(value)
        return data

    async def upsert_connection(
        self,
        *,
        owner_user_id: str,
        provider: str,
        external_account_id: str | None = None,
        external_account_name: str | None = None,
        workspace_id: str | None = None,
        workspace_name: str | None = None,
        bot_user_id: str | None = None,
        scopes: list[str] | None = None,
        capabilities: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "connected",
    ) -> dict[str, Any]:
        external_account_id_value = self._normalize_optional_identity(external_account_id)
        workspace_id_value = self._normalize_optional_identity(workspace_id)

        def _apply(row: ChannelConnectionRow) -> None:
            row.status = status
            row.external_account_name = external_account_name
            row.workspace_name = workspace_name
            row.bot_user_id = bot_user_id
            row.scopes_json = list(scopes or [])
            row.capabilities_json = dict(capabilities or {})
            row.metadata_json = dict(metadata or {})

        stmt = select(ChannelConnectionRow).where(
            ChannelConnectionRow.owner_user_id == owner_user_id,
            ChannelConnectionRow.provider == provider,
            ChannelConnectionRow.external_account_id == external_account_id_value,
            ChannelConnectionRow.workspace_id == workspace_id_value,
        )
        async with self.session_factory() as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                row = ChannelConnectionRow(
                    id=self._new_id(),
                    owner_user_id=owner_user_id,
                    provider=provider,
                    external_account_id=external_account_id_value,
                    workspace_id=workspace_id_value,
                )
                session.add(row)

            _apply(row)
            try:
                await session.commit()
            except IntegrityError:
                # A concurrent writer inserted the same identity first; retry as
                # an update of that row.
                await session.rollback()
                row = (await session.execute(stmt)).scalar_one()
                _apply(row)
                await session.commit()
            await session.refresh(row)
            return self._connection_to_dict(row)

    async def list_connections(self, owner_user_id: str) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(select(ChannelConnectionRow).where(ChannelConnectionRow.owner_user_id == owner_user_id).order_by(ChannelConnectionRow.updated_at.desc(), ChannelConnectionRow.id.desc()))
            return [self._connection_to_dict(row) for row in result.scalars()]

    async def disconnect_connection(self, *, connection_id: str, owner_user_id: str) -> bool:
        async with self.session_factory() as session:
            row = await session.get(ChannelConnectionRow, connection_id)
            if row is None or row.owner_user_id != owner_user_id:
                return False

            row.status = "revoked"
            credential = await session.get(ChannelCredentialRow, connection_id)
            if credential is not None:
                await session.delete(credential)
            await session.commit()
            return True

    async def disconnect_provider_connections(self, *, provider: str) -> int:
        """Revoke all active user connections for an instance-wide provider removal."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(ChannelConnectionRow.id).where(
                    ChannelConnectionRow.provider == provider,
                    ChannelConnectionRow.status != "revoked",
                )
            )
            connection_ids = [row_id for row_id in result.scalars()]
            if not connection_ids:
                return 0

            await session.execute(update(ChannelConnectionRow).where(ChannelConnectionRow.id.in_(connection_ids)).values(status="revoked"))
            await session.execute(delete(ChannelCredentialRow).where(ChannelCredentialRow.connection_id.in_(connection_ids)))
            await session.commit()
            return len(connection_ids)

    async def store_credentials(
        self,
        connection_id: str,
        *,
        access_token: str | None,
        refresh_token: str | None = None,
        token_type: str | None = None,
        expires_at: datetime | None = None,
        refresh_expires_at: datetime | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if self._cipher is None:
            raise RuntimeError("channel connection encryption key is required")
        async with self.session_factory() as session:
            row = await session.get(ChannelCredentialRow, connection_id)
            if row is None:
                row = ChannelCredentialRow(connection_id=connection_id)
                session.add(row)
            row.encrypted_access_token = self._cipher.encrypt_text(access_token)
            row.encrypted_refresh_token = self._cipher.encrypt_text(refresh_token)
            row.token_type = token_type
            row.expires_at = expires_at
            row.refresh_expires_at = refresh_expires_at
            row.encrypted_extra_json = self._cipher.encrypt_text(json.dumps(extra or {}, ensure_ascii=False))
            row.version = (row.version or 0) + 1
            await session.commit()

    async def get_credentials(self, connection_id: str) -> dict[str, Any] | None:
        if self._cipher is None:
            return None
        async with self.session_factory() as session:
            row = await session.get(ChannelCredentialRow, connection_id)
            if row is None:
                return None
            try:
                extra_raw = self._cipher.decrypt_text(row.encrypted_extra_json)
                return {
                    "connection_id": row.connection_id,
                    "access_token": self._cipher.decrypt_text(row.encrypted_access_token),
                    "refresh_token": self._cipher.decrypt_text(row.encrypted_refresh_token),
                    "token_type": row.token_type,
                    "expires_at": self._coerce_datetime(row.expires_at),
                    "refresh_expires_at": self._coerce_datetime(row.refresh_expires_at),
                    "extra": json.loads(extra_raw) if extra_raw else {},
                }
            except (InvalidToken, UnicodeError, json.JSONDecodeError):
                logger.warning(
                    "Unable to decrypt channel connection credentials; treating credentials as unavailable",
                    exc_info=True,
                )
                return None

    @staticmethod
    def hash_state(state: str) -> str:
        return hashlib.sha256(state.encode("utf-8")).hexdigest()

    async def create_oauth_state(
        self,
        *,
        owner_user_id: str,
        provider: str,
        state: str,
        expires_at: datetime,
        code_verifier: str | None = None,
        nonce_hash: str | None = None,
        redirect_after: str | None = None,
        requested_scopes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        row = ChannelOAuthStateRow(
            state_hash=self.hash_state(state),
            owner_user_id=owner_user_id,
            provider=provider,
            code_verifier_encrypted=self._encrypt_optional_secret(code_verifier),
            nonce_hash=nonce_hash,
            redirect_after=redirect_after,
            requested_scopes_json=list(requested_scopes or []),
            metadata_json=dict(metadata or {}),
            expires_at=expires_at,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def count_oauth_states(self, *, owner_user_id: str, provider: str) -> int:
        async with self.session_factory() as session:
            result = await session.execute(
                select(func.count())
                .select_from(ChannelOAuthStateRow)
                .where(
                    ChannelOAuthStateRow.owner_user_id == owner_user_id,
                    ChannelOAuthStateRow.provider == provider,
                )
            )
            return int(result.scalar_one())

    async def consume_oauth_state(
        self,
        *,
        provider: str,
        state: str,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        current_time = now or datetime.now(UTC)
        state_hash = self.hash_state(state)
        async with self.session_factory() as session:
            await session.execute(delete(ChannelOAuthStateRow).where(ChannelOAuthStateRow.expires_at < current_time))
            row = await session.get(ChannelOAuthStateRow, state_hash)
            if row is None or row.provider != provider or row.consumed_at is not None:
                await session.commit()
                return None
            expires_at = self._coerce_datetime(row.expires_at)
            if expires_at is not None and expires_at < current_time:
                await session.commit()
                return None

            # Conditional UPDATE so two concurrent workers cannot both consume
            # the same binding code: only the writer that flips consumed_at
            # from NULL wins.
            result = await session.execute(
                update(ChannelOAuthStateRow)
                .where(
                    ChannelOAuthStateRow.state_hash == state_hash,
                    ChannelOAuthStateRow.consumed_at.is_(None),
                )
                .values(consumed_at=current_time)
            )
            await session.commit()
            if result.rowcount != 1:
                return None
            return {
                "owner_user_id": row.owner_user_id,
                "provider": row.provider,
                "requested_scopes": row.requested_scopes_json or [],
                "metadata": row.metadata_json or {},
                "redirect_after": row.redirect_after,
            }

    async def find_connection_by_external_identity(
        self,
        *,
        provider: str,
        external_account_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(ChannelConnectionRow)
                .where(
                    ChannelConnectionRow.provider == provider,
                    ChannelConnectionRow.external_account_id == self._normalize_optional_identity(external_account_id),
                    ChannelConnectionRow.workspace_id == self._normalize_optional_identity(workspace_id),
                    ChannelConnectionRow.status == "connected",
                )
                .order_by(ChannelConnectionRow.updated_at.desc(), ChannelConnectionRow.id.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return self._connection_to_dict(row) if row is not None else None

    async def set_thread_id(
        self,
        *,
        connection_id: str,
        owner_user_id: str,
        provider: str,
        external_conversation_id: str,
        thread_id: str,
        external_topic_id: str | None = None,
    ) -> None:
        topic_id = external_topic_id or ""
        async with self.session_factory() as session:
            stmt = select(ChannelConversationRow).where(
                ChannelConversationRow.connection_id == connection_id,
                ChannelConversationRow.external_conversation_id == external_conversation_id,
                ChannelConversationRow.external_topic_id == topic_id,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                row = ChannelConversationRow(
                    id=self._new_id(),
                    connection_id=connection_id,
                    owner_user_id=owner_user_id,
                    provider=provider,
                    external_conversation_id=external_conversation_id,
                    external_topic_id=topic_id,
                    thread_id=thread_id,
                )
                session.add(row)
            else:
                row.thread_id = thread_id
                row.owner_user_id = owner_user_id
                row.provider = provider
            await session.commit()

    async def get_thread_id(
        self,
        connection_id: str,
        external_conversation_id: str,
        external_topic_id: str | None = None,
    ) -> str | None:
        async with self.session_factory() as session:
            stmt = select(ChannelConversationRow.thread_id).where(
                ChannelConversationRow.connection_id == connection_id,
                ChannelConversationRow.external_conversation_id == external_conversation_id,
                ChannelConversationRow.external_topic_id == (external_topic_id or ""),
            )
            return (await session.execute(stmt)).scalar_one_or_none()
