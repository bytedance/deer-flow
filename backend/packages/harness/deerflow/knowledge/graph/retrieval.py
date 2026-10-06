"""Graph evidence selection (spec 2026-08-10 D1, phase-2).

The graph structure only defines the candidate pool; semantics decides who
gets in and in what order. Pipeline:

1. ``collect_candidates`` — edge channel (both endpoints in the seen
   subgraph) + node channel (every seen entity's own ``source_chunk_ids``),
   deduped by ``chunk_id`` with all recalling sources merged. The removed
   channel-3 elastic back-query never enters here.
2. ``apply_source_caps`` — each entity/edge source keeps only its top-scored
   chunks, killing the "hot entity monopolizes the budget" failure at the
   source.
3. ``select_evidence`` — two phases: a per-hop0-entity guarantee paid out
   round-robin (coverage first, depth for the higher-scored entities), then a
   pure chunk-score competition for the remaining budget. Entity scores never
   rank chunks; they only order the guarantee payout.

Everything here is a pure function over in-memory structures — no Qdrant, no
database — so the whole policy is unit-testable without IO.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field

import networkx as nx

from deerflow.knowledge.graph.normalizer import cosine_similarity


@dataclass(slots=True)
class Candidate:
    """One candidate evidence chunk plus the sources that recalled it.

    ``hop`` is the minimum over sources: entity sources take the entity's
    hop, edge sources take the smaller endpoint hop (an edge between two
    matched entities is hop-0 evidence).
    """

    chunk_id: str
    entity_sources: set[str] = field(default_factory=set)
    edge_sources: set[tuple[str, str]] = field(default_factory=set)
    hop: int = 0


def collect_candidates(graph: nx.DiGraph, hop_by_node: Mapping[str, int]) -> dict[str, Candidate]:
    """Collect chunk candidates from the seen subgraph, deduped by chunk id."""

    candidates: dict[str, Candidate] = {}

    def _touch(chunk_id: str, hop: int) -> Candidate:
        candidate = candidates.get(chunk_id)
        if candidate is None:
            candidate = candidates[chunk_id] = Candidate(chunk_id=chunk_id, hop=hop)
        else:
            candidate.hop = min(candidate.hop, hop)
        return candidate

    for source, target, data in graph.edges(data=True):
        if source not in hop_by_node or target not in hop_by_node:
            continue
        edge_hop = min(hop_by_node[source], hop_by_node[target])
        for chunk_id in data.get("source_chunk_ids") or []:
            _touch(str(chunk_id), edge_hop).edge_sources.add((source, target))
    for node, hop in hop_by_node.items():
        for chunk_id in graph.nodes[node].get("source_chunk_ids") or []:
            _touch(str(chunk_id), hop).entity_sources.add(node)
    return candidates


def apply_source_caps(
    candidates: dict[str, Candidate],
    scores: Mapping[str, float],
    *,
    per_entity_cap: int,
    per_edge_cap: int,
) -> None:
    """Trim each source to its top-scored chunks, in place.

    A chunk recalled by several sources survives as long as one source keeps
    it; chunks dropped from every source leave the pool entirely.
    """

    def _trim(source_keys: Collection, source_attr: str, cap: int) -> None:
        for key in source_keys:
            members = [cid for cid, candidate in candidates.items() if key in getattr(candidate, source_attr)]
            members.sort(key=lambda cid: (-scores.get(cid, 0.0), cid))
            for cid in members[max(0, cap) :]:
                getattr(candidates[cid], source_attr).discard(key)

    _trim({name for c in candidates.values() for name in c.entity_sources}, "entity_sources", per_entity_cap)
    _trim({edge for c in candidates.values() for edge in c.edge_sources}, "edge_sources", per_edge_cap)
    for cid in [cid for cid, candidate in candidates.items() if not candidate.entity_sources and not candidate.edge_sources]:
        del candidates[cid]


def select_evidence(
    candidates: Mapping[str, Candidate],
    scores: Mapping[str, float],
    entity_scores: Mapping[str, float],
    hop0_names: Collection[str],
    *,
    guarantee: int,
    limit: int,
    hop_penalty: float = 0.0,
) -> list[str]:
    """Pick the evidence chunk ids, guarantee phase first, competition second.

    Phase 1 (guarantee): every hop-0 entity may contribute up to ``guarantee``
    of its own top-scored chunks, paid out **round-robin** — one slice per
    entity per round, entities ordered by ``(-entity_score, name)`` — so a
    crowded budget still leaves every directly-matched entity with at least
    one slice (never a waterfall that shaves the tail). Chunks already paid
    out by another entity are skipped (an overlap covers both). Edge chunks
    never enter this phase, even hop-0 edges.

    Phase 2 (competition): every remaining candidate competes on the pure
    chunk score (``hop_penalty`` is an experimental, default-0 A/B knob);
    ties break by ``(hop, chunk_id)`` for determinism only.
    """
    hop0 = sorted(hop0_names, key=lambda name: (-entity_scores.get(name, 0.0), name))
    queues: dict[str, list[str]] = {
        name: sorted(
            (cid for cid, candidate in candidates.items() if name in candidate.entity_sources),
            key=lambda cid: (-scores.get(cid, 0.0), cid),
        )
        for name in hop0
    }
    selected: list[str] = []
    chosen: set[str] = set()
    for _round in range(max(0, guarantee)):
        if len(selected) >= limit:
            break
        for name in hop0:
            if len(selected) >= limit:
                break
            queue = queues[name]
            while queue and queue[0] in chosen:
                queue.pop(0)
            if not queue:
                continue
            cid = queue.pop(0)
            chosen.add(cid)
            selected.append(cid)

    rest = [cid for cid in candidates if cid not in chosen]
    rest.sort(key=lambda cid: (-(scores.get(cid, 0.0) - hop_penalty * candidates[cid].hop), candidates[cid].hop, cid))
    selected.extend(rest[: max(0, limit - len(selected))])
    return selected


@dataclass(slots=True)
class ExpansionResult:
    """Outcome of a pruned graph expansion (D2).

    ``entity_scores``: hop-0 entities carry their landing score, neighbours
    the cosine that passed the semantic gate — the by-product D1 reuses for
    the guarantee payout order.
    """

    seen: set[str]
    hop_by_node: dict[str, int]
    entity_scores: dict[str, float]


def hub_may_expand(
    *,
    degree: int,
    hop: int,
    entity_score: float,
    hub_degree_threshold: int,
    neighbor_min_score: float,
) -> bool:
    """Hub guard (D2): high-degree nodes may only spread when relevant.

    Degree never decides whether an entity stays — only whether its fan-out
    is allowed to pull in more neighbours. hop-0 (directly matched) entities
    are exempt: the landing threshold is deliberately lower than the neighbor
    gate, and the user's own entity must never be blocked by its own fan-out.
    Under the default pipeline the blocking branch is structurally
    unreachable for hop≥1 nodes (they already passed the gate to enter
    ``seen``); the predicate remains as a configuration safety margin.
    """
    if degree <= hub_degree_threshold:
        return True
    if hop == 0:
        return True
    return entity_score >= neighbor_min_score


async def expand_neighborhood(
    graph: nx.DiGraph,
    seed_scores: Mapping[str, float],
    *,
    hops: int,
    query_vector: Sequence[float],
    fetch_vectors: Callable[[list[str]], Awaitable[Mapping[str, list[float]]]],
    neighbor_min_score: float = 0.4,
    max_expanded_nodes: int = 25,
    hub_degree_threshold: int = 50,
) -> ExpansionResult:
    """1–2 hop expansion with semantic pruning, a node budget and a hub guard.

    Per hop: the hub guard filters the frontier first, then all candidate
    neighbours' vectors are fetched in one batch and only those whose cosine
    against the query reaches ``neighbor_min_score`` enter ``seen`` (missing
    vectors score 0 and are pruned). Zero extra embedding calls — neighbour
    vectors already live in ``kb_entities``. After the last hop, a pure cost
    budget trims ``seen`` to ``max_expanded_nodes``, always keeping hop-0
    entities and preferring higher-scored neighbours. ``hops`` semantics are
    unchanged; an empty ``seen`` is the caller's honest-answer path.
    """
    seen = {name for name in seed_scores if graph.has_node(name)}
    hop_by_node = {name: 0 for name in seen}
    entity_scores = {name: float(seed_scores[name]) for name in seen}
    frontier = set(seen)
    for hop in range(1, max(0, hops) + 1):
        neighbor_names: set[str] = set()
        for node in frontier:
            if not hub_may_expand(
                degree=int(graph.degree(node) or 0),
                hop=hop_by_node[node],
                entity_score=entity_scores.get(node, 0.0),
                hub_degree_threshold=hub_degree_threshold,
                neighbor_min_score=neighbor_min_score,
            ):
                continue
            neighbor_names |= set(graph.successors(node)) | set(graph.predecessors(node))
        neighbor_names -= seen
        if not neighbor_names:
            break
        vectors = await fetch_vectors(sorted(neighbor_names))
        frontier = set()
        for name in sorted(neighbor_names):
            vector = vectors.get(name)
            score = cosine_similarity(list(query_vector), list(vector)) if vector is not None else 0.0
            if score < neighbor_min_score:
                continue
            seen.add(name)
            hop_by_node[name] = hop
            entity_scores[name] = score
            frontier.add(name)
    if len(seen) > max_expanded_nodes:
        hop0 = {name for name, hop in hop_by_node.items() if hop == 0}
        others = sorted(seen - hop0, key=lambda name: (-entity_scores.get(name, 0.0), name))
        keep = hop0 | set(others[: max(0, max_expanded_nodes - len(hop0))])
        seen = keep
        hop_by_node = {name: hop for name, hop in hop_by_node.items() if name in keep}
        entity_scores = {name: score for name, score in entity_scores.items() if name in keep}
    return ExpansionResult(seen=seen, hop_by_node=hop_by_node, entity_scores=entity_scores)
