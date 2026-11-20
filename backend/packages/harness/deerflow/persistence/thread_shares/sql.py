"""Only token digests are stored; each public read rechecks expiry and revocation."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.thread_shares.model import ShareArtifactRow, ThreadShareRow
from deerflow.utils.time import coerce_iso


class ThreadShareRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    @staticmethod
    def _summary(row: ThreadShareRow) -> dict:
        return {
            key: coerce_iso(value) if isinstance(value, datetime) else value
            for key, value in {
                "share_id": row.share_id,
                "checkpoint_id": row.checkpoint_id,
                "seq": row.seq,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "revoked_at": row.revoked_at,
            }.items()
        }

    @staticmethod
    def _live(token: str):
        return (
            select(ThreadShareRow)
            .join(ThreadMetaRow, ThreadMetaRow.thread_id == ThreadShareRow.thread_id)
            .where(
                ThreadShareRow.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                ThreadShareRow.revoked_at.is_(None),
                ThreadShareRow.expires_at > datetime.now(UTC),
                ThreadMetaRow.user_id == ThreadShareRow.owner_id,
                or_(ThreadMetaRow.incarnation == ThreadShareRow.incarnation, ThreadMetaRow.incarnation.is_(None) & ThreadShareRow.incarnation.is_(None)),
            )
        )

    async def create(self, *, thread_id: str, owner_id: str, incarnation: str | None, checkpoint_id: str, seq: int, snapshot: dict, artifacts: list[dict], expires_at: datetime) -> dict:
        token = secrets.token_urlsafe(32)
        row = ThreadShareRow(
            share_id=uuid.uuid4().hex,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            thread_id=thread_id,
            owner_id=owner_id,
            incarnation=incarnation,
            checkpoint_id=checkpoint_id,
            seq=seq,
            snapshot=snapshot,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        async with self._sf() as session:
            session.add(row)
            await session.flush()
            for artifact in artifacts:
                content = artifact["content"]
                session.add(ShareArtifactRow(share_id=row.share_id, path=artifact["path"], content=content, mime_type=artifact["mime_type"], size=len(content), sha256=hashlib.sha256(content).hexdigest()))
            await session.commit()
            return {**self._summary(row), "token": token}

    async def count_active(self, thread_id: str, owner_id: str) -> int:
        async with self._sf() as session:
            return (
                await session.scalar(
                    select(func.count()).select_from(ThreadShareRow).where(ThreadShareRow.thread_id == thread_id, ThreadShareRow.owner_id == owner_id, ThreadShareRow.revoked_at.is_(None), ThreadShareRow.expires_at > datetime.now(UTC))
                )
                or 0
            )

    async def list_owned(self, thread_id: str, owner_id: str) -> list[dict]:
        async with self._sf() as session:
            active = ThreadShareRow.revoked_at.is_(None) & (ThreadShareRow.expires_at > datetime.now(UTC))
            unrevoked = ThreadShareRow.revoked_at.is_(None)
            rows = await session.execute(
                select(ThreadShareRow.share_id, ThreadShareRow.checkpoint_id, ThreadShareRow.seq, ThreadShareRow.created_at, ThreadShareRow.expires_at, ThreadShareRow.revoked_at)
                .where(ThreadShareRow.thread_id == thread_id, ThreadShareRow.owner_id == owner_id)
                .order_by(case((active, 0), (unrevoked, 1), else_=2), ThreadShareRow.created_at.desc())
                .limit(100)
            )
            return [self._summary(row) for row in rows]

    async def get_public(self, token: str) -> dict | None:
        async with self._sf() as session:
            row = await session.scalar(self._live(token))
            if row is None:
                return None
            artifacts = await session.execute(select(ShareArtifactRow.path, ShareArtifactRow.mime_type, ShareArtifactRow.sha256, ShareArtifactRow.size).where(ShareArtifactRow.share_id == row.share_id).order_by(ShareArtifactRow.path))
            return {**self._summary(row), "snapshot": row.snapshot, "artifacts": [dict(a._mapping) for a in artifacts]}

    async def get_artifact(self, token: str, path: str) -> dict | None:
        # One statement checks the grant AND retrieves the bytes. No cached grant
        # and no path resolution against the live owner's filesystem.
        live_ids = self._live(token).with_only_columns(ThreadShareRow.share_id)
        async with self._sf() as session:
            row = await session.scalar(select(ShareArtifactRow).where(ShareArtifactRow.share_id.in_(live_ids), ShareArtifactRow.path == path))
            return row.to_dict() if row else None

    async def revoke(self, thread_id: str, share_id: str, owner_id: str) -> bool:
        async with self._sf() as session:
            result = await session.execute(
                update(ThreadShareRow)
                .where(ThreadShareRow.share_id == share_id, ThreadShareRow.thread_id == thread_id, ThreadShareRow.owner_id == owner_id)
                .values(revoked_at=datetime.now(UTC), snapshot={})
                .returning(ThreadShareRow.share_id)
            )
            if result.scalar_one_or_none() is None:
                return False
            await session.execute(delete(ShareArtifactRow).where(ShareArtifactRow.share_id == share_id))
            await session.commit()
            return True
