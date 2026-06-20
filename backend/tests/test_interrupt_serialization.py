"""Regression tests for issue #3595: __interrupt__ must survive serialize_channel_values."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.graph import StateGraph
from langgraph.types import Interrupt, interrupt


def _interrupting_node(state: dict) -> dict[str, Any]:
    result = interrupt("Please provide API credentials")
    return {"result": result}


def _build_test_graph():
    builder = StateGraph(dict)
    builder.add_node("ask_credential", _interrupting_node)
    builder.set_entry_point("ask_credential")
    builder.set_finish_point("ask_credential")
    return builder.compile()


class _StreamCollector:
    def __init__(self):
        self.events: list[tuple[str, Any]] = []

    async def publish(self, _run_id: str, event: str, data: Any):
        self.events.append((event, data))


@pytest.mark.asyncio
async def test_values_mode_includes_interrupt():
    from deerflow.runtime.serialization import serialize

    graph = _build_test_graph()
    collector = _StreamCollector()
    async for chunk in graph.astream({"messages": []}, stream_mode="values"):
        data = serialize(chunk, mode="values")
        await collector.publish("test", "values", data)
    interrupt_events = [e for e in collector.events if isinstance(e[1], dict) and "__interrupt__" in e[1]]
    assert len(interrupt_events) > 0, "__interrupt__ was stripped from values events"
    # Verify the payload is structured (not a str fallback from serialize_lc_object)
    interrupt_value = interrupt_events[0][1]["__interrupt__"]
    assert isinstance(interrupt_value, list)
    assert len(interrupt_value) > 0
    assert isinstance(interrupt_value[0], dict)
    assert interrupt_value[0]["value"] == "Please provide API credentials"


@pytest.mark.asyncio
async def test_serialize_channel_values_keeps_interrupt():
    from deerflow.runtime.serialization import serialize_channel_values

    interrupt_obj = Interrupt(value={"question": "Enter API key"}, id="test-interrupt-id")
    result = serialize_channel_values(
        {
            "__interrupt__": (interrupt_obj,),
            "__pregel_tasks": "internal",
            "messages": [],
        }
    )
    assert "__interrupt__" in result
    assert "__pregel_tasks" not in result
    assert "messages" in result
    # Verify payload shape: Interrupt must serialize to a dict, not str
    assert isinstance(result["__interrupt__"], list)
    assert len(result["__interrupt__"]) > 0
    assert isinstance(result["__interrupt__"][0], dict)
    assert result["__interrupt__"][0]["value"] == {"question": "Enter API key"}
