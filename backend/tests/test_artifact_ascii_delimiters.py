"""Literal ASCII delimiters must survive artifact capture and resolution."""

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares.artifact_resolution_middleware import ArtifactResolutionMiddleware
from deerflow.sandbox.tools import _format_glob_results
from deerflow.tools.artifact_registry import _detect_refs_in_text, extract_artifacts_from_result


@pytest.mark.parametrize("name", ["archive(old)", "archive[old]", "archive{old}", "archive(old[1])", "archive)old(done)"])
@pytest.mark.parametrize("content_block", [False, True])
def test_glob_directory_handle_resolves_to_existing_directory(tmp_path, name, content_block):
    directory = tmp_path / name
    directory.mkdir()
    root = "/mnt/user-data/workspace"
    reference = f"{root}/{name}"
    text = _format_glob_results(root, [reference], truncated=False)
    message = ToolMessage(content=[{"type": "text", "text": text}] if content_block else text, tool_call_id="glob-1", name="glob")
    entries = extract_artifacts_from_result(message, thread_id="ascii-delimiters")
    request = ToolCallRequest(
        tool_call={"name": "ls", "args": {"path": entries[-1]["handle"]}, "id": "ls-1", "type": "tool_call"},
        tool=None,
        state={"tool_artifacts": entries},
        runtime=None,
    )

    def handler(resolved):
        path = resolved.tool_call["args"]["path"]
        assert path == reference
        assert (tmp_path / path.removeprefix(f"{root}/")).is_dir()
        return ToolMessage(content="directory exists", tool_call_id="ls-1")

    assert ArtifactResolutionMiddleware().wrap_tool_call(request, handler).content == "directory exists"


@pytest.mark.parametrize(
    "ref", ["/mnt/user-data/workspace/archive(old)", "/mnt/user-data/workspace/archive[old]", "/mnt/user-data/workspace/archive{old}", "https://files.example/report.pdf?label=(old)", "https://files.example/report.pdf#section[1]"]
)
@pytest.mark.parametrize("suffix", ["", ".", ")", "]", "。】"])
def test_balanced_ascii_closers_survive_prose_trimming(ref, suffix):
    assert [entry["ref"] for entry in _detect_refs_in_text(f"Reference: ({ref}{suffix}")] == [ref]


@pytest.mark.parametrize("suffix", [")", "]", "}", ").", "]。"])
def test_unpaired_ascii_prose_closers_still_trimmed(suffix):
    ref = "/mnt/user-data/outputs/report.pdf"
    assert [entry["ref"] for entry in _detect_refs_in_text(f"Reference: {ref}{suffix}")] == [ref]
