"""Incremental global entity re-resolution (spec 2026-08-10 D3).

Per-slice normalization only merges aliases inside one chunk's extraction —
the same real-world entity written differently across slices (``Model`` /
``Models``) survives as two graph nodes. After a document's graph leg, the
worker runs this resolver over the touched entities (+ their 1-hop
neighbours; the whole table below ``full_scan_threshold``) and merges the
alias groups found by ``cluster_alias_groups`` (surface fold + embedding
cosine ≥ threshold, the same two mechanisms as the per-slice normalizer).

Side-effect chain per group, all idempotent (Qdrant has no transactions —
idempotency is the recovery story):

1. ``graph_entities``: representative absorbs descriptions (fragment-deduped)
   and ``source_chunk_ids``; alias rows deleted.
2. ``graph_relations``: endpoints rewritten to the representative, duplicate
   triples merged, merge-created self-loops dropped.
3. ``kb_entities``: alias vectors deleted; the representative is re-embedded
   from its merged description.
4. Chunk entity tags dual-written: business-DB ``chunks.entities`` column and
   the ``kb_chunks`` payload — the two mirrors must move together.
5. Wiki lifecycle (spec §3.5 条目生命周期): entries titled by a merged-away
   alias are deleted outright — business row + ``kb_wiki_entries`` vector
   point — since the entity is gone and the title has nothing left to
   regenerate from; the representative's entry is marked ``dirty`` and the
   existing incremental refresh chain regenerates it from the merged
   material.

Failure handling lives in the worker: a failing resolution never blocks the
pipeline — the document still reaches ``ready`` and gains a visible
``entity-resolution failed`` error sub-marker.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from typing import Protocol

from deerflow.knowledge.embed_texts import entity_embed_text
from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.graph.normalizer import cluster_alias_groups
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.vector_store import EntityUpsert, KnowledgeVectorStore
from deerflow.knowledge.wiki.store import WikiStore

logger = logging.getLogger(__name__)


class _Embedder(Protocol):
    batch_size: int

    async def embed(self, texts, *, text_type: str = "document") -> list[EmbeddingResult]: ...


@dataclass(slots=True)
class ResolutionStats:
    """Outcome of one re-resolution run."""

    scanned: int = 0
    merged_groups: int = 0
    merged_entities: int = 0


async def resolve_entity_aliases(
    store: KnowledgeStore,
    graph_store: GraphStore,
    vector_store: KnowledgeVectorStore,
    wiki_store: WikiStore,
    embedder: _Embedder | None,
    *,
    kb_id: str,
    touched_entities: Collection[str],
    full_scan_threshold: int = 500,
    similarity_threshold: float = 0.92,
) -> ResolutionStats:
    """Merge cross-slice alias entities inside one KB.

    Scope: the whole entity table when the graph is smaller than
    ``full_scan_threshold``; otherwise the touched entities plus their 1-hop
    neighbours (an empty touched set then short-circuits to zero work).
    """
    stats = ResolutionStats()
    rows = await graph_store.list_entities(kb_id)
    if not rows:
        return stats
    if len(rows) < full_scan_threshold:
        scope_rows = rows
    else:
        in_graph = {row["name"] for row in rows}
        scope = {name for name in touched_entities if name in in_graph}
        if not scope:
            return stats
        relations = await graph_store.list_relations(kb_id)
        for relation in relations:
            if relation["source"] in scope or relation["target"] in scope:
                scope.add(relation["source"])
                scope.add(relation["target"])
        scope_rows = [row for row in rows if row["name"] in scope]
    stats.scanned = len(scope_rows)

    names = [row["name"] for row in scope_rows]  # list_entities sorts by name
    name_vectors = await vector_store.get_entity_vectors(kb_id, names)
    groups = cluster_alias_groups(names, name_vectors, similarity_threshold)
    for representative, aliases in groups.items():
        name_map = {alias: representative for alias in aliases}
        # ① graph_entities merge.
        merged = await graph_store.merge_entities(kb_id, representative, aliases)
        # ② graph_relations endpoint rewrite (duplicate triples merge,
        #    self-loops drop).
        await graph_store.rewrite_relation_endpoints(kb_id, name_map)
        # ③ kb_entities: drop alias vectors, re-embed the representative.
        await vector_store.delete_entities(kb_id, aliases)
        if merged is not None and embedder is not None:
            (embedding,) = await embedder.embed([entity_embed_text(representative, merged["description"])])
            await vector_store.upsert_entities([EntityUpsert(name=representative, kb_id=kb_id, type=merged["type"], description=merged["description"], dense=embedding.dense)])
        # ④ Chunk entity tags: business-DB column first, then the payload
        #    mirror read back from the rewritten rows.
        affected_chunks = list(merged["source_chunk_ids"]) if merged is not None else []
        if affected_chunks:
            await store.rewrite_chunk_entities(affected_chunks, name_map)
            chunk_rows = await store.get_chunks_by_ids(affected_chunks)
            await vector_store.set_chunk_entities({row["chunk_id"]: list(row.get("entities") or []) for row in chunk_rows})
        # ⑤ Wiki lifecycle: alias entries are deleted outright (the entity is
        #    gone, so the title has nothing to regenerate from); the
        #    representative's entry turns dirty for incremental regeneration
        #    from the merged material.
        await vector_store.delete_wiki_entries(kb_id, aliases)
        await wiki_store.delete_entries(kb_id, aliases)
        await wiki_store.mark_dirty_for_titles(kb_id, {representative})
        stats.merged_groups += 1
        stats.merged_entities += len(aliases)
        logger.info("entity re-resolution merged %s into %s (kb %s)", aliases, representative, kb_id)
    return stats
