import subprocess

from deerflow.subagents.worktree_integrity import capture_worktree_fingerprint


def _git(repo, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_worktree_fingerprint_detects_tracked_and_untracked_changes(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    tracked = repo / "pricing.py"
    tracked.write_text("total = 1\n", encoding="utf-8")
    _git(repo, "add", "pricing.py")
    _git(repo, "commit", "-m", "initial")

    clean = capture_worktree_fingerprint(str(repo))
    tracked.write_text("total = 2\n", encoding="utf-8")
    tracked_change = capture_worktree_fingerprint(str(repo))
    (repo / "report.txt").write_text("review output\n", encoding="utf-8")
    untracked_change = capture_worktree_fingerprint(str(repo))

    assert tracked_change != clean
    assert untracked_change != tracked_change


def test_worktree_fingerprint_detects_head_change_without_file_diff(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "pricing.py").write_text("total = 1\n", encoding="utf-8")
    _git(repo, "add", "pricing.py")
    _git(repo, "commit", "-m", "initial")

    before = capture_worktree_fingerprint(str(repo))
    _git(repo, "commit", "--allow-empty", "-m", "unexpected commit")
    after = capture_worktree_fingerprint(str(repo))

    assert after != before
