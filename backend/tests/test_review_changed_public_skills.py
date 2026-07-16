from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

import review_changed_public_skills as runner


def _completed(command: list[str], *, stdout: bytes = b"", returncode: int = 0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=b"")


def _write_skill(repo_root: Path, package: str) -> Path:
    skill_md = repo_root / "skills" / "public" / package / "SKILL.md"
    skill_md.parent.mkdir(parents=True, exist_ok=True)
    skill_md.write_text("---\nname: demo\ndescription: Demo skill.\n---\n", encoding="utf-8")
    return skill_md


def test_main_skips_successfully_when_no_public_skill_changed(tmp_path: Path, monkeypatch, capsys) -> None:
    def fake_run(command, **kwargs):
        assert command == [
            "git",
            "diff",
            "--name-status",
            "-z",
            "base...head",
            "--",
            runner.PUBLIC_SKILL_PACKAGE_PATHSPEC,
        ]
        assert kwargs["cwd"] == tmp_path
        assert kwargs["capture_output"] is True
        assert kwargs["check"] is False
        return _completed(command)

    def fail_review(*args, **kwargs):
        raise AssertionError("review should not run when no public skill package file changed")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "run_review", fail_review)

    exit_code = runner.main(
        [
            "--base-ref",
            "base",
            "--head-ref",
            "head",
            "--repo-root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "No changed public skill package files; skipping review." in output


def test_main_reviews_changed_public_skill_and_skips_deleted_skill_md(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_skill(tmp_path, "alpha")
    _write_skill(tmp_path, "alpha/evals/fixtures/blocked")
    diff_output = b"\0".join(
        [
            b"M",
            b"skills/public/alpha/SKILL.md",
            b"M",
            b"skills/public/alpha/evals/fixtures/blocked/SKILL.md",
            b"D",
            b"skills/public/deleted/SKILL.md",
            b"M",
            b"skills/public/alpha/references/guide.md",
            b"M",
            b"skills/private/not-public/SKILL.md",
            b"",
        ]
    )
    reviewed: list[str] = []

    def fake_git_diff(command, **kwargs):
        assert command[:3] == ["git", "diff", "--name-status"]
        return _completed(command, stdout=diff_output)

    def fake_review(package: Path, repo_root: Path, python_executable: str) -> int:
        assert repo_root == tmp_path
        assert python_executable
        reviewed.append(package.relative_to(repo_root).as_posix())
        return 0

    monkeypatch.setattr(runner.subprocess, "run", fake_git_diff)
    monkeypatch.setattr(runner, "run_review", fake_review)

    exit_code = runner.main(
        [
            "--before",
            "before",
            "--after",
            "after",
            "--repo-root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert reviewed == ["skills/public/alpha"]
    assert "Queued package: skills/public/alpha" in output
    assert "Skipping deleted SKILL.md: skills/public/deleted/SKILL.md" in output
    assert "All changed public skill packages passed review." in output


def test_main_skips_fully_deleted_skill_package(tmp_path: Path, monkeypatch, capsys) -> None:
    # Nothing is written to tmp_path for "removed": the whole package (SKILL.md and its
    # other files) was deleted, so the package directory does not exist on disk anymore.
    diff_output = b"\0".join(
        [
            b"D",
            b"skills/public/removed/SKILL.md",
            b"D",
            b"skills/public/removed/scripts/helper.py",
            b"D",
            b"skills/public/removed/assets/logo.png",
            b"",
        ]
    )

    def fake_git_diff(command, **kwargs):
        return _completed(command, stdout=diff_output)

    def fail_review(*args, **kwargs):
        raise AssertionError("review should not run for a fully deleted skill package")

    monkeypatch.setattr(runner.subprocess, "run", fake_git_diff)
    monkeypatch.setattr(runner, "run_review", fail_review)

    exit_code = runner.main(
        [
            "--before",
            "before",
            "--after",
            "after",
            "--repo-root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Skipping deleted SKILL.md: skills/public/removed/SKILL.md" in output
    assert "Skipping fully removed package: skills/public/removed" in output
    assert "No changed public skill package files; skipping review." in output


def test_main_reviews_package_when_skill_md_deleted_but_sibling_file_remains(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    # SKILL.md was deleted but a sibling package file still exists on disk: this is a
    # broken/partial package, not a full removal, and must still be queued for review.
    skill_dir = tmp_path / "skills" / "public" / "broken"
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts" / "helper.py").write_text("def helper():\n    return 1\n", encoding="utf-8")

    diff_output = b"\0".join(
        [
            b"D",
            b"skills/public/broken/SKILL.md",
            b"M",
            b"skills/public/broken/scripts/helper.py",
            b"",
        ]
    )
    reviewed: list[str] = []

    def fake_git_diff(command, **kwargs):
        return _completed(command, stdout=diff_output)

    def fake_review(package: Path, repo_root: Path, python_executable: str) -> int:
        reviewed.append(package.relative_to(repo_root).as_posix())
        return 1

    monkeypatch.setattr(runner.subprocess, "run", fake_git_diff)
    monkeypatch.setattr(runner, "run_review", fake_review)

    exit_code = runner.main(
        [
            "--before",
            "before",
            "--after",
            "after",
            "--repo-root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert reviewed == ["skills/public/broken"]
    assert "Queued package: skills/public/broken" in output
    assert "One or more skill reviews failed." in output


def test_main_reviews_package_when_only_support_file_changed(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_skill(tmp_path, "alpha")
    diff_output = b"M\0skills/public/alpha/references/guide.md\0"
    reviewed: list[str] = []

    def fake_git_diff(command, **kwargs):
        assert command[-1] == runner.PUBLIC_SKILL_PACKAGE_PATHSPEC
        return _completed(command, stdout=diff_output)

    def fake_review(package: Path, repo_root: Path, python_executable: str) -> int:
        reviewed.append(package.relative_to(repo_root).as_posix())
        return 0

    monkeypatch.setattr(runner.subprocess, "run", fake_git_diff)
    monkeypatch.setattr(runner, "run_review", fake_review)

    exit_code = runner.main(
        [
            "--base-ref",
            "base",
            "--head-ref",
            "head",
            "--repo-root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert reviewed == ["skills/public/alpha"]
    assert "Queued package: skills/public/alpha" in output


def test_main_maps_eval_fixture_changes_to_owner_package(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_skill(tmp_path, "skill-reviewer")
    _write_skill(tmp_path, "skill-reviewer/evals/fixtures/blocked")
    diff_output = b"M\0skills/public/skill-reviewer/evals/fixtures/blocked/SKILL.md\0"
    reviewed: list[str] = []

    def fake_git_diff(command, **kwargs):
        return _completed(command, stdout=diff_output)

    def fake_review(package: Path, repo_root: Path, python_executable: str) -> int:
        reviewed.append(package.relative_to(repo_root).as_posix())
        return 0

    monkeypatch.setattr(runner.subprocess, "run", fake_git_diff)
    monkeypatch.setattr(runner, "run_review", fake_review)

    exit_code = runner.main(
        [
            "--base-ref",
            "base",
            "--head-ref",
            "head",
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert reviewed == ["skills/public/skill-reviewer"]


def test_main_exits_nonzero_when_review_cli_reports_error(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_skill(tmp_path, "bad")
    diff_output = b"M\0skills/public/bad/SKILL.md\0"
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "git":
            return _completed(command, stdout=diff_output)

        assert command == [
            "test-python",
            "-m",
            "deerflow.skills.review.cli",
            "skills/public/bad",
            "--format",
            "text",
            "--fail-on",
            "error",
            "--fail-on-incomplete",
        ]
        assert kwargs["cwd"] == tmp_path
        assert "backend/packages/harness" in kwargs["env"]["PYTHONPATH"]
        assert kwargs["check"] is False
        return _completed(command, returncode=1)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    exit_code = runner.main(
        [
            "--before",
            "before",
            "--after",
            "after",
            "--repo-root",
            str(tmp_path),
            "--python",
            "test-python",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert [call[0] for call in calls] == ["git", "test-python"]
    assert "Failed: skills/public/bad (exit 1)" in output
    assert "One or more skill reviews failed." in output


def test_main_falls_back_to_empty_tree_when_push_before_is_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_skill(tmp_path, "alpha")
    diff_output = b"M\0skills/public/alpha/SKILL.md\0"
    calls: list[list[str]] = []
    reviewed: list[str] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 128, stdout=b"", stderr=b"fatal: bad object before")
        return _completed(command, stdout=diff_output)

    def fake_review(package: Path, repo_root: Path, python_executable: str) -> int:
        reviewed.append(package.relative_to(repo_root).as_posix())
        return 0

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "run_review", fake_review)

    exit_code = runner.main(
        [
            "--before",
            "f" * 40,
            "--after",
            "a" * 40,
            "--repo-root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert reviewed == ["skills/public/alpha"]
    assert calls[1][4:6] == [runner.EMPTY_TREE_SHA, "a" * 40]
    assert "Fallback diff:" in output


def test_is_fully_removed_package_true_when_all_deletions_and_directory_missing(tmp_path: Path) -> None:
    package_rel = PurePosixPath("skills/public/removed")
    assert runner.is_fully_removed_package(package_rel, ["D", "D"], tmp_path) is True


def test_is_fully_removed_package_false_when_directory_still_exists(tmp_path: Path) -> None:
    package_rel = PurePosixPath("skills/public/broken")
    (tmp_path / package_rel).mkdir(parents=True)
    assert runner.is_fully_removed_package(package_rel, ["D", "D"], tmp_path) is False


def test_is_fully_removed_package_false_when_any_status_is_not_a_deletion(tmp_path: Path) -> None:
    package_rel = PurePosixPath("skills/public/partial")
    assert runner.is_fully_removed_package(package_rel, ["D", "M"], tmp_path) is False


def test_is_zero_sha_requires_full_sha_length() -> None:
    assert runner.is_zero_sha("0" * 40) is True
    assert runner.is_zero_sha("0" * 64) is True
    assert runner.is_zero_sha("0") is False
    assert runner.is_zero_sha("f" * 64) is False
