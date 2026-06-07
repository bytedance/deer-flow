"""Regression anchor: DynamicContextMiddleware must not block the event loop.

``_inject`` performs synchronous file I/O (memory JSON loading) and
potentially blocking network calls (tiktoken encoding download on first
use — see issue #3402).  ``abefore_agent`` offloads the call via
``asyncio.to_thread`` so the event loop stays responsive.

This anchor drives the real ``create_agent`` graph via ``ainvoke`` under
the strict Blockbuster gate.  If the offload regresses and the blocking
I/O runs on the event loop, Blockbuster raises ``BlockingError`` and
this test fails.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest import mock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware

pytestmark = pytest.mark.asyncio


class _FakeModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel with a no-op ``bind_tools`` for create_agent."""

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self


async def test_abefore_agent_does_not_block_event_loop() -> None:
    """``abefore_agent`` must offload _inject() to a thread pool."""
    mw = DynamicContextMiddleware()

    # Mock _build_full_reminder to simulate a slow synchronous operation
    # (file I/O + tiktoken download).  The mock sleeps briefly to make any
    # event-loop blocking visible to the Blockbuster gate.
    original_build = mw._build_full_reminder

    def slow_build_reminder():
        import time

        time.sleep(0.05)  # 50ms sync sleep — blocks the thread it runs on
        return original_build()

    with (
        mock.patch.object(mw, "_build_full_reminder", slow_build_reminder),
        mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=""),
    ):
        agent = await asyncio.to_thread(
            lambda: create_agent(
                model=_FakeModel(responses=[AIMessage(content="ok")]),
                tools=[],
                middleware=[mw],
            )
        )

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="hi")]},
            {"configurable": {"thread_id": "test-thread"}},
        )

    assert result["messages"]


async def test_abefore_agent_returns_same_result_as_before_agent() -> None:
    """``abefore_agent`` (async, offloaded) must produce the same result as
    ``before_agent`` (sync, for backward compatibility)."""
    mw = DynamicContextMiddleware()

    state = {"messages": [HumanMessage(content="Hello", id="msg-1")]}
    runtime = SimpleNamespace(context={})

    with (
        mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=""),
        mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-06-05, Friday"

        # Sync path
        sync_result = mw.before_agent(state, runtime)

        # Async path (offloaded to thread)
        async_result = await mw.abefore_agent(state, runtime)

    assert sync_result is not None
    assert async_result is not None
    assert sync_result.keys() == async_result.keys()
    # Both return 2 messages: reminder + user content
    assert len(sync_result["messages"]) == 2
    assert len(async_result["messages"]) == 2
    # IDs match
    assert sync_result["messages"][0].id == async_result["messages"][0].id
    assert sync_result["messages"][1].id == async_result["messages"][1].id


async def test_abefore_agent_returns_none_on_timeout() -> None:
    """If _inject() exceeds the timeout, abefore_agent returns None gracefully."""
    import time

    mw = DynamicContextMiddleware()

    def blocking_inject(state):
        time.sleep(10)  # Simulate a blocking call that far exceeds the timeout
        return {"messages": [HumanMessage(content="should not reach")]}

    with (
        mock.patch.object(mw, "_inject", blocking_inject),
        mock.patch(
            "deerflow.agents.middlewares.dynamic_context_middleware._INJECT_TIMEOUT_SECONDS",
            0.1,
        ),
    ):
        state = {"messages": [HumanMessage(content="Hello", id="msg-1")]}
        runtime = SimpleNamespace(context={})
        result = await mw.abefore_agent(state, runtime)

    assert result is None
