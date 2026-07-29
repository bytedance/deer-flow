"""Regression anchor: inline RunJournal callbacks stay event-loop safe."""

from __future__ import annotations

from uuid import uuid4

import pytest
from langchain_core.callbacks.manager import ahandle_event
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal

pytestmark = pytest.mark.asyncio


async def test_inline_tool_callback_does_not_block_event_loop() -> None:
    journal = RunJournal("run-1", "thread-1", MemoryRunEventStore(), flush_threshold=100)
    journal._remember_current_run_tool_calls(
        AIMessage(content="", tool_calls=[{"id": "call-1", "name": "present_files", "args": {}}]),
        caller="lead_agent",
    )
    command = Command(
        update={
            "artifacts": ["/mnt/user-data/outputs/report.md"],
            "messages": [ToolMessage("Successfully presented files", tool_call_id="call-1")],
        }
    )

    await ahandle_event(
        [journal],
        "on_tool_end",
        "ignore_agent",
        command,
        run_id=uuid4(),
    )

    assert journal.get_delivery_content()["paths"] == ["/mnt/user-data/outputs/report.md"]
