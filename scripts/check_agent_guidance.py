#!/usr/bin/env python3
"""Check the size of directory-scoped AGENTS.md instruction chains."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Literal, NamedTuple

ROOT_SOFT = 16 * 1024
ROOT_HARD = 20 * 1024
MODULE_SOFT = 24 * 1024
MODULE_HARD = 32 * 1024
LOCAL_SOFT = 40 * 1024
LOCAL_HARD = 48 * 1024
CHAIN_SOFT = 80 * 1024
CHAIN_HARD = 96 * 1024


class Finding(NamedTuple):
    severity: Literal["error", "warning"]
    code: str
    path: PurePosixPath
    message: str


def normalized_utf8_size(text: str) -> int:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return len(normalized.encode("utf-8"))


def agent_budget(path: PurePosixPath) -> tuple[int, int]:
    if path == PurePosixPath("AGENTS.md"):
        return ROOT_SOFT, ROOT_HARD
    if len(path.parts) == 2:
        return MODULE_SOFT, MODULE_HARD
    return LOCAL_SOFT, LOCAL_HARD


def guidance_paths(paths: Iterable[PurePosixPath]) -> set[PurePosixPath]:
    return {path for path in paths if path.name == "AGENTS.md"}


def _is_descendant_or_same(path: PurePosixPath, parent: PurePosixPath) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _ancestor_agents(
    target: PurePosixPath,
    candidates: Iterable[PurePosixPath],
) -> list[PurePosixPath]:
    target_dir = target.parent
    ancestors = [
        candidate
        for candidate in candidates
        if _is_descendant_or_same(target_dir, candidate.parent)
    ]
    return sorted(ancestors, key=lambda item: (len(item.parts), item.as_posix()))


def _relevant_change(
    paths: Iterable[PurePosixPath],
    changed_paths: set[PurePosixPath] | None,
) -> bool:
    return changed_paths is None or any(path in changed_paths for path in paths)


def _budget_finding(
    *,
    code: str,
    path: PurePosixPath,
    actual: int,
    soft: int,
    hard: int,
    base_actual: int | None,
    relevant_change: bool,
    label: str,
) -> Finding | None:
    if actual > hard:
        if base_actual is None or actual > base_actual:
            return Finding(
                "error",
                code,
                path,
                f"{label} is {actual} bytes; hard limit is {hard}. Remove inherited or local instructions.",
            )
        if relevant_change:
            return Finding(
                "warning",
                code,
                path,
                f"{label} remains above {hard} bytes at {actual}, but did not grow from {base_actual}.",
            )
        return None
    if actual > soft and relevant_change:
        return Finding(
            "warning",
            code,
            path,
            f"{label} is {actual} bytes; soft limit is {soft} and hard limit is {hard}.",
        )
    return None


def analyze(
    repo_root: Path,
    head_files: Mapping[PurePosixPath, str],
    *,
    base_files: Mapping[PurePosixPath, str] | None = None,
    changed_paths: set[PurePosixPath] | None = None,
) -> list[Finding]:
    """Analyze AGENTS instructions. ``repo_root`` is kept for a stable test API."""

    del repo_root
    findings: list[Finding] = []
    agents = guidance_paths(head_files)
    base_files = base_files or {}
    base_agents = guidance_paths(base_files)

    for path in sorted(agents):
        actual = normalized_utf8_size(head_files[path])
        soft, hard = agent_budget(path)
        base_actual = normalized_utf8_size(base_files[path]) if path in base_files else None
        file_finding = _budget_finding(
            code="AG001",
            path=path,
            actual=actual,
            soft=soft,
            hard=hard,
            base_actual=base_actual,
            relevant_change=_relevant_change([path], changed_paths),
            label="AGENTS.md",
        )
        if file_finding:
            findings.append(file_finding)

        chain = _ancestor_agents(path, agents)
        chain_actual = sum(normalized_utf8_size(head_files[item]) for item in chain)
        base_chain = _ancestor_agents(path, base_agents)
        base_chain_actual = (
            sum(normalized_utf8_size(base_files[item]) for item in base_chain)
            if base_files
            else None
        )
        chain_finding = _budget_finding(
            code="AG002",
            path=path,
            actual=chain_actual,
            soft=CHAIN_SOFT,
            hard=CHAIN_HARD,
            base_actual=base_chain_actual,
            relevant_change=_relevant_change(chain, changed_paths),
            label="Effective AGENTS.md chain",
        )
        if chain_finding:
            findings.append(chain_finding)

    return sorted(findings, key=lambda finding: (finding.path.as_posix(), finding.code))


def _run_git(repo_root: Path, args: Sequence[str]) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _parse_paths(output: bytes) -> set[PurePosixPath]:
    return {
        PurePosixPath(item.decode("utf-8", errors="surrogateescape"))
        for item in output.split(b"\0")
        if item
    }


def _worktree_paths(repo_root: Path) -> set[PurePosixPath]:
    return _parse_paths(
        _run_git(repo_root, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    )


def _load_worktree_agents(repo_root: Path) -> dict[PurePosixPath, str]:
    files: dict[PurePosixPath, str] = {}
    for path in guidance_paths(_worktree_paths(repo_root)):
        local_path = repo_root / Path(path.as_posix())
        if local_path.is_file():
            files[path] = local_path.read_text(encoding="utf-8")
    return files


def _load_ref_agents(repo_root: Path, ref: str | None) -> dict[PurePosixPath, str]:
    if not ref or set(ref) == {"0"}:
        return {}
    paths = guidance_paths(
        _parse_paths(_run_git(repo_root, ["ls-tree", "-r", "--name-only", "-z", ref]))
    )
    return {
        path: _run_git(repo_root, ["show", f"{ref}:{path.as_posix()}"]).decode("utf-8")
        for path in paths
    }


def _changed_paths(
    repo_root: Path,
    base_ref: str | None,
    head_ref: str | None,
    *,
    use_merge_base: bool,
) -> set[PurePosixPath]:
    if base_ref and head_ref:
        if set(base_ref) == {"0"}:
            return set(_load_ref_agents(repo_root, head_ref))
        revision_range = (
            f"{base_ref}...{head_ref}" if use_merge_base else f"{base_ref}..{head_ref}"
        )
        return guidance_paths(
            _parse_paths(
                _run_git(repo_root, ["diff", "--name-only", "-z", revision_range, "--"])
            )
        )
    tracked = _parse_paths(_run_git(repo_root, ["diff", "--name-only", "-z", "HEAD", "--"]))
    untracked = _parse_paths(
        _run_git(repo_root, ["ls-files", "--others", "--exclude-standard", "-z"])
    )
    return guidance_paths(tracked | untracked)


def _print_finding(finding: Finding, github_annotations: bool) -> None:
    if github_annotations:
        level = "error" if finding.severity == "error" else "warning"
        print(f"::{level} file={finding.path.as_posix()},line=1,title={finding.code}::{finding.message}")
    print(
        f"{finding.severity.upper()} {finding.code} {finding.path.as_posix()}:1 — {finding.message}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument("--before")
    parser.add_argument("--after")
    parser.add_argument("--github-annotations", action="store_true")
    parser.add_argument("--strict-warnings", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if bool(args.base_ref) != bool(args.head_ref):
        raise SystemExit("--base-ref and --head-ref must be provided together")
    if bool(args.before) != bool(args.after):
        raise SystemExit("--before and --after must be provided together")
    if args.base_ref and args.before:
        raise SystemExit("choose either --base-ref/--head-ref or --before/--after")

    repo_root = args.repo_root.resolve()
    base_ref = args.base_ref or args.before
    head_ref = args.head_ref or args.after
    try:
        if head_ref:
            head_files = _load_ref_agents(repo_root, head_ref)
            base_files = _load_ref_agents(repo_root, base_ref)
        else:
            head_files = _load_worktree_agents(repo_root)
            base_files = {}
        changed = _changed_paths(
            repo_root,
            base_ref,
            head_ref,
            use_merge_base=bool(args.base_ref),
        )
        findings = analyze(
            repo_root,
            head_files,
            base_files=base_files if base_ref else None,
            changed_paths=changed,
        )
    except (OSError, RuntimeError, UnicodeError) as exc:
        print(f"ERROR AG000 {exc}", file=sys.stderr)
        return 1

    for finding in findings:
        _print_finding(finding, args.github_annotations)
    errors = sum(finding.severity == "error" for finding in findings)
    warnings = sum(finding.severity == "warning" for finding in findings)
    print(f"Agent guidance check: {len(head_files)} AGENTS.md, {errors} errors, {warnings} warnings.")
    return 1 if errors or (warnings and args.strict_warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
