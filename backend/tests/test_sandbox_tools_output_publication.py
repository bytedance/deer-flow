"""Tests for output publication hooks in sandbox mutating tools."""

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

sandbox_tools = importlib.import_module("src.sandbox.tools")


def _runtime(outputs_path: str) -> SimpleNamespace:
    return SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": "/tmp/workspace",
                "uploads_path": "/tmp/uploads",
                "outputs_path": outputs_path,
            },
        },
        context={"thread_id": "thread-1"},
    )


def test_write_file_publishes_outputs(monkeypatch, tmp_path):
    runtime = _runtime(str(tmp_path / "outputs"))
    target = tmp_path / "outputs" / "report.txt"

    sandbox = MagicMock()
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr(sandbox_tools, "ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda runtime: True)
    monkeypatch.setattr(sandbox_tools, "replace_virtual_path", lambda path, thread_data: str(target))

    publish_mock = MagicMock()
    monkeypatch.setattr(sandbox_tools, "publish_output_file", publish_mock)

    result = sandbox_tools.write_file_tool.func(
        runtime=runtime,
        description="write report",
        path="/mnt/user-data/outputs/report.txt",
        content="hello",
    )

    assert result == "OK"
    sandbox.write_file.assert_called_once_with(str(target), "hello", False)
    publish_mock.assert_called_once_with("thread-1", "/mnt/user-data/outputs/report.txt", str(target))


def test_str_replace_publishes_outputs(monkeypatch, tmp_path):
    runtime = _runtime(str(tmp_path / "outputs"))
    target = tmp_path / "outputs" / "notes.txt"

    sandbox = MagicMock()
    sandbox.read_file.return_value = "abc"
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr(sandbox_tools, "ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda runtime: True)
    monkeypatch.setattr(sandbox_tools, "replace_virtual_path", lambda path, thread_data: str(target))

    publish_mock = MagicMock()
    monkeypatch.setattr(sandbox_tools, "publish_output_file", publish_mock)

    result = sandbox_tools.str_replace_tool.func(
        runtime=runtime,
        description="replace",
        path="/mnt/user-data/outputs/notes.txt",
        old_str="a",
        new_str="z",
    )

    assert result == "OK"
    sandbox.write_file.assert_called_once_with(str(target), "zbc")
    publish_mock.assert_called_once_with("thread-1", "/mnt/user-data/outputs/notes.txt", str(target))


def test_bash_publishes_changed_outputs(monkeypatch, tmp_path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True)
    runtime = _runtime(str(outputs_dir))

    def _execute(_command: str) -> str:
        (outputs_dir / "generated.txt").write_text("ok")
        return "done"

    sandbox = MagicMock()
    sandbox.execute_command.side_effect = _execute

    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr(sandbox_tools, "ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda runtime: False)

    publish_mock = MagicMock()
    monkeypatch.setattr(sandbox_tools, "publish_output_file", publish_mock)

    result = sandbox_tools.bash_tool.func(
        runtime=runtime,
        description="generate output",
        command="echo ok",
    )

    assert result == "done"
    publish_mock.assert_called_once_with("thread-1", "/mnt/user-data/outputs/generated.txt", outputs_dir / "generated.txt")


def test_read_file_materializes_upload_before_local_read(monkeypatch, tmp_path):
    runtime = _runtime(str(tmp_path / "outputs"))
    upload_target = tmp_path / "uploads" / "notes.txt"

    sandbox = MagicMock()
    sandbox.read_file.return_value = "rehydrated"

    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr(sandbox_tools, "ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda runtime: True)
    monkeypatch.setattr(sandbox_tools, "replace_virtual_path", lambda path, thread_data: str(upload_target))

    materialize_mock = MagicMock()
    monkeypatch.setattr(sandbox_tools, "materialize_upload_to_local_cache", materialize_mock)

    result = sandbox_tools.read_file_tool.func(
        runtime=runtime,
        description="read upload",
        path="/mnt/user-data/uploads/notes.txt",
    )

    assert result == "rehydrated"
    materialize_mock.assert_called_once_with("thread-1", "/mnt/user-data/uploads/notes.txt")
    sandbox.read_file.assert_called_once_with(str(upload_target))


def test_bash_materializes_upload_paths_before_execution(monkeypatch, tmp_path):
    runtime = _runtime(str(tmp_path / "outputs"))

    sandbox = MagicMock()
    sandbox.execute_command.return_value = "ok"

    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr(sandbox_tools, "ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda runtime: True)
    monkeypatch.setattr(sandbox_tools, "replace_virtual_paths_in_command", lambda command, thread_data: command)

    materialize_mock = MagicMock()
    monkeypatch.setattr(sandbox_tools, "materialize_upload_to_local_cache", materialize_mock)

    result = sandbox_tools.bash_tool.func(
        runtime=runtime,
        description="process upload",
        command="cat /mnt/user-data/uploads/input.csv && wc -l /mnt/user-data/uploads/input.csv",
    )

    assert result == "ok"
    materialize_mock.assert_called_once_with("thread-1", "/mnt/user-data/uploads/input.csv")
