"""str_replace tool behaviour on empty files.

An empty file used to short-circuit to ``"OK"`` regardless of ``old_str``,
so a real substring replacement silently "succeeded" without changing anything
and without telling the model the target was missing. The fix only returns
``"OK"`` on an empty file when ``old_str`` is itself empty (a no-op edit);
a non-empty ``old_str`` now reports the string was not found.
"""

from pathlib import Path
from types import SimpleNamespace

from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.tools import str_replace_tool


def _local_runtime(tmp_path: Path) -> SimpleNamespace:
    for sub in ("workspace", "uploads", "outputs"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    thread_data = {
        "workspace_path": str(tmp_path / "workspace"),
        "uploads_path": str(tmp_path / "uploads"),
        "outputs_path": str(tmp_path / "outputs"),
    }
    return SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local:t1"}, "thread_data": thread_data},
        context={"thread_id": "t1"},
    )


def _str_replace(tmp_path, monkeypatch, *, old_str: str, new_str: str = "x") -> str:
    runtime = _local_runtime(tmp_path)
    (tmp_path / "outputs" / "empty.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    return str_replace_tool.func(
        runtime=runtime,
        description="replace in empty file",
        path="/mnt/user-data/outputs/empty.txt",
        old_str=old_str,
        new_str=new_str,
    )


def test_empty_file_with_non_empty_old_str_reports_not_found(tmp_path, monkeypatch) -> None:
    result = _str_replace(tmp_path, monkeypatch, old_str="something")
    assert result.startswith("Error: String to replace not found in file")
    assert "empty.txt" in result


def test_empty_file_with_empty_old_str_returns_ok(tmp_path, monkeypatch) -> None:
    # An empty old_str is a no-op edit and remains a benign "OK" on an empty file.
    result = _str_replace(tmp_path, monkeypatch, old_str="")
    assert result == "OK"
