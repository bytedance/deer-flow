"""Qdrant vector store for the RAG knowledge base.

One collection (spec §3.3–§3.5), with named vectors ``dense``
(1024-dim COSINE by default — the width is a deployment setting since
spec 2026-09-26 D1 乙) + ``sparse`` (Qdrant sparse vectors always score by dot
product, giving the DOT path):

- ``kb_chunks``       — chunk vectors; payload carries the ``chunk_id``
  pointer, filter fields (``kb_id``/``doc_id``/``entities``) and unindexed
  display metadata (``doc_name``/``heading_path``/``page``). Never the chunk
  text — text lives only in the business DB ``chunks`` table.

A non-default width appends it to every name (``kb_chunks_1536``): the width is part of
the identity of a vector space, so a rebuild into a new width writes a *new* generation
and the old one keeps answering until the switch (spec 2026-09-26 D5-2). The default
width keeps the unsuffixed names, which are what every deployment created before the
width became configurable — an untouched deployment must be byte-for-byte unchanged.

The async client keeps the offline indexing worker and the online retrieval
tools off the event loop's blocking path.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    Fusion,
    FusionQuery,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    Record,
    ScoredPoint,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from deerflow_knowledge.embedder_factory import DEFAULT_COLLECTION_DIMENSION, effective_dimension

logger = logging.getLogger(__name__)

#: Payload fields that get a KEYWORD index on ``kb_chunks`` (spec §3.3) —
#: only filter conditions are indexed; display metadata stays unindexed.
_CHUNKS_PAYLOAD_INDEXES: tuple[str, ...] = ("kb_id", "doc_id", "entities")

#: The logical collections, in the order they are created.
_KINDS: tuple[str, ...] = ("chunks",)

#: Named-vector key of the dense half (the sparse half is the other).
_DENSE_VECTOR_NAME = "dense"


class DimensionMigrationRequired(ValueError):
    """The live generation is not the one this configuration writes, and no migration ran.

    Raised instead of quietly creating an empty collection: the new one would answer every
    query with nothing, which the user reads as "my library was wiped". A ``ValueError``,
    not an ``EmbedderError``, so the indexer never buries it as a soft per-batch failure.
    """

    def __init__(self, *, existing: str, existing_size: int, expected: int) -> None:
        self.existing = existing
        self.existing_size = existing_size
        self.expected = expected
        super().__init__(f"向量库集合 {existing} 是 {existing_size} 维，而当前生效宽度是 {expected} 维 ⇒ 拒绝启用，需要先完成维度迁移（到「设置 → 模型 → 功能模型」保存该维度以触发全库重建，重建完成后配置才会切过去）。")


@dataclass(slots=True)
class ChunkUpsert:
    """One chunk vector + its Qdrant payload (no chunk text, by design)."""

    chunk_id: str
    kb_id: str
    doc_id: str
    dense: list[float]
    sparse: SparseVector
    doc_name: str = ""
    heading_path: list[str] = field(default_factory=list)
    page: int | None = None
    entities: list[str] = field(default_factory=list)


class KnowledgeVectorStore:
    """Qdrant facade for the knowledge collections."""

    def __init__(
        self,
        url: str | None = None,
        *,
        client: AsyncQdrantClient | None = None,
        collection_prefix: str = "kb",
        dense_size: int = DEFAULT_COLLECTION_DIMENSION,
    ) -> None:
        if client is None:
            if url is None:
                raise ValueError("KnowledgeVectorStore requires a Qdrant url or a client")
            client = AsyncQdrantClient(url)
        self._client = client
        self._url = url
        self._prefix = collection_prefix
        self._dense_size = dense_size

    def _name(self, kind: str) -> str:
        return f"{self._prefix}_{kind}{self._suffix(self._dense_size)}"

    @staticmethod
    def _suffix(width: int) -> str:
        return "" if width == DEFAULT_COLLECTION_DIMENSION else f"_{width}"

    @property
    def collection_prefix(self) -> str:
        return self._prefix

    @property
    def dense_size(self) -> int:
        return self._dense_size

    @property
    def url(self) -> str | None:
        return self._url

    def names_at_width(self, width: int) -> tuple[str, ...]:
        """This deployment's collection names at *width* (the generation GC's anchor)."""
        suffix = self._suffix(width)
        return tuple(f"{self._prefix}_{kind}{suffix}" for kind in _KINDS)

    @property
    def chunks_collection(self) -> str:
        return self._name("chunks")

    @property
    def collection_names(self) -> tuple[str, ...]:
        return tuple(self._name(kind) for kind in _KINDS)

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        """Deterministic UUID per chunk so re-upserts overwrite in place."""
        return uuid.uuid5(uuid.NAMESPACE_URL, f"deerflow:kb-chunk:{chunk_id}").hex

    async def collection_size(self, name: str) -> int | None:
        """The dense width a collection was created at; ``None`` when it does not exist.

        The width is readable off the collection, which is what lets the runtime tell a
        finished migration from one that never ran (spec 2026-09-26 D1 乙 / 验收 5).
        """
        if not await self._client.collection_exists(name):
            return None
        info = await self._client.get_collection(name)
        vectors = info.config.params.vectors
        params = vectors.get(_DENSE_VECTOR_NAME) if isinstance(vectors, dict) else vectors
        return getattr(params, "size", None)

    async def init_collections(self) -> None:
        """Create the live generation's collections, unless that would hide an older one.

        The hand-off is the point: with a declared width and no migration behind it, the
        declaration's collections do not exist yet while the vectors are all in the older
        generation. Creating them here would make the library read as empty, so this refuses
        and names the migration instead (``DimensionMigrationRequired``).
        """
        if self._dense_size != DEFAULT_COLLECTION_DIMENSION:
            for kind in _KINDS:
                legacy = f"{self._prefix}_{kind}"
                existing_size = await self.collection_size(legacy)
                if existing_size is not None:
                    raise DimensionMigrationRequired(existing=legacy, existing_size=existing_size, expected=self._dense_size)
        await self.create_collections()

    async def drop_collections(self) -> list[str]:
        """Delete this store's collections (the ones that exist), returning their names.

        Two callers, both about generations: the migration drops a leftover from an
        interrupted run before building the new one, and drops the *old* generation once
        the switch is done (spec 2026-09-26 D5-2 — best-effort, the vectors are already
        served by the new one).
        """
        dropped: list[str] = []
        for name in self.collection_names:
            if await self._client.collection_exists(name):
                await self._client.delete_collection(name)
                dropped.append(name)
        return dropped

    async def list_all_collections(self) -> list[str]:
        """Every collection name in the deployment's Qdrant (generation GC input)."""
        response = await self._client.get_collections()
        return sorted(collection.name for collection in response.collections)

    async def drop_collection(self, name: str) -> bool:
        """Drop one named collection; returns False when it did not exist."""
        if not await self._client.collection_exists(name):
            return False
        await self._client.delete_collection(name)
        return True

    async def create_collections(self) -> None:
        """Create the collections + payload indexes at this store's width, idempotently.
        No judgement about older generations: this is also the migration's own entry — it is
        the migration's job to build the new generation while the old one still answers.
        """
        for name in self.collection_names:
            if await self._client.collection_exists(name):
                continue
            await self._client.create_collection(
                collection_name=name,
                vectors_config={_DENSE_VECTOR_NAME: VectorParams(size=self._dense_size, distance=Distance.COSINE)},
                sparse_vectors_config={"sparse": SparseVectorParams()},
            )
        # create_payload_index is itself idempotent (same name+schema → ok).
        for field_name in _CHUNKS_PAYLOAD_INDEXES:
            await self._client.create_payload_index(self.chunks_collection, field_name, PayloadSchemaType.KEYWORD)

    async def upsert_chunks(self, chunks: Sequence[ChunkUpsert]) -> int:
        points = [
            PointStruct(
                id=self._point_id(chunk.chunk_id),
                vector={"dense": chunk.dense, "sparse": chunk.sparse},
                payload={
                    "chunk_id": chunk.chunk_id,
                    "kb_id": chunk.kb_id,
                    "doc_id": chunk.doc_id,
                    "entities": chunk.entities,
                    "doc_name": chunk.doc_name,
                    "heading_path": chunk.heading_path,
                    "page": chunk.page,
                },
            )
            for chunk in chunks
        ]
        if not points:
            return 0
        await self._client.upsert(collection_name=self.chunks_collection, points=points)
        return len(points)

    async def hybrid_query(
        self,
        *,
        dense: list[float],
        sparse: SparseVector,
        kb_id: str,
        top_k: int = 5,
        per_path_limit: int = 20,
    ) -> list[ScoredPoint]:
        """Dense+sparse prefetch (per-path limit) fused with RRF, scoped to one KB."""
        kb_filter = Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))])
        response = await self._client.query_points(
            collection_name=self.chunks_collection,
            prefetch=[
                Prefetch(query=dense, using="dense", filter=kb_filter, limit=per_path_limit),
                Prefetch(query=sparse, using="sparse", filter=kb_filter, limit=per_path_limit),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
        return response.points

    async def get_chunk_vectors(self, chunk_ids: Sequence[str]) -> dict[str, list[float]]:
        """Retrieve dense chunk vectors by chunk ids (deterministic point ids).

        Powers the D1 evidence scoring: one batched retrieve, zero extra
        embedding calls. Missing points (deleted / not yet indexed) are
        skipped silently — their candidates simply score 0 downstream.
        """
        if not chunk_ids:
            return {}
        points = await self._client.retrieve(
            collection_name=self.chunks_collection,
            ids=[self._point_id(str(chunk_id)) for chunk_id in chunk_ids],
            with_vectors=True,
        )
        vectors: dict[str, list[float]] = {}
        for point in points:
            chunk_id = (point.payload or {}).get("chunk_id")
            vector = point.vector if isinstance(point.vector, dict) else {}
            dense = vector.get("dense")
            if chunk_id and dense:
                vectors[str(chunk_id)] = list(dense)
        return vectors

    async def delete_chunks(self, chunk_ids: Sequence[str]) -> None:
        """Drop the listed chunk points (Task 5 收尾 single-chunk delete).

        Payload-filter delete (chunk_id in list), mirroring ``delete_by_doc``.
        Idempotent: deleting an absent point is a no-op.
        """
        if not chunk_ids:
            return
        await self._client.delete(
            collection_name=self.chunks_collection,
            points_selector=FilterSelector(filter=Filter(must=[FieldCondition(key="chunk_id", match=MatchAny(any=list(chunk_ids)))])),
        )

    async def scroll_collection(
        self,
        collection_name: str,
        kb_id: str | None = None,
        *,
        with_vectors: bool = False,
        batch_size: int = 512,
    ) -> list[Record]:
        """Page through a collection: one KB's points, or all of them when *kb_id* is None.

        Default is ids + payload only; the unfiltered form is the sweep
        round's enumeration (spec 2026-10-05 D4).
        """
        kb_filter = None if kb_id is None else Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))])
        records: list[Record] = []
        offset = None
        while True:
            batch, offset = await self._client.scroll(
                collection_name=collection_name,
                scroll_filter=kb_filter,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=with_vectors,
            )
            records.extend(batch)
            if offset is None:
                return records

    async def delete_by_doc(self, doc_id: str) -> None:
        """Drop all chunk points of one document (re-upload / delete path)."""
        await self._client.delete(
            collection_name=self.chunks_collection,
            points_selector=FilterSelector(filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))])),
        )

    async def delete_by_kb(self, kb_id: str) -> None:
        """Wipe every point of a KB across all collections (spec §3.7)."""
        kb_filter = Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))])
        for name in self.collection_names:
            await self._client.delete(collection_name=name, points_selector=FilterSelector(filter=kb_filter))


def refreshed_store(held: Any) -> Any:
    """Return *held* unless the live config now declares a different (url, width).

    自检只对「真实例且 url 已知」生效：假体与 ``client=`` 注入的实例（url 未知）
    直通——生产恒经 ``get_vector_store()`` 带 url；url 未知时若自检会把每次取值都
    判成不符、死循环式重建（spec 2026-10-05 D1）。仅宽度差复用同一 client；url 差
    按新配置重建。
    """
    if not isinstance(held, KnowledgeVectorStore) or held.url is None:
        return held
    from deerflow.config.app_config import get_app_config

    rag = get_app_config().rag
    declared_url = rag.qdrant_url
    declared_width = effective_dimension(rag)
    if held.url == declared_url and held.dense_size == declared_width:
        return held
    if held.url == declared_url:
        refreshed = KnowledgeVectorStore(url=declared_url, client=held._client, collection_prefix=held.collection_prefix, dense_size=declared_width)
    else:
        refreshed = KnowledgeVectorStore(declared_url, collection_prefix=held.collection_prefix, dense_size=declared_width)
    logger.info("knowledge vector store refreshed: url %s→%s, width %s→%s", held.url, declared_url, held.dense_size, declared_width)
    return refreshed


def get_vector_store() -> KnowledgeVectorStore:
    """Build the store from ``rag`` — its address, and the width it writes at."""
    from deerflow.config.app_config import get_app_config

    rag = get_app_config().rag
    return KnowledgeVectorStore(rag.qdrant_url, dense_size=effective_dimension(rag))
