"""Externalized outputs retain stable, distinct paths for each call and content."""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage

from deerflow.agents.middlewares.tool_output_budget_middleware import (
    ToolOutputBudgetMiddleware,
    _build_externalized_filename,
    _externalize,
    _externalize_to_sandbox,
)
from deerflow.config.tool_output_config import ToolOutputConfig
from deerflow.sandbox.sandbox import Sandbox


def test_the_same_tool_call_gets_the_same_filename():
    """The host-disk and sandbox paths share this helper to agree on one name.

    A random suffix cannot do that: the same call would be written under two
    names, and externalizing one output twice would leave two files behind.
    """
    first = _build_externalized_filename(tool_name="bash", tool_call_id="call_abc123", content="output")
    second = _build_externalized_filename(tool_name="bash", tool_call_id="call_abc123", content="output")

    assert first == second
    assert re.fullmatch(r"bash-[a-f0-9]{64}\.log", first)


@pytest.mark.parametrize("first_id, second_id", [("call_a", "call_b"), ("a/call", "b/call"), ("../call", "call")])
def test_different_tool_calls_get_different_filenames(first_id: str, second_id: str):
    first = _build_externalized_filename(tool_name="bash", tool_call_id=first_id, content="output")
    second = _build_externalized_filename(tool_name="bash", tool_call_id=second_id, content="output")

    assert first != second


@pytest.mark.parametrize("tool_call_id", ["../../etc/passwd", "..\\..\\etc\\passwd", "\x00", ""])
def test_a_tool_call_id_cannot_escape_the_output_directory(tool_call_id: str):
    name = _build_externalized_filename(tool_name="bash", tool_call_id=tool_call_id, content="output")

    assert "/" not in name
    assert ".." not in name
    assert name.startswith("bash-")
    assert re.fullmatch(r"bash-[a-f0-9]{64}\.log", name)


@pytest.mark.parametrize("tool_call_id", ["", "call_abc123"])
def test_changed_content_gets_a_distinct_filename(tool_call_id: str):
    first = _build_externalized_filename(tool_name="bash", tool_call_id=tool_call_id, content="first output")
    second = _build_externalized_filename(tool_name="bash", tool_call_id=tool_call_id, content="second output")

    assert first != second


@pytest.mark.parametrize("first, second", [(("a", "bc"), ("ab", "c")), (("a\x00b", "c"), ("a", "b\x00c"))])
def test_call_id_and_content_are_unambiguously_combined(first: tuple[str, str], second: tuple[str, str]):
    first_name = _build_externalized_filename(tool_name="bash", tool_call_id=first[0], content=first[1])
    second_name = _build_externalized_filename(tool_name="bash", tool_call_id=second[0], content=second[1])

    assert first_name != second_name


@pytest.mark.parametrize(
    "first_id, second_id, first_content, second_content",
    [("", "", "first output", "second output"), ("a/call", "b/call", "output", "output"), ("call_1", "call_1", "first output", "second output")],
    ids=["missing-ids", "sanitized-collision", "changed-content"],
)
def test_host_externalization_preserves_earlier_outputs(tmp_path: Path, first_id: str, second_id: str, first_content: str, second_content: str):
    kwargs = dict(tool_name="bash", outputs_path=str(tmp_path), storage_subdir=".tool-results")
    first_path = _externalize(first_content, tool_call_id=first_id, **kwargs)
    second_path = _externalize(second_content, tool_call_id=second_id, **kwargs)

    assert first_path is not None
    assert second_path is not None
    assert first_path != second_path
    storage_dir = tmp_path / ".tool-results"
    assert (storage_dir / first_path.rsplit("/", 1)[1]).read_text(encoding="utf-8") == first_content
    assert (storage_dir / second_path.rsplit("/", 1)[1]).read_text(encoding="utf-8") == second_content


@pytest.mark.parametrize("tool_call_id", ["", "a/call", "x" * 10_000, "调用" * 10_000], ids=["empty", "path", "long-ascii", "long-unicode"])
def test_host_and_sandbox_use_the_same_bounded_filename(tmp_path: Path, tool_call_id: str):
    content = "输出\nfull output"
    kwargs = dict(tool_name="bash", tool_call_id=tool_call_id, storage_subdir=".tool-results")
    sandbox = MagicMock(spec=Sandbox)
    sandbox.execute_command.return_value = "OK"

    host_path = _externalize(content, outputs_path=str(tmp_path), **kwargs)
    sandbox_path = _externalize_to_sandbox(content, sandbox=sandbox, **kwargs)

    assert host_path is not None
    assert sandbox_path == host_path
    filename = host_path.rsplit("/", 1)[1]
    assert re.fullmatch(r"bash-[a-f0-9]{64}\.log", filename)
    assert len(filename.encode("utf-8")) < 255
    assert (tmp_path / ".tool-results" / filename).read_text(encoding="utf-8") == content
    sandbox.write_file.assert_called_once_with(host_path, content)


@pytest.mark.parametrize("invalid_field", ["content", "tool_call_id"])
def test_host_externalization_handles_filename_encoding_failure(tmp_path: Path, invalid_field: str):
    kwargs = dict(content="output", tool_call_id="call_1")
    kwargs[invalid_field] += "\ud800"

    result = _externalize(tool_name="bash", storage_subdir=".tool-results", outputs_path=str(tmp_path), **kwargs)

    assert result is None
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


@pytest.mark.parametrize("invalid_field", ["content", "tool_call_id"])
def test_sandbox_externalization_handles_filename_encoding_failure(invalid_field: str):
    sandbox = MagicMock(spec=Sandbox)
    kwargs = dict(content="output", tool_call_id="call_1")
    kwargs[invalid_field] += "\ud800"

    result = _externalize_to_sandbox(tool_name="bash", storage_subdir=".tool-results", sandbox=sandbox, **kwargs)

    assert result is None
    sandbox.execute_command.assert_not_called()
    sandbox.write_file.assert_not_called()


@pytest.mark.parametrize("async_wrapper", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("invalid_field", ["content", "tool_call_id"])
@pytest.mark.parametrize("storage_target", ["sandbox", "host", "mounted-host", "blob"])
@pytest.mark.asyncio
async def test_filename_encoding_failure_uses_bounded_fallback(monkeypatch, tmp_path: Path, async_wrapper: bool, invalid_field: str, storage_target: str):
    from deerflow.agents.middlewares import tool_output_budget_middleware as mw

    sandbox = MagicMock(spec=Sandbox)
    provider = SimpleNamespace(uses_thread_data_mounts=storage_target == "mounted-host", get=lambda _: sandbox)
    monkeypatch.setattr(mw, "get_sandbox_provider", lambda: provider)
    blob_store = MagicMock() if storage_target == "blob" else None
    monkeypatch.setattr(mw, "get_blob_store_if_enabled", lambda: blob_store)
    content = "A" * 16_000 + ("\ud800" if invalid_field == "content" else "X") + "B" * 16_000
    call_id = "call_1" + ("\ud800" if invalid_field == "tool_call_id" else "")
    message = ToolMessage(content=content, name="remote_executor", tool_call_id=call_id, id="message_1", artifact={"original": True})
    state = {"thread_data": {"outputs_path": str(tmp_path)}}
    if storage_target in {"sandbox", "mounted-host"}:
        state["sandbox"] = {"sandbox_id": "sb-1"}
    request = SimpleNamespace(
        tool_call={"name": "remote_executor", "id": call_id},
        runtime=SimpleNamespace(state=state, context={"thread_id": "thread-1"}),
    )
    config = ToolOutputConfig()
    middleware = ToolOutputBudgetMiddleware(config=config)
    if async_wrapper:

        async def handler(_):
            return message

        result = await middleware.awrap_tool_call(request, handler)
    else:
        result = middleware.wrap_tool_call(request, lambda _: message)

    assert isinstance(result, ToolMessage)
    assert "Persistent storage unavailable" in result.content
    assert result.content.startswith("A" * config.fallback_head_chars)
    assert result.content.endswith("B" * config.fallback_tail_chars)
    assert len(result.content) <= config.fallback_max_chars
    result.content.encode("utf-8")
    assert result.tool_call_id == call_id
    assert result.id == message.id
    assert result.artifact == message.artifact
    assert message.content == content
    sandbox.execute_command.assert_not_called()
    sandbox.write_file.assert_not_called()
    if blob_store is not None:
        blob_store.put_bytes.assert_not_called()
    assert not any(path.is_file() for path in tmp_path.rglob("*"))
