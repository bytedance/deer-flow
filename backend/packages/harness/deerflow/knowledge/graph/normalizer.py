"""Entity normalization (spec §3.4).

Two merge mechanisms, applied in order:

1. **Surface alias table** — names are keyed by ``casefold`` + whitespace
   removal, with a naive English plural (trailing ``s``) fold for pure-ASCII
   names and a parenthetical fold (Task 10): a trailing wrapped ``A（B）`` /
   ``A(B)`` name registers the full name plus the ``A`` and ``B`` keys, so a
   cross-language canonical name 「中文（英文）」 meets either half in the
   table. Cluster display name: the parenthetical full name wins when the
   cluster has one, otherwise the first-seen name; alias descriptions are
   appended so no extraction content is lost.
2. **Embedding-similarity merge** — when the caller supplies ``name_vectors``
   (name → dense vector, e.g. from the DashScope embedder), representative
   names whose cosine similarity meets the threshold union-merge into the
   first-seen name.

Relation endpoints are rewritten through the same mapping; self-loops created
by a merge are dropped. The normalized names are what get backfilled into
chunk ``entities`` fields and used as graph node names.

``normalize_extraction`` works on one chunk's extraction result (per-slice);
``cluster_alias_groups`` (spec 2026-08-10 D3) reuses the same two mechanisms
over plain stored-name lists for the cross-slice re-resolution.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence

from deerflow.knowledge.graph.extractor import ExtractedEntity, ExtractedRelation, ExtractionResult

_WS_RE = re.compile(r"\s+")


def _alias_key(name: str) -> str:
    key = _WS_RE.sub("", name).casefold()
    # Naive English plural fold: "models" → "model" (ASCII names only, so
    # Chinese names are never touched).
    if len(key) > 3 and key.isascii() and key.endswith("s") and not key.endswith("ss"):
        key = key[:-1]
    return key


#: Trailing wrapped parenthetical: ``A（B）`` / ``A(B)`` (no nested parens).
_PAREN_RE = re.compile(r"^(?P<outer>[^()（）]+?)[（(](?P<inner>[^()（）]+)[)）]$")


def _parenthetical_parts(name: str) -> tuple[str, str] | None:
    """Split a trailing wrapped-parenthetical name into (outer, inner) parts.

    Anything else — no parens, non-trailing parens (``C++（进阶）指南``), an
    empty inner — returns ``None``.
    """
    match = _PAREN_RE.match(name)
    if not match:
        return None
    return match.group("outer").strip(), match.group("inner").strip()


def _alias_keys(name: str) -> list[str]:
    """All surface alias keys for a name (Task 10 parenthetical fold).

    A trailing wrapped parenthetical ``A（B）`` registers up to three keys —
    the full name, the outer ``A`` and the inner ``B`` — so a cross-language
    canonical name meets either half in the alias table. Degenerate forms
    keep only the full key: empty inner (the regex rejects it), inner folding
    to the same key as the outer (``String（string）``), or an empty outer
    (``（String）``). A single-character inner is not registered (too fuzzy).
    """
    full = _alias_key(name)
    parts = _parenthetical_parts(name)
    if not parts:
        return [full]
    outer_key = _alias_key(parts[0])
    inner_key = _alias_key(parts[1])
    if not outer_key or not inner_key or inner_key == outer_key:
        return [full]
    keys = [full, outer_key]
    if len(inner_key) > 1:
        keys.append(inner_key)
    return keys


def _is_parenthetical_full_name(name: str) -> bool:
    parts = _parenthetical_parts(name)
    return bool(parts and parts[0] and parts[1])


def _choose_representative_name(names: list[str]) -> str:
    """Display name for a merged cluster: the first parenthetical full name in
    input order wins (Task 10); clusters without one keep the historical
    convention (first name in input order) unchanged."""
    for name in names:
        if _is_parenthetical_full_name(name):
            return name
    return names[0]


#: Quote pairs for the hygiene gate's "quoted literal" rule.
_QUOTE_OPEN_CLOSE = {'"': '"', "'": "'", "`": "`", "「": "」", "『": "』", "“": "”", "‘": "’"}


def is_low_quality_entity_name(name: str) -> bool:
    """Hygiene gate for wiki eligibility (spec §3.5 Task 8): pure
    symbols/operators, quoted literals, single chars, and overlong fragments
    never deserve a wiki entry. Deliberately NOT applied at graph ingestion
    (Task 10 收缩): a filtered-out node would also vanish from graph-path
    retrieval, while a kept one is harmless (the landing/expansion gates
    filter noise at query time)."""
    stripped = name.strip()
    if len(stripped) <= 1 or len(stripped) > 30:
        return True
    if not any(ch.isalnum() for ch in stripped):
        return True
    return len(stripped) >= 2 and stripped[0] in _QUOTE_OPEN_CLOSE and stripped[-1] == _QUOTE_OPEN_CLOSE[stripped[0]]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two dense vectors (0.0 for zero norms).

    Shared by the offline normalizer, the online evidence scorer (D1) and the
    entity re-resolver (D3) — one metric, one implementation.
    """
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _merge_descriptions(existing: str, extra: str) -> str:
    parts = [part for part in existing.split("\n") if part]
    for part in extra.split("\n"):
        if part and part not in parts:
            parts.append(part)
    return "\n".join(parts)


def normalize_extraction(
    result: ExtractionResult,
    *,
    name_vectors: dict[str, list[float]] | None = None,
    similarity_threshold: float = 0.92,
) -> ExtractionResult:
    """Return a new ExtractionResult with alias/similar names merged."""
    # Union-find over entity indices.
    parent = list(range(len(result.entities)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i == root_j:
            return
        # Keep the lower index (first-seen) as the representative.
        parent[max(root_i, root_j)] = min(root_i, root_j)

    # Pass 1: surface alias table (multi-key: parenthetical names register
    # their outer/inner halves too).
    by_key: dict[str, int] = {}
    for i, entity in enumerate(result.entities):
        for key in _alias_keys(entity.name):
            if key in by_key:
                union(i, by_key[key])
            else:
                by_key[key] = i

    # Pass 2: embedding-similarity merge over representatives.
    if name_vectors:
        reps = sorted({find(i) for i in range(len(result.entities))})
        for pos, i in enumerate(reps):
            vec_i = name_vectors.get(result.entities[i].name)
            if vec_i is None:
                continue
            for j in reps[pos + 1 :]:
                vec_j = name_vectors.get(result.entities[j].name)
                if vec_j is None or len(vec_i) != len(vec_j):
                    continue
                if cosine_similarity(vec_i, vec_j) >= similarity_threshold:
                    union(i, j)

    # Rebuild entities: one display name per cluster — the parenthetical full
    # name when present, else the first-seen name — absorbing the alias
    # descriptions in first-seen order.
    clusters: dict[int, list[int]] = {}
    for i in range(len(result.entities)):
        clusters.setdefault(find(i), []).append(i)
    merged_entities: dict[int, ExtractedEntity] = {}
    for root, indices in clusters.items():
        entity = ExtractedEntity(
            name=_choose_representative_name([result.entities[index].name for index in indices]),
            type=result.entities[root].type,
            description=result.entities[root].description,
        )
        for index in indices:
            if index != root:
                entity.description = _merge_descriptions(entity.description, result.entities[index].description)
        merged_entities[root] = entity
    entities = [merged_entities[root] for root in sorted(merged_entities)]

    # Rewrite relation endpoints through the mapping; drop merge-created loops.
    name_of = {i: merged_entities[find(i)].name for i in range(len(result.entities))} if merged_entities else {}
    index_of = {id(entity): i for i, entity in enumerate(result.entities)}
    relations: list[ExtractedRelation] = []
    seen: set[tuple[str, str, str]] = set()
    for relation in result.relations:
        source = _map_name(relation.source, result.entities, name_of, index_of)
        target = _map_name(relation.target, result.entities, name_of, index_of)
        if source == target:
            continue
        triple = (source, target, relation.relation)
        if triple in seen:
            continue
        seen.add(triple)
        relations.append(ExtractedRelation(source=source, target=target, relation=relation.relation, description=relation.description))
    return ExtractionResult(entities=entities, relations=relations)


def _map_name(name: str, entities: list[ExtractedEntity], name_of: dict[int, str], index_of: dict[int, int]) -> str:
    """Map a (possibly alias) endpoint name to its representative display name."""
    for entity in entities:
        if entity.name == name:
            return name_of.get(index_of[id(entity)], name)
    # Endpoint not extracted as an entity (dangling): alias-fold it when any
    # of its keys meets a known entity's keys, else pass through unchanged.
    keys = set(_alias_keys(name))
    for i, entity in enumerate(entities):
        if keys & set(_alias_keys(entity.name)):
            return name_of.get(i, entity.name)
    return name


def cluster_alias_groups(
    names: Sequence[str],
    name_vectors: Mapping[str, list[float]] | None,
    similarity_threshold: float,
) -> dict[str, list[str]]:
    """Cluster stored entity names into alias groups (spec 2026-08-10 D3).

    Same two mechanisms as ``normalize_extraction`` — surface alias fold,
    then embedding-similarity union over representatives — but over a plain
    name list. The representative is the parenthetical full name when the
    cluster has one (Task 10), else the first name in input order
    (``list_entities`` sorts by name, so the choice is deterministic).
    Returns only non-trivial groups: ``{representative: [alias, ...]}``.
    """
    parent = list(range(len(names)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i == root_j:
            return
        parent[max(root_i, root_j)] = min(root_i, root_j)

    by_key: dict[str, int] = {}
    for i, name in enumerate(names):
        for key in _alias_keys(name):
            if key in by_key:
                union(i, by_key[key])
            else:
                by_key[key] = i

    if name_vectors:
        reps = sorted({find(i) for i in range(len(names))})
        for pos, i in enumerate(reps):
            vec_i = name_vectors.get(names[i])
            if vec_i is None:
                continue
            for j in reps[pos + 1 :]:
                vec_j = name_vectors.get(names[j])
                if vec_j is None or len(vec_i) != len(vec_j):
                    continue
                if cosine_similarity(vec_i, vec_j) >= similarity_threshold:
                    union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(len(names)):
        clusters.setdefault(find(i), []).append(i)
    groups: dict[str, list[str]] = {}
    for members in clusters.values():
        if len(members) < 2:
            continue
        representative = _choose_representative_name([names[index] for index in members])
        groups[representative] = [names[index] for index in members if names[index] != representative]
    return groups
