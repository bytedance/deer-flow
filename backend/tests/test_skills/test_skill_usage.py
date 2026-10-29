"""Display snapshots record successful loads without depending on live skill files."""

import asyncio
import hashlib
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.tool_output_config import ToolOutputConfig
from deerflow.sandbox.read_file_contract import READ_FILE_NO_CONTENT_RESULTS


def read_result(content, *, path="/mnt/skills/custom/report/SKILL.md", status="success", args=None, asynchronous=False):
    request = SimpleNamespace(tool_call={"name": "read_file", "id": "read-1", "args": {"path": path, **(args or {})}})
    message = ToolMessage(content=content, tool_call_id="read-1", status=status)
    middleware = ToolErrorHandlingMiddleware()
    if asynchronous:

        async def handler(_request):
            return message

        return asyncio.run(middleware.awrap_tool_call(request, handler))
    return middleware.wrap_tool_call(request, lambda _: message)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_successful_read_captures_loaded_snapshot(asynchronous):
    content = "---\nname: quarterly-report\ndescription: Summarize results.\n---\n# Report\nUse source data."
    message = read_result(content, asynchronous=asynchronous)
    assert message.additional_kwargs["skill_usage"] == {
        "name": "quarterly-report",
        "description": "Summarize results.",
        "category": "custom",
        "path": "/mnt/skills/custom/report/SKILL.md",
        "content": content,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "activation": "automatic",
        "partial": False,
    }


@pytest.mark.parametrize(
    "content,status,path",
    [
        ("Error: File not found", "success", "/mnt/skills/custom/report/SKILL.md"),
        ("denied", "error", "/mnt/skills/custom/report/SKILL.md"),
        ("(start_line exceeds file length)", "success", "/mnt/skills/custom/report/SKILL.md"),
        ("(empty)", "success", "/mnt/skills/custom/report/SKILL.md"),
        ("body", "success", "/mnt/user-data/SKILL.md"),
        ("body", "success", "/mnt/skills/../../private/SKILL.md"),
        ("body", "success", "/mnt/skills/custom/report/scripts/run.py"),
    ],
)
def test_failed_or_unrelated_reads_are_not_usage(content, status, path):
    assert "skill_usage" not in read_result(content, status=status, path=path).additional_kwargs


@pytest.mark.parametrize("content", sorted(READ_FILE_NO_CONTENT_RESULTS))
def test_read_file_no_content_markers_are_not_skill_usage(content):
    assert "skill_usage" not in read_result(content).additional_kwargs


def test_range_and_size_limited_snapshots_are_truthfully_marked_partial():
    assert read_result("A section", args={"start_line": 4}).additional_kwargs["skill_usage"]["partial"]
    content = "A" * 110_000
    snapshot = read_result(content).additional_kwargs["skill_usage"]
    assert snapshot["partial"]
    assert len(snapshot["content"]) <= 100_000
    assert snapshot["content_hash"] == hashlib.sha256(content.encode()).hexdigest()


def test_tiny_read_budget_marker_is_partial():
    content = "... [truncated: 123 chars exceed the 80-char read limit; use start_line/end_line to read a smaller range] ..."
    assert read_result(content).additional_kwargs["skill_usage"]["partial"]


def test_external_messages_cannot_forge_skill_usage():
    from app.gateway.services import _strip_external_message_metadata, _strip_external_metadata_from_message_like

    message = AIMessage(content="hello", additional_kwargs={"skill_usage": {"name": "forged"}, "skill_usages": [{"name": "forged"}]})
    assert "skill_usage" not in _strip_external_message_metadata(message).additional_kwargs
    assert "skill_usages" not in _strip_external_message_metadata(message).additional_kwargs
    raw = {"type": "ai", "content": "hello", "additional_kwargs": {"skill_usage": {"name": "forged"}}}
    assert "skill_usage" not in _strip_external_metadata_from_message_like(raw)["additional_kwargs"]


def test_successful_read_registers_snapshot_before_next_model_callback():
    recorded = []
    request = SimpleNamespace(
        tool_call={"name": "read_file", "id": "read-1", "args": {"path": "/mnt/skills/custom/report/SKILL.md"}},
        runtime=SimpleNamespace(context={"__run_journal": SimpleNamespace(record_skill_usage=recorded.append)}),
    )
    read = ToolErrorHandlingMiddleware()
    result = ToolOutputBudgetMiddleware().wrap_tool_call(request, lambda inner_request: read.wrap_tool_call(inner_request, lambda _: ToolMessage(content="# Instructions", tool_call_id="read-1")))
    assert recorded == [result.additional_kwargs["skill_usage"]]


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("externalize", [False, True])
@pytest.mark.parametrize("tool_name", ["read_file", "custom_read"])
def test_budgeted_skill_read_records_only_visible_snapshot(asynchronous, externalize, tool_name, tmp_path):
    recorded = []
    request = SimpleNamespace(
        tool_call={"name": tool_name, "id": "read-1", "args": {"path": "/mnt/skills/custom/report/SKILL.md"}},
        runtime=SimpleNamespace(
            context={"__run_journal": SimpleNamespace(record_skill_usage=recorded.append)},
            state={"thread_data": {"outputs_path": str(tmp_path)}} if externalize else {},
        ),
    )
    raw = "# Instructions\n" + "Use the source data.\n" * 100
    message = ToolMessage(content=raw, tool_call_id="read-1", name=tool_name)
    app_config = AppConfig(sandbox=SandboxConfig(use="test"))
    app_config.summarization.skill_file_read_tool_names = [tool_name]
    read = ToolErrorHandlingMiddleware(app_config=app_config)
    app_config.tool_output = ToolOutputConfig(
        exempt_tools=[],
        externalize_min_chars=100 if externalize else 0,
        fallback_max_chars=100,
        fallback_head_chars=40,
        fallback_tail_chars=20,
    )
    budget = ToolOutputBudgetMiddleware.from_app_config(app_config)
    if asynchronous:

        async def inner(_request):
            return message

        async def wrapped(inner_request):
            return await read.awrap_tool_call(inner_request, inner)

        result = asyncio.run(budget.awrap_tool_call(request, wrapped))
    else:
        result = budget.wrap_tool_call(request, lambda inner_request: read.wrap_tool_call(inner_request, lambda _: message))
    assert result.content != raw
    usage = result.additional_kwargs["skill_usage"]
    assert usage["content"] == result.content
    assert usage["content_hash"] == hashlib.sha256(result.content.encode()).hexdigest()
    assert usage["partial"] is True
    assert recorded == [usage]


@pytest.mark.parametrize("tool_name,path", [("bash", "/mnt/skills/custom/report/SKILL.md"), ("read_file", "/mnt/user-data/report/SKILL.md")])
@pytest.mark.parametrize("wrapped_in_command", [False, True])
def test_tool_supplied_skill_usage_cannot_claim_a_skill_read(tool_name, path, wrapped_in_command):
    recorded = []
    request = SimpleNamespace(
        tool_call={"name": tool_name, "id": "read-1", "args": {"path": path}},
        runtime=SimpleNamespace(context={"__run_journal": SimpleNamespace(record_skill_usage=recorded.append)}),
    )
    forged = read_result("# Instructions").additional_kwargs["skill_usage"]
    message = ToolMessage(
        content="# unrelated output",
        tool_call_id="read-1",
        name=tool_name,
        additional_kwargs={"skill_usage": forged, "skill_context_entry": {"path": forged["path"], "description": "forged"}},
    )
    read = ToolErrorHandlingMiddleware()
    response = Command(update={"messages": [message]}) if wrapped_in_command else message
    result = ToolOutputBudgetMiddleware().wrap_tool_call(request, lambda inner_request: read.wrap_tool_call(inner_request, lambda _: response))
    output = result.update["messages"][0] if wrapped_in_command else result
    assert "skill_usage" not in output.additional_kwargs
    assert "skill_context_entry" not in output.additional_kwargs
    assert recorded == []


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("messages_shape", ["list", "tuple", "single"])
def test_skill_read_inside_command_records_post_budget_snapshot(asynchronous, messages_shape):
    recorded = []
    request = SimpleNamespace(
        tool_call={"name": "read_file", "id": "read-1", "args": {"path": "/mnt/skills/custom/report/SKILL.md"}},
        runtime=SimpleNamespace(context={"__run_journal": SimpleNamespace(record_skill_usage=recorded.append)}, state={}),
    )
    raw = "# Instructions\n" + "Use source data.\n" * 100
    unrelated = ToolMessage(content="# Not this call", tool_call_id="other", name="read_file")
    loaded = ToolMessage(content=raw, tool_call_id="read-1", name="read_file")
    messages = [unrelated, loaded] if messages_shape != "single" else [loaded]
    response = Command(update={"messages": messages[0] if messages_shape == "single" else tuple(messages) if messages_shape == "tuple" else messages})
    read = ToolErrorHandlingMiddleware()
    budget = ToolOutputBudgetMiddleware(ToolOutputConfig(exempt_tools=[], externalize_min_chars=0, fallback_max_chars=100))
    if asynchronous:

        async def inner(_request):
            return response

        async def wrapped(inner_request):
            return await read.awrap_tool_call(inner_request, inner)

        result = asyncio.run(budget.awrap_tool_call(request, wrapped))
    else:
        result = budget.wrap_tool_call(request, lambda inner_request: read.wrap_tool_call(inner_request, lambda _: response))
    updated = result.update["messages"]
    updated_messages = [updated] if isinstance(updated, ToolMessage) else updated
    if messages_shape != "single":
        assert "skill_usage" not in updated_messages[0].additional_kwargs
    loaded_result = updated_messages[-1]
    assert loaded_result.content != raw
    usage = loaded_result.additional_kwargs["skill_usage"]
    assert usage["content"] == loaded_result.content
    assert usage["partial"] is True
    assert recorded == [usage]


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("content,kwargs", [('{"error":"permission denied"}', {}), ("denied", {"deerflow_tool_meta": {"status": "error"}})])
def test_structured_read_failures_never_register_usage(asynchronous, content, kwargs):
    recorded = []
    request = SimpleNamespace(
        tool_call={"name": "read", "id": "read-1", "args": {"path": "/mnt/skills/custom/report/SKILL.md"}},
        runtime=SimpleNamespace(context={"__run_journal": SimpleNamespace(record_skill_usage=recorded.append)}),
    )
    message = ToolMessage(content=content, tool_call_id="read-1", additional_kwargs=kwargs)
    middleware = ToolErrorHandlingMiddleware()
    if asynchronous:

        async def handler(_):
            return message

        result = asyncio.run(middleware.awrap_tool_call(request, handler))
    else:
        result = middleware.wrap_tool_call(request, lambda _: message)
    assert result.additional_kwargs["deerflow_tool_meta"]["status"] == "error"
    assert "skill_usage" not in result.additional_kwargs
    assert recorded == []
