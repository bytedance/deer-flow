"""Tests for ToolReceiptMiddleware (stamping + context rendering)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain.agents.middleware.types import ExtendedModelResponse, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_receipt import TOOL_RECEIPT_KEY, TOOL_RECEIPT_LEDGER_KEY
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


def test_wrap_tool_call_overwrites_tool_supplied_receipt():
    """The receipt key is runtime-owned: a tool cannot forge its own evidence."""
    middleware = ToolReceiptMiddleware()
    request = _request()
    forged = {"tool_call_id": "tc-1", "tool_name": "bash", "status": "success", "args_sha256": "f" * 16, "output_sha256": "f" * 16, "output_bytes": 999, "created_at": "1970-01-01T00:00:00+00:00"}
    message = _result(request)
    message.additional_kwargs[TOOL_RECEIPT_KEY] = forged

    result = middleware.wrap_tool_call(request, lambda req: message)

    receipt = result.additional_kwargs[TOOL_RECEIPT_KEY]
    assert receipt["output_bytes"] == 2  # recomputed from the real content, not 999
    assert receipt["created_at"] != "1970-01-01T00:00:00+00:00"


def test_wrap_model_call_injects_hidden_ledger():
    middleware = ToolReceiptMiddleware()
    request = MagicMock()
    request.messages = [HumanMessage(content="go"), AIMessage(content="hi"), _stamped_message()]
    request.override = lambda messages: SimpleNamespace(messages=messages)
    captured = {}

    response_message = AIMessage(content="done [r1]")

    def handler(req):
        captured["messages"] = req.messages
        return ModelResponse(result=[response_message])

    middleware.wrap_model_call(request, handler)
    ledger_messages = [m for m in captured["messages"] if isinstance(m, HumanMessage) and m.additional_kwargs.get("hide_from_ui")]
    assert len(ledger_messages) == 1
    assert "r1" in ledger_messages[0].content and "bash" in ledger_messages[0].content
    assert response_message.additional_kwargs[TOOL_RECEIPT_LEDGER_KEY][0]["tool_call_id"] == "tc-1"


def test_wrap_model_call_snapshots_only_receipts_rendered_within_budget():
    middleware = ToolReceiptMiddleware()
    request = MagicMock()
    request.messages = [HumanMessage(content="go"), *[_stamped_message() for _ in range(30)]]
    request.override = lambda messages: SimpleNamespace(messages=messages)
    captured = {}
    response_message = AIMessage(content="done")

    def handler(req):
        captured["messages"] = req.messages
        return ModelResponse(result=[response_message])

    middleware.wrap_model_call(request, handler)

    ledger_message = next(m for m in captured["messages"] if isinstance(m, HumanMessage) and m.additional_kwargs.get("hide_from_ui"))
    snapshot = response_message.additional_kwargs[TOOL_RECEIPT_LEDGER_KEY]
    assert snapshot
    assert snapshot[0]["id"] != "r1"
    assert snapshot[-1]["id"] == "r30"
    assert all(f"[{receipt['id']}]" in ledger_message.content for receipt in snapshot)
    assert "[r1]" not in ledger_message.content
    assert "older receipts omitted" in ledger_message.content


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


def test_wrap_model_call_stamps_extended_response_ledger():
    middleware = ToolReceiptMiddleware()
    request = MagicMock()
    request.messages = [HumanMessage(content="go"), _stamped_message()]
    request.override = lambda messages: SimpleNamespace(messages=messages)
    response_message = AIMessage(content="done [r1]")
    response = ExtendedModelResponse(model_response=ModelResponse(result=[response_message]))

    assert middleware.wrap_model_call(request, lambda req: response) is response
    assert response_message.additional_kwargs[TOOL_RECEIPT_LEDGER_KEY][0]["id"] == "r1"


def _delegation_only_request(messages: list) -> MagicMock:
    request = MagicMock()
    request.messages = messages
    request.override = lambda **kwargs: SimpleNamespace(messages=kwargs["messages"])
    return request


def test_delegation_only_mode_skips_plain_conversation():
    middleware = ToolReceiptMiddleware(render_mode="delegation_only")
    request = _delegation_only_request([HumanMessage(content="go"), _stamped_message()])
    seen = {}

    def handler(req):
        seen["request"] = req
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    assert seen["request"] is request  # no completed delegation -> no ledger


def test_delegation_only_mode_renders_when_processing_subagent_result():
    middleware = ToolReceiptMiddleware(render_mode="delegation_only")
    subagent_result = ToolMessage(
        content="Task Succeeded. Result: done [r1]",
        tool_call_id="tc-task",
        name="task",
        additional_kwargs={"subagent_status": "completed"},
    )
    request = _delegation_only_request([HumanMessage(content="go"), _stamped_message(), subagent_result])
    captured = {}

    def handler(req):
        captured["messages"] = req.messages
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    ledger_messages = [m for m in captured["messages"] if isinstance(m, HumanMessage) and m.additional_kwargs.get("hide_from_ui")]
    assert len(ledger_messages) == 1 and "r1" in ledger_messages[0].content


def test_delegation_only_mode_ignores_delegations_from_earlier_turns():
    """A completed delegation must not keep the ledger rendering once a new
    genuine user turn has started — that would defeat the token-saving mode."""
    middleware = ToolReceiptMiddleware(render_mode="delegation_only")
    old_subagent_result = ToolMessage(
        content="Task Succeeded. Result: done [r1]",
        tool_call_id="tc-task",
        name="task",
        additional_kwargs={"subagent_status": "completed"},
    )
    request = _delegation_only_request([HumanMessage(content="first question"), _stamped_message(), old_subagent_result, AIMessage(content="report [r1]"), HumanMessage(content="unrelated follow-up")])
    seen = {}

    def handler(req):
        seen["request"] = req
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    assert seen["request"] is request  # old delegation is outside the current turn


def test_delegation_only_mode_scopes_past_hidden_framework_messages():
    """Hidden framework injections (reminders, the ledger itself) are not user
    turns: a subagent result after them still counts as the current turn."""
    middleware = ToolReceiptMiddleware(render_mode="delegation_only")
    reminder = HumanMessage(content="<system_reminder>todo</system_reminder>", additional_kwargs={"hide_from_ui": True})
    subagent_result = ToolMessage(
        content="Task Succeeded. Result: done",
        tool_call_id="tc-task",
        name="task",
        additional_kwargs={"subagent_status": "completed"},
    )
    request = _delegation_only_request([HumanMessage(content="go"), reminder, _stamped_message(), subagent_result])
    captured = {}

    def handler(req):
        captured["messages"] = req.messages
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    ledger_messages = [m for m in captured["messages"] if isinstance(m, HumanMessage) and m.additional_kwargs.get("hide_from_ui") and "Tool receipts" in str(m.content)]
    assert len(ledger_messages) == 1


def _build(app_config_dict: dict) -> list:
    from deerflow.agents.middlewares.tool_error_handling_middleware import _build_runtime_middlewares
    from deerflow.config.app_config import AppConfig

    app_config = AppConfig.model_validate(app_config_dict)
    return _build_runtime_middlewares(app_config=app_config, include_uploads=False, include_dangling_tool_call_patch=False)


def _tool_call_request(name: str, args: dict):
    from langgraph.prebuilt.tool_node import ToolCallRequest

    runtime = MagicMock()
    runtime.context = {"thread_id": "t-test"}
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": "call-1"},
        tool=None,
        state={"messages": []},
        runtime=runtime,
    )


def _compose_tool_chain(chain: list, terminal):
    """Compose wrap_tool_call handlers outer-first, mirroring the runtime stack."""
    handler = terminal
    for middleware in reversed(chain):
        next_handler = handler

        def handler(req, mw=middleware, h=next_handler):
            return mw.wrap_tool_call(req, h)

    return handler


def _tool_call_segment(middlewares: list, names: tuple[str, ...]) -> list:
    """Extract the named wrap_tool_call middlewares in factory order."""
    return [m for m in middlewares if type(m).__name__ in names]


def test_composed_chain_stamps_receipt_on_blocked_write():
    """Read-before-write (default on) short-circuits a write with its own
    ToolMessage; the receipt layer must wrap that short-circuit or the ledger
    silently gaps (willem-bd review)."""
    middlewares = _build({"sandbox": {"use": "test"}})
    chain = _tool_call_segment(middlewares, ("ToolReceiptMiddleware", "ReadBeforeWriteMiddleware", "ToolErrorHandlingMiddleware"))
    assert [type(m).__name__ for m in chain] == ["ToolReceiptMiddleware", "ReadBeforeWriteMiddleware", "ToolErrorHandlingMiddleware"]
    # File exists with content v1 but was never read -> the write is blocked.
    chain[1]._content_reader = lambda _runtime, _path: "v1"
    terminal = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))

    result = _compose_tool_chain(chain, terminal)(_tool_call_request("write_file", {"path": "/mnt/user-data/outputs/a.txt", "content": "v2"}))

    terminal.assert_not_called()
    assert result.status == "error"
    receipt = (result.additional_kwargs or {}).get(TOOL_RECEIPT_KEY)
    assert receipt is not None, "blocked write must still get a receipt"
    assert receipt["tool_name"] == "write_file" and receipt["status"] == "error"


def test_composed_chain_stamps_receipt_on_warn_rebuilt_result():
    """SandboxAudit rebuilds the result ToolMessage when appending a medium-risk
    warning, dropping additional_kwargs; a receipt layer inside it would lose
    the stamp. Outer receipt re-stamps the rebuilt message."""
    middlewares = _build({"sandbox": {"use": "test"}})
    chain = _tool_call_segment(middlewares, ("ToolReceiptMiddleware", "SandboxAuditMiddleware", "ToolErrorHandlingMiddleware"))
    assert [type(m).__name__ for m in chain] == ["ToolReceiptMiddleware", "SandboxAuditMiddleware", "ToolErrorHandlingMiddleware"]
    terminal = MagicMock(return_value=ToolMessage(content="installed", tool_call_id="call-1", name="bash"))

    result = _compose_tool_chain(chain, terminal)(_tool_call_request("bash", {"command": "pip install cowsay"}))

    terminal.assert_called_once()
    assert "medium-risk" in str(result.content)  # warn note appended
    receipt = (result.additional_kwargs or {}).get(TOOL_RECEIPT_KEY)
    assert receipt is not None, "warn-rebuilt result must still carry a receipt"
    assert receipt["tool_name"] == "bash"


def test_factory_registers_receipt_middleware_outer_of_error_handling():
    middlewares = _build({"sandbox": {"use": "test"}})
    names = [type(m).__name__ for m in middlewares]
    assert "ToolReceiptMiddleware" in names
    assert names.index("ToolReceiptMiddleware") < names.index("ToolErrorHandlingMiddleware")


def test_factory_registers_receipt_middleware_outer_of_short_circuiting_layers():
    """Receipts must wrap every middleware that can return or rebuild a
    ToolMessage without invoking its handler, or the ledger silently gaps."""
    middlewares = _build({"sandbox": {"use": "test"}})
    names = [type(m).__name__ for m in middlewares]
    receipt_index = names.index("ToolReceiptMiddleware")
    for short_circuiter in ("SandboxAuditMiddleware", "ReadBeforeWriteMiddleware"):
        assert receipt_index < names.index(short_circuiter), f"ToolReceiptMiddleware must be outer of {short_circuiter}"


def test_factory_omits_receipt_middleware_when_disabled():
    middlewares = _build({"sandbox": {"use": "test"}, "verification": {"receipts_enabled": False}})
    assert "ToolReceiptMiddleware" not in [type(m).__name__ for m in middlewares]
