"""Regression coverage for ToolMessages returned inside LangGraph Commands.

Several built-in tools return ``Command(update={"messages": [...]})`` rather
than a bare ``ToolMessage``.  Those messages must receive the same metadata,
progress accounting, and receipts as direct tool results.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from _agent_e2e_helpers import build_single_tool_call_model
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

from deerflow.agents.middlewares.tool_error_handling_middleware import (
    ToolErrorHandlingMiddleware,
    build_lead_runtime_middlewares,
)
from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware
from deerflow.agents.middlewares.tool_receipt import TOOL_RECEIPT_KEY
from deerflow.agents.middlewares.tool_receipt_middleware import ToolReceiptMiddleware
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY, normalize_tool_result
from deerflow.config.app_config import AppConfig
from deerflow.tools.builtins.setup_agent_tool import setup_agent
from deerflow.tools.builtins.view_image_tool import view_image_tool


def _request(tool_name: str = "command_tool", tool_call_id: str = "tc-command") -> SimpleNamespace:
    runtime = SimpleNamespace(
        context={"thread_id": "thread-command", "run_id": "run-command"},
        tool_call_id=tool_call_id,
    )
    return SimpleNamespace(
        tool_call={"name": tool_name, "id": tool_call_id, "args": {}},
        runtime=runtime,
    )


def _command_result(
    content: str,
    *,
    status: str = "success",
    meta: dict[str, object] | None = None,
) -> tuple[Command, ToolMessage]:
    additional_kwargs = {TOOL_META_KEY: dict(meta)} if meta is not None else {}
    message = ToolMessage(
        content=content,
        tool_call_id="tc-command",
        name="command_tool",
        status=status,
        additional_kwargs=additional_kwargs,
    )
    command = Command(
        update={"messages": [message], "preserved_state": "keep-me"},
        goto="next_node",
    )
    return command, message


def _recoverable_error_meta() -> dict[str, object]:
    return {
        "status": "error",
        "error_type": "no_results",
        "recoverable_by_model": True,
        "recommended_next_action": "rewrite_query",
        "source": "tool_return",
    }


def _success_meta() -> dict[str, object]:
    return {
        "status": "success",
        "error_type": None,
        "recoverable_by_model": True,
        "recommended_next_action": "continue",
        "source": "content_analysis",
    }


def _capture_model_messages(
    middleware: ToolProgressMiddleware,
    runtime: SimpleNamespace,
) -> list:
    request = MagicMock()
    request.messages = []
    request.runtime = runtime
    request.override = lambda **kwargs: SimpleNamespace(
        messages=kwargs["messages"],
        runtime=runtime,
    )
    captured: list = []

    def handler(current_request: SimpleNamespace) -> MagicMock:
        captured.extend(current_request.messages)
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    return captured


async def _capture_model_messages_async(
    middleware: ToolProgressMiddleware,
    runtime: SimpleNamespace,
) -> list:
    request = MagicMock()
    request.messages = []
    request.runtime = runtime
    request.override = lambda **kwargs: SimpleNamespace(
        messages=kwargs["messages"],
        runtime=runtime,
    )
    captured: list = []

    async def handler(current_request: SimpleNamespace) -> MagicMock:
        captured.extend(current_request.messages)
        return MagicMock()

    await middleware.awrap_model_call(request, handler)
    return captured


def _real_command_error_message(
    *,
    tool,
    tool_name: str,
    tool_args: dict[str, object],
) -> ToolMessage:
    """Run a real Command-returning tool through production-built middleware."""
    from langchain.agents import create_agent

    app_config = AppConfig.model_validate(
        {
            "sandbox": {"use": "test"},
            "tool_progress": {
                "enabled": True,
                "stagnation_threshold": 2,
                "warn_escalation_count": 1,
            },
        }
    )
    middleware = build_lead_runtime_middlewares(app_config=app_config)
    model = build_single_tool_call_model(
        tool_name=tool_name,
        tool_args=tool_args,
        tool_call_id=f"tc-real-{tool_name}",
    )
    graph = create_agent(
        model=model,
        tools=[tool],
        middleware=middleware,
    )

    thread_id = f"thread-real-{tool_name}"
    runtime = Runtime(
        context={"thread_id": thread_id, "run_id": f"run-real-{tool_name}"},
        store=None,
    )
    config = {
        "configurable": {
            "thread_id": thread_id,
            "__pregel_runtime": runtime,
        },
        "recursion_limit": 20,
    }
    result = graph.invoke(
        {"messages": [HumanMessage(content=f"Call {tool_name}")]},
        config=config,
    )
    return next(message for message in result["messages"] if isinstance(message, ToolMessage) and message.tool_call_id == f"tc-real-{tool_name}")


_REAL_COMMAND_ERROR_CASES = [
    pytest.param(
        setup_agent,
        "setup_agent",
        {"soul": "   ", "description": "demo"},
        id="setup-agent",
    ),
    pytest.param(
        view_image_tool,
        "view_image",
        {"image_path": "/outside/image.png"},
        id="view-image",
    ),
]


@pytest.mark.parametrize(
    ("content", "expected_status"),
    [
        ("Agent created successfully", "success"),
        ("Error: no results found", "error"),
        ("Partial results; additional sources were unavailable", "partial_success"),
    ],
    ids=("success", "error-prefix", "partial-success"),
)
def test_normalize_tool_result_normalizes_messages_inside_command(
    content: str,
    expected_status: str,
) -> None:
    command, message = _command_result(content)

    result = normalize_tool_result(command)

    assert result is command
    assert command.update["preserved_state"] == "keep-me"
    assert message.additional_kwargs[TOOL_META_KEY]["status"] == expected_status


def test_normalize_command_preserves_existing_partial_success_meta() -> None:
    command, message = _command_result(
        "Tool-specific partial result",
        meta={
            "status": "partial_success",
            "error_type": "provider_limit",
            "recoverable_by_model": False,
            "recommended_next_action": "summarize",
            "source": "tool_return",
        },
    )
    existing_meta = message.additional_kwargs[TOOL_META_KEY]

    result = normalize_tool_result(command)

    assert result is command
    assert message.additional_kwargs[TOOL_META_KEY] is existing_meta


def test_sync_tool_error_middleware_normalizes_command_message() -> None:
    middleware = ToolErrorHandlingMiddleware()
    request = _request()
    command, message = _command_result("Error: no results found")

    result = middleware.wrap_tool_call(request, lambda _request: command)

    assert result is command
    assert message.additional_kwargs.get(TOOL_META_KEY, {}).get("status") == "error"


@pytest.mark.anyio
async def test_async_tool_error_middleware_normalizes_command_message() -> None:
    middleware = ToolErrorHandlingMiddleware()
    request = _request()
    command, message = _command_result("Error: no results found")

    result = await middleware.awrap_tool_call(request, AsyncMock(return_value=command))

    assert result is command
    assert message.additional_kwargs.get(TOOL_META_KEY, {}).get("status") == "error"


def test_direct_tool_message_control_gets_error_meta_and_receipt() -> None:
    """The same middleware contract already works for an unwrapped result."""
    request = _request()
    message = ToolMessage(
        content="Error: no results found",
        tool_call_id="tc-command",
        name="command_tool",
    )
    error_middleware = ToolErrorHandlingMiddleware()
    receipt_middleware = ToolReceiptMiddleware()

    result = receipt_middleware.wrap_tool_call(
        request,
        lambda current_request: error_middleware.wrap_tool_call(
            current_request,
            lambda _request: message,
        ),
    )

    assert result is message
    assert message.additional_kwargs[TOOL_META_KEY]["status"] == "error"
    assert message.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == "error"


@pytest.mark.anyio
async def test_async_receipt_chain_stamps_only_matching_command_error() -> None:
    request = _request()
    unrelated = ToolMessage(
        content="Error: unrelated tool failed",
        tool_call_id="tc-unrelated",
        name="unrelated_tool",
    )
    command, matching = _command_result("Error: no results found")
    command.update["messages"] = [unrelated, matching]
    error_middleware = ToolErrorHandlingMiddleware()
    receipt_middleware = ToolReceiptMiddleware()

    async def run_error_middleware(current_request: SimpleNamespace) -> Command:
        return await error_middleware.awrap_tool_call(
            current_request,
            AsyncMock(return_value=command),
        )

    result = await receipt_middleware.awrap_tool_call(
        request,
        run_error_middleware,
    )

    assert result is command
    assert TOOL_META_KEY not in unrelated.additional_kwargs
    assert TOOL_RECEIPT_KEY not in unrelated.additional_kwargs
    assert matching.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == "error"


@pytest.mark.parametrize(
    ("unrelated_meta", "matching_meta", "expects_hint"),
    [
        (_success_meta(), _recoverable_error_meta(), True),
        (_recoverable_error_meta(), _success_meta(), False),
    ],
    ids=("matching-error", "unrelated-error"),
)
def test_progress_uses_matching_tool_message_inside_command(
    unrelated_meta: dict[str, object],
    matching_meta: dict[str, object],
    expects_hint: bool,
) -> None:
    middleware = ToolProgressMiddleware(
        stagnation_threshold=1,
        warn_escalation_count=1,
        inject_assessment=True,
    )
    request = _request()
    unrelated = ToolMessage(
        content=("Error: unrelated tool failed" if unrelated_meta["status"] == "error" else "Unrelated tool succeeded with useful output"),
        tool_call_id="tc-unrelated",
        name="unrelated_tool",
        status=str(unrelated_meta["status"]),
        additional_kwargs={TOOL_META_KEY: unrelated_meta},
    )
    command, matching = _command_result(
        ("Error: no results found" if matching_meta["status"] == "error" else "Current tool succeeded with useful output"),
        status=str(matching_meta["status"]),
        meta=matching_meta,
    )
    command.update["messages"] = [unrelated, matching]

    result = middleware.wrap_tool_call(request, lambda _request: command)

    assert result is command
    captured = _capture_model_messages(middleware, request.runtime)
    has_hint = any(isinstance(message, HumanMessage) and "PROGRESS HINT" in str(message.content) for message in captured)
    assert has_hint is expects_hint


@pytest.mark.parametrize("command_wrapped", [False, True], ids=("direct-control", "command"))
def test_sync_tool_progress_injects_hint_for_repeated_errors(
    command_wrapped: bool,
) -> None:
    middleware = ToolProgressMiddleware(
        stagnation_threshold=2,
        warn_escalation_count=1,
        inject_assessment=True,
    )
    request = _request()

    for _ in range(2):
        command, message = _command_result(
            "Error: no results found",
            status="error",
            meta=_recoverable_error_meta(),
        )
        result = command if command_wrapped else message
        assert (
            middleware.wrap_tool_call(
                request,
                lambda _request, current_result=result: current_result,
            )
            is result
        )

    captured = _capture_model_messages(middleware, request.runtime)
    assert any(isinstance(message, HumanMessage) and "PROGRESS HINT" in str(message.content) for message in captured)


@pytest.mark.anyio
@pytest.mark.parametrize("command_wrapped", [False, True], ids=("direct-control", "command"))
async def test_async_tool_progress_injects_hint_for_repeated_errors(
    command_wrapped: bool,
) -> None:
    middleware = ToolProgressMiddleware(
        stagnation_threshold=2,
        warn_escalation_count=1,
        inject_assessment=True,
    )
    request = _request()

    for _ in range(2):
        command, message = _command_result(
            "Error: no results found",
            status="error",
            meta=_recoverable_error_meta(),
        )
        result = command if command_wrapped else message
        assert (
            await middleware.awrap_tool_call(
                request,
                AsyncMock(return_value=result),
            )
            is result
        )

    captured = await _capture_model_messages_async(middleware, request.runtime)
    assert any(isinstance(message, HumanMessage) and "PROGRESS HINT" in str(message.content) for message in captured)


@pytest.mark.parametrize(("tool", "tool_name", "tool_args"), _REAL_COMMAND_ERROR_CASES)
def test_real_graph_command_error_gets_structured_error_meta(
    tool,
    tool_name: str,
    tool_args: dict[str, object],
) -> None:
    message = _real_command_error_message(
        tool=tool,
        tool_name=tool_name,
        tool_args=tool_args,
    )

    assert str(message.content).startswith("Error:")
    assert message.additional_kwargs[TOOL_META_KEY]["status"] == "error"


@pytest.mark.parametrize(("tool", "tool_name", "tool_args"), _REAL_COMMAND_ERROR_CASES)
def test_real_graph_command_error_gets_error_receipt(
    tool,
    tool_name: str,
    tool_args: dict[str, object],
) -> None:
    message = _real_command_error_message(
        tool=tool,
        tool_name=tool_name,
        tool_args=tool_args,
    )

    assert str(message.content).startswith("Error:")
    assert message.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == "error"
