"""RAG tools for agent integration."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool

from deerflow.config.rag_config import get_rag_config
from deerflow.config.tenant import _DEFAULT_TENANT_ID, get_current_tenant_id
from deerflow.knowledge_base.retrieval import resolve_runtime_kb_selection
from deerflow.knowledge_base.telemetry import get_kb_telemetry
from deerflow.rag.decisions import RagDecisionEvent
from deerflow.rag.errors import KbResolutionError, RagError, VectorStoreError
from deerflow.runtime.user_context import DEFAULT_USER_ID, get_effective_user_id

logger = logging.getLogger(__name__)


def _emit(payload: dict, decision: RagDecisionEvent) -> str:
    """Attach the decision dict to the tool payload and JSON-encode."""
    return json.dumps({**payload, "decision": decision.to_dict()}, ensure_ascii=False)


@tool
async def search_knowledge_base(
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
        get_kb_telemetry().record_event("retrieval.blocked", {
            "source": "tool",
            "reason": "rag.enabled=false",
            "query": query[:200],
        })
        return _emit(
            {"error": "RAG subsystem is not enabled", "results": []},
            RagDecisionEvent(
                outcome="disabled",
                reason="rag.enabled=false",
                source="tool",
                query=query[:200],
            ),
        )

    try:
        kb_selection = await _extract_kb_selection(config)
        if kb_selection and collection == "default":
            result = await _search_selected_kbs(query, kb_selection, rag_config, config)
            get_kb_telemetry().record_event("retrieval.completed", {
                "source": "tool",
                "query": query[:200],
                "kb_count": len(kb_selection.get("selected_ids", [])),
            })
            return result
        result = await _search_single_collection(query, collection, rag_config, config)
        get_kb_telemetry().record_event("retrieval.completed", {
            "source": "tool",
            "query": query[:200],
            "collection": collection,
        })
        return result
    except KbResolutionError as exc:
        logger.warning("search_knowledge_base: KB resolution failed: %s", exc)
        get_kb_telemetry().record_event("retrieval.blocked", {
            "source": "tool",
            "reason": f"KbResolutionError: {exc!s}"[:200],
            "query": query[:200],
        })
        return _emit(
            {"error": "Knowledge base resolution failed", "results": []},
            RagDecisionEvent(
                outcome="blocked",
                reason=f"KbResolutionError: {exc!s}"[:200],
                source="tool",
                query=query[:200],
            ),
        )
    except VectorStoreError as exc:
        logger.warning("search_knowledge_base: vector store rejected: %s", exc)
        get_kb_telemetry().record_event("retrieval.failed", {
            "source": "tool",
            "error_category": "VectorStoreError",
            "reason": f"VectorStoreError: {exc!s}"[:200],
            "query": query[:200],
        })
        return _emit(
            {"error": "Vector store unavailable", "results": []},
            RagDecisionEvent(
                outcome="failed",
                reason=f"VectorStoreError: {exc!s}"[:200],
                source="tool",
                query=query[:200],
            ),
        )
    except RagError as exc:
        logger.warning("search_knowledge_base: RAG error: %s", exc)
        get_kb_telemetry().record_event("retrieval.failed", {
            "source": "tool",
            "error_category": type(exc).__name__,
            "reason": f"{type(exc).__name__}: {exc!s}"[:200],
            "query": query[:200],
        })
        return _emit(
            {"error": "Knowledge base search failed", "results": []},
            RagDecisionEvent(
                outcome="failed",
                reason=f"{type(exc).__name__}: {exc!s}"[:200],
                source="tool",
                query=query[:200],
            ),
        )
    except Exception as exc:
        logger.exception("search_knowledge_base failed")
        get_kb_telemetry().record_event("retrieval.failed", {
            "source": "tool",
            "error_category": type(exc).__name__,
            "reason": f"{type(exc).__name__}: {exc!s}"[:200],
            "query": query[:200],
        })
        return _emit(
            {"error": "Knowledge base search failed", "results": []},
            RagDecisionEvent(
                outcome="failed",
                reason=f"{type(exc).__name__}: {exc!s}"[:200],
                source="tool",
                query=query[:200],
            ),
        )


async def _extract_kb_selection(config: RunnableConfig | None) -> dict | None:
    """Extract knowledge_base_selection from runtime context in RunnableConfig."""
    if not config:
        return None
    configurable = config.get("configurable") or {}
    runtime = configurable.get("__pregel_runtime")
    if runtime is None:
        return None
    selection, _ = await resolve_runtime_kb_selection(runtime)
    return selection


def _extract_runtime_context(config: RunnableConfig | None) -> dict:
    configurable = (config or {}).get("configurable") or {}
    runtime = configurable.get("__pregel_runtime")
    return getattr(runtime, "context", None) or {}


async def _search_selected_kbs(
    query: str, selection: dict, rag_config, config: RunnableConfig | None
) -> str:
    """Search across user's selected knowledge bases."""
    from deerflow.knowledge_base.retrieval import multi_kb_retrieve
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

    context = _extract_runtime_context(config)
    tenant_id = context.get("tenant_id") or get_current_tenant_id()
    user_id = context.get("user_id") or get_effective_user_id()
    selected_ids_capped = list(selection.get("selected_ids") or [])[: rag_config.max_selected_kbs]

    if not tenant_id or tenant_id == _DEFAULT_TENANT_ID or not user_id:
        return _emit(
            {"error": "Missing tenant or user context", "results": []},
            RagDecisionEvent(
                outcome="blocked",
                reason="missing tenant or user context",
                source="tool",
                query=query[:200],
                selected_kb_ids=selected_ids_capped,
            ),
        )

    if user_id == DEFAULT_USER_ID and not rag_config.allow_no_auth_kb:
        return _emit(
            {"error": "Knowledge base access requires authentication", "results": []},
            RagDecisionEvent(
                outcome="blocked",
                reason="no-auth user and rag.allow_no_auth_kb=false",
                source="tool",
                query=query[:200],
                selected_kb_ids=selected_ids_capped,
            ),
        )

    sf = get_session_factory()
    if sf is None:
        return _emit(
            {"error": "Database not configured", "results": []},
            RagDecisionEvent(
                outcome="failed",
                reason="session factory unavailable",
                source="tool",
                query=query[:200],
                selected_kb_ids=selected_ids_capped,
            ),
        )

    repo = KnowledgeBaseRepository(sf)
    knowledge_bases = await repo.resolve_accessible_by_ids(
        selected_ids_capped, tenant_id=tenant_id, user_id=user_id
    )
    accessible_ids = [str(kb.get("id", "")) for kb in (knowledge_bases or [])]
    denied_ids = [kid for kid in selected_ids_capped if kid not in accessible_ids]

    # Explicit application-level permission verification via KbAccessControl
    from deerflow.knowledge_base.access_control import KbAccessControl, UserContext

    ac = KbAccessControl(permission_repo=None)
    user_ctx = UserContext(user_id=user_id, tenant_id=tenant_id, role="user")
    verified_kbs = [kb for kb in (knowledge_bases or []) if ac.can_read(user_ctx, kb)]
    verified_ids = [str(kb.get("id", "")) for kb in verified_kbs]

    if len(verified_kbs) != len(knowledge_bases or []):
        logger.warning(
            "can_read verification filtered %d KBs that passed SQL-level access check",
            len(knowledge_bases or []) - len(verified_kbs),
        )

    if not verified_kbs:
        denied_detail = None
        if denied_ids:
            denied_detail = {
                "denied_kb_ids": denied_ids,
                "reason": "access_denied",
                "hint": "You do not have read access to the requested knowledge bases. Contact the KB owner to request access.",
            }
        return _emit(
            {"query": query, "results": [], "note": "No accessible knowledge bases found", **({"denied": denied_detail} if denied_detail else {})},
            RagDecisionEvent(
                outcome="blocked",
                reason="no accessible KB after permission filter",
                source="tool",
                query=query[:200],
                selected_kb_ids=selected_ids_capped,
                accessible_kb_ids=[],
                denied_kb_ids=denied_ids,
            ),
        )

    results = await asyncio.to_thread(
        multi_kb_retrieve,
        verified_kbs,
        query,
        rag_config.retrieval_top_k,
        tenant_id=tenant_id,
        user_id=user_id,
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

    response_payload: dict = {"query": query, "results": formatted}
    if denied_ids:
        response_payload["denied"] = {
            "denied_kb_ids": denied_ids,
            "reason": "access_denied",
            "hint": "Some requested knowledge bases were skipped due to insufficient permissions.",
        }

    if not results:
        decision = RagDecisionEvent(
            outcome="skipped",
            reason="no chunks returned from selected KBs",
            source="tool",
            query=query[:200],
            selected_kb_ids=selected_ids_capped,
            accessible_kb_ids=verified_ids,
            denied_kb_ids=denied_ids,
            score_strategy=getattr(rag_config, "cross_kb_score_strategy", None),
        )
    else:
        decision = RagDecisionEvent(
            outcome="injected",
            reason=f"returned {len(results)} chunks from {len(verified_kbs)} KB",
            source="tool",
            query=query[:200],
            selected_kb_ids=selected_ids_capped,
            accessible_kb_ids=verified_ids,
            denied_kb_ids=denied_ids,
            chunks_returned=len(results),
            chunks_injected=len(results),
            score_strategy=getattr(rag_config, "cross_kb_score_strategy", None),
        )

    return _emit(response_payload, decision)


async def _search_single_collection(query: str, collection: str, rag_config, config: RunnableConfig | None) -> str:
    """Search a single named collection through owner-scoped KB resolution."""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

    context = _extract_runtime_context(config)
    tenant_id = context.get("tenant_id") or get_current_tenant_id()
    user_id = context.get("user_id") or get_effective_user_id()

    if not tenant_id or tenant_id == _DEFAULT_TENANT_ID or not user_id:
        return _emit(
            {"error": "Missing tenant or user context", "results": []},
            RagDecisionEvent(
                outcome="blocked",
                reason="missing tenant or user context",
                source="tool",
                query=query[:200],
            ),
        )

    if user_id == DEFAULT_USER_ID and not rag_config.allow_no_auth_kb:
        return _emit(
            {"error": "Knowledge base access requires authentication", "results": []},
            RagDecisionEvent(
                outcome="blocked",
                reason="no-auth user and rag.allow_no_auth_kb=false",
                source="tool",
                query=query[:200],
            ),
        )

    sf = get_session_factory()
    if sf is None:
        return _emit(
            {"error": "Database not configured", "results": []},
            RagDecisionEvent(
                outcome="failed",
                reason="session factory unavailable",
                source="tool",
                query=query[:200],
            ),
        )

    repo = KnowledgeBaseRepository(sf)
    knowledge_bases = await repo.resolve_accessible_by_collections(
        [collection], tenant_id=tenant_id, user_id=user_id
    )
    [str(kb.get("id", "")) for kb in (knowledge_bases or [])]

    # Explicit application-level permission verification via KbAccessControl
    from deerflow.knowledge_base.access_control import KbAccessControl, UserContext

    ac = KbAccessControl(permission_repo=None)
    user_ctx = UserContext(user_id=user_id, tenant_id=tenant_id, role="user")
    verified_kbs = [kb for kb in (knowledge_bases or []) if ac.can_read(user_ctx, kb)]

    if not verified_kbs:
        return _emit(
            {"error": "Knowledge base not accessible", "results": [], "denied": {"collection": collection, "reason": "access_denied", "hint": "You do not have read access to this knowledge base."}},
            RagDecisionEvent(
                outcome="blocked",
                reason=f"collection {collection!r} not in accessible KBs",
                source="tool",
                query=query[:200],
                accessible_kb_ids=[],
            ),
        )

    from deerflow.knowledge_base.retrieval import multi_kb_retrieve

    results = await asyncio.to_thread(
        multi_kb_retrieve,
        verified_kbs,
        query,
        rag_config.retrieval_top_k,
        tenant_id=tenant_id,
        user_id=user_id,
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

    verified_ids = [str(kb.get("id", "")) for kb in verified_kbs]

    if not results:
        decision = RagDecisionEvent(
            outcome="skipped",
            reason=f"no chunks returned from collection {collection!r}",
            source="tool",
            query=query[:200],
            accessible_kb_ids=verified_ids,
        )
    else:
        decision = RagDecisionEvent(
            outcome="injected",
            reason=f"returned {len(results)} chunks from collection {collection!r}",
            source="tool",
            query=query[:200],
            accessible_kb_ids=verified_ids,
            chunks_returned=len(results),
            chunks_injected=len(results),
        )

    return _emit({"query": query, "collection": collection, "results": formatted}, decision)
