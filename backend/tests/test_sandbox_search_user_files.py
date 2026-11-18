"""Searches hide repository noise, not the user's own files.

``IGNORE_PATTERNS`` was written to walk source checkouts, but the same filter
ran over ``/mnt/user-data/uploads``, where ``*.log`` and ``logs/`` are the
content the agent was asked to read. A user-data root now hides only repository
noise, an explicit glob wins even inside a checkout, and a file named as the
search root is read whatever its size.
"""

from __future__ import annotations

from pathlib import Path

from deerflow.sandbox.local.list_dir import list_dir
from deerflow.sandbox.search import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    find_glob_matches,
    find_grep_matches,
    ignore_rules_for,
    inside_git_checkout,
)


def _uploads(tmp_path: Path) -> Path:
    uploads = tmp_path / "uploads"
    (uploads / "logs").mkdir(parents=True)
    (uploads / "app.log").write_text("FATAL out of memory\n", encoding="utf-8")
    (uploads / "logs" / "worker.log").write_text("FATAL in worker\n", encoding="utf-8")
    (uploads / "notes.txt").write_text("FATAL in notes\n", encoding="utf-8")
    return uploads


def test_a_user_data_root_lists_and_searches_data_looking_names(tmp_path: Path) -> None:
    uploads = _uploads(tmp_path)

    listed = list_dir(str(uploads), max_depth=2, user_data=True)
    assert str(uploads / "app.log") in listed
    assert str(uploads / "logs" / "worker.log") in listed

    glob_matches, _ = find_glob_matches(uploads, "*.log", user_data=True)
    assert {Path(match).name for match in glob_matches} == {"app.log", "worker.log"}

    matches, _ = find_grep_matches(uploads, "FATAL", user_data=True)
    assert {Path(match.path).name for match in matches} == {"app.log", "worker.log", "notes.txt"}


def test_a_checkout_keeps_hiding_data_looking_names(tmp_path: Path) -> None:
    checkout = tmp_path / "repo"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "app.log").write_text("FATAL out of memory\n", encoding="utf-8")
    (checkout / "notes.txt").write_text("FATAL in notes\n", encoding="utf-8")

    assert inside_git_checkout(checkout) is True
    assert ignore_rules_for(checkout).should_ignore("app.log") is True
    # The user-data flag wins over the checkout: uploads inside a checkout are
    # still the user's files.
    assert ignore_rules_for(checkout, user_data=True).should_ignore("app.log") is False

    listed = list_dir(str(checkout), max_depth=2)
    assert str(checkout / "app.log") not in listed

    glob_matches, _ = find_glob_matches(checkout, "*")
    assert str(checkout / "app.log") not in glob_matches

    matches, _ = find_grep_matches(checkout, "FATAL")
    assert {Path(match.path).name for match in matches} == {"notes.txt"}


def test_an_explicit_glob_wins_inside_a_checkout(tmp_path: Path) -> None:
    checkout = tmp_path / "repo"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "app.log").write_text("FATAL out of memory\n", encoding="utf-8")

    glob_matches, _ = find_glob_matches(checkout, "*.log")
    assert glob_matches == [str(checkout / "app.log")]

    matches, _ = find_grep_matches(checkout, "FATAL", glob_pattern="*.log")
    assert [Path(match.path).name for match in matches] == ["app.log"]


def test_a_file_named_as_the_root_is_read_above_the_size_bound(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    big = uploads / "server.txt"
    big.write_text("ok\n" * 400_000 + "FATAL at the end\n", encoding="utf-8")
    assert big.stat().st_size > DEFAULT_MAX_FILE_SIZE_BYTES

    matches, truncated = find_grep_matches(big, "FATAL")
    assert [match.line for match in matches] == ["FATAL at the end"]
    assert truncated is False


def test_a_directory_search_keeps_the_size_bound(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    big = uploads / "server.txt"
    big.write_text("ok\n" * 400_000 + "FATAL at the end\n", encoding="utf-8")

    matches, _ = find_grep_matches(uploads, "FATAL", user_data=True)
    assert matches == []
