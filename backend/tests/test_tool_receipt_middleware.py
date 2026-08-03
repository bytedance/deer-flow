"""Tests for ToolReceiptMiddleware (stamping + context rendering)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_receipt import TOOL_RECEIPT_KEY
from deerflow.agents.middlewares.tool_receipt_middleware import ToolReceiptMiddleware
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY


def _request(tool_name: str = "bash") -> SimpleNamespace:
    return SimpleNamespace(tool_call={"name": tool_name, "id": f"tc-{tool_name}", "args": {"cmd": "ls"}})


def _result(request) -> ToolMessage:
    return ToolMessage(
        content="ok",
        tool_call_id=request.tool_call["id"],
        name=request.tool_call["name"],
        additional_kwargs={TOOL_META_KEY: {"status": "success"}},
    )


def _stamped_message() -> ToolMessage:
    message = ToolMessage(content="ok", tool_call_id="tc-1", name="bash")
    message.additional_kwargs = {
        TOOL_META_KEY: {"status": "success"},
        TOOL_RECEIPT_KEY: {
            "tool_call_id": "tc-1",
            "tool_name": "bash",
            "status": "success",
            "args_sha256": "a" * 16,
            "output_sha256": "b" * 16,
            "output_bytes": 2,
            "created_at": "2026-08-03T00:00:00+00:00",
        },
    }
    return message


def test_wrap_tool_call_stamps_receipt():
    middleware = ToolReceiptMiddleware()
    request = _request()
    result = middleware.wrap_tool_call(request, lambda req: _result(req))
    receipt = result.additional_kwargs[TOOL_RECEIPT_KEY]
    assert receipt["tool_name"] == "bash"
    assert receipt["status"] == "success"


def test_wrap_tool_call_stamps_matching_messages_in_command():
    middleware = ToolReceiptMiddleware()
    request = _request("task")
    matching = _result(request)
    unrelated = ToolMessage(content="other", tool_call_id="tc-other", name="other")
    command = Command(update={"messages": [unrelated, matching], "other_state": True})

    result = middleware.wrap_tool_call(request, lambda req: command)

    assert result is command
    assert TOOL_RECEIPT_KEY not in unrelated.additional_kwargs
    receipt = matching.additional_kwargs[TOOL_RECEIPT_KEY]
    assert receipt["tool_call_id"] == "tc-task"
    assert receipt["tool_name"] == "task"


def test_wrap_tool_call_failure_does_not_break_result():
    middleware = ToolReceiptMiddleware()
    request = SimpleNamespace(tool_call={"name": None, "id": None, "args": None})
    message = ToolMessage(content="ok", tool_call_id="x", name="x")
    assert middleware.wrap_tool_call(request, lambda req: message) is message


def test_wrap_model_call_injects_hidden_ledger():
    middleware = ToolReceiptMiddleware()
    request = MagicMock()
    request.messages = [HumanMessage(content="go"), AIMessage(content="hi"), _stamped_message()]
    request.override = lambda messages: SimpleNamespace(messages=messages)
    captured = {}

    def handler(req):
        captured["messages"] = req.messages
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    ledger_messages = [m for m in captured["messages"] if isinstance(m, HumanMessage) and m.additional_kwargs.get("hide_from_ui")]
    assert len(ledger_messages) == 1
    assert "r1" in ledger_messages[0].content and "bash" in ledger_messages[0].content


def test_wrap_model_call_no_receipts_no_injection():
    middleware = ToolReceiptMiddleware()
    request = MagicMock()
    request.messages = [HumanMessage(content="go")]
    seen = {}

    def handler(req):
        seen["request"] = req
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    assert seen["request"] is request  # untouched passthrough


def _build(app_config_dict: dict) -> list:
    from deerflow.agents.middlewares.tool_error_handling_middleware import _build_runtime_middlewares
    from deerflow.config.app_config import AppConfig

    app_config = AppConfig.model_validate(app_config_dict)
    return _build_runtime_middlewares(app_config=app_config, include_uploads=False, include_dangling_tool_call_patch=False)


def test_factory_registers_receipt_middleware_outer_of_error_handling():
    middlewares = _build({"sandbox": {"use": "test"}})
    names = [type(m).__name__ for m in middlewares]
    assert "ToolReceiptMiddleware" in names
    assert names.index("ToolReceiptMiddleware") < names.index("ToolErrorHandlingMiddleware")


def test_factory_omits_receipt_middleware_when_disabled():
    middlewares = _build({"sandbox": {"use": "test"}, "verification": {"receipts_enabled": False}})
    assert "ToolReceiptMiddleware" not in [type(m).__name__ for m in middlewares]
