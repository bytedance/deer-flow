"""JSON depth limits must not replace successful native tool results."""

import json
from unittest.mock import AsyncMock, Mock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares import tool_result_meta as meta
from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.agents.middlewares.tool_receipt import TOOL_RECEIPT_KEY
from deerflow.agents.middlewares.tool_receipt_middleware import ToolReceiptMiddleware
from deerflow.agents.thread_state import ThreadState


@pytest.mark.parametrize("status", ["success", "error"])
def test_json_depth_limit_preserves_result(monkeypatch, status):
    content = '{"records": [[[0]]], "user_id": 401}'
    loads = Mock(side_effect=RecursionError("parser depth limit"))
    monkeypatch.setattr(meta.json, "loads", loads)
    message = ToolMessage(content=content, name="custom_tool", tool_call_id="depth", status=status)

    result = meta.normalize_tool_message(message)

    assert result is message
    assert result.content == content
    assert result.tool_call_id == "depth"
    assert result.status == status
    assert result.additional_kwargs[meta.TOOL_META_KEY] == {
        "status": status,
        "error_type": "unknown" if status == "error" else None,
        "recoverable_by_model": True,
        "recommended_next_action": "try_alternative" if status == "error" else "continue",
        "source": "tool_return" if status == "error" else "content_analysis",
    }
    assert loads.call_count == (2 if status == "error" else 1)


def test_second_json_probe_depth_limit_is_unknown(monkeypatch):
    loads = Mock(side_effect=[{}, RecursionError("parser depth limit")])
    monkeypatch.setattr(meta.json, "loads", loads)
    message = ToolMessage(content='{"user_id": 401}', tool_call_id="depth", status="error")

    result = meta.normalize_tool_message(message)

    assert loads.call_count == 2
    assert result.status == "error"
    assert result.additional_kwargs[meta.TOOL_META_KEY]["error_type"] == "unknown"
    assert result.additional_kwargs[meta.TOOL_META_KEY]["recommended_next_action"] == "try_alternative"


def test_producer_metadata_bypasses_depth_analysis(monkeypatch):
    loads = Mock(side_effect=RecursionError("parser depth limit"))
    monkeypatch.setattr(meta.json, "loads", loads)
    stamp = {"status": "error", "error_type": "auth", "source": "tool_return"}
    message = ToolMessage(content="[0]", tool_call_id="depth", additional_kwargs={meta.TOOL_META_KEY: stamp})

    assert meta.normalize_tool_message(message).additional_kwargs[meta.TOOL_META_KEY] is stamp
    loads.assert_not_called()


@pytest.mark.parametrize("name,expected", [("custom_tool", "error"), ("read_file", "success")])
def test_shallow_error_envelope_classification(name, expected):
    message = ToolMessage(content='{"error": {"code": 401}}', name=name, tool_call_id="shallow")
    result = meta.normalize_tool_message(message)
    assert result.additional_kwargs[meta.TOOL_META_KEY]["status"] == expected
    assert result.additional_kwargs[meta.TOOL_META_KEY]["error_type"] == ("auth" if expected == "error" else None)


class _ScriptedModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("depth", [10, 10000])
@pytest.mark.asyncio
async def test_native_read_file_graph_preserves_deep_json(tmp_path, monkeypatch, mode, depth):
    from deerflow.sandbox import tools as sandbox_tools
    from deerflow.sandbox.local.local_sandbox import LocalSandbox

    # String construction avoids recursive Python fixtures. Count the deep case
    # as regression coverage only when the real parser rejects this fixture.
    content = "[" * depth + "0" + "]" * depth
    if depth > 10:
        try:
            json.loads(content)
        except RecursionError:
            pass
        else:
            pytest.skip(f"json.loads accepts {depth} nested arrays; parser depth limit is not exercised")
    path = tmp_path / "nested.json"
    path.write_text(content, encoding="utf-8")
    sandbox = LocalSandbox("json-depth-test")
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda *_args, **_kwargs: sandbox)
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized_async", AsyncMock(return_value=sandbox))
    responses = [AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": str(path)}, "id": "read-depth"}]), AIMessage(content="Done.")]
    graph = create_agent(
        _ScriptedModel(messages=iter(responses)),
        tools=[sandbox_tools.read_file_tool],
        middleware=[ToolReceiptMiddleware(render_mode="delegation_only"), ToolErrorHandlingMiddleware()],
        state_schema=ThreadState,
    )
    state = {
        "messages": [HumanMessage(content="Read the JSON file.")],
        "sandbox": {"sandbox_id": "json-depth-test"},
        "thread_data": {"outputs_path": str(tmp_path)},
        "thread_directories_created": True,
    }
    context = {"thread_id": "json-depth-test", "user_id": "default"}
    result = graph.invoke(state, context=context) if mode == "sync" else await graph.ainvoke(state, context=context)
    message = next(message for message in result["messages"] if isinstance(message, ToolMessage))
    assert message.content == content
    assert message.tool_call_id == "read-depth"
    assert message.status == "success"
    assert message.additional_kwargs[meta.TOOL_META_KEY]["status"] == "success"
    assert message.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == "success"
    assert result["messages"][-1].content == "Done."
