"""Wiki entry persistence (spec §3.5).

Full text + status live here in the business DB; Qdrant ``kb_wiki_entries``
only mirrors the dense vector + an ``entry_id`` pointer. Entry ids are
deterministic per ``(kb_id, title)`` so regenerating an entry overwrites the
same row (and, via the same id, the same vector point).
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.knowledge.models import WikiEntryRow
from deerflow.utils.time import coerce_iso


def wiki_entry_id(kb_id: str, title: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"deerflow:kb-wiki-entry:{kb_id}:{title}").hex


class WikiStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _to_dict(row: WikiEntryRow) -> dict[str, Any]:
        data = row.to_dict()
        if data.get("updated_at") is not None:
            data["updated_at"] = coerce_iso(data["updated_at"])
        return data

    # Sentinel to distinguish "parameter not provided" from "explicitly set to None".
    # This enables two operations:
    #   - Omitting supplement_content: preserve existing value (dirty re-generation)
    #   - Passing supplement_content=None: explicitly clear existing value
    _UNSET = object()

    async def upsert_entry(
        self,
        kb_id: str,
        *,
        title: str,
        content: str,
        source_chunk_ids: list[str],
        status: str = "ready",
        supplement_content: str | None = _UNSET,
    ) -> dict[str, Any]:
        """Create or fully refresh an entry; regeneration clears ``dirty``.

        supplement_content (Phase-3 Batch-1 P1): user annotations that survive
        dirty re-generation cycles. If provided, it overwrites existing value;
        if omitted or None, the column is explicitly set to provided value (allowing
        explicit nulling). The main ``content`` area is replaced on every call.
        """
        entry_id = wiki_entry_id(kb_id, title)
        async with self._sf() as session:
            row = await session.get(WikiEntryRow, entry_id)
            if row is None:
                # For new entries, _UNSET means "no supplement provided" → set to None
                supplement_value = None if supplement_content is self._UNSET else supplement_content
                row = WikiEntryRow(id=entry_id, kb_id=kb_id, title=title, content=content, status=status, source_chunk_ids=list(source_chunk_ids), supplement_content=supplement_value)
                session.add(row)
            else:
                row.content = content
                row.status = status
                row.source_chunk_ids = list(source_chunk_ids)
                # Phase-3 Batch-1 P1: supplement_content persists across regeneration.
                # Two modes:
                #   - If caller omits the parameter (default _UNSET): preserve existing value
                #   - If caller provides any value (including None): replace existing value
                # This allows dirty re-generation to keep user annotations while still
                # enabling explicit clearing via None.
                if supplement_content is not self._UNSET:
                    row.supplement_content = supplement_content
                row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._to_dict(row)

    async def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(WikiEntryRow, entry_id)
            return None if row is None else self._to_dict(row)

    async def list_entries(self, kb_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
        stmt = select(WikiEntryRow).where(WikiEntryRow.kb_id == kb_id)
        if status is not None:
            stmt = stmt.where(WikiEntryRow.status == status)
        stmt = stmt.order_by(WikiEntryRow.updated_at.desc(), WikiEntryRow.id.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._to_dict(row) for row in result.scalars().all()]

    async def list_kb_ids_with_dirty(self) -> list[str]:
        """Every KB carrying at least one ``dirty`` entry (boot scan scope).

        Global and unfiltered on purpose — startup resume must cover all
        owners' libraries (same shape as ``list_non_terminal_documents()``);
        ``list_kbs(owner_id)`` filters by user and cannot serve this.
        """
        stmt = select(WikiEntryRow.kb_id).where(WikiEntryRow.status == "dirty").distinct()
        async with self._sf() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_entries(self, kb_id: str, titles: Collection[str]) -> int:
        """Delete entries titled in ``titles`` (spec §3.5 条目生命周期：失格即删).

        Eligibility is the entry's raison d'être: once the entity drops below
        the wiki threshold or disappears/merges away, the entry (and its
        ``kb_wiki_entries`` vector point, deleted by the caller) goes with it.
        The entity node and its ``kb_entities`` vector stay untouched — the
        surviving chunks still serve it through the vector path. Idempotent:
        re-deleting an absent title is a no-op.
        """
        if not titles:
            return 0
        async with self._sf() as session:
            result = await session.execute(delete(WikiEntryRow).where(WikiEntryRow.kb_id == kb_id, WikiEntryRow.title.in_(list(titles))))
            await session.commit()
            return int(result.rowcount or 0)

    async def mark_dirty_for_titles(self, kb_id: str, titles: Collection[str]) -> int:
        """Flag entries whose title is one of ``titles`` as ``dirty``."""
        if not titles:
            return 0
        async with self._sf() as session:
            result = await session.execute(update(WikiEntryRow).where(WikiEntryRow.kb_id == kb_id, WikiEntryRow.title.in_(list(titles)), WikiEntryRow.status != "dirty").values(status="dirty"))
            await session.commit()
            return int(result.rowcount or 0)
