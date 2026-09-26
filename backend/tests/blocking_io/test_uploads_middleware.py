"""Regression anchor: UploadsMiddleware must not block the event loop.

``before_agent`` scans the thread uploads directory (``exists`` / ``iterdir`` /
``stat`` plus reading sibling ``.md`` outlines). LangChain wires a sync-only
``before_agent`` as ``RunnableCallable(before_agent, None)``; langgraph's
``ainvoke`` runs it directly on the event loop when ``afunc is None``. So the
filesystem scan must be offloaded (the middleware provides ``abefore_agent``).

This anchor drives the real ``create_agent`` graph via ``ainvoke`` under the
strict Blockbuster gate. If the scan regresses back onto the event loop,
Blockbuster raises ``BlockingError`` and this test fails.

The graph/middleware construction is offloaded with ``asyncio.to_thread`` only
because ``Paths.__init__`` resolves paths synchronously; the surface under test
(``before_agent``'s directory scan) is exercised on the event loop, not
bypassed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

pytestmark = pytest.mark.asyncio


class _FakeModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel with a no-op ``bind_tools`` for create_agent."""

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self


async def test_before_agent_uploads_scan_does_not_block_event_loop(tmp_path: Path) -> None:
    from langchain.agents import create_agent

    from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware
    from deerflow.runtime.user_context import get_effective_user_id

    mw = await asyncio.to_thread(UploadsMiddleware, str(tmp_path))
    uploads_dir = await asyncio.to_thread(mw._paths.sandbox_uploads_dir, "t1", user_id=get_effective_user_id())
    uploads_dir.mkdir(parents=True, exist_ok=True)  # test-side seeding (not in scanned_modules)
    (uploads_dir / "existing.txt").write_text("hello", encoding="utf-8")

    agent = await asyncio.to_thread(lambda: create_agent(model=_FakeModel(responses=[AIMessage(content="ok")]), tools=[], middleware=[mw]))

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        {"configurable": {"thread_id": "t1"}},
    )

    assert result["messages"]
