"""SQLAlchemy-backed personal access token storage.

Each method acquires its own short-lived session. The raw ``dfp_…`` token is
generated and returned by the caller (the app layer) exactly once; this
repository only ever persists the SHA-256 digest passed to :meth:`create`.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.personal_access_tokens.model import PersonalAccessTokenRow
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)


class PersonalAccessTokenRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, last_used_write_interval_seconds: float = 300.0) -> None:
        self._sf = session_factory
        self._last_used_write_interval = last_used_write_interval_seconds
        self._last_used_written_at: dict[str, float] = {}

    @staticmethod
    def _row_to_dict(row: PersonalAccessTokenRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("expires_at", "last_used_at", "created_at", "revoked_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                # SQLite drops tzinfo on read; normalize so output is tz-aware.
                d[key] = coerce_iso(val)
        return d

    async def create(
        self,
        *,
        user_id: str,
        name: str,
        scopes: list[str],
        token_digest: str,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        row = PersonalAccessTokenRow(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=name,
            token_digest=token_digest,
            scopes=sorted(scopes),
            expires_at=expires_at,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get_active_by_digest(self, token_digest: str) -> dict[str, Any] | None:
        """Return the non-revoked, non-expired row for *token_digest*.

        Revocation and expiry are evaluated here so a stale durable row can
        never authenticate even though it remains readable for audit history.
        """
        async with self._sf() as session:
            row = (await session.execute(select(PersonalAccessTokenRow).where(PersonalAccessTokenRow.token_digest == token_digest))).scalar_one_or_none()
            if row is None or row.revoked_at is not None:
                return None
            expires_at = row.expires_at
            if expires_at is not None:
                # SQLite drops tzinfo on read; normalize before comparing.
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at <= datetime.now(UTC):
                    return None
            return self._row_to_dict(row)

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        async with self._sf() as session:
            rows = (await session.execute(select(PersonalAccessTokenRow).where(PersonalAccessTokenRow.user_id == user_id).order_by(PersonalAccessTokenRow.created_at.desc()))).scalars()
            return [self._row_to_dict(row) for row in rows]

    async def revoke(self, pat_id: str, user_id: str) -> bool:
        """Revoke one of *user_id*'s tokens; returns False if not owned/absent."""
        async with self._sf() as session:
            result = await session.execute(
                update(PersonalAccessTokenRow)
                .where(
                    PersonalAccessTokenRow.id == pat_id,
                    PersonalAccessTokenRow.user_id == user_id,
                    PersonalAccessTokenRow.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
            await session.commit()
            return result.rowcount != 0

    def _should_write_last_used(self, pat_id: str) -> bool:
        now = time.monotonic()
        last = self._last_used_written_at.get(pat_id)
        if last is not None and (now - last) < self._last_used_write_interval:
            return False
        # Bound the stamp cache: revoked/expired tokens never return here, so
        # their entries are stale by definition once the cache outgrows very
        # active token populations.
        if len(self._last_used_written_at) > 4096:
            self._last_used_written_at.clear()
        self._last_used_written_at[pat_id] = now
        return True

    async def touch_last_used(self, pat_id: str) -> None:
        """Best-effort, throttled usage stamp (at most one write per interval).

        Never raises: a failure to stamp usage must not fail the request. On
        failure the throttle window is rolled back so the next attempt
        retries promptly instead of waiting out the full interval.
        """
        if not self._should_write_last_used(pat_id):
            return
        try:
            async with self._sf() as session:
                await session.execute(update(PersonalAccessTokenRow).where(PersonalAccessTokenRow.id == pat_id).values(last_used_at=datetime.now(UTC)))
                await session.commit()
        except Exception:
            self._last_used_written_at.pop(pat_id, None)
            logger.debug("Failed to stamp last_used_at for PAT %s (non-fatal)", pat_id, exc_info=True)
