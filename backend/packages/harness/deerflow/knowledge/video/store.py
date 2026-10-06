"""Shot persistence (spec 2026-09-08 §3).

``video_shots`` keeps the media-side fields only — the PTS interval, the
keyframe pointer, and the three raw extraction paths. The assembled card
body lives in ``chunks``; this store never touches it.

Upsert contract (resume/re-run safe): payload mappings key off
``shot_index``; **present keys overwrite, absent keys persist** on update
and fall back to column defaults on insert. ``caption_status`` therefore
survives a re-materialize unless the payload explicitly resets it — status
resets belong to the recaption flow (plan Task 8b), not to the write path.

A mapping that would INSERT (row absent) but lacks the non-null
``start_ms``/``end_ms`` columns is skipped with a warning instead of violating
NOT NULL — the delete-vs-index race (same-name re-upload cascades the rows
away mid-flight) must degrade to a no-op, not kill the whole indexing leg
(2026-09-09 incident).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.knowledge.models import VideoShotRow
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)

#: Columns a payload mapping may write (``shot_index`` is the lookup key).
_WRITABLE = ("start_ms", "end_ms", "keyframe_path", "asr_text", "ocr_text", "caption", "caption_status")


class VideoShotStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _to_dict(row: VideoShotRow) -> dict[str, Any]:
        data = row.to_dict()
        if data.get("created_at") is not None:
            data["created_at"] = coerce_iso(data["created_at"])
        return data

    async def bulk_upsert_shots(self, doc_id: str, *, kb_id: str, shots: Sequence[Mapping[str, Any]]) -> int:
        """Insert-or-update one document's shots; returns rows written.

        Insert requires ``shot_index``/``start_ms``/``end_ms`` (non-null
        columns); update applies only the keys present in each mapping (see
        module docstring). One transaction for the whole batch — a mid-batch
        failure leaves the previous state intact.
        """
        if not shots:
            return 0
        written = 0
        async with self._sf() as session:
            for shot in shots:
                index = int(shot["shot_index"])
                result = await session.execute(select(VideoShotRow).where(VideoShotRow.doc_id == doc_id, VideoShotRow.shot_index == index))
                row = result.scalar_one_or_none()
                if row is None:
                    if "start_ms" not in shot or "end_ms" not in shot:
                        logger.warning("skip shot upsert insert: doc %s shot %d has no row and payload lacks start_ms/end_ms", doc_id, index)
                        continue
                    row = VideoShotRow(id=uuid.uuid4().hex, doc_id=doc_id, kb_id=kb_id, shot_index=index, **{key: shot[key] for key in _WRITABLE if key in shot})
                    session.add(row)
                else:
                    for key in _WRITABLE:
                        if key in shot:
                            setattr(row, key, shot[key])
                written += 1
            await session.commit()
        return written

    async def list_shots(self, doc_id: str) -> list[dict[str, Any]]:
        """All shots of a document, ascending by ``shot_index`` (media order)."""
        stmt = select(VideoShotRow).where(VideoShotRow.doc_id == doc_id).order_by(VideoShotRow.shot_index)
        async with self._sf() as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [self._to_dict(row) for row in rows]

    async def list_pending_shots(self, doc_id: str) -> list[dict[str, Any]]:
        """Shots whose caption leg still owes a run (resume state machine:
        pending → done / failed / empty). The worker re-entry consumes this
        list and nothing else — done/failed/empty shots are never re-captioned
        implicitly."""
        stmt = select(VideoShotRow).where(VideoShotRow.doc_id == doc_id, VideoShotRow.caption_status == "pending").order_by(VideoShotRow.shot_index)
        async with self._sf() as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [self._to_dict(row) for row in rows]

    async def delete_by_doc(self, doc_id: str) -> int:
        """Cascade helper for document deletion; idempotent (absent doc → 0).
        Keyframe files live outside the DB — the caller's cascade removes the
        frames dir (plan Task 7, mirrors ``_remove_dir``)."""
        async with self._sf() as session:
            result = await session.execute(delete(VideoShotRow).where(VideoShotRow.doc_id == doc_id))
            await session.commit()
            return int(result.rowcount or 0)
