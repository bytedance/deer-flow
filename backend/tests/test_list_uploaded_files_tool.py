"""Tests for the list_uploaded_files built-in tool."""

import os
from pathlib import Path
from unittest.mock import MagicMock

from deerflow.config.paths import Paths
from deerflow.tools.builtins.list_uploaded_files_tool import _format_omitted_summary, _list_uploaded_files_impl, _resolve_thread_id


def _paths(tmp_path):
    return Paths(str(tmp_path))


def _uploads_dir(tmp_path: Path, thread_id: str = "thread-abc") -> Path:
    from deerflow.runtime.user_context import get_effective_user_id

    d = Paths(str(tmp_path)).sandbox_uploads_dir(thread_id, user_id=get_effective_user_id())
    d.mkdir(parents=True, exist_ok=True)
    return d


def _runtime(thread_id: str = "thread-abc", state_uploaded: list[dict] | None = None):
    rt = MagicMock()
    rt.context = {"thread_id": thread_id}
    rt.state = {"uploaded_files": state_uploaded or []}
    return rt


# ---------------------------------------------------------------------------
# _resolve_thread_id
# ---------------------------------------------------------------------------


class TestResolveThreadId:
    def test_from_context(self):
        rt = MagicMock()
        rt.context = {"thread_id": "ctx-thread"}
        rt.config = None
        assert _resolve_thread_id(rt) == "ctx-thread"

    def test_from_config(self):
        rt = MagicMock()
        rt.context = {}
        rt.config = {"configurable": {"thread_id": "cfg-thread"}}
        assert _resolve_thread_id(rt) == "cfg-thread"

    def test_none_when_missing(self):
        rt = MagicMock()
        rt.context = {}
        rt.config = None
        assert _resolve_thread_id(rt) is None


# ---------------------------------------------------------------------------
# _format_omitted_summary
# ---------------------------------------------------------------------------


class TestFormatOmittedSummary:
    def test_single_type(self):
        summary = _format_omitted_summary(["a.txt", "b.txt"], 2)
        assert "2 .txt" in summary

    def test_mixed_types(self):
        summary = _format_omitted_summary(["a.txt", "b.pdf", "c.txt"], 3)
        assert ".pdf" in summary
        assert ".txt" in summary

    def test_with_total(self):
        summary = _format_omitted_summary(["a.txt"], 10)
        assert "... (10 total)" in summary


# ---------------------------------------------------------------------------
# list_uploaded_files tool
# ---------------------------------------------------------------------------


class TestListUploadedFiles:
    def test_no_runtime_returns_empty(self):
        result = _list_uploaded_files_impl(runtime=None)
        assert result["files"] == []
        assert "No runtime context" in result["message"]

    def test_no_thread_id_returns_empty(self, tmp_path):
        rt = MagicMock()
        rt.context = {}
        rt.config = None
        result = _list_uploaded_files_impl(runtime=rt, _paths=_paths(tmp_path))
        assert result["files"] == []
        assert "Thread not found" in result["message"]

    def test_no_uploads_dir_returns_empty(self, tmp_path):
        rt = _runtime(thread_id="nonexistent-thread")
        # Don't create the uploads dir — so it doesn't exist
        result = _list_uploaded_files_impl(runtime=rt)
        assert result["files"] == []
        assert "No uploads directory" in result["message"]

    def test_empty_uploads_dir(self, tmp_path):
        _uploads_dir(tmp_path)
        result = _list_uploaded_files_impl(runtime=_runtime(), _paths=_paths(tmp_path))
        assert result["files"] == []
        assert "No historical uploaded files" in result["message"]

    def test_lists_historical_files(self, tmp_path):
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.pdf").write_bytes(b"pdf content")
        (uploads_dir / "data.csv").write_bytes(b"a,b,c")
        # Set mtimes so ordering is deterministic
        os.utime(uploads_dir / "report.pdf", (100, 100))
        os.utime(uploads_dir / "data.csv", (200, 200))

        result = _list_uploaded_files_impl(runtime=_runtime(), _paths=_paths(tmp_path))

        assert len(result["files"]) == 2
        # Most recent first (by mtime)
        assert result["files"][0]["filename"] == "data.csv"
        assert result["files"][1]["filename"] == "report.pdf"
        assert result["files"][0]["size"] == 5
        assert result["files"][0]["path"] == "/mnt/user-data/uploads/data.csv"
        assert result["files"][0]["extension"] == ".csv"
        assert result["total_count"] == 2

    def test_excludes_current_run_files(self, tmp_path):
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "old.txt").write_bytes(b"old")
        (uploads_dir / "new.txt").write_bytes(b"new")

        result = _list_uploaded_files_impl(
            runtime=_runtime(state_uploaded=[{"filename": "new.txt", "size": 3, "path": "/mnt/user-data/uploads/new.txt"}]),
            _paths=_paths(tmp_path),
        )

        filenames = {f["filename"] for f in result["files"]}
        assert "old.txt" in filenames
        assert "new.txt" not in filenames
        assert result["total_count"] == 1

    def test_excludes_staging_files(self, tmp_path):
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "good.txt").write_bytes(b"good")
        (uploads_dir / ".upload-active.part").write_bytes(b"partial")

        result = _list_uploaded_files_impl(runtime=_runtime(), _paths=_paths(tmp_path))

        filenames = {f["filename"] for f in result["files"]}
        assert "good.txt" in filenames
        assert ".upload-active.part" not in filenames

    def test_max_results_truncation(self, tmp_path):
        uploads_dir = _uploads_dir(tmp_path)
        for i in range(25):
            p = uploads_dir / f"file_{i:02}.txt"
            p.write_text(f"content {i}", encoding="utf-8")
            os.utime(p, (i, i))

        result = _list_uploaded_files_impl(max_results=10, runtime=_runtime(), _paths=_paths(tmp_path))

        assert len(result["files"]) == 10
        assert result["total_count"] == 25
        assert result["truncated"] is True
        assert "omitted_summary" in result

    def test_max_results_clamped_to_max(self, tmp_path):
        """max_results should be clamped to _MAX_MAX_RESULTS (100)."""
        uploads_dir = _uploads_dir(tmp_path)
        for i in range(5):
            p = uploads_dir / f"file_{i:02}.txt"
            p.write_text(f"content {i}", encoding="utf-8")
            os.utime(p, (i, i))

        # Request 999 but it gets clamped
        result = _list_uploaded_files_impl(max_results=999, runtime=_runtime(), _paths=_paths(tmp_path))
        assert len(result["files"]) == 5  # Only 5 files exist

    def test_include_outline_true(self, tmp_path):
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "doc.pdf").write_bytes(b"%PDF")
        (uploads_dir / "doc.md").write_text("# Heading 1\n\n## Heading 2\n\nBody text.\n", encoding="utf-8")

        result = _list_uploaded_files_impl(include_outline=True, runtime=_runtime(), _paths=_paths(tmp_path))

        assert len(result["files"]) == 1
        assert "outline" in result["files"][0]
        assert result["files"][0]["outline"][0]["title"] == "Heading 1"
        assert result["files"][0]["outline"][1]["title"] == "Heading 2"

    def test_include_outline_list(self, tmp_path):
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "a.pdf").write_bytes(b"%PDF")
        (uploads_dir / "a.md").write_text("# A Heading\n", encoding="utf-8")
        (uploads_dir / "b.pdf").write_bytes(b"%PDF")
        (uploads_dir / "b.md").write_text("# B Heading\n", encoding="utf-8")

        result = _list_uploaded_files_impl(include_outline=["a.pdf"], runtime=_runtime(), _paths=_paths(tmp_path))

        files_by_name = {f["filename"]: f for f in result["files"]}
        assert "outline" in files_by_name["a.pdf"]
        assert "outline" not in files_by_name.get("b.pdf", {})

    def test_include_outline_false(self, tmp_path):
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "doc.pdf").write_bytes(b"%PDF")
        (uploads_dir / "doc.md").write_text("# Heading\n", encoding="utf-8")

        result = _list_uploaded_files_impl(include_outline=False, runtime=_runtime(), _paths=_paths(tmp_path))

        assert "outline" not in result["files"][0]
        assert "outline_preview" not in result["files"][0]

    def test_fallback_preview_when_no_headings(self, tmp_path):
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "plain.pdf").write_bytes(b"%PDF")
        (uploads_dir / "plain.md").write_text("Just some text.\nNo headings.\n", encoding="utf-8")

        result = _list_uploaded_files_impl(include_outline=True, runtime=_runtime(), _paths=_paths(tmp_path))

        f = result["files"][0]
        assert "outline" not in f or f["outline"] == []
        assert "outline_preview" in f
        assert "Just some text." in f["outline_preview"]

    def test_files_without_md_conversion(self, tmp_path):
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "image.png").write_bytes(b"PNG data")

        result = _list_uploaded_files_impl(include_outline=True, runtime=_runtime(), _paths=_paths(tmp_path))

        f = result["files"][0]
        assert "outline" not in f
        assert "outline_preview" not in f

    def test_cross_turn_state_clear_does_not_exclude_historical_file(self, tmp_path):
        """Two-turn regression: file uploaded in turn 1 must appear in turn 2.

        Turn 1: upload report.pdf → state.uploaded_files = [{filename: "report.pdf"}]
                list_uploaded_files excludes it (it's the current run's file).
        Turn 2: no upload → middleware clears state.uploaded_files = []
                list_uploaded_files MUST now include report.pdf (it became historical).
        """
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.pdf").write_bytes(b"%PDF content")

        # — Turn 1: file just uploaded, excluded from historical listing —
        rt_turn1 = _runtime(state_uploaded=[{"filename": "report.pdf", "size": 12, "path": "/mnt/user-data/uploads/report.pdf"}])
        result1 = _list_uploaded_files_impl(runtime=rt_turn1, _paths=_paths(tmp_path))
        filenames1 = {f["filename"] for f in result1["files"]}
        assert "report.pdf" not in filenames1, "Turn 1: current-run file must be excluded"
        assert result1.get("total_count", 0) == 0

        # — Turn 2: no new uploads, middleware cleared uploaded_files →
        #           report.pdf is now historical and must appear —
        rt_turn2 = _runtime(state_uploaded=[])
        result2 = _list_uploaded_files_impl(runtime=rt_turn2, _paths=_paths(tmp_path))
        filenames2 = {f["filename"] for f in result2["files"]}
        assert "report.pdf" in filenames2, "Turn 2: file must appear after state is cleared"
        assert result2["total_count"] == 1
