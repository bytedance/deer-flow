#!/usr/bin/env python3
"""Run deterministic skill review for changed public skills."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = REPO_ROOT / "backend" / "packages" / "harness"
if HARNESS_PATH.is_dir():
    sys.path.insert(0, str(HARNESS_PATH))

PUBLIC_SKILL_PACKAGE_PATHSPEC = ":(glob)skills/public/**"
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


@dataclass(frozen=True)
class ChangedPath:
    status: str
    path: PurePosixPath


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    diff_args = build_diff_args(args)

    print(f"[skill-review] Repository: {repo_root}")
    print(f"[skill-review] Diff: git diff {' '.join(diff_args)}")

    result = subprocess.run(
        ["git", "diff", *diff_args, "--", PUBLIC_SKILL_PACKAGE_PATHSPEC],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fallback_args = build_force_push_fallback_diff_args(args)
        if fallback_args is None:
            sys.stderr.write("[skill-review] Failed to collect changed public skill files.\n")
            sys.stderr.write(result.stderr.decode("utf-8", errors="replace"))
            return result.returncode
        sys.stderr.write("[skill-review] Primary push diff failed; falling back to empty-tree comparison.\n")
        sys.stderr.write(result.stderr.decode("utf-8", errors="replace"))
        diff_args = fallback_args
        print(f"[skill-review] Fallback diff: git diff {' '.join(diff_args)}")
        result = subprocess.run(
            ["git", "diff", *diff_args, "--", PUBLIC_SKILL_PACKAGE_PATHSPEC],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            sys.stderr.write("[skill-review] Failed to collect changed public skill files.\n")
            sys.stderr.write(result.stderr.decode("utf-8", errors="replace"))
            return result.returncode

    changes = parse_name_status(result.stdout)
    packages = select_skill_packages(changes, repo_root)
    if not packages:
        print("[skill-review] No changed public skill package files; skipping review.")
        return 0

    print(f"[skill-review] Reviewing {len(packages)} changed public skill package(s).")
    failed = False
    for package in packages:
        if run_review(package, repo_root, args.python) != 0:
            failed = True

    if failed:
        print("[skill-review] One or more skill reviews failed.")
        return 1

    print("[skill-review] All changed public skill packages passed review.")
    return 0


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=("Review public skill packages whose SKILL.md changed in a PR or push diff."))
    parser.add_argument(
        "--base-ref",
        "--base_ref",
        dest="base_ref",
        help="Base ref/SHA for PR-style base...head comparison.",
    )
    parser.add_argument(
        "--head-ref",
        "--head_ref",
        dest="head_ref",
        help="Head ref/SHA for PR-style base...head comparison.",
    )
    parser.add_argument("--before", help="Before SHA for push-style before/after comparison.")
    parser.add_argument("--after", help="After SHA for push-style before/after comparison.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root. Defaults to this script's parent repository.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to invoke python -m deerflow.skills.review.cli.",
    )
    args = parser.parse_args(argv)

    has_pr_args = bool(args.base_ref or args.head_ref)
    has_push_args = bool(args.before or args.after)
    if has_pr_args == has_push_args:
        parser.error("pass either --base-ref/--head-ref or --before/--after, but not both")
    if has_pr_args and not (args.base_ref and args.head_ref):
        parser.error("--base-ref and --head-ref must be provided together")
    if has_push_args and not (args.before and args.after):
        parser.error("--before and --after must be provided together")

    return args


def build_diff_args(args: argparse.Namespace) -> list[str]:
    if args.base_ref and args.head_ref:
        return ["--name-status", "-z", f"{args.base_ref}...{args.head_ref}"]

    before = str(args.before)
    after = str(args.after)
    if is_zero_sha(before):
        return ["--name-status", "-z", EMPTY_TREE_SHA, after]
    return ["--name-status", "-z", before, after]


def build_force_push_fallback_diff_args(args: argparse.Namespace) -> list[str] | None:
    if not args.before or not args.after or is_zero_sha(str(args.before)):
        return None
    return ["--name-status", "-z", EMPTY_TREE_SHA, str(args.after)]


def parse_name_status(output: bytes) -> list[ChangedPath]:
    parts = [part for part in output.split(b"\0") if part]
    changes: list[ChangedPath] = []
    index = 0
    while index < len(parts):
        status = parts[index].decode("utf-8", errors="surrogateescape")
        index += 1
        if not status:
            continue

        path_index = index + 1 if status[0] in {"C", "R"} else index
        if path_index >= len(parts):
            raise ValueError(f"Malformed git diff --name-status output near {status!r}")

        path = parts[path_index].decode("utf-8", errors="surrogateescape")
        changes.append(ChangedPath(status=status, path=PurePosixPath(path)))
        index = path_index + 1

    return changes


def select_skill_packages(changes: Sequence[ChangedPath], repo_root: Path) -> list[Path]:
    package_statuses: dict[PurePosixPath, list[str]] = {}
    resolutions: list[tuple[ChangedPath, PurePosixPath]] = []

    for change in changes:
        if not is_public_skill_package_path(change.path):
            continue

        if change.status.startswith("D") and is_public_skill_md(change.path):
            print(f"[skill-review] Skipping deleted SKILL.md: {change.path}")
            continue

        package_rel = find_public_skill_package(change.path, repo_root)
        if package_rel is None:
            print(f"[skill-review] Skipping path outside public skill package: {change.path}")
            continue

        package_statuses.setdefault(package_rel, []).append(change.status)
        resolutions.append((change, package_rel))

    packages: list[Path] = []
    seen: set[PurePosixPath] = set()

    for _, package_rel in resolutions:
        if package_rel in seen:
            print(f"[skill-review] Already queued package: {package_rel}")
            continue
        seen.add(package_rel)

        if is_fully_removed_package(package_rel, package_statuses[package_rel], repo_root):
            print(f"[skill-review] Skipping fully removed package: {package_rel}")
            continue

        packages.append(repo_root / package_rel)
        print(f"[skill-review] Queued package: {package_rel}")

    return packages


def is_fully_removed_package(package_rel: PurePosixPath, statuses: Sequence[str], repo_root: Path) -> bool:
    """Whether every changed file that resolved to ``package_rel`` was a deletion and the
    package directory itself no longer exists on disk.

    This identifies a whole public skill package being intentionally deleted (all of its
    files removed, not just SKILL.md), as distinct from a package left in a broken/partial
    state (e.g. SKILL.md deleted while other package files remain on disk) — the latter
    must still be reviewed and flagged.
    """
    if not all(status.startswith("D") for status in statuses):
        return False
    return not (repo_root / package_rel).is_dir()


def is_public_skill_md(path: PurePosixPath) -> bool:
    parts = path.parts
    return len(parts) >= 4 and parts[0] == "skills" and parts[1] == "public" and parts[-1] == "SKILL.md" and not _is_eval_fixture_skill_md(path)


def is_public_skill_package_path(path: PurePosixPath) -> bool:
    parts = path.parts
    return len(parts) >= 3 and parts[0] == "skills" and parts[1] == "public"


def find_public_skill_package(path: PurePosixPath, repo_root: Path) -> PurePosixPath | None:
    if not is_public_skill_package_path(path):
        return None

    current = path.parent if path.name else path
    while len(current.parts) >= 3:
        skill_md_rel = current / "SKILL.md"
        if not _is_eval_fixture_skill_md(skill_md_rel) and (repo_root / skill_md_rel).is_file():
            return current
        if len(current.parts) == 3:
            return current
        current = current.parent

    return None


def _is_eval_fixture_skill_md(path: PurePosixPath) -> bool:
    from deerflow.skills.package_paths import is_eval_fixture_skill_md

    return is_eval_fixture_skill_md(path)


def run_review(package: Path, repo_root: Path, python_executable: str) -> int:
    package_rel = package.relative_to(repo_root).as_posix()
    command = [
        python_executable,
        "-m",
        "deerflow.skills.review.cli",
        package_rel,
        "--format",
        "text",
        "--fail-on",
        "error",
        "--fail-on-incomplete",
    ]
    log_command = [
        "python",
        "-m",
        "deerflow.skills.review.cli",
        package_rel,
        "--format",
        "text",
        "--fail-on",
        "error",
        "--fail-on-incomplete",
    ]

    print(f"[skill-review] Reviewing package: {package_rel}")
    print(f"[skill-review] $ {' '.join(log_command)}")
    result = subprocess.run(
        command,
        cwd=repo_root,
        env=review_env(repo_root),
        check=False,
    )
    if result.returncode == 0:
        print(f"[skill-review] Passed: {package_rel}")
    else:
        print(f"[skill-review] Failed: {package_rel} (exit {result.returncode})")
    return result.returncode


def review_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    harness_path = repo_root / "backend" / "packages" / "harness"
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(harness_path) if not existing_pythonpath else f"{harness_path}{os.pathsep}{existing_pythonpath}"
    return env


def is_zero_sha(value: str) -> bool:
    return len(value) in {40, 64} and set(value) == {"0"}


if __name__ == "__main__":
    sys.exit(main())
