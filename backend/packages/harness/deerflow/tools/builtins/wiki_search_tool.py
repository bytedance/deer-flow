"""wiki_search — the wiki path (spec §4.3 + Phase-3 P6 §8).

query → embedding → ``kb_wiki_entries`` + ``kb_manual_cards`` dense top-k →
full entry/card fetched from the business DB by ``entry_id``/``card_id``.
Zero online generation cost: entries are pre-written offline (Task 6), a hit
returns the whole entry.

Phase-3 P6 (spec §8 可选混合): manual cards with ``include_in_wiki_search``
on hold a point in ``kb_manual_cards`` and compete with AI entries for the
SAME top_k pool — candidates merge, sort by score desc (stable: wiki wins
ties), truncate at top_k; every hit carries ``source_type`` so the frontend
citation strip can badge 「百科」/「我的卡片」.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from langchain.tools import tool

from deerflow.knowledge.access import ACCESS_DENIED_MESSAGE, NO_KB_GUIDANCE, can_access, resolve_kb_scope
from deerflow.knowledge.citation_counter import claim_citation_range
from deerflow.knowledge.embedder_factory import build_embedder
from deerflow.knowledge.store import KnowledgeStore, get_knowledge_store
from deerflow.knowledge.vector_store import KnowledgeVectorStore, get_vector_store
from deerflow.knowledge.wiki.store import WikiStore
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)


async def _wiki_search_impl(
    query: str,
    runtime: Any,
    *,
    store: KnowledgeStore | None = None,
    wiki_store: WikiStore | None = None,
    vector_store: KnowledgeVectorStore | None = None,
    embedder: Any = None,
    top_k: int = 3,
) -> dict:
    """Core implementation — testable without the @tool wrapper."""
    kb_id, user_id = resolve_kb_scope(runtime)
    if not kb_id:
        return {"entries": [], "message": NO_KB_GUIDANCE}
    store = store or get_knowledge_store()
    if not await can_access(store, user_id, kb_id):
        return {"entries": [], "message": ACCESS_DENIED_MESSAGE}
    wiki_store = wiki_store or WikiStore(store._sf)
    vector_store = vector_store or get_vector_store()
    embedder = embedder or build_embedder()

    (query_vector,) = await embedder.embed([query], text_type="query")
    wiki_points = await vector_store.query_wiki_entries(dense=query_vector.dense, kb_id=kb_id, top_k=top_k)
    manual_points = await vector_store.query_manual_cards(dense=query_vector.dense, kb_id=kb_id, top_k=top_k)
    # Shared top_k pool (spec §8): merge both candidate lists, sort by score
    # desc (Python's sort is stable — wiki wins score ties), then hydrate in
    # that order and keep the first top_k VALID hits. Stale manual points
    # (toggle-off / card deleted after a swallowed vector-delete failure) are
    # skipped at hydration so they never waste a pool slot.
    candidates = [("wiki", point) for point in wiki_points] + [("manual", point) for point in manual_points]
    candidates.sort(key=lambda item: item[1].score, reverse=True)
    entries = []
    for kind, point in candidates:
        if len(entries) >= top_k:
            break
        if kind == "wiki":
            entry = await wiki_store.get_entry(point.payload["entry_id"])
            if entry is None:
                continue
            entries.append(
                {
                    "entry_id": entry["id"],
                    "title": entry["title"],
                    "content": entry["content"],
                    "score": point.score,
                    "updated_at": entry.get("updated_at"),
                    "source_type": "wiki",
                }
            )
        else:
            card = await store.get_manual_card(point.payload["card_id"])
            if card is None or not card.get("include_in_wiki_search"):
                continue
            entries.append(
                {
                    "entry_id": card["id"],
                    "title": card["title"],
                    "content": card["content"],
                    "score": point.score,
                    "updated_at": card.get("updated_at"),
                    "source_type": "manual",
                }
            )
    if not entries:
        return {"entries": [], "message": "百科条目与人工知识卡片中均未找到相关内容（该知识库可能尚未生成百科条目）。"}
    # Shared per-run citation counter — see hybrid_search_tool. The span is
    # also stated in the message text (prose >> JSON fields for attention).
    start = claim_citation_range(runtime, len(entries))
    for i, item in enumerate(entries):
        item["citation_no"] = start + i + 1
    span = f"[{start + 1}]" if len(entries) == 1 else f"[{start + 1}]-[{start + len(entries)}]"
    wiki_count = sum(1 for item in entries if item["source_type"] == "wiki")
    manual_count = len(entries) - wiki_count
    parts = []
    if wiki_count:
        parts.append(f"{wiki_count} 篇百科条目")
    if manual_count:
        parts.append(f"{manual_count} 张人工知识卡片")
    return {"entries": entries, "message": f"命中 {'、'.join(parts)}（引用编号 {span}，标注时照抄 citation_no）。"}


@tool(parse_docstring=True)
async def wiki_search(
    runtime: Runtime,
    query: Annotated[str, "The concept/topic question, phrased in the user's language."],
    top_k: Annotated[int, "Number of wiki entries to return (default 3)."] = 3,
) -> dict:
    """Search the generated wiki entries (LLM-written encyclopedia pages) of the bound knowledge base.

    Use this tool when:
    - The question asks for a conceptual overview, definition, or deep dive on an important entity/topic
    - You want a digested long-form answer rather than raw evidence chunks

    Skip this tool when:
    - The question needs precise wording or citation-grade facts — use hybrid_search
    - The question is about relationships between entities — use graph_search

    Entries cover only the head entities (~top 20%); a miss here does not mean the knowledge base lacks the topic — fall back to hybrid_search.

    Args:
        runtime: Tool runtime carrying the bound ``kb_id`` in its context.
        query: The concept/topic question, phrased in the user's language.
        top_k: Number of wiki entries to return (default 3).
    """
    return await _wiki_search_impl(query, runtime, top_k=top_k)
