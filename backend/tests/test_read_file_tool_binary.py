"""read_file tool behaviour on binary files.

``read_file`` decodes with UTF-8. Binary uploads (``.xlsx``, images, ...) raise
``UnicodeDecodeError`` deep in the sandbox layer, which previously surfaced to
the model as a vague ``Unexpected error reading file`` message. The model could
not tell that the file was binary, so it retried ``read_file`` instead of
switching to ``bash`` + pandas/openpyxl — burning LLM round-trips. These tests
pin the actionable error contract and guard the normal text path.
"""

from pathlib import Path
from types import SimpleNamespace

from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.tools import read_file_tool


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


def test_read_file_tool_binary_file_returns_actionable_hint(tmp_path, monkeypatch) -> None:
    runtime = _local_runtime(tmp_path)
    # .xlsx is a zip container: header bytes PK\x03\x04 plus a non-UTF-8 byte 0x82
    # that makes strict UTF-8 decoding fail (the exact byte seen in the field logs).
    (tmp_path / "uploads" / "data.xlsx").write_bytes(b"PK\x03\x04\x14\x00\x00\x00\x08\x00\x82\x6a\xb1\x55")
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)

    result = read_file_tool.func(
        runtime=runtime,
        description="read uploaded excel",
        path="/mnt/user-data/uploads/data.xlsx",
    )

    assert "Unexpected error" not in result, result
    assert "binary" in result.lower(), result
    # The model must be steered to bash + pandas/openpyxl, not another read_file.
    assert "bash" in result.lower(), result


def test_read_file_tool_text_file_unaffected(tmp_path, monkeypatch) -> None:
    runtime = _local_runtime(tmp_path)
    (tmp_path / "uploads" / "notes.txt").write_text("hello 你好\nsecond line", encoding="utf-8")
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)

    result = read_file_tool.func(
        runtime=runtime,
        description="read notes",
        path="/mnt/user-data/uploads/notes.txt",
    )

    assert "hello 你好" in result, result
    assert "binary" not in result.lower(), result
