"""Unaddressable calls must never become approval pauses or tool results."""

import json
from unittest.mock import AsyncMock

import pytest
from _agent_e2e_helpers import FakeToolCallingModel
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.approvals.middleware import ToolApprovalMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.hitl_approval_config import HitlApprovalConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("mode", ["ask", "auto", "full"])
@pytest.mark.parametrize("unattended", [False, True], ids=["interactive", "unattended"])
@pytest.mark.parametrize("call_ids", [[None], [""], ["shared", "shared"], ["shared", "shared", "shared"]], ids=["null", "empty", "duplicate", "mixed-collision"])
async def test_unusable_call_ids_are_removed_before_review_or_execution(asynchronous, mode, unattended, call_ids):
    executed = []

    @tool
    def external_write(value: str) -> str:
        """Record a write."""
        executed.append(value)
        return "written"

    @tool
    def ordinary_read() -> str:
        """Record an ordinary read."""
        executed.append("read")
        return "read"

    calls = [{"name": "external_write", "args": {"value": str(i)}, "id": call_id} for i, call_id in enumerate(call_ids)]
    if len(calls) == 3:
        calls[-1].update(name="ordinary_read", args={})
    raw = [{"id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": json.dumps(call["args"])}} for call in calls]
    content = [{"type": "text", "text": "Original explanation"}]
    # Exercise every provider surface the shared cloning helper must trim.
    for call in calls:
        content.extend(
            [
                {"type": "tool_use", "id": call["id"], "name": call["name"], "input": call["args"]},
                {"type": "function_call", "id": "fc_item", "call_id": call["id"], "name": call["name"], "arguments": json.dumps(call["args"])},
                {"type": "custom_tool_call", "call_id": call["id"], "name": call["name"], "input": "value"},
                {"type": "tool_call", **call},
                {"type": "tool_call_chunk", **call},
                {"type": "function_call", "name": call["name"], "args": call["args"]},
            ]
        )
    initial = AIMessage(content=content, tool_calls=calls, additional_kwargs={"tool_calls": raw, "function_call": raw[0]["function"]}, response_metadata={"finish_reason": "tool_calls"})
    reviewer = AsyncMock(return_value={"outcome": "allow", "risk": "low", "authorization": "explicit", "reason": "authorized"})
    policy = HitlApprovalConfig(enabled=True, tools=["external_write"], allow_tools=["ordinary_read"], default_mode=mode, allowed_modes=["ask", "auto", "full"])
    app = AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, hitl_approval=policy)
    graph = create_agent(
        FakeToolCallingModel(responses=[initial, AIMessage(content="Next turn works")]),
        tools=[external_write, ordinary_read],
        middleware=[ToolApprovalMiddleware(policy, app_config=app, reviewer=reviewer)],
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "unusable-calls"}}
    context = {"non_interactive": unattended}

    async def invoke(input):
        if asynchronous:
            return await graph.ainvoke(input, config, context=context)
        return graph.invoke(input, config, context=context)

    result = await invoke({"messages": [("user", "Perform the operation")]})

    assert not result.get("__interrupt__")
    assert executed == []
    reviewer.assert_not_called()
    assert not any(isinstance(message, ToolMessage) for message in result["messages"])
    answer = result["messages"][-1]
    assert answer.tool_calls == []
    assert "tool_calls" not in answer.additional_kwargs
    assert "function_call" not in answer.additional_kwargs
    assert answer.response_metadata["finish_reason"] == "stop"
    assert all(block["type"] == "text" for block in answer.content)
    visible_text = "\n".join(block["text"] for block in answer.content)
    assert "Original explanation" in visible_text
    assert "no usable id" in visible_text

    # A real second invocation on the same checkpoint must remain usable.
    following = await invoke({"messages": [("user", "Continue with the explanation")]})
    assert not following.get("__interrupt__")
    assert following["messages"][-1].content == "Next turn works"
    assert executed == []
