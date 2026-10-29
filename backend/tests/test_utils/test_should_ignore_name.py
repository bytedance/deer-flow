"""should_ignore_name must stay behavior-identical to the original per-pattern
fnmatch loop while doing O(1) set lookup + one combined glob regex instead of
~50 fnmatch calls per directory entry.
"""

from __future__ import annotations

import fnmatch

from deerflow.sandbox.search import IGNORE_PATTERNS, should_ignore_name, should_ignore_path


def _reference(name: str) -> bool:
    """Original implementation, kept here as the equivalence oracle."""
    return any(fnmatch.fnmatch(name, pattern) for pattern in IGNORE_PATTERNS)


_SAMPLES = [
    # exact-name ignores
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "env",
    "logs",
    "coverage",
    ".pytest_cache",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    # glob ignores
    "thing.egg-info",
    "x.swp",
    "y.swo",
    "z.log",
    "a.tmp",
    "b.temp",
    "c.bak",
    "d.cache",
    "core~",
    "shortcut.lnk",
    # kept (must NOT be ignored)
    "foo.py",
    "README.md",
    "src",
    "myenv",
    "node_modules_x",
    "x.git",
    "log",
    "main.c",
]


def test_matches_reference_for_all_samples():
    for name in _SAMPLES:
        assert should_ignore_name(name) == _reference(name), name


def test_known_ignored_names():
    for name in [".git", "node_modules", "__pycache__", "x.swp", "z.log", "core~", "thing.egg-info"]:
        assert should_ignore_name(name) is True


def test_known_kept_names():
    for name in ["foo.py", "README.md", "src", "myenv", "node_modules_x", "x.git"]:
        assert should_ignore_name(name) is False


def test_should_ignore_path_segments():
    assert should_ignore_path("a/node_modules/b") is True
    assert should_ignore_path("proj/.git/config") is True
    assert should_ignore_path("a/b/c.py") is False
