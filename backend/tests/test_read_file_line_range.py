"""read_file tool line-range handling for one-sided (single-bound) ranges.

Previously ``read_file`` only sliced when BOTH ``start_line`` and ``end_line``
were supplied; a lone ``start_line`` (or lone ``end_line``) was silently ignored
and the whole file was returned. These tests pin the one-sided range contract:
tail-from-start, head-to-end, rejection of non-positive line numbers, and clean
error strings for an inverted range or a start beyond EOF (instead of an
empty/garbage slice).
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

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
    (tmp_path / "uploads" / "five.txt").write_text(_FIVE_LINES, encoding="utf-8", newline="\n")
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


def test_start_line_zero_returns_clean_error(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, start_line=0)
    assert "start_line must be >= 1" in result
    assert "line1" not in result


def test_start_line_negative_returns_clean_error(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, start_line=-1)
    assert "start_line must be >= 1" in result
    assert "line5" not in result


def test_start_line_greater_than_end_line_returns_clean_error(tmp_path, monkeypatch) -> None:
    from deerflow.sandbox.read_file_contract import READ_FILE_EMPTY_RANGE

    result = _read(tmp_path, monkeypatch, start_line=4, end_line=2)
    assert result == READ_FILE_EMPTY_RANGE
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


def test_contract_constants_parity_with_localsandbox() -> None:
    """count_file_lines must agree with LocalSandbox line numbering and all no-content
    strings must remain in READ_FILE_NO_CONTENT_RESULTS."""
    from deerflow.sandbox.read_file_contract import (
        READ_FILE_INVALID_RANGE,
        READ_FILE_NO_CONTENT_RESULTS,
        count_file_lines,
    )

    assert READ_FILE_INVALID_RANGE in READ_FILE_NO_CONTENT_RESULTS

    # Parity with LocalSandbox.read_file (Python text-mode, universal \n only):
    assert count_file_lines("") == 0
    assert count_file_lines("line1\n") == 1
    assert count_file_lines("line1\nline2\n") == 2
    assert count_file_lines("line1\nline2") == 2  # no trailing newline
    assert count_file_lines("page\fend\n") == 1  # \f not a line separator
    assert count_file_lines("x\u2028y\n") == 1  # \u2028 not a line separator


def _model_read(tmp_path, monkeypatch, content, *, directory="uploads", **kwargs):
    runtime = _local_runtime(tmp_path)
    runtime.tool_call_id = "read-1"
    (tmp_path / directory / "five.txt").write_bytes(content)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    return read_file_tool.func(runtime=runtime, path=f"/mnt/user-data/{directory}/five.txt", **kwargs)


@pytest.mark.parametrize("directory", ["uploads", "workspace"])
def test_short_model_range_labels_original_source_lines(tmp_path, monkeypatch, directory) -> None:
    result = _model_read(
        tmp_path,
        monkeypatch,
        "first\r\nsource\u2028note\r\n\r\n12 | literal payload\r\nlast\r\n".encode(),
        directory=directory,
        start_line=2,
        end_line=4,
    )
    assert result.content == ("Source lines (for exact edits, copy the text after the first ' | '):\n2 | source\u2028note\n3 | \n4 | 12 | literal payload")
    assert result.status == "success"
    assert result.additional_kwargs["deerflow_tool_meta"]["status"] == "success"


@pytest.mark.parametrize("start_line", [1, 2])
def test_model_start_only_range_labels_trailing_blank_line(tmp_path, monkeypatch, start_line) -> None:
    result = _model_read(tmp_path, monkeypatch, b"a\nb\n\n", start_line=start_line)

    assert result.content.split("\n")[1:] == ["1 | a", "2 | b", "3 | "][start_line - 1 :]


def test_model_full_read_keeps_original_display(tmp_path, monkeypatch) -> None:
    assert _model_read(tmp_path, monkeypatch, _FIVE_LINES.encode()).content == _FIVE_LINES


def test_model_range_with_over_forty_actual_lines_keeps_original_display(tmp_path, monkeypatch) -> None:
    content = "\n".join(f"line{number}" for number in range(1, 43))
    assert _model_read(tmp_path, monkeypatch, content.encode(), start_line=2).content == "\n".join(content.split("\n")[1:])


@pytest.mark.parametrize(
    ("source_end", "bounds", "first", "last"),
    [
        (111, {"start_line": 97}, 97, 111),
        (111, {"end_line": 25}, 1, 25),
        (5, {"start_line": 1, "end_line": 41}, 1, 5),
        (69, {"start_line": 30, "end_line": 150}, 30, 69),
    ],
    ids=["short-tail", "short-head", "eof-shortens-window", "forty-actual-lines"],
)
def test_short_model_range_uses_effective_start_and_actual_line_count(
    tmp_path,
    monkeypatch,
    source_end,
    bounds,
    first,
    last,
) -> None:
    content = "\n".join(f"line{number}" for number in range(1, source_end + 1))
    result = _model_read(tmp_path, monkeypatch, content.encode(), **bounds)
    rows = result.content.split("\n")[1:]
    assert rows == [f"{number} | line{number}" for number in range(first, last + 1)]


@pytest.mark.parametrize("limit", [85, 240])
def test_numbered_display_does_not_change_output_when_it_exceeds_budget(tmp_path, monkeypatch, limit) -> None:
    content = ("a" * 48 + "\n" + "b" * 48 + "\n" + "c" * 106).encode()
    monkeypatch.setattr(
        "deerflow.config.app_config.get_app_config",
        lambda: SimpleNamespace(sandbox=SimpleNamespace(read_file_output_max_chars=limit)),
    )
    model = _model_read(tmp_path, monkeypatch, content, start_line=1, end_line=3)
    raw = read_file_tool.func(
        runtime=_local_runtime(tmp_path),
        path="/mnt/user-data/uploads/five.txt",
        start_line=1,
        end_line=3,
    )
    assert model.content == raw
    assert len(model.content) <= limit


@pytest.mark.parametrize("content", ["Error: remote read unavailable", " (start_line exceeds file length) "])
def test_model_range_preserves_in_band_read_failure_text(tmp_path, monkeypatch, content) -> None:
    runtime = _local_runtime(tmp_path)
    runtime.tool_call_id = "read-1"
    monkeypatch.setattr("deerflow.sandbox.tools._read_file_from_sandbox", lambda *args, **kwargs: content)

    result = read_file_tool.func(runtime=runtime, path="/mnt/user-data/uploads/five.txt", start_line=2, end_line=4)

    assert result.content == content
