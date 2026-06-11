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
    rmtree_line = next(
        f["location"]["line"] for f in all_findings if f["blocking_call"]["symbol"] == "shutil.rmtree"
    )

    # Stub only the git boundary; the static scan runs for real against tmp_path.
    monkeypatch.setattr(
        changed,
        "changed_python_lines",
        lambda base, repo_root: {"agents.py": {rmtree_line}},
    )

    result = changed.find_changed_blocking_io("origin/main", repo_root=tmp_path)

    assert [f["blocking_call"]["symbol"] for f in result] == ["shutil.rmtree"]
