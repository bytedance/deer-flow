"""Middleware for automatic RAG chunk injection."""

from __future__ import annotations

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.config.rag_config import get_rag_config
from deerflow.rag.prompt import format_chunks_for_injection
from deerflow.rag.retrieval import DocumentRetriever

logger = logging.getLogger(__name__)


class RagMiddlewareState(AgentState):
    """Compatible with the ``ThreadState`` schema."""

    pass


class RagMiddleware(AgentMiddleware[RagMiddlewareState]):
    """Middleware that injects relevant knowledge base chunks before each agent turn.

    Follows the same pattern as :class:`MemoryMiddleware`:
    1. Before each agent execution, extracts the last user message
    2. Searches the vector store for relevant chunks
    3. Injects formatted chunks into the system prompt

    Only activates when ``rag.enabled`` and ``rag.injection_enabled`` are both true.
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
        config = get_rag_config()
        if not config.enabled or not config.injection_enabled:
            return None

        messages = state.get("messages", [])
        if not messages:
            return None

        # Extract the last human message as the search query
        last_user_content = ""
        for msg in reversed(messages):
            if getattr(msg, "type", None) == "human":
                content = getattr(msg, "content", "")
                if isinstance(content, str):
                    last_user_content = content
                elif isinstance(content, list):
                    parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
                    last_user_content = " ".join(parts)
                break

        if not last_user_content.strip():
            return None

        try:
            result = self._get_retriever().retrieve(
                query=last_user_content,
                top_k=config.max_injection_chunks,
                score_threshold=config.score_threshold,
            )

            if not result.results:
                return None

            formatted = format_chunks_for_injection(result.results, max_tokens=config.max_injection_tokens)
            if not formatted:
                return None

            # Inject into system prompt by adding a system message
            from langchain_core.messages import SystemMessage

            return {"messages": [SystemMessage(content=formatted)]}
        except Exception as e:
            logger.warning("RagMiddleware.before_agent failed: %s", e)
            return None
