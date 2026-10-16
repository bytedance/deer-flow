"""Fixed-string local searches must not inherit the regex long-line guard."""

from pathlib import Path

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.search import GrepMatch, find_grep_matches, truncate_line


@pytest.mark.parametrize("single_file", [False, True])
@pytest.mark.parametrize("case_sensitive", [False, True])
@pytest.mark.parametrize("ending", ["\n", "\r\n", ""])
def test_literal_grep_finds_text_beyond_long_line_guard(tmp_path: Path, single_file: bool, case_sensitive: bool, ending: str) -> None:
    target = tmp_path / "data.json"
    line = "x" * 2500 + "Needle[0].value"
    target.write_text("header\n" + line + ending, encoding="utf-8", newline="")
    root = target if single_file else tmp_path
    pattern = "Needle[0].value" if case_sensitive else "needle[0].VALUE"

    matches, truncated = find_grep_matches(root, pattern, literal=True, case_sensitive=case_sensitive)

    assert matches == [GrepMatch(path=str(target.resolve()), line_number=2, line=truncate_line(line))]
    assert len(matches[0].line) == 200
    assert truncated is False


def test_regex_grep_keeps_long_line_guard(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("x" * 2500 + "needle\nshort needle\n", encoding="utf-8", newline="")

    matches, truncated = find_grep_matches(target, "needle")

    assert matches == [GrepMatch(path=str(target.resolve()), line_number=2, line="short needle")]
    assert truncated is False


def test_literal_grep_keeps_file_size_limit(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("x" * 2500 + "needle", encoding="utf-8")

    matches, truncated = find_grep_matches(target, "needle", literal=True, max_file_size=2500)

    assert matches == []
    assert truncated is False


def test_literal_grep_keeps_glob_filter(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    target.write_text("x" * 2500 + "needle", encoding="utf-8")

    matches, truncated = find_grep_matches(tmp_path, "needle", literal=True, glob_pattern="*.txt")

    assert matches == []
    assert truncated is False


def test_literal_grep_keeps_result_limit(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    line = "x" * 2500 + "needle\n"
    target.write_text(line * 3, encoding="utf-8", newline="")

    matches, truncated = find_grep_matches(target, "needle", literal=True, max_results=2)

    assert [match.line_number for match in matches] == [1, 2]
    assert all(len(match.line) == 200 for match in matches)
    assert truncated is True


def test_literal_grep_keeps_binary_file_exclusion(tmp_path: Path) -> None:
    target = tmp_path / "data.bin"
    target.write_bytes(b"\0" + b"x" * 2500 + b"needle")

    matches, truncated = find_grep_matches(target, "needle", literal=True)

    assert matches == []
    assert truncated is False


@pytest.mark.parametrize("single_file", [False, True])
def test_local_sandbox_literal_grep_keeps_virtual_paths(tmp_path: Path, single_file: bool) -> None:
    target = tmp_path / "data.json"
    line = "x" * 2500 + "needle"
    target.write_text(line, encoding="utf-8")
    virtual_root = "/mnt/user-data/workspace"
    sandbox = LocalSandbox(id="local:test", path_mappings=[PathMapping(container_path=virtual_root, local_path=str(tmp_path))])
    root = f"{virtual_root}/data.json" if single_file else virtual_root

    matches, truncated = sandbox.grep(root, "needle", literal=True)

    assert matches == [GrepMatch(path=f"{virtual_root}/data.json", line_number=1, line=truncate_line(line))]
    assert truncated is False
