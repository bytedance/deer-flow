"""Regression anchor: SubagentDateContextMiddleware must not block the event loop.

``_inject`` can resolve ``DEER_FLOW_DATE_TIMEZONE`` through ``ZoneInfo``, which
reads the OS timezone database (or the bundled ``tzdata`` wheel) on a cold
cache. ``abefore_agent`` runs on the async subagent path with no guarantee that
an assembly observer warmed that resolution first, so it offloads the call via
``asyncio.to_thread`` — the same pattern ``DynamicContextMiddleware`` uses for
its file-I/O injection (see issue #3402).

This anchor drives the real ``create_agent`` graph via ``ainvoke`` under the
strict Blockbuster gate with the knob enabled. If the offload regresses and
``ZoneInfo`` resolution runs on the event loop, Blockbuster raises
``BlockingError`` and this test fails.
"""

from __future__ import annotations

import asyncio

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.agents.middlewares.dynamic_context_middleware import (
    _DYNAMIC_CONTEXT_REMINDER_KEY,
    SubagentDateContextMiddleware,
)

pytestmark = pytest.mark.asyncio


class _FakeModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel with a no-op ``bind_tools`` for create_agent."""

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self


async def test_subagent_abefore_agent_does_not_block_event_loop_with_timezone_enabled(monkeypatch) -> None:
    """A cold DEER_FLOW_DATE_TIMEZONE resolution must stay off the event loop."""
    monkeypatch.setenv("DEER_FLOW_DATE_TIMEZONE", "Asia/Shanghai")
    middleware = SubagentDateContextMiddleware()

    agent = await asyncio.to_thread(
        lambda: create_agent(
            model=_FakeModel(responses=[AIMessage(content="ok")]),
            tools=[],
            middleware=[middleware],
        )
    )

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        {"configurable": {"thread_id": "test-thread"}},
    )

    reminders = [message for message in result["messages"] if isinstance(message, SystemMessage) and (message.additional_kwargs or {}).get(_DYNAMIC_CONTEXT_REMINDER_KEY)]
    assert reminders, "the subagent date reminder must have been injected"
    assert "<current_date>" in reminders[0].content
