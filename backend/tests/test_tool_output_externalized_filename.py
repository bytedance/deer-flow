"""Externalized outputs retain stable, distinct paths for each call and content."""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deerflow.agents.middlewares.tool_output_budget_middleware import (
    _build_externalized_filename,
    _externalize,
    _externalize_to_sandbox,
)
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
