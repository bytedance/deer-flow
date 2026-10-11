"""Root-relative glob semantics of ``deerflow.sandbox.search.path_matches``.

``path_matches`` backs the ``glob`` tool and the ``grep`` ``glob=`` filter for
every sandbox provider. It relied on ``PurePosixPath.match``, which matches
from the right and treats ``**`` as a single-segment ``*`` on Python 3.12+, so
only a leading ``**/`` behaved recursively:

- ``src/**/*.py`` missed ``src/top.py`` and anything two or more levels deep;
- ``docs/*.md`` also matched ``vendor/docs/b.md`` although the pattern is
  documented as relative to the search root.
"""

from pathlib import Path

import pytest

from deerflow.sandbox.search import find_glob_matches, find_grep_matches, path_matches

TREE = (
    "src/top.py",
    "src/pkg/mid.py",
    "src/pkg/sub/deep.py",
    "docs/a.md",
    "vendor/docs/b.md",
)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for rel in TREE:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("needle\n", encoding="utf-8")
    return tmp_path


def _rel(paths: list[str], root: Path) -> set[str]:
    return {Path(p).relative_to(root).as_posix() for p in paths}


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("src/**/*.py", {"src/top.py", "src/pkg/mid.py", "src/pkg/sub/deep.py"}),
        ("src/**", {"src/top.py", "src/pkg/mid.py", "src/pkg/sub/deep.py"}),
        ("src/**/sub/*.py", {"src/pkg/sub/deep.py"}),
        ("docs/*.md", {"docs/a.md"}),
        ("**/docs/*.md", {"docs/a.md", "vendor/docs/b.md"}),
        # Unchanged behavior pinned elsewhere: a leading ``**/`` also matches
        # at the root, and a pattern without "/" matches a basename anywhere.
        ("**/*.py", {"src/top.py", "src/pkg/mid.py", "src/pkg/sub/deep.py"}),
        ("*.md", {"docs/a.md", "vendor/docs/b.md"}),
    ],
)
def test_glob_patterns_are_root_relative_and_recursive(tree: Path, pattern: str, expected: set[str]) -> None:
    matches, truncated = find_glob_matches(tree, pattern)

    assert _rel(matches, tree) == expected
    assert truncated is False


def test_grep_glob_filter_uses_the_same_recursive_semantics(tree: Path) -> None:
    matches, _ = find_grep_matches(tree, "needle", glob_pattern="src/**/*.py")

    assert _rel([m.path for m in matches], tree) == {"src/top.py", "src/pkg/mid.py", "src/pkg/sub/deep.py"}


@pytest.mark.parametrize(
    ("pattern", "rel_path", "expected"),
    [
        ("**", "a/b/c.txt", True),
        ("a/**/**/c.txt", "a/c.txt", True),
        ("a/*/c.txt", "a/b/x/c.txt", False),
        ("nested/*.txt", "nested/result.txt", True),
        ("nested/*.txt", "other/nested/result.txt", False),
        ("./nested/*.txt", "nested/result.txt", True),
        ("*.TXT", "a.txt", False),
    ],
)
def test_path_matches_segments(pattern: str, rel_path: str, expected: bool) -> None:
    assert path_matches(pattern, rel_path) is expected
