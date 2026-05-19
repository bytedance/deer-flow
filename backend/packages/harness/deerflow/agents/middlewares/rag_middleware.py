"""Middleware for automatic RAG chunk injection."""

from __future__ import annotations

import asyncio
import json
import logging
from contextvars import ContextVar
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from deerflow.config.rag_config import compute_effective_top_k, get_rag_config
from deerflow.config.tenant import get_current_tenant_id
from deerflow.knowledge_base.retrieval import (
    build_retrieval_trace_data,
    build_selection_snapshot,
    resolve_runtime_kb_selection,
)
from deerflow.rag.decisions import KB_DECISION_KEY, RagDecisionEvent
from deerflow.rag.prompt import format_chunks_for_injection, format_multi_kb_context
from deerflow.rag.retrieval import DocumentRetriever
from deerflow.runtime.user_context import DEFAULT_USER_ID, get_effective_user_id

logger = logging.getLogger(__name__)

KB_SELECTION_SNAPSHOT_KEY = "knowledge_base_selection_snapshot"
KB_RETRIEVAL_TRACE_KEY = "knowledge_base_retrieval_trace"

_rag_retrieval_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "_rag_retrieval_context", default=None
)
_rag_decision_context: ContextVar[RagDecisionEvent | None] = ContextVar(
    "_rag_decision_context", default=None
)


class RagMiddlewareState(AgentState):
    """Compatible with the ``ThreadState`` schema."""

    pass


class RagMiddleware(AgentMiddleware[RagMiddlewareState]):
    """Middleware that injects relevant knowledge base chunks before each agent turn.

    Supports two modes:
    1. Default collection: searches the global "default" collection (legacy behavior)
    2. Multi-KB selection: when ``runtime.context["knowledge_base_selection"]`` is set,
       searches across the user's selected knowledge bases in parallel
    """

    state_schema = RagMiddlewareState

    def __init__(self) -> None:
        super().__init__()
        self._retriever: DocumentRetriever | None = None

    def _get_retriever(self) -> DocumentRetriever:
        if self._retriever is None:
            self._retriever = DocumentRetriever()
        return self._retriever

    @override
    async def abefore_agent(self, state: RagMiddlewareState, runtime: Runtime) -> dict | None:
        _rag_retrieval_context.set(None)
        _rag_decision_context.set(None)

        config = get_rag_config()
        if not config.enabled or not config.injection_enabled:
            logger.info("RagMiddleware: skipped (enabled=%s, injection_enabled=%s)", config.enabled, config.injection_enabled)
            _rag_decision_context.set(
                RagDecisionEvent(
                    outcome="disabled",
                    reason=f"rag.enabled={config.enabled}, injection_enabled={config.injection_enabled}",
                    source="middleware",
                )
            )
            return None

        messages = state.get("messages", [])
        if not messages:
            logger.info("RagMiddleware: skipped — no messages in state")
            return None

        last_user_content = self._extract_last_user_message(messages)
        if not last_user_content.strip():
            logger.info("RagMiddleware: skipped — empty user message")
            _rag_decision_context.set(
                RagDecisionEvent(
                    outcome="skipped",
                    reason="empty user message",
                    source="middleware",
                )
            )
            return None

        logger.info("RagMiddleware: processing query=%r", last_user_content[:100])

        try:
            kb_selection, selection_source = await resolve_runtime_kb_selection(runtime)
            logger.info("RagMiddleware: kb_selection=%s, source=%s", kb_selection, selection_source)
            if kb_selection:
                return await self._retrieve_from_selected_kbs(
                    kb_selection,
                    last_user_content,
                    runtime,
                    selection_source=selection_source,
                )
            if self._is_no_auth_kb_blocked(runtime, config):
                logger.info("RagMiddleware: blocked — no-auth KB access not allowed")
                _rag_decision_context.set(
                    RagDecisionEvent(
                        outcome="blocked",
                        reason="no-auth user and rag.allow_no_auth_kb=false",
                        source="middleware",
                        query=last_user_content[:200],
                    )
                )
                return None
            return await self._retrieve_from_default(last_user_content, config)
        except Exception as e:
            logger.warning("RagMiddleware.before_agent failed: %s", e)
            _rag_decision_context.set(
                RagDecisionEvent(
                    outcome="failed",
                    reason=f"{type(e).__name__}: {e!s}"[:200],
                    source="middleware",
                    query=last_user_content[:200],
                )
            )
            return None

    @override
    def after_agent(self, state: RagMiddlewareState, runtime: Runtime) -> dict | None:
        ctx = _rag_retrieval_context.get()
        decision = _rag_decision_context.get()
        _rag_retrieval_context.set(None)
        _rag_decision_context.set(None)

        if not ctx and not decision:
            return None

        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None

        additional_kwargs = dict(getattr(last, "additional_kwargs", {}) or {})
        if ctx:
            additional_kwargs[KB_SELECTION_SNAPSHOT_KEY] = ctx.get("selection_snapshot")
            additional_kwargs[KB_RETRIEVAL_TRACE_KEY] = ctx.get("retrieval_trace")
        if decision is not None:
            additional_kwargs[KB_DECISION_KEY] = decision.to_dict()

        updated_msg = last.model_copy(update={"additional_kwargs": additional_kwargs})
        return {"messages": [updated_msg]}

    @staticmethod
    def _extract_last_user_message(messages: list) -> str:
        for msg in reversed(messages):
            if getattr(msg, "type", None) == "human":
                content = getattr(msg, "content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
                    return " ".join(parts)
                break
        return ""

    @staticmethod
    def _is_no_auth_kb_blocked(runtime: Runtime, config: Any) -> bool:
        context = runtime.context or {}
        owner_user_id = context.get("user_id") or get_effective_user_id()
        return owner_user_id == DEFAULT_USER_ID and not config.allow_no_auth_kb

    async def _retrieve_from_selected_kbs(
        self,
        selection: dict,
        query: str,
        runtime: Runtime,
        *,
        selection_source: str | None,
    ) -> dict | None:
        from langchain_core.messages import SystemMessage

        from deerflow.knowledge_base.retrieval import multi_kb_retrieve
        from deerflow.persistence.engine import get_session_factory
        from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

        config = get_rag_config()
        context = runtime.context or {}
        tenant_id = context.get("tenant_id") or get_current_tenant_id()
        owner_user_id = context.get("user_id") or get_effective_user_id()

        logger.info(
            "RagMiddleware._retrieve_from_selected_kbs: tenant_id=%s, user_id=%s, selected_ids=%s",
            tenant_id, owner_user_id, selection.get("selected_ids"),
        )

        selected_ids = list(selection.get("selected_ids") or [])

        if not tenant_id or not owner_user_id:
            logger.warning("RagMiddleware: missing tenant_id=%r or user_id=%r in context (context keys: %s)",
                           tenant_id, owner_user_id, list(context.keys()))
            _rag_decision_context.set(
                RagDecisionEvent(
                    outcome="blocked",
                    reason="missing tenant_id or user_id in runtime context",
                    source="middleware",
                    query=query[:200],
                    selected_kb_ids=selected_ids,
                )
            )
            return None

        if owner_user_id == DEFAULT_USER_ID and not config.allow_no_auth_kb:
            logger.debug("RagMiddleware: KB access blocked in no-auth mode (allow_no_auth_kb=False)")
            _rag_decision_context.set(
                RagDecisionEvent(
                    outcome="blocked",
                    reason="no-auth user and rag.allow_no_auth_kb=false",
                    source="middleware",
                    query=query[:200],
                    selected_kb_ids=selected_ids,
                )
            )
            return None

        selected_ids_capped = selected_ids[: config.max_selected_kbs]
        sf = get_session_factory()
        if sf is None:
            _rag_decision_context.set(
                RagDecisionEvent(
                    outcome="failed",
                    reason="session factory unavailable",
                    source="middleware",
                    query=query[:200],
                    selected_kb_ids=selected_ids_capped,
                )
            )
            return None

        repo = KnowledgeBaseRepository(sf)

        knowledge_bases = await repo.resolve_accessible_by_ids(
            selected_ids_capped, tenant_id=tenant_id, user_id=owner_user_id
        )

        accessible_ids = [str(kb.get("id", "")) for kb in (knowledge_bases or [])]

        if not knowledge_bases:
            _rag_decision_context.set(
                RagDecisionEvent(
                    outcome="blocked",
                    reason="no accessible KB after permission filter",
                    source="middleware",
                    query=query[:200],
                    selected_kb_ids=selected_ids_capped,
                    accessible_kb_ids=[],
                )
            )
            return None

        # multi_kb_retrieve is sync today (chroma calls are blocking).
        # Wrap in to_thread so we don't pin the event loop while embeddings
        # are computed; the dispatcher handles the heavy indexing path,
        # but query-time retrieval still has to happen here.
        results = await asyncio.to_thread(
            multi_kb_retrieve,
            knowledge_bases,
            query,
            compute_effective_top_k(config),
        )
        # multi_kb_retrieve already applies the reranker; trim to the
        # injection budget so downstream formatters see exactly the K
        # the operator asked for.
        results = results[: config.max_injection_chunks]

        if not results:
            _rag_decision_context.set(
                RagDecisionEvent(
                    outcome="skipped",
                    reason="no chunks returned from selected KBs",
                    source="middleware",
                    query=query[:200],
                    selected_kb_ids=selected_ids_capped,
                    accessible_kb_ids=accessible_ids,
                    score_strategy=getattr(config, "cross_kb_score_strategy", None),
                )
            )
            return None

        formatted = format_multi_kb_context(results, max_tokens=config.max_injection_tokens)
        if not formatted:
            _rag_decision_context.set(
                RagDecisionEvent(
                    outcome="skipped",
                    reason="formatted context exceeds token budget",
                    source="middleware",
                    query=query[:200],
                    selected_kb_ids=selected_ids_capped,
                    accessible_kb_ids=accessible_ids,
                    chunks_returned=len(results),
                )
            )
            return None

        trace = build_retrieval_trace_data(
            query=query,
            results=results,
            knowledge_bases=knowledge_bases,
            filtered_ids=[kb_id for kb_id in selected_ids_capped if kb_id not in {str(kb.get("id", "")) for kb in knowledge_bases}],
            timeouts=[],
        )
        content = formatted + "\n" + f"<retrieval_trace>{json.dumps(trace, ensure_ascii=False)}</retrieval_trace>"

        _rag_retrieval_context.set({
            "selection_snapshot": build_selection_snapshot(
                selection,
                knowledge_bases,
                source=selection_source,
            ),
            "retrieval_trace": trace,
        })
        _rag_decision_context.set(
            RagDecisionEvent(
                outcome="injected",
                reason=f"injected {len(results)} chunks from {len(knowledge_bases)} KB",
                source="middleware",
                query=query[:200],
                selected_kb_ids=selected_ids_capped,
                accessible_kb_ids=accessible_ids,
                chunks_returned=len(results),
                chunks_injected=len(results),
                score_strategy=getattr(config, "cross_kb_score_strategy", None),
            )
        )

        logger.info(
            "RagMiddleware: injected %d chunks from %d KBs (query=%r, source=%s)",
            len(results),
            len(knowledge_bases),
            query[:80],
            selection_source,
        )
        return {"messages": [SystemMessage(content=content)]}

    async def _retrieve_from_default(self, query: str, config) -> dict | None:
        from langchain_core.messages import SystemMessage

        from deerflow.rag.retrieval import rerank

        retriever = self._get_retriever()
        result = await asyncio.to_thread(
            retriever.retrieve,
            query=query,
            top_k=compute_effective_top_k(config),
            score_threshold=config.score_threshold,
        )

        if not result.results:
            logger.debug("RagMiddleware: no results from default collection for query=%r", query[:80])
            _rag_decision_context.set(
                RagDecisionEvent(
                    outcome="skipped",
                    reason="no results from default collection",
                    source="middleware",
                    query=query[:200],
                )
            )
            return None

        chunks = result.results
        if config.reranker_enabled:
            chunks = rerank(query, chunks)
        chunks = chunks[: config.max_injection_chunks]

        formatted = format_chunks_for_injection(chunks, max_tokens=config.max_injection_tokens)
        if not formatted:
            _rag_decision_context.set(
                RagDecisionEvent(
                    outcome="skipped",
                    reason="formatted context exceeds token budget",
                    source="middleware",
                    query=query[:200],
                    chunks_returned=len(chunks),
                )
            )
            return None

        _rag_decision_context.set(
            RagDecisionEvent(
                outcome="injected",
                reason=f"injected {len(chunks)} chunks from default collection",
                source="middleware",
                query=query[:200],
                chunks_returned=len(chunks),
                chunks_injected=len(chunks),
            )
        )
        logger.info(
            "RagMiddleware: injected %d chunks from default collection (query=%r)",
            len(chunks),
            query[:80],
        )
        return {"messages": [SystemMessage(content=formatted)]}
