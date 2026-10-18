"""Fixed-string local searches must not inherit the regex long-line guard."""

import os
import re
import subprocess
import sys
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


@pytest.mark.parametrize("case_sensitive", [False, True])
@pytest.mark.parametrize(
    ("pattern", "body"),
    [
        ("aaaaab", "a" * 30 + "b"),
        ("aAaB", "a" * 30 + "AAab"),
        ("i", "İ"),
        ("i", "ı"),
        ("s", "ſ"),
        ("k", "K"),
        ("iıiX", "İİİİX"),
        ("ΣσςX", "ςΣσςX"),
        ("β", "ϐ"),
        ("μ", "µ"),
        ("φ", "ϕ"),
        ("ss", "ß"),
        ("ß", "ẞ"),
        ("i\u0307", "İ"),
        ("Needle[0].value", "needle[0].VALUE"),
        ("", "no needle"),
        ("a" * 60, "a" * 30),
    ],
)
def test_literal_long_line_preserves_regex_case_semantics(tmp_path: Path, pattern: str, body: str, case_sensitive: bool) -> None:
    target = tmp_path / "unicode.txt"
    line = "x" * 2500 + body
    target.write_text(line, encoding="utf-8")
    expected = re.search(re.escape(pattern), line, 0 if case_sensitive else re.IGNORECASE) is not None

    matches, truncated = find_grep_matches(target, pattern, literal=True, case_sensitive=case_sensitive)

    assert bool(matches) is expected
    assert truncated is False


def test_case_insensitive_literal_repeated_prefix_finishes_within_deadline(tmp_path: Path) -> None:
    missing = tmp_path / "missing.txt"
    present = tmp_path / "present.txt"
    missing.write_text("a" * 900_000, encoding="utf-8")
    present.write_text("a" * 900_000 + "b", encoding="utf-8")
    env = os.environ.copy()
    harness = Path(__file__).resolve().parents[1] / "packages" / "harness"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(harness), env.get("PYTHONPATH", ""))))
    script = """
import sys
from pathlib import Path
from deerflow.sandbox.search import find_grep_matches
pattern = "a" * 10_000 + "b"
assert find_grep_matches(Path(sys.argv[1]), pattern, literal=True) == ([], False)
matches, truncated = find_grep_matches(Path(sys.argv[2]), pattern, literal=True)
assert len(matches) == 1 and matches[0].line_number == 1
assert truncated is False
"""

    # A subprocess deadline kills and reaps a regressing regex search rather
    # than leaving an uninterruptible worker running after this test fails.
    result = subprocess.run([sys.executable, "-c", script, str(missing), str(present)], env=env, capture_output=True, text=True, timeout=10, check=False)

    assert result.returncode == 0, result.stderr
