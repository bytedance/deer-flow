"""Exercise artifact hooks under conftest's detect_blocking_io_strict gate."""

import asyncio
import re
from types import SimpleNamespace

import pytest
from _agent_e2e_helpers import FakeToolCallingModel
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares.artifact_capture_middleware import ArtifactCaptureMiddleware
from deerflow.agents.middlewares.artifact_resolution_middleware import ArtifactResolutionMiddleware
from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.agents.thread_state import ThreadState

pytestmark = pytest.mark.asyncio


class HandleFollowingModel(FakeToolCallingModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.i == 1:
            block = next(m.content for m in messages if m.additional_kwargs.get("durable_context_data"))
            self.responses[1].tool_calls[0]["args"]["path"] = re.search(r"art_[0-9a-f]{8}", block).group()
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


async def test_async_capture_project_and_resolve_cycle_does_not_block():
    seen = []

    @tool(response_format="content_and_artifact")
    async def make_file() -> tuple[str, dict]:
        """Create a structured file reference."""
        return "done", {"structured_content": {"file": "/mnt/user-data/outputs/report.md"}}

    @tool
    async def read_file(path: str) -> str:
        """Read a file."""
        seen.append(path)
        return "read"

    model = HandleFollowingModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "make_file", "args": {}, "id": "make", "type": "tool_call"}]),
            AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "pending"}, "id": "read", "type": "tool_call"}]),
            AIMessage(content="done"),
        ]
    )
    graph = await asyncio.to_thread(lambda: create_agent(model=model, tools=[make_file, read_file], middleware=[ArtifactResolutionMiddleware(), ArtifactCaptureMiddleware(), DurableContextMiddleware()], state_schema=ThreadState))
    state = await graph.ainvoke({"messages": [HumanMessage(content="make then read")]}, context={"thread_id": "strict-artifact-thread"})
    assert seen == ["/mnt/user-data/outputs/report.md"]
    assert state["tool_artifacts"][0]["consumed_by"] == ["read"]


async def test_async_unknown_handle_returns_error_without_io_or_execution():
    req = ToolCallRequest(tool_call={"name": "read_file", "args": {"path": "art_00000000"}, "id": "read", "type": "tool_call"}, tool=None, state={"tool_artifacts": []}, runtime=SimpleNamespace(context={"thread_id": "t"}))

    async def never(_request):
        raise AssertionError("Unknown handles must not execute tools")

    reply = await ArtifactResolutionMiddleware().awrap_tool_call(req, never)
    assert reply.status == "error" and "art_00000000" in reply.content


async def test_async_oversized_structured_payload_is_rejected_before_serialization(monkeypatch):
    import deerflow.tools.artifact_registry as registry

    def never_encode(*args, **kwargs):
        raise AssertionError("Do not serialize oversized MCP payloads on the loop")

    message = ToolMessage(id="huge", content="done", tool_call_id="make", artifact={"structured_content": {"opaque": "x" * 1000000}})
    # Ledger identity uses json.dumps too; only intercept the actual payload.
    encode = registry.json.dumps

    def guarded_encode(value, *args, **kwargs):
        if isinstance(value, dict) and "opaque" in value:
            return never_encode()
        return encode(value, *args, **kwargs)

    monkeypatch.setattr(registry.json, "dumps", guarded_encode)
    update = await ArtifactCaptureMiddleware().abefore_model({"messages": [message]}, SimpleNamespace(context={"thread_id": "t"}))
    assert "tool_artifacts" not in update
    assert update["tool_artifact_processed"]
