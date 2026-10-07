"""Vector indexing stage: chunk rows → embeddings → Qdrant (spec §3.3).

The chunk→vector leg of the indexing pipeline. Chunks are embedded in batches
(``embedder.batch_size``); a batch whose embed call ultimately fails marks its
chunks ``extract_status=failed`` (with the error persisted for resume) and the
run continues with the next batch — one bad batch never aborts the document.
Successful vectors are upserted with the spec §3.3 payload (``chunk_id``
pointer + filter fields + display metadata, never the text), and the document
row's ``chunk_count`` is updated to the number actually indexed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from deerflow_knowledge.embedder import EmbedderError, EmbeddingResult
from deerflow_knowledge.store import KnowledgeStore
from deerflow_knowledge.vector_store import ChunkUpsert, KnowledgeVectorStore

logger = logging.getLogger(__name__)


class _Embedder(Protocol):
    """Structural type for the embedder dependency (real or stub)."""

    batch_size: int

    async def embed(self, texts: Sequence[str], *, text_type: str = "document") -> list[EmbeddingResult]: ...


@dataclass(slots=True)
class IndexStats:
    """Outcome of one document's vector indexing run."""

    total: int
    indexed: int
    failed_chunk_ids: list[str] = field(default_factory=list)


async def index_chunks(
    store: KnowledgeStore,
    vector_store: KnowledgeVectorStore | None,
    embedder: _Embedder,
    *,
    kb_id: str,
    doc_id: str,
    chunks: Sequence[dict[str, Any]],
) -> IndexStats:
    """Embed chunk texts and upsert their vectors, batch by batch.

    ``chunks`` are business-DB rows (dicts) carrying ``chunk_id`` / ``text`` /
    ``heading_path`` / ``page`` / ``entities``. The document row supplies the
    ``doc_name`` display metadata and receives the final ``chunk_count``.
    """
    document = await store.get_document(doc_id)
    if document is None:
        raise ValueError(f"document {doc_id} not found")
    if not chunks:
        await store.update_document_status(doc_id, document["status"], chunk_count=0)
        return IndexStats(total=0, indexed=0)

    stats = IndexStats(total=len(chunks), indexed=0)
    batch_size = max(1, embedder.batch_size)
    for start in range(0, len(chunks), batch_size):
        batch = list(chunks[start : start + batch_size])
        try:
            embeddings = await embedder.embed([chunk["text"] for chunk in batch])
        except EmbedderError as exc:
            logger.warning("embed batch failed for doc %s (chunks %s..%s): %s", doc_id, start, start + len(batch) - 1, exc)
            for chunk in batch:
                await store.update_chunk_extract(chunk["chunk_id"], "failed", error=f"embed: {exc}")
                stats.failed_chunk_ids.append(chunk["chunk_id"])
            continue
        if vector_store is not None:
            await vector_store.upsert_chunks(
                [
                    ChunkUpsert(
                        chunk_id=chunk["chunk_id"],
                        kb_id=kb_id,
                        doc_id=doc_id,
                        dense=embedding.dense,
                        sparse=embedding.sparse,
                        doc_name=document["name"],
                        heading_path=list(chunk.get("heading_path") or []),
                        page=chunk.get("page"),
                        entities=list(chunk.get("entities") or []),
                    )
                    for chunk, embedding in zip(batch, embeddings, strict=True)
                ]
            )
        stats.indexed += len(batch)

    await store.update_document_status(doc_id, document["status"], chunk_count=stats.indexed)
    return stats
