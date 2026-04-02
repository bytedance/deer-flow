"""Core behavior tests for write_file no-op guidance."""

import importlib
from types import SimpleNamespace

write_file_tool_module = importlib.import_module("deerflow.sandbox.tools")


class _FakeSandbox:
    def __init__(self, content_by_path: dict[str, str] | None = None):
        self.content_by_path = dict(content_by_path or {})
        self.write_calls: list[tuple[str, str, bool]] = []

    def read_file(self, path: str) -> str:
        if path not in self.content_by_path:
            raise FileNotFoundError(path)
        return self.content_by_path[path]

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        self.write_calls.append((path, content, append))
        self.content_by_path[path] = content


def _make_runtime() -> SimpleNamespace:
    return SimpleNamespace(
        state={"thread_data": {"workspace_path": "/tmp/workspace", "uploads_path": "/tmp/uploads", "outputs_path": "/tmp/outputs"}},
        context={"thread_id": "thread-1"},
    )


def test_write_file_noops_for_identical_workspace_content(monkeypatch):
    sandbox = _FakeSandbox({"/resolved/workspace/ethereal-dream.json": '{"subject":"wow"}'})
    monkeypatch.setattr(write_file_tool_module, "ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr(write_file_tool_module, "ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr(write_file_tool_module, "is_local_sandbox", lambda runtime: True)
    monkeypatch.setattr(write_file_tool_module, "get_thread_data", lambda runtime: runtime.state["thread_data"])
    monkeypatch.setattr(write_file_tool_module, "validate_local_tool_path", lambda path, thread_data: None)
    monkeypatch.setattr(write_file_tool_module, "_resolve_and_validate_user_data_path", lambda path, thread_data: "/resolved/workspace/ethereal-dream.json")

    result = write_file_tool_module.write_file_tool.func(
        runtime=_make_runtime(),
        description="Save intermediate prompt json",
        path="/mnt/user-data/workspace/ethereal-dream.json",
        content='{"subject":"wow"}',
        append=False,
    )

    assert result.startswith("No-op: file already contains identical content.")
    assert "/mnt/user-data/outputs" in result
    assert sandbox.write_calls == []


def test_write_file_noops_for_identical_outputs_content(monkeypatch):
    sandbox = _FakeSandbox({"/resolved/outputs/final.html": "<html>done</html>"})
    monkeypatch.setattr(write_file_tool_module, "ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr(write_file_tool_module, "ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr(write_file_tool_module, "is_local_sandbox", lambda runtime: True)
    monkeypatch.setattr(write_file_tool_module, "get_thread_data", lambda runtime: runtime.state["thread_data"])
    monkeypatch.setattr(write_file_tool_module, "validate_local_tool_path", lambda path, thread_data: None)
    monkeypatch.setattr(write_file_tool_module, "_resolve_and_validate_user_data_path", lambda path, thread_data: "/resolved/outputs/final.html")

    result = write_file_tool_module.write_file_tool.func(
        runtime=_make_runtime(),
        description="Save final deliverable",
        path="/mnt/user-data/outputs/final.html",
        content="<html>done</html>",
        append=False,
    )

    assert "call present_files now" in result
    assert sandbox.write_calls == []


def test_write_file_writes_when_content_changes(monkeypatch):
    sandbox = _FakeSandbox({"/resolved/workspace/ethereal-dream.json": '{"subject":"old"}'})
    monkeypatch.setattr(write_file_tool_module, "ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr(write_file_tool_module, "ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr(write_file_tool_module, "is_local_sandbox", lambda runtime: True)
    monkeypatch.setattr(write_file_tool_module, "get_thread_data", lambda runtime: runtime.state["thread_data"])
    monkeypatch.setattr(write_file_tool_module, "validate_local_tool_path", lambda path, thread_data: None)
    monkeypatch.setattr(write_file_tool_module, "_resolve_and_validate_user_data_path", lambda path, thread_data: "/resolved/workspace/ethereal-dream.json")

    result = write_file_tool_module.write_file_tool.func(
        runtime=_make_runtime(),
        description="Update prompt json",
        path="/mnt/user-data/workspace/ethereal-dream.json",
        content='{"subject":"new"}',
        append=False,
    )

    assert result == "OK"
    assert sandbox.write_calls == [("/resolved/workspace/ethereal-dream.json", '{"subject":"new"}', False)]
