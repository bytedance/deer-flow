"""RAG tools for agent integration."""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool

from deerflow.config.rag_config import get_rag_config
from deerflow.config.tenant import _DEFAULT_TENANT_ID, get_current_tenant_id
from deerflow.knowledge_base.retrieval import resolve_runtime_kb_selection
from deerflow.runtime.user_context import DEFAULT_USER_ID, get_effective_user_id

logger = logging.getLogger(__name__)

_resolve_pool = ThreadPoolExecutor(max_workers=2)


@tool
def search_knowledge_base(
    query: str,
    collection: str = "default",
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Search the knowledge base for information relevant to the query.

    Use this tool to find documents, facts, or context that may have been
    previously ingested into the vector store. Returns the most relevant
    text chunks with their similarity scores and source metadata.

    Args:
        query: The search query string.
        collection: The knowledge base collection to search (default: "default").

    Returns:
        JSON string with search results including content, scores, and sources.
    """
    rag_config = get_rag_config()
    if not rag_config.enabled:
        return json.dumps({"error": "RAG subsystem is not enabled", "results": []})

    try:
        kb_selection = _extract_kb_selection(config)
        if kb_selection and collection == "default":
            return _search_selected_kbs(query, kb_selection, rag_config, config)
        return _search_single_collection(query, collection, rag_config, config)
    except Exception:
        logger.exception("search_knowledge_base failed")
        return json.dumps({"error": "Knowledge base search failed", "results": []})


def _extract_kb_selection(config: RunnableConfig | None) -> dict | None:
    """Extract knowledge_base_selection from runtime context in RunnableConfig."""
    resolved_selection, _ = _resolve_kb_selection(config)
    return resolved_selection


def _resolve_kb_selection(config: RunnableConfig | None) -> tuple[dict | None, str | None]:
    if not config:
        return None, None

    configurable = config.get("configurable") or {}
    runtime = configurable.get("__pregel_runtime")
    if runtime is None:
        return None, None

    def _run_async() -> tuple[dict | None, str | None]:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(resolve_runtime_kb_selection(runtime))
        finally:
            loop.close()

    return _resolve_pool.submit(_run_async).result(timeout=10)


def _extract_runtime_context(config: RunnableConfig | None) -> dict:
    configurable = (config or {}).get("configurable") or {}
    runtime = configurable.get("__pregel_runtime")
    return getattr(runtime, "context", None) or {}


def _search_selected_kbs(
    query: str, selection: dict, rag_config, config: RunnableConfig | None
) -> str:
    """Search across user's selected knowledge bases."""
    from deerflow.knowledge_base.retrieval import multi_kb_retrieve
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

    context = _extract_runtime_context(config)
    tenant_id = context.get("tenant_id") or get_current_tenant_id()
    user_id = context.get("user_id") or get_effective_user_id()

    if not tenant_id or tenant_id == _DEFAULT_TENANT_ID or not user_id:
        return json.dumps({"error": "Missing tenant or user context", "results": []})

    if user_id == DEFAULT_USER_ID and not rag_config.allow_no_auth_kb:
        return json.dumps({"error": "Knowledge base access requires authentication", "results": []})

    sf = get_session_factory()
    if sf is None:
        return json.dumps({"error": "Database not configured", "results": []})

    selected_ids = selection["selected_ids"][: rag_config.max_selected_kbs]
    repo = KnowledgeBaseRepository(sf)

    async def _resolve():
        return await repo.resolve_accessible_by_ids(
            selected_ids, tenant_id=tenant_id, user_id=user_id
        )

    def _run_async():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_resolve())
        finally:
            loop.close()

    knowledge_bases = _resolve_pool.submit(_run_async).result(timeout=10)

    if not knowledge_bases:
        return json.dumps({"query": query, "results": [], "note": "No active knowledge bases found"})

    results = multi_kb_retrieve(
        knowledge_bases=knowledge_bases,
        query=query,
        top_k=rag_config.retrieval_top_k,
    )

    formatted = [
        {
            "rank": i + 1,
            "content": r.content,
            "score": round(r.score, 4),
            "kb_name": r.metadata.get("kb_name", ""),
            "doc_title": r.metadata.get("title", ""),
            "source": r.metadata.get("source", "unknown"),
        }
        for i, r in enumerate(results)
    ]

    return json.dumps({"query": query, "results": formatted}, ensure_ascii=False)


def _search_single_collection(query: str, collection: str, rag_config, config: RunnableConfig | None) -> str:
    """Search a single named collection through owner-scoped KB resolution."""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

    context = _extract_runtime_context(config)
    tenant_id = context.get("tenant_id") or get_current_tenant_id()
    user_id = context.get("user_id") or get_effective_user_id()

    if not tenant_id or tenant_id == _DEFAULT_TENANT_ID or not user_id:
        return json.dumps({"error": "Missing tenant or user context", "results": []})

    if user_id == DEFAULT_USER_ID and not rag_config.allow_no_auth_kb:
        return json.dumps({"error": "Knowledge base access requires authentication", "results": []})

    sf = get_session_factory()
    if sf is None:
        return json.dumps({"error": "Database not configured", "results": []})

    repo = KnowledgeBaseRepository(sf)

    async def _resolve():
        return await repo.resolve_accessible_by_collections(
            [collection], tenant_id=tenant_id, user_id=user_id
        )

    def _run_async():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_resolve())
        finally:
            loop.close()

    knowledge_bases = _resolve_pool.submit(_run_async).result(timeout=10)
    if not knowledge_bases:
        return json.dumps({"error": "Knowledge base not available", "results": []})

    from deerflow.knowledge_base.retrieval import multi_kb_retrieve

    results = multi_kb_retrieve(
        knowledge_bases=knowledge_bases,
        query=query,
        top_k=rag_config.retrieval_top_k,
    )

    formatted = [
        {
            "rank": i + 1,
            "content": r.content,
            "score": round(r.score, 4),
            "kb_name": r.metadata.get("kb_name", ""),
            "doc_title": r.metadata.get("title", ""),
            "source": r.metadata.get("source", "unknown"),
        }
        for i, r in enumerate(results)
    ]

    return json.dumps({"query": query, "collection": collection, "results": formatted}, ensure_ascii=False)
