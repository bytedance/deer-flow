"""SQLite graph store + NetworkX in-memory loader (spec §3.4).

Persistence choice per the spec's storage table: business-DB two tables
(``graph_entities`` / ``graph_relations``) + NetworkX for in-memory compute —
no extra container. Same-name entities merge LightRAG-style inside one KB:
descriptions append (deduped per fragment) and ``source_chunk_ids`` union, so
re-indexing or incremental documents never trigger a full graph rebuild. Uniqueness scope
is ``(kb_id, name)`` / ``(kb_id, source, target, relation)`` — two KBs keep
independent graphs.

``merge_entities`` / ``rewrite_relation_endpoints`` (spec 2026-08-10 D3) are
the cross-slice alias merge primitives used by the incremental re-resolver.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.knowledge.graph.extractor import ExtractedEntity, ExtractedRelation
from deerflow.knowledge.models import GraphEntityRow, GraphRelationRow


def _entity_id(kb_id: str, name: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"deerflow:kb-entity:{kb_id}:{name}").hex


def _relation_id(kb_id: str, source: str, target: str, relation: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"deerflow:kb-relation:{kb_id}:{source}:{target}:{relation}").hex


def _merge_text(existing: str | None, extra: str) -> str:
    """Append-only fragment merge: ``extra`` fragments not already present are added."""
    parts = [part for part in (existing or "").split("\n") if part]
    for fragment in extra.split("\n"):
        if fragment and fragment not in parts:
            parts.append(fragment)
    return "\n".join(parts)


def _merge_chunk_ids(existing: list, chunk_id: str) -> list:
    ids = list(existing or [])
    if chunk_id not in ids:
        ids.append(chunk_id)
    return ids


class GraphStore:
    """CRUD + merge facade over the two graph tables."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def upsert_entities(self, kb_id: str, entities: Sequence[ExtractedEntity], *, chunk_id: str) -> None:
        if not entities:
            return
        async with self._sf() as session:
            for entity in entities:
                row = await session.get(GraphEntityRow, _entity_id(kb_id, entity.name))
                if row is None:
                    session.add(
                        GraphEntityRow(
                            id=_entity_id(kb_id, entity.name),
                            kb_id=kb_id,
                            name=entity.name,
                            type=entity.type,
                            description=entity.description,
                            source_chunk_ids=[chunk_id],
                            status="ready",
                        )
                    )
                else:
                    if entity.type and not row.type:
                        row.type = entity.type
                    row.description = _merge_text(row.description, entity.description)
                    row.source_chunk_ids = _merge_chunk_ids(row.source_chunk_ids, chunk_id)
            await session.commit()

    async def upsert_relations(self, kb_id: str, relations: Sequence[ExtractedRelation], *, chunk_id: str) -> None:
        if not relations:
            return
        async with self._sf() as session:
            for relation in relations:
                row = await session.get(GraphRelationRow, _relation_id(kb_id, relation.source, relation.target, relation.relation))
                if row is None:
                    session.add(
                        GraphRelationRow(
                            id=_relation_id(kb_id, relation.source, relation.target, relation.relation),
                            kb_id=kb_id,
                            source=relation.source,
                            target=relation.target,
                            relation=relation.relation,
                            description=relation.description,
                            source_chunk_ids=[chunk_id],
                        )
                    )
                else:
                    row.description = _merge_text(row.description, relation.description)
                    row.source_chunk_ids = _merge_chunk_ids(row.source_chunk_ids, chunk_id)
            await session.commit()

    async def list_entities(self, kb_id: str) -> list[dict[str, Any]]:
        stmt = select(GraphEntityRow).where(GraphEntityRow.kb_id == kb_id).order_by(GraphEntityRow.name)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [row.to_dict() for row in result.scalars().all()]

    async def list_relations(self, kb_id: str) -> list[dict[str, Any]]:
        stmt = select(GraphRelationRow).where(GraphRelationRow.kb_id == kb_id).order_by(GraphRelationRow.source, GraphRelationRow.target)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [row.to_dict() for row in result.scalars().all()]

    async def remove_chunk_contributions(self, kb_id: str, chunk_ids: Sequence[str]) -> tuple[list[str], list[str]]:
        """Remove a set of chunks' contributions from the graph (document delete/retry).

        For every entity/relation in this KB, the given chunk ids are removed
        from ``source_chunk_ids``. Entities left with zero sources are orphan
        nodes and deleted outright (their relations go with them); entities
        that still have other sources survive. Relations left with zero
        sources are deleted.

        Returns ``(orphaned_entity_names, affected_entity_names)`` — callers
        delete the orphans' vectors from ``kb_entities`` and mark the
        affected entities' wiki entries dirty (spec §3.7 级联删除).
        """
        if not chunk_ids:
            return [], []
        targets = set(chunk_ids)
        orphaned: list[str] = []
        affected: list[str] = []
        async with self._sf() as session:
            entity_rows = (await session.execute(select(GraphEntityRow).where(GraphEntityRow.kb_id == kb_id))).scalars().all()
            for row in entity_rows:
                remaining = [cid for cid in (row.source_chunk_ids or []) if cid not in targets]
                if len(remaining) == len(row.source_chunk_ids or []):
                    continue
                if not remaining:
                    orphaned.append(row.name)
                    await session.delete(row)
                else:
                    affected.append(row.name)
                    row.source_chunk_ids = remaining
            relation_rows = (await session.execute(select(GraphRelationRow).where(GraphRelationRow.kb_id == kb_id))).scalars().all()
            for row in relation_rows:
                if row.source in orphaned or row.target in orphaned:
                    await session.delete(row)
                    continue
                remaining = [cid for cid in (row.source_chunk_ids or []) if cid not in targets]
                if len(remaining) != len(row.source_chunk_ids or []) and not remaining:
                    await session.delete(row)
                elif len(remaining) != len(row.source_chunk_ids or []):
                    row.source_chunk_ids = remaining
            await session.commit()
        return orphaned, affected

    async def calculate_deletion_impact(self, kb_id: str, chunk_ids: Sequence[str]) -> dict[str, Any]:
        """Calculate deletion impact WITHOUT actually deleting (Phase-3 Batch-1 P5).

        Pure read-only computation: same logic as remove_chunk_contributions but
        returns impact analysis instead of modifying data.

        Returns:
            {
                "orphaned_entities": ["entity1", "entity2"],
                "affected_entities": ["entity3"],
                "relation_deletions": [{"source": "e1", "target": "e2", "relation": "关联"}]
            }
        """
        if not chunk_ids:
            return {"orphaned_entities": [], "affected_entities": [], "relation_deletions": []}

        targets = set(chunk_ids)
        orphaned: list[str] = []
        affected: list[str] = []
        relation_deletions: list[dict[str, str]] = []

        async with self._sf() as session:
            # Analyze entities
            entity_rows = (await session.execute(select(GraphEntityRow).where(GraphEntityRow.kb_id == kb_id))).scalars().all()
            for row in entity_rows:
                remaining = [cid for cid in (row.source_chunk_ids or []) if cid not in targets]
                if len(remaining) == len(row.source_chunk_ids or []):
                    continue  # No impact
                if not remaining:
                    orphaned.append(row.name)
                else:
                    affected.append(row.name)

            # Analyze relations
            relation_rows = (await session.execute(select(GraphRelationRow).where(GraphRelationRow.kb_id == kb_id))).scalars().all()
            for row in relation_rows:
                # Relation deleted if source or target is orphaned
                if row.source in orphaned or row.target in orphaned:
                    relation_deletions.append(
                        {
                            "source": row.source,
                            "target": row.target,
                            "relation": row.relation,
                        }
                    )
                    continue
                # Relation deleted if all sources removed
                remaining = [cid for cid in (row.source_chunk_ids or []) if cid not in targets]
                if len(remaining) != len(row.source_chunk_ids or []) and not remaining:
                    relation_deletions.append(
                        {
                            "source": row.source,
                            "target": row.target,
                            "relation": row.relation,
                        }
                    )

        return {
            "orphaned_entities": orphaned,
            "affected_entities": affected,
            "relation_deletions": relation_deletions,
        }

    async def merge_entities(self, kb_id: str, representative: str, aliases: Sequence[str]) -> dict[str, Any] | None:
        """Merge alias rows into the representative entity (spec 2026-08-10 D3).

        Description fragments append (deduped), ``source_chunk_ids`` union,
        type backfilled when empty; alias rows are deleted. Returns the merged
        representative row as a dict (``None`` when the representative does
        not exist). Idempotent — re-running with already-merged aliases is a
        no-op.
        """
        if not aliases:
            return None
        async with self._sf() as session:
            rep_row = await session.get(GraphEntityRow, _entity_id(kb_id, representative))
            if rep_row is None:
                return None
            for alias in aliases:
                alias_row = await session.get(GraphEntityRow, _entity_id(kb_id, alias))
                if alias_row is None:
                    continue
                rep_row.description = _merge_text(rep_row.description, alias_row.description or "")
                if alias_row.type and not rep_row.type:
                    rep_row.type = alias_row.type
                for chunk_id in alias_row.source_chunk_ids or []:
                    rep_row.source_chunk_ids = _merge_chunk_ids(rep_row.source_chunk_ids, chunk_id)
                await session.delete(alias_row)
            # Read attributes before commit: afterwards they expire and
            # touching them would trigger implicit IO (MissingGreenlet).
            merged = {
                "name": representative,
                "type": rep_row.type or "",
                "description": rep_row.description or "",
                "source_chunk_ids": list(rep_row.source_chunk_ids or []),
            }
            await session.commit()
            return merged

    async def rewrite_relation_endpoints(self, kb_id: str, name_map: Mapping[str, str]) -> None:
        """Rewrite relation endpoints through ``name_map`` (spec 2026-08-10 D3).

        Duplicates created by the rewrite merge via the usual upsert semantics
        (description append + chunk-id union); self-loops produced by the
        merge are dropped. Idempotent — endpoints already rewritten are left
        untouched.
        """
        if not name_map:
            return
        async with self._sf() as session:
            rows = (await session.execute(select(GraphRelationRow).where(GraphRelationRow.kb_id == kb_id))).scalars().all()
            for row in rows:
                new_source = name_map.get(row.source, row.source)
                new_target = name_map.get(row.target, row.target)
                if new_source == row.source and new_target == row.target:
                    continue
                relation, description = row.relation, row.description or ""
                chunk_ids = list(row.source_chunk_ids or [])
                if new_source == new_target:
                    await session.delete(row)
                    continue
                existing = await session.get(GraphRelationRow, _relation_id(kb_id, new_source, new_target, relation))
                if existing is not None and existing.id != row.id:
                    existing.description = _merge_text(existing.description, description)
                    for chunk_id in chunk_ids:
                        existing.source_chunk_ids = _merge_chunk_ids(existing.source_chunk_ids, chunk_id)
                    await session.delete(row)
                else:
                    await session.delete(row)
                    session.add(
                        GraphRelationRow(
                            id=_relation_id(kb_id, new_source, new_target, relation),
                            kb_id=kb_id,
                            source=new_source,
                            target=new_target,
                            relation=relation,
                            description=description,
                            source_chunk_ids=chunk_ids,
                        )
                    )
            await session.commit()

    async def load_networkx(self, kb_id: str) -> nx.DiGraph:
        """Load the KB graph into memory. Multiple relations between the same
        endpoint pair collapse into one edge whose attributes join them
        (``relation`` fragments joined by ``、``) — DiGraph keeps traversal
        simple for the 1–2 hop online expansion."""
        graph = nx.DiGraph()
        entities = await self.list_entities(kb_id)
        relations = await self.list_relations(kb_id)
        for row in entities:
            graph.add_node(
                row["name"],
                type=row.get("type") or "",
                description=row.get("description") or "",
                source_chunk_ids=list(row.get("source_chunk_ids") or []),
                status=row.get("status") or "ready",
            )
        for row in relations:
            source, target = row["source"], row["target"]
            if graph.has_edge(source, target):
                edge = graph[source][target]
                if row["relation"] not in edge["relation"]:
                    edge["relation"] = f"{edge['relation']}、{row['relation']}"
                edge["description"] = _merge_text(edge["description"], row.get("description") or "")
                edge["source_chunk_ids"] = sorted(set(edge["source_chunk_ids"]) | set(row.get("source_chunk_ids") or []))
            else:
                graph.add_edge(
                    source,
                    target,
                    relation=row["relation"],
                    description=row.get("description") or "",
                    source_chunk_ids=list(row.get("source_chunk_ids") or []),
                )
        return graph
