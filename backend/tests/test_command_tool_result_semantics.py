"""Command-wrapped ToolMessages must share bare-ToolMessage result semantics.

Tools such as setup_agent and view_image return LangGraph Command(update={"messages": [...]})
instead of a bare ToolMessage. Normalization, progress tracking, and receipts must treat
those wrapped messages like direct results so an "Error:" payload is not recorded as success.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware
from deerflow.agents.middlewares.tool_receipt import TOOL_RECEIPT_KEY
from deerflow.agents.middlewares.tool_receipt_middleware import ToolReceiptMiddleware
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY, normalize_tool_result


def _runtime(thread_id: str = "t1", run_id: str = "r1", tool_call_id: str = "call-1") -> SimpleNamespace:
    return SimpleNamespace(context={"thread_id": thread_id, "run_id": run_id}, tool_call_id=tool_call_id, state=None)


def _request(tool_name: str = "setup_agent", tool_call_id: str = "call-1", runtime=None):
    return SimpleNamespace(
        tool_call={"name": tool_name, "id": tool_call_id, "args": {}},
        runtime=runtime if runtime is not None else _runtime(tool_call_id=tool_call_id),
    )


def _tool_message(
    content: str,
    *,
    tool_call_id: str = "call-1",
    name: str = "setup_agent",
    status: str = "success",
    kwargs: dict | None = None,
) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=tool_call_id,
        name=name,
        status=status,
        additional_kwargs=kwargs or {},
    )


def _command(*messages, goto: str | None = None, extra_update: dict | None = None) -> Command:
    update = {"messages": list(messages), **(extra_update or {})}
    return Command(goto=goto, update=update) if goto is not None else Command(update=update)


def _meta(message: ToolMessage) -> dict:
    return message.additional_kwargs[TOOL_META_KEY]


def _chain_error_then_receipt(request, handler):
    error_middleware = ToolErrorHandlingMiddleware()
    receipt_middleware = ToolReceiptMiddleware()
    return receipt_middleware.wrap_tool_call(
        request,
        lambda current: error_middleware.wrap_tool_call(current, handler),
    )


# ---------------------------------------------------------------------------
# Direct-result controls: bare ToolMessages already normalize and receipt as error
# ---------------------------------------------------------------------------


def test_bare_error_tool_message_normalizes_and_receipts_as_error():
    request = _request()
    message = _tool_message("Error: soul content is empty; refusing to create agent with an empty SOUL.md")

    result = _chain_error_then_receipt(request, lambda _req: message)

    assert result is message
    assert _meta(result)["status"] == "error"
    assert result.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == "error"


def test_bare_success_tool_message_normalizes_and_receipts_as_success():
    request = _request()
    message = _tool_message("Agent 'demo' created successfully!")

    result = _chain_error_then_receipt(request, lambda _req: message)

    assert _meta(result)["status"] == "success"
    assert result.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == "success"


# ---------------------------------------------------------------------------
# normalize_tool_result Command wrappers
# ---------------------------------------------------------------------------


def test_normalize_command_error_prefix_stamps_error_meta():
    message = _tool_message("Error: soul content is empty; refusing to create agent with an empty SOUL.md")
    result = normalize_tool_result(_command(message, extra_update={"created_agent_name": None}))

    assert isinstance(result, Command)
    stamped = result.update["messages"][0]
    assert _meta(stamped)["status"] == "error"
    assert _meta(stamped)["source"] == "tool_return"


def test_normalize_command_success_stamps_success_meta():
    message = _tool_message("Agent 'demo' created successfully!")
    result = normalize_tool_result(_command(message))

    assert _meta(result.update["messages"][0])["status"] == "success"


def test_normalize_command_partial_success_from_content():
    message = _tool_message("no results found for query")
    result = normalize_tool_result(_command(message))

    assert _meta(result.update["messages"][0])["status"] == "partial_success"
    assert _meta(result.update["messages"][0])["recommended_next_action"] == "rewrite_query"


def test_normalize_command_preserves_producer_supplied_meta():
    existing = {
        "status": "error",
        "error_type": "custom",
        "recoverable_by_model": True,
        "recommended_next_action": "stop",
        "source": "tool_return",
    }
    message = _tool_message("Error: overwritten?", kwargs={TOOL_META_KEY: existing})
    result = normalize_tool_result(_command(message))

    assert result.update["messages"][0].additional_kwargs[TOOL_META_KEY] is existing


def test_normalize_command_preserves_other_fields_and_unrelated_messages():
    matching = _tool_message("Error: file not found")
    unrelated = _tool_message("other", tool_call_id="tc-other", name="other")
    note = HumanMessage(content="keep me")
    command = _command(unrelated, matching, note, goto="next_node", extra_update={"other_state": True})

    result = normalize_tool_result(command, tool_call_id="call-1")

    assert result is command
    assert result.goto == "next_node"
    assert result.update["other_state"] is True
    assert result.update["messages"][0] is unrelated
    assert result.update["messages"][2] is note
    assert _meta(matching)["status"] == "error"
    assert TOOL_META_KEY not in unrelated.additional_kwargs
    assert note.additional_kwargs == {}


def test_normalize_command_without_messages_passthrough():
    command = Command(goto="next_node")
    assert normalize_tool_result(command) is command


# ---------------------------------------------------------------------------
# ToolErrorHandlingMiddleware stamps Command results on sync and async paths
# ---------------------------------------------------------------------------


def test_error_handling_normalizes_command_sync():
    middleware = ToolErrorHandlingMiddleware()
    request = _request()
    command = _command(_tool_message("Error: soul content is empty"))

    result = middleware.wrap_tool_call(request, lambda _req: command)

    assert result is command
    assert _meta(result.update["messages"][0])["status"] == "error"


@pytest.mark.anyio
async def test_error_handling_normalizes_command_async():
    middleware = ToolErrorHandlingMiddleware()
    request = _request()
    command = _command(_tool_message("Error: soul content is empty"))

    result = await middleware.awrap_tool_call(request, AsyncMock(return_value=command))

    assert result is command
    assert _meta(result.update["messages"][0])["status"] == "error"


# ---------------------------------------------------------------------------
# ToolProgressMiddleware assesses the matching Command message
# ---------------------------------------------------------------------------


def _progress_mw() -> ToolProgressMiddleware:
    return ToolProgressMiddleware(stagnation_threshold=2, warn_escalation_count=2, min_words=5)


def _error_meta_kwargs() -> dict:
    return {
        TOOL_META_KEY: {
            "status": "error",
            "error_type": "no_results",
            "recoverable_by_model": True,
            "recommended_next_action": "rewrite_query",
            "source": "tool_return",
        }
    }


def test_progress_tracks_command_error_matching_tool_call_id_sync():
    mw = _progress_mw()
    request = _request(tool_name="web_search", tool_call_id="tc-web_search")
    matching = _tool_message("Error: no results found", tool_call_id="tc-web_search", name="web_search", kwargs=_error_meta_kwargs())
    unrelated = _tool_message("ok", tool_call_id="tc-other", name="other")
    command = _command(unrelated, matching)

    mw.wrap_tool_call(request, lambda _req: command)

    state = mw._phase_states["t1"]["web_search"]
    assert state.consecutive_problems == 1
    assert state.phase == "active"


def test_progress_ignores_unrelated_command_error_when_match_is_success():
    mw = _progress_mw()
    request = _request(tool_name="web_search", tool_call_id="tc-web_search")
    unrelated_error = _tool_message(
        "Error: no results found",
        tool_call_id="tc-other",
        name="web_search",
        kwargs=_error_meta_kwargs(),
    )
    matching_success = _tool_message(
        "A" * 200,
        tool_call_id="tc-web_search",
        name="web_search",
        kwargs={
            TOOL_META_KEY: {
                "status": "success",
                "error_type": None,
                "recoverable_by_model": True,
                "recommended_next_action": "continue",
                "source": "content_analysis",
            }
        },
    )
    command = _command(unrelated_error, matching_success)

    mw.wrap_tool_call(request, lambda _req: command)

    state = mw._phase_states["t1"]["web_search"]
    assert state.consecutive_problems == 0
    assert state.phase == "active"


@pytest.mark.anyio
async def test_progress_tracks_command_error_async():
    mw = _progress_mw()
    request = _request(tool_name="web_search", tool_call_id="tc-web_search")
    matching = _tool_message("Error: no results found", tool_call_id="tc-web_search", name="web_search", kwargs=_error_meta_kwargs())

    await mw.awrap_tool_call(request, AsyncMock(return_value=_command(matching)))

    assert mw._phase_states["t1"]["web_search"].consecutive_problems == 1


def test_progress_and_error_handling_chain_counts_command_error():
    progress = _progress_mw()
    error_handling = ToolErrorHandlingMiddleware()
    request = _request(tool_name="web_search", tool_call_id="tc-web_search")
    command = _command(_tool_message("Error: no results found", tool_call_id="tc-web_search", name="web_search"))

    progress.wrap_tool_call(request, lambda current: error_handling.wrap_tool_call(current, lambda _req: command))

    assert progress._phase_states["t1"]["web_search"].consecutive_problems == 1
    assert _meta(command.update["messages"][0])["status"] == "error"


# ---------------------------------------------------------------------------
# Receipts use normalized Command status (error, not default success)
# ---------------------------------------------------------------------------


def test_command_error_receipt_is_error_not_success():
    request = _request()
    command = _command(_tool_message("Error: soul content is empty; refusing to create agent with an empty SOUL.md"))

    result = _chain_error_then_receipt(request, lambda _req: command)

    message = result.update["messages"][0]
    assert message.status == "success"  # producer did not set status="error"
    assert _meta(message)["status"] == "error"
    assert message.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == "error"


@pytest.mark.anyio
async def test_command_error_receipt_async_is_error():
    error_middleware = ToolErrorHandlingMiddleware()
    receipt_middleware = ToolReceiptMiddleware()
    request = _request()
    command = _command(_tool_message("Error: Image file not found: /mnt/user-data/workspace/missing.png", name="view_image"))

    async def inner(current):
        return await error_middleware.awrap_tool_call(current, AsyncMock(return_value=command))

    result = await receipt_middleware.awrap_tool_call(request, inner)

    message = result.update["messages"][0]
    assert _meta(message)["status"] == "error"
    assert message.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == "error"


def test_command_success_receipt_is_success():
    request = _request()
    command = _command(_tool_message("Agent 'demo' created successfully!"), extra_update={"created_agent_name": "demo"})

    result = _chain_error_then_receipt(request, lambda _req: command)

    message = result.update["messages"][0]
    assert _meta(message)["status"] == "success"
    assert message.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == "success"
    assert result.update["created_agent_name"] == "demo"


def test_receipt_stamps_only_matching_command_message():
    request = _request(tool_call_id="call-1")
    unrelated = _tool_message("other", tool_call_id="tc-other", name="other")
    matching = _tool_message("Error: not found", tool_call_id="call-1")
    command = _command(unrelated, matching)

    result = _chain_error_then_receipt(request, lambda _req: command)

    assert TOOL_RECEIPT_KEY not in unrelated.additional_kwargs
    assert matching.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == "error"
    assert result is command


# ---------------------------------------------------------------------------
# Real tools through the error-handling + receipt chain
# ---------------------------------------------------------------------------


def test_setup_agent_empty_soul_receipt_is_error():
    from deerflow.tools.builtins.setup_agent_tool import setup_agent

    runtime = _runtime()
    request = _request(tool_name="setup_agent", runtime=runtime)

    def call_setup_agent(current):
        return setup_agent.func(soul="   ", description="demo", runtime=current.runtime)

    result = _chain_error_then_receipt(request, call_setup_agent)
    message = result.update["messages"][0]

    assert "soul content is empty" in message.content
    assert message.status == "success"
    assert _meta(message)["status"] == "error"
    assert message.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == "error"


def test_view_image_disallowed_path_receipt_is_error():
    from deerflow.tools.builtins.view_image_tool import view_image_tool

    request = _request(tool_name="view_image")

    def call_view_image(current):
        return view_image_tool.func(
            runtime=current.runtime,
            image_path="/etc/passwd",
            tool_call_id=current.tool_call["id"],
        )

    result = _chain_error_then_receipt(request, call_view_image)
    message = result.update["messages"][0]

    assert message.content.startswith("Error:")
    assert _meta(message)["status"] == "error"
    assert message.additional_kwargs[TOOL_RECEIPT_KEY]["status"] == "error"
