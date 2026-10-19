"""Ignore patterns are scoped to the search root, not to the absolute path.

``list_dir`` already applies ``IGNORE_PATTERNS`` relative to the listing root:
explicitly listing ``build`` -- or any path below an ignored ancestor -- returns
its contents. ``glob``/``grep`` used to test the *absolute* path, so a search
rooted at (or under) an ignored name returned nothing on every remote sandbox
while the local walk listed the very same files without any trouble.

These are the unit tests for the helper itself; the end-to-end cases that drive
the real provider ``list_dir``/``glob``/``grep`` for every provider live in
``test_sandbox_search_contract.py``.
"""

from __future__ import annotations

from deerflow.sandbox.search import should_ignore_path, should_ignore_path_under_root


def test_ignored_root_keeps_its_contents() -> None:
    """`glob build/**` must not come back empty just because the root is named ``build``."""
    path = "/data/build/app.js"
    assert should_ignore_path(path) is True  # what the old absolute check did
    assert should_ignore_path_under_root(path, "/data/build") is False


def test_ignored_ancestor_of_the_root_hides_nothing() -> None:
    assert should_ignore_path_under_root("/data/build/workspace/report.txt", "/data/build/workspace") is False


def test_ignored_descendant_of_the_root_is_still_hidden() -> None:
    assert should_ignore_path_under_root("/data/node_modules", "/data") is True
    assert should_ignore_path_under_root("/data/node_modules/pkg/index.js", "/data") is True


def test_ignored_descendant_below_an_ignored_root_is_hidden() -> None:
    """An ignored root still hides its own descendants, as ``list_dir`` does."""
    assert should_ignore_path_under_root("/data/build/node_modules/pkg/index.js", "/data/build") is True


def test_the_requested_root_itself_is_never_hidden() -> None:
    """A single-file ``grep`` hits this on every match: ``file_path == root``."""
    assert should_ignore_path_under_root("/data/logs", "/data/logs") is False
    assert should_ignore_path_under_root("/data/build/notes.txt", "/data/build/notes.txt") is False


def test_path_outside_the_root_keeps_the_absolute_check() -> None:
    assert should_ignore_path_under_root("/other/node_modules/x.js", "/data") is True


def test_root_is_the_filesystem_root() -> None:
    assert should_ignore_path_under_root("/node_modules/x.js", "/") is True
    assert should_ignore_path_under_root("/home/a.py", "/") is False


def test_trailing_slash_on_the_root_is_ignored() -> None:
    assert should_ignore_path_under_root("/data/build/app.js", "/data/build/") is False
