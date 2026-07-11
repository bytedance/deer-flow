"""read_file tool line-range handling for one-sided (single-bound) ranges.

Previously ``read_file`` only sliced when BOTH ``start_line`` and ``end_line``
were supplied; a lone ``start_line`` (or lone ``end_line``) was silently ignored
and the whole file was returned. These tests pin the one-sided range contract:
tail-from-start, head-to-end, clamping of ``start_line=0``, and clean error
strings for an inverted range or a start beyond EOF (instead of an empty/garbage
slice).
"""

from pathlib import Path
from types import SimpleNamespace

from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.tools import read_file_tool

_FIVE_LINES = "line1\nline2\nline3\nline4\nline5"


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


def _read(tmp_path, monkeypatch, **kwargs) -> str:
    runtime = _local_runtime(tmp_path)
    (tmp_path / "uploads" / "five.txt").write_text(_FIVE_LINES, encoding="utf-8")
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    return read_file_tool.func(
        runtime=runtime,
        description="read a line range",
        path="/mnt/user-data/uploads/five.txt",
        **kwargs,
    )


def test_only_start_line_returns_tail_from_that_line(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, start_line=3)
    assert result == "line3\nline4\nline5"


def test_only_end_line_returns_head_up_to_that_line(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, end_line=2)
    assert result == "line1\nline2"


def test_start_line_zero_is_clamped_to_first_line(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, start_line=0)
    assert result == _FIVE_LINES


def test_start_line_greater_than_end_line_returns_clean_error(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, start_line=4, end_line=2)
    assert "start_line > end_line" in result
    # No garbage slice content leaked into the error.
    assert "line4" not in result


def test_start_line_beyond_eof_returns_clean_error(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, start_line=99)
    assert "start_line exceeds file length" in result


def test_both_bounds_still_slice_inclusive_range(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, start_line=2, end_line=4)
    assert result == "line2\nline3\nline4"


def test_only_end_line_zero_returns_clean_error(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, end_line=0)
    assert "end_line must be >= 1" in result
    # No leaked line content in the error.
    assert "line1" not in result


def test_only_end_line_negative_returns_clean_error(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, end_line=-1)
    assert "end_line must be >= 1" in result
    assert "line4" not in result


def test_end_line_past_eof_clamps_to_last_line(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, end_line=99)
    assert result == _FIVE_LINES
