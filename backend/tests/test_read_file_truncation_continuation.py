"""Following the truncation marker's start_line reads a long file end to end.

Pins the real contract through ``read_file_tool`` and ``LocalSandbox.read_file``:
each truncated read names the next ``start_line`` in file line numbers, so the
kept text of successive reads reproduces the file without a gap or an overlap,
including the second hop, where the ranged read is itself truncated and the
provider has renumbered its lines from 1.
"""

import re
from pathlib import Path
from types import SimpleNamespace

from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.tools import read_file_tool

_CONTINUE = re.compile(r"Continue with start_line=(\d+)")
_WHOLE_LINE = re.compile(r"Read that line whole with start_line=(\d+), end_line=(\d+)(?:, then continue with start_line=(\d+))?")


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


def _read(runtime, **kwargs) -> str:
    return read_file_tool.func(runtime=runtime, description="read", path="/mnt/user-data/uploads/long.txt", **kwargs)


def test_following_the_markers_reads_the_whole_file_without_gap_or_overlap(tmp_path, monkeypatch) -> None:
    runtime = _local_runtime(tmp_path)
    lines = [f"{i:05d} " + "x" * (50 + i % 7) for i in range(1, 2601)]  # 2,600 lines of ~57 chars, > 150k chars
    content = "\n".join(lines) + "\n"
    (tmp_path / "uploads" / "long.txt").write_text(content, encoding="utf-8")
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)

    segments, starts, kwargs = [], [], {}
    for _hop in range(10):
        result = _read(runtime, **kwargs)
        assert len(result) <= 50000
        marker = result.find("... [truncated:")
        if marker == -1:
            segments.append(result)
            break
        kept = result[:marker]
        assert kept.endswith("\n"), "a cut on a line boundary ends with a complete line"
        segments.append(kept)
        match = _CONTINUE.search(result)
        assert match, result[marker:]
        start = int(match.group(1))
        assert start == sum(seg.count("\n") for seg in segments) + 1, "the named line is the first unread file line"
        assert not starts or start > starts[-1]
        starts.append(start)
        kwargs = {"start_line": start}
    else:
        raise AssertionError("did not reach the end of the file in 10 hops")

    assert len(starts) >= 2, "the second hop is a ranged read that is itself truncated"
    assert "".join(segments).rstrip("\n") == content.rstrip("\n")


def _follow_markers(runtime, content: str) -> tuple[str, list[str]]:
    """Read the file the way a model following the markers would; return (reconstruction, marker forms seen)."""
    segments, forms, kwargs = [], [], {}
    for _hop in range(20):
        result = _read(runtime, **kwargs)
        assert len(result) <= 50000
        marker = result.find("... [truncated:")
        if marker == -1:
            segments.append(result if result.endswith("\n") else result + "\n")
            return "".join(segments), forms
        if "cut inside line" in result:
            # A fallback cut ends mid-line and its marker starts with a newline;
            # drop the partial line, the continuation re-reads it whole.
            kept = result[: result.find("\n... [truncated:")]
            kept = kept[: kept.rfind("\n") + 1]
        else:
            kept = result[:marker]
        segments.append(kept)
        whole = _WHOLE_LINE.search(result)
        if whole:
            forms.append("whole_line")
            first, last = int(whole.group(1)), int(whole.group(2))
            assert first == last == sum(seg.count("\n") for seg in segments) + 1
            line = _read(runtime, start_line=first, end_line=last)
            assert "... [truncated:" not in line, "a single-line read the marker promised came back truncated"
            segments.append(line + "\n")
            if whole.group(3) is None:
                return "".join(segments), forms  # that line was the last one
            kwargs = {"start_line": int(whole.group(3))}
            continue
        match = _CONTINUE.search(result)
        if not match:
            forms.append("bash")
            return "".join(segments), forms
        forms.append("next")
        start = int(match.group(1))
        assert start == sum(seg.count("\n") for seg in segments) + 1, "the named line is the first unread file line"
        kwargs = {"start_line": start}
    raise AssertionError("did not finish in 20 hops")


def test_long_lines_near_the_budget_are_followed_without_gap_or_overlap(tmp_path, monkeypatch) -> None:
    runtime = _local_runtime(tmp_path)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    tail = "".join(f"{i:05d} tail line\n" for i in range(1, 3001))
    for length in (49600, 49743, 49750, 49760, 50000):
        content = "a\n" + "y" * length + "\n" + tail
        (tmp_path / "uploads" / "long.txt").write_text(content, encoding="utf-8")
        rebuilt, forms = _follow_markers(runtime, content)
        assert rebuilt == content, (length, forms)
        assert "bash" not in forms, (length, forms)


def test_a_line_longer_than_max_chars_is_pointed_at_bash_not_at_a_read(tmp_path, monkeypatch) -> None:
    runtime = _local_runtime(tmp_path)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    content = "a\n" + "y" * 50001 + "\n" + "".join(f"{i:05d} tail line\n" for i in range(1, 301))
    (tmp_path / "uploads" / "long.txt").write_text(content, encoding="utf-8")
    result = _read(runtime)
    assert "cut inside line 2 of 302 lines" in result
    assert "Continue with start_line" not in result and "Read that line whole" not in result
    assert "cut -c" in result
    # No read_file call can return that line whole, so bash is the only honest pointer.
    assert "... [truncated:" in _read(runtime, start_line=2, end_line=2)


def test_a_ranged_read_ending_in_a_blank_line_reports_the_full_span(tmp_path, monkeypatch) -> None:
    runtime = _local_runtime(tmp_path)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    content = "".join(f"{i:05d} " + "x" * 51 + "\n" for i in range(1, 3001)) + "\n"  # 3,001 lines, the last one blank
    (tmp_path / "uploads" / "long.txt").write_text(content, encoding="utf-8")
    assert "of 3001 lines" in _read(runtime)
    assert "of 2-3001 lines" in _read(runtime, start_line=2)
    assert "of 3001 lines" in _read(runtime, start_line=1, end_line=3001)


def test_a_last_line_read_whole_is_the_end_of_the_walk(tmp_path, monkeypatch) -> None:
    runtime = _local_runtime(tmp_path)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    content = "a\n" + "y" * 50000 + "\n"
    (tmp_path / "uploads" / "long.txt").write_text(content, encoding="utf-8")
    rebuilt, forms = _follow_markers(runtime, content)
    assert forms == ["whole_line"]
    assert rebuilt == content
