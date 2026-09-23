"""Display snapshots record successful loads without depending on live skill files."""

import asyncio
import hashlib
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware


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


def test_range_and_size_limited_snapshots_are_truthfully_marked_partial():
    assert read_result("A section", args={"start_line": 4}).additional_kwargs["skill_usage"]["partial"]
    content = "A" * 110_000
    snapshot = read_result(content).additional_kwargs["skill_usage"]
    assert snapshot["partial"]
    assert len(snapshot["content"]) <= 100_000
    assert snapshot["content_hash"] == hashlib.sha256(content.encode()).hexdigest()


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
    result = ToolErrorHandlingMiddleware().wrap_tool_call(request, lambda _: ToolMessage(content="# Instructions", tool_call_id="read-1"))
    assert recorded == [result.additional_kwargs["skill_usage"]]


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
