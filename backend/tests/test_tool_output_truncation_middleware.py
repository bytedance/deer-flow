from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_output_truncation_middleware import ToolOutputTruncationMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig


def _request(name: str = "remote_executor", tool_call_id: str = "tc-1"):
    return SimpleNamespace(tool_call={"name": name, "id": tool_call_id})


def test_tool_message_over_limit_is_truncated_with_standard_hint():
    middleware = ToolOutputTruncationMiddleware(max_bytes=10)
    message = ToolMessage(content="a" * 200, tool_call_id="tc-1", name="remote_executor")

    result = middleware.wrap_tool_call(_request(), lambda _req: message)

    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "tc-1"
    assert result.name == "remote_executor"
    assert result.status == "success"
    assert result.text.startswith("[输出已截断，共200字节] 请使用过滤条件缩小查询范围\n")
    assert result.text.endswith("a" * 10)
    assert len(result.text.encode("utf-8")) < len(message.text.encode("utf-8"))


def test_tool_message_under_limit_is_preserved():
    middleware = ToolOutputTruncationMiddleware(max_bytes=50)
    message = ToolMessage(content="small output", tool_call_id="tc-1", name="remote_executor")

    result = middleware.wrap_tool_call(_request(), lambda _req: message)

    assert result is message


def test_zero_limit_disables_truncation():
    middleware = ToolOutputTruncationMiddleware(max_bytes=0)
    message = ToolMessage(content="a" * 100, tool_call_id="tc-1", name="remote_executor")

    result = middleware.wrap_tool_call(_request(), lambda _req: message)

    assert result is message


def test_truncation_respects_utf8_boundaries():
    middleware = ToolOutputTruncationMiddleware(max_bytes=5)
    message = ToolMessage(content="你好世界", tool_call_id="tc-1", name="remote_executor")

    result = middleware.wrap_tool_call(_request(), lambda _req: message)

    assert isinstance(result, ToolMessage)
    assert result.text.startswith("[输出已截断，共12字节] 请使用过滤条件缩小查询范围\n")
    assert result.text.endswith("你")


def test_command_update_messages_are_truncated():
    middleware = ToolOutputTruncationMiddleware(max_bytes=12)
    tool_message = ToolMessage(content="x" * 40, tool_call_id="tc-1", name="present_files")
    command = Command(update={"messages": [tool_message], "artifacts": ["/mnt/user-data/outputs/report.md"]})

    result = middleware.wrap_tool_call(_request(name="present_files"), lambda _req: command)

    assert isinstance(result, Command)
    assert result is not command
    assert result.update["artifacts"] == ["/mnt/user-data/outputs/report.md"]
    new_message = result.update["messages"][0]
    assert isinstance(new_message, ToolMessage)
    assert new_message.text.startswith("[输出已截断，共40字节] 请使用过滤条件缩小查询范围\n")
    assert new_message.text.endswith("x" * 12)


def test_model_request_history_tool_messages_are_truncated():
    middleware = ToolOutputTruncationMiddleware(max_bytes=15)
    oversized = ToolMessage(content="h" * 60, tool_call_id="tc-history", name="remote_executor")
    request = ModelRequest(model=None, messages=[oversized], tools=[], state={})
    captured: dict[str, ModelRequest] = {}

    def handler(req):
        captured["request"] = req
        return []

    middleware.wrap_model_call(request, handler)

    forwarded = captured["request"]
    assert forwarded is not request
    new_message = forwarded.messages[0]
    assert isinstance(new_message, ToolMessage)
    assert new_message.text.startswith("[输出已截断，共60字节] 请使用过滤条件缩小查询范围\n")
    assert new_message.text.endswith("h" * 15)


def test_from_config_uses_tool_output_limit():
    config = AppConfig(
        sandbox=SandboxConfig(use="test"),
        tool_output={"max_bytes": 123},
    )

    middleware = ToolOutputTruncationMiddleware.from_config(config)

    assert middleware.max_bytes == 123


@pytest.mark.anyio
async def test_async_tool_message_over_limit_is_truncated():
    middleware = ToolOutputTruncationMiddleware(max_bytes=8)
    message = ToolMessage(content="z" * 20, tool_call_id="tc-async", name="remote_executor")

    async def handler(_request):
        return message

    result = await middleware.awrap_tool_call(_request(tool_call_id="tc-async"), handler)

    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "tc-async"
    assert result.text.startswith("[输出已截断，共20字节] 请使用过滤条件缩小查询范围\n")
    assert result.text.endswith("z" * 8)


@pytest.mark.anyio
async def test_async_model_request_history_tool_messages_are_truncated():
    middleware = ToolOutputTruncationMiddleware(max_bytes=6)
    oversized = ToolMessage(content="q" * 30, tool_call_id="tc-history", name="remote_executor")
    request = ModelRequest(model=None, messages=[oversized], tools=[], state={})
    captured: dict[str, ModelRequest] = {}

    async def handler(req):
        captured["request"] = req
        return []

    await middleware.awrap_model_call(request, handler)

    new_message = captured["request"].messages[0]
    assert isinstance(new_message, ToolMessage)
    assert new_message.text.startswith("[输出已截断，共30字节] 请使用过滤条件缩小查询范围\n")
    assert new_message.text.endswith("q" * 6)
