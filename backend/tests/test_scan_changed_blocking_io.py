from __future__ import annotations

import textwrap
from pathlib import Path

from support.detectors import blocking_io_changed as changed
from support.detectors import blocking_io_static as static


def _write_python(path: Path, source: str) -> Path:
    path.write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")
    return path


_CLEANUP_BRANCH_SOURCE = """
    import shutil
    from pathlib import Path

    async def create_agent(path: Path) -> None:
        path.mkdir()
        try:
            await _save(path)
        except Exception:
            shutil.rmtree(path)
            raise
"""


def test_parse_changed_lines_records_added_lines_only() -> None:
    diff = textwrap.dedent(
        """\
        diff --git a/backend/app/x.py b/backend/app/x.py
        --- a/backend/app/x.py
        +++ b/backend/app/x.py
        @@ -10,0 +11,2 @@ def f():
        +    a = 1
        +    b = 2
        @@ -20 +22,0 @@ def g():
        -    gone = 1
        """
    )
    assert changed.parse_changed_lines(diff) == {"backend/app/x.py": {11, 12}}


def test_parse_changed_lines_handles_context_diffs() -> None:
    diff = textwrap.dedent(
        """\
        diff --git a/backend/app/x.py b/backend/app/x.py
        --- a/backend/app/x.py
        +++ b/backend/app/x.py
        @@ -8,7 +8,8 @@ def f():
             ctx1
             ctx2
        -    removed
        +    added_one
             ctx3
        +    added_two
             ctx4
        \\ No newline at end of file
        """
    )
    assert changed.parse_changed_lines(diff) == {"backend/app/x.py": {10, 12}}


def test_parse_changed_lines_ignores_deleted_files() -> None:
    diff = textwrap.dedent(
        """\
        diff --git a/x.py b/x.py
        +++ /dev/null
        @@ -1,2 +0,0 @@
        -gone
        """
    )
    assert changed.parse_changed_lines(diff) == {}


def test_select_findings_keeps_only_touched_candidates(tmp_path: Path) -> None:
    src = _write_python(tmp_path / "agents.py", _CLEANUP_BRANCH_SOURCE)
    findings = [f.to_dict() for f in static.scan_file(src, repo_root=tmp_path)]
    rmtree = next(f for f in findings if f["blocking_call"]["symbol"] == "shutil.rmtree")
    other = next(f for f in findings if f["blocking_call"]["symbol"] != "shutil.rmtree")

    changed_lines = {"agents.py": {rmtree["location"]["line"]}}
    selected = changed.select_findings_on_changed_lines(findings, changed_lines)

    assert [f["blocking_call"]["symbol"] for f in selected] == ["shutil.rmtree"]
    assert other not in selected


def test_find_changed_blocking_io_surfaces_only_changed_candidate(tmp_path: Path, monkeypatch) -> None:
    src = _write_python(tmp_path / "agents.py", _CLEANUP_BRANCH_SOURCE)
    all_findings = [f.to_dict() for f in static.scan_file(src, repo_root=tmp_path)]
    rmtree_line = next(f["location"]["line"] for f in all_findings if f["blocking_call"]["symbol"] == "shutil.rmtree")

    # Stub only the git boundary; the static scan runs for real against tmp_path.
    monkeypatch.setattr(
        changed,
        "changed_python_lines",
        lambda base, repo_root: {"agents.py": {rmtree_line}},
    )
    # Base content identical to head: every finding already existed, so only
    # the changed-line selection contributes (and the union must not double).
    monkeypatch.setattr(
        changed,
        "base_python_contents",
        lambda base, paths, repo_root: {"agents.py": src.read_text(encoding="utf-8")},
    )

    result = changed.find_changed_blocking_io("origin/main", repo_root=tmp_path)

    assert [f["blocking_call"]["symbol"] for f in result] == ["shutil.rmtree"]


_SYNC_HELPER_BASE = """
    from pathlib import Path

    def load(path: Path) -> str:
        return path.read_text()
"""

_SYNC_HELPER_HEAD = """
    from pathlib import Path

    def load(path: Path) -> str:
        return path.read_text()

    async def route(path: Path) -> str:
        return load(path)
"""


def test_new_async_caller_exposing_old_sync_helper_is_reported(tmp_path: Path, monkeypatch) -> None:
    """The blocking line is NOT in the diff — only the new async caller is.

    The finding sits on the untouched `read_text` line, so changed-line
    selection alone would return empty; the new-vs-base comparison must
    surface it.
    """
    src = _write_python(tmp_path / "mod.py", _SYNC_HELPER_HEAD)
    head_findings = [f.to_dict() for f in static.scan_file(src, repo_root=tmp_path)]
    read_text_line = next(f["location"]["line"] for f in head_findings if f["blocking_call"]["symbol"] == "path.read_text")
    added_lines = {line for line in range(1, len(src.read_text().splitlines()) + 1) if line > read_text_line}

    monkeypatch.setattr(changed, "changed_python_lines", lambda base, repo_root: {"mod.py": added_lines})
    monkeypatch.setattr(
        changed,
        "base_python_contents",
        lambda base, paths, repo_root: {"mod.py": textwrap.dedent(_SYNC_HELPER_BASE).strip() + "\n"},
    )

    result = changed.find_changed_blocking_io("origin/main", repo_root=tmp_path)

    assert len(result) == 1
    assert result[0]["blocking_call"]["symbol"] == "path.read_text"
    assert result[0]["event_loop_exposure"] == "ASYNC_REACHABLE_SAME_FILE"


def test_select_findings_new_vs_base_matches_by_stable_key(tmp_path: Path) -> None:
    head = _write_python(tmp_path / "mod.py", _SYNC_HELPER_HEAD)
    head_findings = [f.to_dict() for f in static.scan_file(head, repo_root=tmp_path)]

    base_findings = changed.scan_python_contents({"mod.py": textwrap.dedent(_SYNC_HELPER_BASE).strip() + "\n"})
    assert base_findings == []  # no async exposure at base -> detector is silent

    new = changed.select_findings_new_vs_base(head_findings, base_findings)
    assert [f["blocking_call"]["symbol"] for f in new] == ["path.read_text"]

    # Same content at base and head -> nothing is new, regardless of line drift.
    assert changed.select_findings_new_vs_base(head_findings, head_findings) == []


def test_format_report_empty_warns_about_cross_file_blind_spot() -> None:
    report = changed.format_report([], base="origin/main")
    assert "No blocking-IO candidates" in report
    assert "defined in another file" in report
