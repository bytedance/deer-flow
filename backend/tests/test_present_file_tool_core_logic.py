"""Core behavior tests for present_files path normalization."""

import importlib
from types import SimpleNamespace

import pytest

from deerflow.config.paths import Paths

present_file_tool_module = importlib.import_module("deerflow.tools.builtins.present_file_tool")


def _make_runtime(outputs_path: str) -> SimpleNamespace:
    return SimpleNamespace(
        state={"thread_data": {"outputs_path": outputs_path}},
        context={"thread_id": "thread-1"},
        config={},
    )


def test_present_files_normalizes_host_outputs_path(tmp_path):
    outputs_dir = tmp_path / "threads" / "thread-1" / "user-data" / "outputs"
    outputs_dir.mkdir(parents=True)
    artifact_path = outputs_dir / "report.md"
    artifact_path.write_text("ok")

    result = present_file_tool_module.present_file_tool.func(
        runtime=_make_runtime(str(outputs_dir)),
        filepaths=[str(artifact_path)],
        tool_call_id="tc-1",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/report.md"]
    assert result.update["messages"][0].content == "Successfully presented files"


def test_present_files_keeps_virtual_outputs_path(tmp_path, monkeypatch):
    outputs_dir = tmp_path / "threads" / "thread-1" / "user-data" / "outputs"
    outputs_dir.mkdir(parents=True)
    artifact_path = outputs_dir / "summary.json"
    artifact_path.write_text("{}")

    monkeypatch.setattr(
        present_file_tool_module,
        "get_paths",
        lambda: SimpleNamespace(resolve_virtual_path=lambda thread_id, path, *, user_id=None: artifact_path),
    )

    result = present_file_tool_module.present_file_tool.func(
        runtime=_make_runtime(str(outputs_dir)),
        filepaths=["/mnt/user-data/outputs/summary.json"],
        tool_call_id="tc-2",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/summary.json"]


@pytest.mark.no_auto_user
def test_present_files_uses_runtime_user_for_virtual_outputs_path(tmp_path, monkeypatch):
    """A runtime user must resolve virtual output paths even without a request ContextVar."""
    paths = Paths(tmp_path)
    user_id = "runtime-user"
    thread_id = "thread-runtime-user"
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    outputs_dir.mkdir(parents=True)
    (outputs_dir / "report.md").write_text("ok")

    monkeypatch.setattr(present_file_tool_module, "get_paths", lambda: paths)
    runtime = SimpleNamespace(
        state={"thread_data": {"outputs_path": str(outputs_dir)}},
        context={"thread_id": thread_id, "user_id": user_id},
        config={},
    )

    result = present_file_tool_module.present_file_tool.func(
        runtime=runtime,
        filepaths=["/mnt/user-data/outputs/report.md"],
        tool_call_id="tc-runtime-user",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/report.md"]
    assert result.update["messages"][0].content == "Successfully presented files"
    assert not paths.sandbox_outputs_dir(thread_id, user_id="default").exists()


def test_present_files_uses_config_thread_id_when_context_missing(tmp_path, monkeypatch):
    outputs_dir = tmp_path / "threads" / "thread-from-config" / "user-data" / "outputs"
    outputs_dir.mkdir(parents=True)
    artifact_path = outputs_dir / "summary.json"
    artifact_path.write_text("{}")

    monkeypatch.setattr(
        present_file_tool_module,
        "get_paths",
        lambda: SimpleNamespace(resolve_virtual_path=lambda thread_id, path: artifact_path),
    )

    runtime = SimpleNamespace(
        state={"thread_data": {"outputs_path": str(outputs_dir)}},
        context={},
        config={"configurable": {"thread_id": "thread-from-config"}},
    )

    result = present_file_tool_module.present_file_tool.func(
        runtime=runtime,
        filepaths=["/mnt/user-data/outputs/summary.json"],
        tool_call_id="tc-config",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/summary.json"]
    assert result.update["messages"][0].content == "Successfully presented files"


def test_present_files_rejects_paths_outside_outputs(tmp_path):
    outputs_dir = tmp_path / "threads" / "thread-1" / "user-data" / "outputs"
    workspace_dir = tmp_path / "threads" / "thread-1" / "user-data" / "workspace"
    outputs_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)
    leaked_path = workspace_dir / "notes.txt"
    leaked_path.write_text("leak")

    result = present_file_tool_module.present_file_tool.func(
        runtime=_make_runtime(str(outputs_dir)),
        filepaths=[str(leaked_path)],
        tool_call_id="tc-3",
    )

    assert "artifacts" not in result.update
    assert result.update["messages"][0].content == f"Error: Only files in /mnt/user-data/outputs can be presented: {leaked_path}"


# --- Edge cases added in this PR ---


def test_present_files_rejects_path_traversal_via_dotdot(tmp_path):
    """Path traversal attempts (../../etc/passwd) must NOT escape outputs_path."""
    outputs_dir = tmp_path / "threads" / "thread-1" / "user-data" / "outputs"
    parent_dir = tmp_path / "threads" / "thread-1" / "user-data"
    outputs_dir.mkdir(parents=True)

    # Build a path that starts in outputs_dir and tries to escape via ..
    traversal = outputs_dir / ".." / ".." / ".." / "etc" / "passwd"
    traversal_str = str(traversal)

    result = present_file_tool_module.present_file_tool.func(
        runtime=_make_runtime(str(outputs_dir)),
        filepaths=[traversal_str],
        tool_call_id="tc-traversal",
    )

    assert "artifacts" not in result.update
    assert "Error" in result.update["messages"][0].content
    assert "Only files in /mnt/user-data/outputs can be presented" in result.update["messages"][0].content


def test_present_files_rejects_symlink_pointing_outside_outputs(tmp_path):
    """Symlinks pointing outside outputs_path must be rejected."""
    outputs_dir = tmp_path / "threads" / "thread-1" / "user-data" / "outputs"
    outside_dir = tmp_path / "outside"
    outputs_dir.mkdir(parents=True)
    outside_dir.mkdir(parents=True)
    outside_target = outside_dir / "secret.txt"
    outside_target.write_text("secret")
    symlink_in_outputs = outputs_dir / "link_to_secret"
    symlink_in_outputs.symlink_to(outside_target)

    result = present_file_tool_module.present_file_tool.func(
        runtime=_make_runtime(str(outputs_dir)),
        filepaths=[str(symlink_in_outputs)],
        tool_call_id="tc-symlink",
    )

    assert "artifacts" not in result.update
    assert "Error" in result.update["messages"][0].content
    assert "Only files in /mnt/user-data/outputs can be presented" in result.update["messages"][0].content


def test_present_files_propagates_runtime_user_id_to_virtual_path_resolution(tmp_path, monkeypatch):
    """When a runtime has a user_id, present_files must pass it through to resolve_virtual_path."""
    outputs_dir = tmp_path / "threads" / "thread-1" / "user-data" / "outputs"
    outputs_dir.mkdir(parents=True)
    artifact_path = outputs_dir / "report.md"
    artifact_path.write_text("ok")

    captured_kwargs = {}

    def fake_resolve(thread_id, virtual_path, *, user_id=None):
        captured_kwargs["user_id"] = user_id
        return artifact_path

    monkeypatch.setattr(
        present_file_tool_module,
        "get_paths",
        lambda: SimpleNamespace(resolve_virtual_path=fake_resolve),
    )

    runtime = SimpleNamespace(
        state={"thread_data": {"outputs_path": str(outputs_dir)}},
        context={"thread_id": "thread-1", "user_id": "alice-uuid-42"},
        config={},
    )

    result = present_file_tool_module.present_file_tool.func(
        runtime=runtime,
        filepaths=["/mnt/user-data/outputs/report.md"],
        tool_call_id="tc-userid",
    )

    assert captured_kwargs["user_id"] == "alice-uuid-42", (
        f"user_id must propagate to resolve_virtual_path, got {captured_kwargs}"
    )
    assert result.update["artifacts"] == ["/mnt/user-data/outputs/report.md"]


def test_present_files_batch_handles_mixed_valid_and_invalid_paths(tmp_path):
    """In a batch of mixed valid/invalid paths, valid ones are presented and invalid ones are reported as errors.
    The contract is that errors do NOT abort the whole call."""
    outputs_dir = tmp_path / "threads" / "thread-1" / "user-data" / "outputs"
    outputs_dir.mkdir(parents=True)
    valid_path = outputs_dir / "ok.md"
    valid_path.write_text("ok")

    result = present_file_tool_module.present_file_tool.func(
        runtime=_make_runtime(str(outputs_dir)),
        filepaths=[str(valid_path), "/nonexistent/path/foo.md", str(valid_path)],
        tool_call_id="tc-batch",
    )

    # Both valid paths should be in artifacts
    assert result.update["artifacts"] == ["/mnt/user-data/outputs/ok.md", "/mnt/user-data/outputs/ok.md"]
    # At least one error message should mention the invalid path
    error_messages = [m.content for m in result.update.get("messages", []) if "Error" in m.content]
    assert any("/nonexistent/path/foo.md" in m for m in error_messages), (
        f"expected error message for /nonexistent/path/foo.md, got: {error_messages}"
    )
