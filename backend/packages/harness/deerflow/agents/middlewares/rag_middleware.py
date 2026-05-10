"""Middleware for automatic RAG chunk injection."""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from deerflow.config.rag_config import get_rag_config
from deerflow.config.tenant import get_current_tenant_id
from deerflow.knowledge_base.retrieval import (
    build_retrieval_trace_data,
    build_selection_snapshot,
    resolve_runtime_kb_selection,
)
from deerflow.rag.prompt import format_chunks_for_injection, format_multi_kb_context
from deerflow.rag.retrieval import DocumentRetriever
from deerflow.runtime.user_context import DEFAULT_USER_ID, get_effective_user_id

logger = logging.getLogger(__name__)

_resolve_pool = ThreadPoolExecutor(max_workers=2)

KB_SELECTION_SNAPSHOT_KEY = "knowledge_base_selection_snapshot"
KB_RETRIEVAL_TRACE_KEY = "knowledge_base_retrieval_trace"

_rag_retrieval_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "_rag_retrieval_context", default=None
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
    def before_agent(self, state: RagMiddlewareState, runtime: Runtime) -> dict | None:
        _rag_retrieval_context.set(None)

        config = get_rag_config()
        if not config.enabled or not config.injection_enabled:
            logger.info("RagMiddleware: skipped (enabled=%s, injection_enabled=%s)", config.enabled, config.injection_enabled)
            return None

        messages = state.get("messages", [])
        if not messages:
            logger.info("RagMiddleware: skipped — no messages in state")
            return None

        last_user_content = self._extract_last_user_message(messages)
        if not last_user_content.strip():
            logger.info("RagMiddleware: skipped — empty user message")
            return None

        logger.info("RagMiddleware: processing query=%r", last_user_content[:100])

        try:
            kb_selection, selection_source = self._resolve_kb_selection(runtime)
            logger.info("RagMiddleware: kb_selection=%s, source=%s", kb_selection, selection_source)
            if kb_selection:
                return self._retrieve_from_selected_kbs(
                    kb_selection,
                    last_user_content,
                    runtime,
                    selection_source=selection_source,
                )
            if self._is_no_auth_kb_blocked(runtime, config):
                logger.info("RagMiddleware: blocked — no-auth KB access not allowed")
                return None
            return self._retrieve_from_default(last_user_content, config)
        except Exception as e:
            logger.warning("RagMiddleware.before_agent failed: %s", e)
            return None

    @override
    def after_agent(self, state: RagMiddlewareState, runtime: Runtime) -> dict | None:
        ctx = _rag_retrieval_context.get()
        _rag_retrieval_context.set(None)

        if not ctx:
            return None

        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None

        additional_kwargs = dict(getattr(last, "additional_kwargs", {}) or {})
        additional_kwargs[KB_SELECTION_SNAPSHOT_KEY] = ctx.get("selection_snapshot")
        additional_kwargs[KB_RETRIEVAL_TRACE_KEY] = ctx.get("retrieval_trace")

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
    def _resolve_kb_selection(runtime: Runtime) -> tuple[dict | None, str | None]:
        def _run_async() -> tuple[dict | None, str | None]:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(resolve_runtime_kb_selection(runtime))
            finally:
                loop.close()

        return _resolve_pool.submit(_run_async).result(timeout=10)

    @staticmethod
    def _is_no_auth_kb_blocked(runtime: Runtime, config: Any) -> bool:
        context = runtime.context or {}
        owner_user_id = context.get("user_id") or get_effective_user_id()
        return owner_user_id == DEFAULT_USER_ID and not config.allow_no_auth_kb

    def _retrieve_from_selected_kbs(
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

        if not tenant_id or not owner_user_id:
            logger.warning("RagMiddleware: missing tenant_id=%r or user_id=%r in context (context keys: %s)",
                           tenant_id, owner_user_id, list(context.keys()))
            return None

        if owner_user_id == DEFAULT_USER_ID and not config.allow_no_auth_kb:
            logger.debug("RagMiddleware: KB access blocked in no-auth mode (allow_no_auth_kb=False)")
            return None

        selected_ids = selection["selected_ids"][:config.max_selected_kbs]
        sf = get_session_factory()
        if sf is None:
            return None

        repo = KnowledgeBaseRepository(sf)

        async def _resolve():
            return await repo.resolve_accessible_by_ids(
                selected_ids, tenant_id=tenant_id, user_id=owner_user_id
            )

        def _run_async():
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_resolve())
            finally:
                loop.close()

        knowledge_bases = _resolve_pool.submit(_run_async).result(timeout=10)

        if not knowledge_bases:
            return None

        results = multi_kb_retrieve(
            knowledge_bases=knowledge_bases,
            query=query,
            top_k=config.max_injection_chunks,
        )

        if not results:
            return None

        formatted = format_multi_kb_context(results, max_tokens=config.max_injection_tokens)
        if not formatted:
            return None

        trace = build_retrieval_trace_data(
            query=query,
            results=results,
            knowledge_bases=knowledge_bases,
            filtered_ids=[kb_id for kb_id in selected_ids if kb_id not in {str(kb.get("id", "")) for kb in knowledge_bases}],
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

        logger.info(
            "RagMiddleware: injected %d chunks from %d KBs (query=%r, source=%s)",
            len(results),
            len(knowledge_bases),
            query[:80],
            selection_source,
        )
        return {"messages": [SystemMessage(content=content)]}

    def _retrieve_from_default(self, query: str, config) -> dict | None:
        from langchain_core.messages import SystemMessage

        from deerflow.rag.retrieval import rerank

        retriever = self._get_retriever()
        result = retriever.retrieve(
            query=query,
            top_k=config.max_injection_chunks,
            score_threshold=config.score_threshold,
        )

        if not result.results:
            logger.debug("RagMiddleware: no results from default collection for query=%r", query[:80])
            return None

        chunks = result.results
        if config.reranker_enabled:
            chunks = rerank(query, chunks)

        formatted = format_chunks_for_injection(chunks, max_tokens=config.max_injection_tokens)
        if not formatted:
            return None

        logger.info(
            "RagMiddleware: injected %d chunks from default collection (query=%r)",
            len(chunks),
            query[:80],
        )
        return {"messages": [SystemMessage(content=formatted)]}
