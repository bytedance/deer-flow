"""Tests for RagMiddleware decision-event injection (Sprint A.2 + B.2.1).

After Sprint B.2.1 the middleware is async-native: ``abefore_agent`` is a
coroutine and we call ``resolve_runtime_kb_selection`` directly without a
thread pool. The test surface adapts: each ``abefore_agent`` invocation
must be awaited, and patches target the imported name in the middleware
module rather than a private static helper.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.rag_middleware import (
    RagMiddleware,
    _rag_decision_context,
    _rag_retrieval_context,
)
from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.config.tenant import get_current_tenant_id
from deerflow.rag.decisions import KB_DECISION_KEY, RagDecisionEvent


def _make_runtime(context: dict | None = None) -> Any:
    runtime = MagicMock()
    runtime.context = context or {}
    return runtime


def _read_decision_from_after_agent(
    middleware: RagMiddleware, last_msg: AIMessage
) -> dict | None:
    state = {"messages": [last_msg]}
    result = middleware.after_agent(state, _make_runtime({}))
    if not result:
        return None
    out_msgs = result.get("messages", [])
    if not out_msgs:
        return None
    kwargs = getattr(out_msgs[-1], "additional_kwargs", {}) or {}
    return kwargs.get(KB_DECISION_KEY)


class TestRagMiddlewareDecisionEvents:
    def setup_method(self) -> None:
        _rag_decision_context.set(None)
        _rag_retrieval_context.set(None)

    def teardown_method(self) -> None:
        _rag_decision_context.set(None)
        _rag_retrieval_context.set(None)
        set_rag_config(RagConfig())

    @pytest.mark.asyncio
    async def test_disabled_outcome_when_rag_disabled(self) -> None:
        set_rag_config(RagConfig(enabled=False))
        mw = RagMiddleware()
        state = {"messages": [HumanMessage(content="hello")]}

        result = await mw.abefore_agent(state, _make_runtime())

        assert result is None
        decision = _rag_decision_context.get()
        assert isinstance(decision, RagDecisionEvent)
        assert decision.outcome == "disabled"
        assert decision.source == "middleware"

        ai = AIMessage(content="hi")
        payload = _read_decision_from_after_agent(mw, ai)
        assert payload is not None
        assert payload["outcome"] == "disabled"

    @pytest.mark.asyncio
    async def test_disabled_outcome_when_injection_disabled(self) -> None:
        set_rag_config(RagConfig(enabled=True, injection_enabled=False))
        mw = RagMiddleware()
        state = {"messages": [HumanMessage(content="hello")]}

        await mw.abefore_agent(state, _make_runtime())
        decision = _rag_decision_context.get()
        assert decision is not None
        assert decision.outcome == "disabled"
        assert "injection_enabled=False" in decision.reason

    @pytest.mark.asyncio
    async def test_skipped_when_user_message_empty(self) -> None:
        set_rag_config(RagConfig(enabled=True, injection_enabled=True))
        mw = RagMiddleware()
        state = {"messages": [HumanMessage(content="   ")]}

        await mw.abefore_agent(state, _make_runtime())
        decision = _rag_decision_context.get()
        assert decision is not None
        assert decision.outcome == "skipped"
        assert "empty" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_blocked_no_auth_default_path(self) -> None:
        set_rag_config(
            RagConfig(enabled=True, injection_enabled=True, allow_no_auth_kb=False)
        )
        mw = RagMiddleware()
        state = {"messages": [HumanMessage(content="what is x?")]}
        runtime = _make_runtime({"user_id": "default"})

        async def _no_selection(_runtime):
            return None, None

        with patch(
            "deerflow.agents.middlewares.rag_middleware.resolve_runtime_kb_selection",
            side_effect=_no_selection,
        ):
            await mw.abefore_agent(state, runtime)

        decision = _rag_decision_context.get()
        assert decision is not None
        assert decision.outcome == "blocked"
        assert "no-auth" in decision.reason

    @pytest.mark.asyncio
    async def test_failed_outcome_on_unexpected_exception(self) -> None:
        set_rag_config(RagConfig(enabled=True, injection_enabled=True))
        mw = RagMiddleware()
        state = {"messages": [HumanMessage(content="hello")]}

        async def _boom(_runtime):
            raise RuntimeError("boom")

        with patch(
            "deerflow.agents.middlewares.rag_middleware.resolve_runtime_kb_selection",
            side_effect=_boom,
        ):
            result = await mw.abefore_agent(state, _make_runtime())

        assert result is None
        decision = _rag_decision_context.get()
        assert decision is not None
        assert decision.outcome == "failed"
        assert "RuntimeError" in decision.reason

    @pytest.mark.asyncio
    async def test_blocked_when_selected_path_missing_tenant(self) -> None:
        set_rag_config(
            RagConfig(enabled=True, injection_enabled=True, allow_no_auth_kb=True)
        )
        mw = RagMiddleware()
        state = {"messages": [HumanMessage(content="q")]}
        runtime = _make_runtime({"thread_id": "t1", "tenant_id": "", "user_id": ""})

        async def _selected(_runtime):
            return ({"selected_ids": ["kb-1"]}, "thread_metadata")

        with patch(
            "deerflow.agents.middlewares.rag_middleware.resolve_runtime_kb_selection",
            side_effect=_selected,
        ), patch(
            "deerflow.agents.middlewares.rag_middleware.get_effective_user_id",
            return_value="",
        ), patch(
            "deerflow.agents.middlewares.rag_middleware.get_current_tenant_id",
            return_value="",
        ):
            await mw.abefore_agent(state, runtime)

        decision = _rag_decision_context.get()
        assert decision is not None
        assert decision.outcome == "blocked"
        assert (
            "missing tenant" in decision.reason
            or "missing user" in decision.reason
            or "missing" in decision.reason.lower()
        )

    @pytest.mark.asyncio
    async def test_default_path_restores_runtime_tenant_inside_worker_thread(self) -> None:
        set_rag_config(
            RagConfig(enabled=True, injection_enabled=True, allow_no_auth_kb=True)
        )
        mw = RagMiddleware()
        state = {"messages": [HumanMessage(content="what is x?")]}
        runtime = _make_runtime({"tenant_id": "tenant-acme", "user_id": "user-1"})

        async def _no_selection(_runtime):
            return None, None

        observed: dict[str, str | None] = {}

        class _FakeRetriever:
            def retrieve(self, *, query, top_k, score_threshold):
                from deerflow.rag.retrieval import RetrievalResult
                from deerflow.rag.vector_store import SearchResult

                observed["tenant_id"] = get_current_tenant_id()
                return RetrievalResult(
                    query=query,
                    collection="default",
                    results=[
                        SearchResult(
                            chunk_id="c1",
                            content="chunk",
                            metadata={"source": "kb"},
                            score=0.9,
                        )
                    ],
                )

        with patch(
            "deerflow.agents.middlewares.rag_middleware.resolve_runtime_kb_selection",
            side_effect=_no_selection,
        ):
            mw._retriever = _FakeRetriever()
            result = await mw.abefore_agent(state, runtime)

        assert result is not None
        assert observed["tenant_id"] == "tenant-acme"
        decision = _rag_decision_context.get()
        assert decision is not None
        assert decision.outcome == "injected"


    def test_namespaced_decision_key(self) -> None:
        assert KB_DECISION_KEY == "knowledge_base_decision"
