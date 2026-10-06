"""Fetcher for the vector-space projection (spec §5 P2).

Merges the four Qdrant collections into one tagged point set for the reducer:
ID-first paging (a light scroll without vectors), random subsampling for the
chunk collection only, then one batched dense retrieve for the chosen points.
Chunk hover previews join from the business DB — the payload never carries
text (spec §3.3), only the ``chunk_id`` pointer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from deerflow.knowledge.store import KnowledgeStore
    from deerflow.knowledge.vector_store import KnowledgeVectorStore

#: Default sampling budget for the chunk collection (spec §5).
DEFAULT_SAMPLE_SIZE = 5_000
#: Hard cap regardless of the requested sample size (spec §5 采样上限).
MAX_SAMPLE_SIZE = 10_000
_PREVIEW_LEN = 120

#: collection key → (source_type, KnowledgeVectorStore attribute).
_COLLECTIONS: dict[str, tuple[str, str]] = {
    "chunks": ("chunk", "chunks_collection"),
    "entities": ("entity", "entities_collection"),
    "wiki": ("wiki", "wiki_entries_collection"),
    "cards": ("card", "manual_cards_collection"),
}


@dataclass(frozen=True)
class ProjectionPoint:
    """One plottable point: business id + display metadata.

    The dense vector itself lives in :attr:`FetchedProjection.matrix` at the
    same index — keeping it out of the dataclass avoids 1024-float reprs.
    """

    id: str  # chunk_id / entity name / entry_id / card_id
    source_type: str  # chunk | entity | wiki | card
    label: str  # doc_name / entity name / title
    color_key: str  # doc_id (chunks) / entity type / source_type
    preview: str  # ≤120 chars hover preview
    heading_path: tuple[str, ...] = ()
    entity_type: str | None = None


@dataclass(frozen=True)
class FetchedProjection:
    """Fetcher output: tagged points + their dense matrix (row-aligned)."""

    points: tuple[ProjectionPoint, ...]
    matrix: np.ndarray  # (n, D) float32, row i ↔ points[i]
    total_points: int  # points across the selected collections before sampling
    sampled: bool

    @property
    def shown_points(self) -> int:
        return len(self.points)


async def fetch_projection_vectors(
    vector_store: KnowledgeVectorStore,
    store: KnowledgeStore,
    kb_id: str,
    *,
    collections: Sequence[str] = ("chunks", "entities", "wiki", "cards"),
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    rng: np.random.Generator | None = None,
) -> FetchedProjection:
    """Scroll → subsample → retrieve → preview-join for one KB's projection.

    Sampling applies to the chunk collection only (spec §5): entities, wiki
    entries and manual cards are few and always shown in full.
    """
    unknown = [key for key in collections if key not in _COLLECTIONS]
    if unknown:
        raise ValueError(f"unknown collection(s): {', '.join(unknown)}")
    if rng is None:
        rng = np.random.default_rng()
    sample_size = min(sample_size, MAX_SAMPLE_SIZE)

    points: list[ProjectionPoint] = []
    vectors: list[list[float]] = []
    total = 0
    sampled = False

    for key in collections:
        source_type, attr = _COLLECTIONS[key]
        collection = getattr(vector_store, attr)
        records = await vector_store.scroll_collection(collection, kb_id, with_vectors=False)
        total += len(records)
        if not records:
            continue
        chosen = records
        if key == "chunks" and len(records) > sample_size:
            picked = np.sort(rng.choice(len(records), size=sample_size, replace=False))
            chosen = [records[int(i)] for i in picked]
            sampled = True
        dense_map = await vector_store.retrieve_vectors(collection, [r.id for r in chosen])
        previews = await _chunk_previews(store, chosen) if key == "chunks" else {}
        for record in chosen:
            dense = dense_map.get(str(record.id))
            if dense is None:
                continue  # deleted between scroll and retrieve — drop silently
            point = _to_point(key, source_type, record.payload or {}, previews)
            if point is None:
                continue
            points.append(point)
            vectors.append(dense)

    matrix = np.asarray(vectors, dtype=np.float32).reshape(len(vectors), -1) if vectors else np.empty((0, 0), dtype=np.float32)
    return FetchedProjection(points=tuple(points), matrix=matrix, total_points=total, sampled=sampled)


async def _chunk_previews(store: KnowledgeStore, records: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """Batch-join chunk rows for hover previews (text + heading_path)."""
    chunk_ids = [str((r.payload or {}).get("chunk_id")) for r in records if (r.payload or {}).get("chunk_id")]
    if not chunk_ids:
        return {}
    rows = await store.get_chunks_by_ids(chunk_ids)
    return {str(row["chunk_id"]): row for row in rows}


def _to_point(
    key: str,
    source_type: str,
    payload: dict[str, Any],
    previews: dict[str, dict[str, Any]],
) -> ProjectionPoint | None:
    """Map one collection payload to its plottable point (None = skip)."""
    if key == "chunks":
        chunk_id = payload.get("chunk_id")
        if not chunk_id:
            return None
        row = previews.get(str(chunk_id), {})
        text = str(row.get("text") or "")
        doc_name = str(payload.get("doc_name") or "")
        heading = row.get("heading_path") or payload.get("heading_path") or []
        return ProjectionPoint(
            id=str(chunk_id),
            source_type=source_type,
            label=doc_name or str(chunk_id),
            color_key=str(payload.get("doc_id") or ""),
            preview=text[:_PREVIEW_LEN] if text else doc_name,
            heading_path=tuple(str(h) for h in heading),
        )
    if key == "entities":
        name = payload.get("name")
        if not name:
            return None
        entity_type = str(payload.get("type") or "")
        description = str(payload.get("description") or "")
        return ProjectionPoint(
            id=str(name),
            source_type=source_type,
            label=str(name),
            color_key=entity_type or source_type,
            preview=description[:_PREVIEW_LEN] if description else str(name),
            entity_type=entity_type or None,
        )
    # wiki / cards: pointer payload — title doubles as label and preview.
    id_field = "entry_id" if key == "wiki" else "card_id"
    point_id = payload.get(id_field)
    if not point_id:
        return None
    title = str(payload.get("title") or point_id)
    return ProjectionPoint(
        id=str(point_id),
        source_type=source_type,
        label=title,
        color_key=source_type,
        preview=title,
    )
