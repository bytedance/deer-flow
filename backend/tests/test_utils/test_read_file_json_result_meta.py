"""File contents are not a JSON error envelope from the read_file tool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware
from deerflow.agents.middlewares.tool_receipt import TOOL_RECEIPT_KEY
from deerflow.agents.middlewares.tool_receipt_middleware import ToolReceiptMiddleware
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY, normalize_tool_message
from deerflow.agents.thread_state import ThreadState
from deerflow.config.tool_progress_config import ToolProgressConfig


@pytest.mark.parametrize("error", ["Unauthorized", {"code": 401, "message": "Unauthorized"}, ["missing config"], 500, True, "no results found"])
def test_read_file_json_error_field_is_document_data(error):
    content = json.dumps({"error": error})
    message = ToolMessage(content=content, name="read_file", tool_call_id="read")

    result = normalize_tool_message(message)

    assert result.content == content
    assert result.additional_kwargs[TOOL_META_KEY] == {
        "status": "success",
        "error_type": None,
        "recoverable_by_model": True,
        "recommended_next_action": "continue",
        "source": "content_analysis",
    }


@pytest.mark.parametrize("name,status", [("read_file", "error"), ("web_search", "success"), ("custom_tool", "success")])
def test_actual_tool_json_errors_are_still_classified(name, status):
    message = ToolMessage(content='{"error": {"code": 401, "message": "Unauthorized"}}', name=name, tool_call_id="call", status=status)

    meta = normalize_tool_message(message).additional_kwargs[TOOL_META_KEY]

    assert meta["status"] == "error"
    assert meta["error_type"] == "auth"
    assert meta["recoverable_by_model"] is False
    assert meta["recommended_next_action"] == "stop"


@pytest.mark.parametrize("source", ["exception", "tool_return", "custom"])
def test_read_file_preserves_explicit_failure_metadata(source):
    metadata = {"status": "error", "source": source, "error_type": "auth"}
    message = ToolMessage(content='{"error":"Unauthorized"}', name="read_file", tool_call_id="read", additional_kwargs={TOOL_META_KEY: metadata})

    assert normalize_tool_message(message).additional_kwargs[TOOL_META_KEY] is metadata


class _ScriptedModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("progress_enabled", [False, True])
@pytest.mark.parametrize("first_kind", ["json_error", "success", "missing", "truncated"])
@pytest.mark.asyncio
async def test_native_read_file_keeps_followup_reads_available(tmp_path, monkeypatch, mode, progress_enabled, first_kind):
    from deerflow.sandbox import tools as sandbox_tools
    from deerflow.sandbox.local.local_sandbox import LocalSandbox

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    first_content = '{"error": {"code": 401, "message": "Unauthorized"}}\n'
    if first_kind == "success":
        first_content = '{"result": "OK"}\n'
    elif first_kind == "truncated":
        first_content = json.dumps({"error": "Unauthorized", "details": "sample line\n" * 10000})
    if first_kind != "missing":
        (outputs / "response.json").write_text(first_content, encoding="utf-8")
    notes = "The saved response belongs to an earlier request.\n"
    (outputs / "notes.txt").write_text(notes, encoding="utf-8")

    sandbox = LocalSandbox("json-result-test")
    reads = []
    original_read = sandbox.read_file

    def trace_read(path, *args, **kwargs):
        reads.append(path)
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(sandbox, "read_file", trace_read)
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda *_args, **_kwargs: sandbox)
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized_async", AsyncMock(return_value=sandbox))
    responses = [AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": f"/mnt/user-data/outputs/{filename}"}, "id": f"read-{index}"}]) for index, filename in enumerate(("response.json", "notes.txt"))]
    responses.append(AIMessage(content="Done."))
    middleware = [ToolReceiptMiddleware(render_mode="delegation_only"), ReadBeforeWriteMiddleware()]
    if progress_enabled:
        middleware.append(ToolProgressMiddleware.from_config(ToolProgressConfig(enabled=True)))
    middleware.append(ToolErrorHandlingMiddleware())
    graph = create_agent(_ScriptedModel(messages=iter(responses)), tools=[sandbox_tools.read_file_tool], middleware=middleware, state_schema=ThreadState)
    state = {
        "messages": [HumanMessage(content="Read the saved API response and then the notes explaining it.")],
        "sandbox": {"sandbox_id": "local:json-result-test"},
        "thread_data": {"outputs_path": str(outputs)},
        "thread_directories_created": True,
    }
    context = {"thread_id": "json-result-test", "user_id": "default"}
    result = graph.invoke(state, context=context) if mode == "sync" else await graph.ainvoke(state, context=context)
    first, second = [message for message in result["messages"] if isinstance(message, ToolMessage)]

    assert second.content == notes
    assert str(outputs / "notes.txt") in reads
    assert second.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == "success"
    expected_status = {"missing": "error", "truncated": "partial_success"}.get(first_kind, "success")
    assert first.additional_kwargs[TOOL_META_KEY]["status"] == expected_status
    assert first.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == expected_status
    if first_kind == "missing":
        assert first.content.startswith("Error: File not found:")
        assert first.additional_kwargs[TOOL_META_KEY]["error_type"] == "not_found"
    elif first_kind == "truncated":
        assert len(first.content) < len(first_content)
        assert "truncated" in first.content.lower()
    else:
        assert first.content == first_content
