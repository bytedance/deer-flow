"""Read evidence belongs to the current tool call, including Command updates."""

import asyncio
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, StructuredTool
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.read_before_write_middleware import READ_MARK_KEY, WRITE_BLOCK_KEY, ReadBeforeWriteMiddleware
from deerflow.sandbox.read_file_contract import READ_FILE_INVALID_RANGE


class GateTestModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.mark.parametrize("invocation", ["invoke", "ainvoke"])
@pytest.mark.parametrize("layout", ["direct", "matching_first", "matching_last"])
@pytest.mark.parametrize("read_outcome", ["success", "error", "no_content"])
def test_read_command_cannot_borrow_another_calls_evidence(tmp_path, invocation, layout, read_outcome):
    target = tmp_path / "report.md"
    target.write_text("Original report", encoding="utf-8")
    path = target.as_posix()
    previous = ToolMessage(content="Earlier audit completed", tool_call_id="audit-old", id="audit-result", name="audit", additional_kwargs={"audit": "keep"})
    previous_snapshot = copy.deepcopy(previous)
    executions = []
    returned = []

    def read_file(path: str, tool_call_id: Annotated[str, InjectedToolCallId]):
        """Read an existing file and optionally update another historical result."""
        executions.append("read")
        content = Path(path).read_text(encoding="utf-8") if read_outcome == "success" else "Error: read failed" if read_outcome == "error" else READ_FILE_INVALID_RANGE
        own = ToolMessage(content=content, tool_call_id=tool_call_id, status="error" if read_outcome == "error" else "success")
        if layout == "direct":
            result = own
        else:
            historical = copy.deepcopy(previous)
            messages = [own, historical] if layout == "matching_first" else [historical, own]
            result = Command(update={"messages": messages})
        returned.append(result)
        return result

    def write_file(path: str, content: str):
        """Overwrite an existing report after its current version was read."""
        executions.append("write")
        Path(path).write_text(content, encoding="utf-8")
        return "Written."

    async def aread_file(path: str, tool_call_id: Annotated[str, InjectedToolCallId]):
        return await asyncio.to_thread(read_file, path, tool_call_id)

    async def awrite_file(path: str, content: str):
        return await asyncio.to_thread(write_file, path, content)

    tools = [StructuredTool.from_function(read_file, coroutine=aread_file), StructuredTool.from_function(write_file, coroutine=awrite_file)]
    responses = iter(
        [
            AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": path}, "id": "read-current"}]),
            AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": path, "content": "Updated report"}, "id": "write-current"}]),
            AIMessage(content="Finished."),
        ]
    )
    gate = ReadBeforeWriteMiddleware(content_reader=lambda _runtime, path: Path(path).read_text(encoding="utf-8"))
    graph = create_agent(GateTestModel(messages=responses), tools=tools, middleware=[gate])
    history = [
        HumanMessage(content="Audit the report.", id="earlier-request"),
        AIMessage(content="", tool_calls=[{"name": "audit", "args": {}, "id": "audit-old"}], id="earlier-call"),
        previous,
        HumanMessage(content="Read the report, then update it.", id="current-request"),
    ]
    original_history = copy.deepcopy(history)
    initial = {"messages": history}
    result = graph.invoke(initial, context={"thread_id": "gate-test"}) if invocation == "invoke" else asyncio.run(graph.ainvoke(initial, context={"thread_id": "gate-test"}))
    successful = read_outcome == "success"
    assert executions == (["read", "write"] if successful else ["read"])
    assert target.read_text(encoding="utf-8") == ("Updated report" if successful else "Original report")
    messages = {message.tool_call_id: message for message in result["messages"] if isinstance(message, ToolMessage)}
    assert messages["audit-old"] == previous_snapshot
    if successful:
        assert messages["read-current"].additional_kwargs[READ_MARK_KEY] == {"path": path, "hash": hashlib.sha256(b"Original report").hexdigest()}
        assert messages["write-current"].status == "success"
    else:
        assert READ_MARK_KEY not in messages["read-current"].additional_kwargs
        assert messages["write-current"].status == "error"
        assert WRITE_BLOCK_KEY in messages["write-current"].additional_kwargs
    assert history == original_history
    if layout != "direct":
        command_messages = returned[0].update["messages"]
        historical = next(message for message in command_messages if message.tool_call_id == "audit-old")
        assert historical == previous_snapshot


@pytest.mark.parametrize("container", ["direct", "single", "list", "tuple"])
@pytest.mark.parametrize("matching", [True, False])
def test_read_mark_requires_matching_result_before_inspecting_file(container, matching):
    inspections = []

    def reader(_runtime, path):
        inspections.append(path)
        return "Report contents"

    gate = ReadBeforeWriteMiddleware(content_reader=reader)
    message = ToolMessage(content="Report contents", tool_call_id="read-current" if matching else "other-call", additional_kwargs={"keep": "metadata"})
    messages = message if container == "single" else [message] if container == "list" else (message,)
    result = message if container == "direct" else Command(update={"messages": messages, "other_state": "keep"}, goto="next")
    request = ToolCallRequest(tool_call={"name": "read_file", "args": {"path": "/report.md"}, "id": "read-current"}, tool=None, state={}, runtime=SimpleNamespace(context={"thread_id": "gate-test"}))
    actual = gate.wrap_tool_call(request, lambda _request: result)
    assert actual is result
    assert inspections == (["/report.md"] if matching else [])
    assert (READ_MARK_KEY in message.additional_kwargs) is matching
    assert message.additional_kwargs["keep"] == "metadata"
    if isinstance(result, Command):
        assert result.goto == "next"
        assert result.update["other_state"] == "keep"
