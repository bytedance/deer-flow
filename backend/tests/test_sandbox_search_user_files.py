"""Searches hide repository noise, not the user's own files.

``IGNORE_PATTERNS`` was written to walk source checkouts, but the same filter
ran over ``/mnt/user-data/uploads``, where ``*.log`` and ``logs/`` are the
content the agent was asked to read. A user-data root now hides only repository
noise, an explicit glob wins even inside a checkout, and a file named as the
search root is read whatever its size.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from deerflow.sandbox.local.list_dir import list_dir
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.search import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    find_glob_matches,
    find_grep_matches,
    ignore_rules_for,
)
from deerflow.sandbox.tools import glob_tool, grep_tool, ls_tool


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


def test_in_flight_upload_files_stay_hidden_in_user_data(tmp_path: Path) -> None:
    uploads = _uploads(tmp_path)
    (uploads / ".upload-active.part").write_text("partial", encoding="utf-8")

    rules = ignore_rules_for(uploads, user_data=True)
    assert rules.should_ignore(".upload-active.part")
    assert not rules.should_ignore("app.log")
    assert not any(".upload-active.part" in name for name in list_dir(str(uploads), max_depth=2, user_data=True))


def test_host_path_resolved_from_the_user_data_mount_still_counts_as_user_data(tmp_path: Path) -> None:
    # The public ls/glob/grep tools resolve /mnt/user-data/... to host paths
    # before they call the provider, so a prefix check on the argument alone
    # misses every real entry point. The mount table decides instead.
    (tmp_path / ".git").mkdir()
    uploads = _uploads(tmp_path)
    sandbox = LocalSandbox("local", [PathMapping("/mnt/user-data/uploads", str(uploads))])

    assert any(name.endswith("uploads/app.log") for name in sandbox.list_dir(str(uploads)))
    matches, _ = sandbox.glob(str(uploads), "**/*")
    assert "/mnt/user-data/uploads/app.log" in matches
    greps, _ = sandbox.grep(str(uploads), "FATAL")
    assert sorted(match.path for match in greps) == [
        "/mnt/user-data/uploads/app.log",
        "/mnt/user-data/uploads/logs/worker.log",
        "/mnt/user-data/uploads/notes.txt",
    ]


def test_a_root_outside_the_user_data_mount_keeps_the_repository_filter(tmp_path: Path) -> None:
    # Any root the mount table does not label as user data -- a skills mount, an
    # ad-hoc host path, a checkout -- keeps the filter it always had.
    inbox = _uploads(tmp_path)
    sandbox = LocalSandbox("local", [])

    assert ignore_rules_for(inbox).should_ignore("app.log") is True
    matches, _ = sandbox.glob(str(inbox), "**/*")
    assert {Path(name).name for name in matches} == {"notes.txt"}


def test_public_tools_keep_uploaded_logs_when_the_host_tree_is_a_checkout(tmp_path: Path, monkeypatch) -> None:
    # The reviewer's reproduction: the real public tools, with the user-data
    # directory inside the checkout the Gateway runs from.
    (tmp_path / ".git").mkdir()
    for name in ("workspace", "uploads", "outputs"):
        (tmp_path / name).mkdir()
    (tmp_path / "uploads" / "app.log").write_text("FATAL out of memory\n", encoding="utf-8")
    sandbox = LocalSandbox("local", [PathMapping(f"/mnt/user-data/{name}", str(tmp_path / name)) for name in ("workspace", "uploads", "outputs")])
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
    runtime = SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": str(tmp_path / "workspace"),
                "uploads_path": str(tmp_path / "uploads"),
                "outputs_path": str(tmp_path / "outputs"),
            },
        },
        context={"thread_id": "thread-1"},
    )

    assert "app.log" in ls_tool.func(runtime=runtime, description="list uploads", path="/mnt/user-data/uploads")
    assert "app.log" in glob_tool.func(runtime=runtime, description="all uploads", pattern="**/*", path="/mnt/user-data/uploads")
    assert "app.log" in grep_tool.func(runtime=runtime, description="find fatal", pattern="FATAL", path="/mnt/user-data/uploads")
