"""Async repository for App-Key profiles, credentials, and capabilities."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from deerflow.persistence.app_keys.model import AppCapabilityRow, AppCredentialRow, AppKeyAuditRow, AppProfileRow

_CAPABILITIES = frozenset({"agents", "models", "skills", "tool_groups", "tools"})


class AppKeyRepository:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    @staticmethod
    def hash_key(app_key: str) -> str:
        return hashlib.sha256(app_key.encode("utf-8")).hexdigest()

    async def create_profile(self, *, app_id: str, name: str, description: str | None, capabilities: dict[str, Iterable[str]], actor_user_id: str) -> dict:
        async with self._sf() as session:
            row = AppProfileRow(id=app_id, name=name, description=description, created_by=actor_user_id)
            session.add(row)
            self._replace_capabilities(session, app_id, capabilities)
            self._audit(session, "profile.create", app_id, None, actor_user_id)
            await session.commit()
        return await self.get_profile(app_id, include_disabled=True)  # type: ignore[return-value]

    async def get_profile(self, app_id: str, *, include_disabled: bool = False) -> dict | None:
        async with self._sf() as session:
            row = await session.get(AppProfileRow, app_id)
            if row is None or (row.disabled and not include_disabled):
                return None
            caps = list((await session.execute(select(AppCapabilityRow).where(AppCapabilityRow.app_id == app_id))).scalars())
            credentials = list((await session.execute(select(AppCredentialRow).where(AppCredentialRow.app_id == app_id).order_by(AppCredentialRow.created_at.desc()))).scalars())
            return self._profile_dict(row, caps, credentials)

    async def list_profiles(self) -> list[dict]:
        async with self._sf() as session:
            profiles = list((await session.execute(select(AppProfileRow).order_by(AppProfileRow.id))).scalars())
        return [profile for profile in [await self.get_profile(row.id, include_disabled=True) for row in profiles] if profile is not None]

    async def update_profile(
        self,
        app_id: str,
        *,
        name: str | None,
        description: str | None,
        disabled: bool | None,
        capabilities: dict[str, Iterable[str]] | None,
        actor_user_id: str,
    ) -> dict | None:
        async with self._sf() as session:
            row = await session.get(AppProfileRow, app_id)
            if row is None:
                return None
            if name is not None:
                row.name = name
            if description is not None:
                row.description = description
            if disabled is not None:
                row.disabled = disabled
            if capabilities is not None:
                for capability in capabilities:
                    if capability not in _CAPABILITIES:
                        raise ValueError(f"Unsupported capability: {capability}")
                existing = list((await session.execute(select(AppCapabilityRow).where(AppCapabilityRow.app_id == app_id))).scalars())
                merged_capabilities: dict[str, list[str]] = {capability: [] for capability in _CAPABILITIES}
                for capability in existing:
                    merged_capabilities[capability.capability].append(capability.value)
                merged_capabilities.update({capability: list(values) for capability, values in capabilities.items()})
                await session.execute(delete(AppCapabilityRow).where(AppCapabilityRow.app_id == app_id))
                self._replace_capabilities(session, app_id, merged_capabilities)
            self._audit(session, "profile.update", app_id, None, actor_user_id)
            await session.commit()
        return await self.get_profile(app_id, include_disabled=True)

    async def generate_credential(self, app_id: str, *, actor_user_id: str, expires_at: datetime | None = None) -> dict | None:
        app_key = f"dfak_{secrets.token_urlsafe(32)}"
        key_hash = self.hash_key(app_key)
        async with self._sf() as session:
            profile = await session.get(AppProfileRow, app_id)
            if profile is None or profile.disabled:
                return None
            session.add(AppCredentialRow(key_hash=key_hash, key_prefix=app_key[:12], app_id=app_id, created_by=actor_user_id, expires_at=expires_at))
            self._audit(session, "key.generate", app_id, key_hash, actor_user_id)
            await session.commit()
        return {"app_id": app_id, "app_key": app_key, "key_hash": key_hash, "key_prefix": app_key[:12], "created_at": datetime.now(UTC)}

    async def revoke_credential(self, key_hash: str, *, actor_user_id: str) -> bool:
        async with self._sf() as session:
            row = await session.get(AppCredentialRow, key_hash)
            if row is None or row.revoked_at is not None:
                return False
            row.revoked_at = datetime.now(UTC)
            self._audit(session, "key.revoke", row.app_id, key_hash, actor_user_id)
            await session.commit()
            return True

    async def find_active_profile_by_api_key(self, app_key: str) -> dict | None:
        """Direct DB lookup; intentionally no process-local or Redis cache."""
        key_hash = self.hash_key(app_key)
        async with self._sf() as session:
            credential = await session.get(AppCredentialRow, key_hash)
            if credential is None or credential.revoked_at is not None or (credential.expires_at is not None and credential.expires_at <= datetime.now(UTC)):
                return None
            profile = await session.get(AppProfileRow, credential.app_id)
            if profile is None or profile.disabled:
                return None
        return await self.get_profile(credential.app_id)

    @staticmethod
    def _replace_capabilities(session, app_id: str, capabilities: dict[str, Iterable[str]]) -> None:
        for capability, values in capabilities.items():
            if capability not in _CAPABILITIES:
                raise ValueError(f"Unsupported capability: {capability}")
            for value in set(values):
                session.add(AppCapabilityRow(app_id=app_id, capability=capability, value=value))

    @staticmethod
    def _audit(session, action: str, app_id: str | None, key_hash: str | None, actor_user_id: str) -> None:
        session.add(AppKeyAuditRow(id=uuid.uuid4().hex, action=action, app_id=app_id, key_hash=key_hash, actor_user_id=actor_user_id))

    @staticmethod
    def _profile_dict(row: AppProfileRow, caps: list[AppCapabilityRow], credentials: list[AppCredentialRow]) -> dict:
        grouped = {name: [] for name in _CAPABILITIES}
        for cap in caps:
            grouped[cap.capability].append(cap.value)
        return {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "created_by": row.created_by,
            "disabled": row.disabled,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            **grouped,
            "credentials": [{"key_hash": c.key_hash, "key_prefix": c.key_prefix, "created_at": c.created_at, "expires_at": c.expires_at, "revoked_at": c.revoked_at, "last_used_at": c.last_used_at} for c in credentials],
        }
