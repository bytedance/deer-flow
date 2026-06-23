"""Intersect a git diff with static blocking-IO findings.

Wraps the static detector (`blocking_io_static`) to answer a narrower question:
which blocking-IO candidates does THIS change introduce? A candidate qualifies
when its blocking line is on an added line of the diff, or when the finding is
new versus the merge base — the latter catches exposure created without
touching the blocking line itself (a new async caller making an old sync
helper async-reachable). Used by the `blocking-io-guard` skill as the
deterministic scope step.

Not directly executable: import as `support.detectors.blocking_io_changed` or
run via the CLI shim `scripts/scan_changed_blocking_io.py`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from support.detectors import blocking_io_static as static
from support.detectors.repo_root import resolve_repo_root

REPO_ROOT = resolve_repo_root(Path(__file__))
SCAN_ROOTS = (
    "backend/app",
    "backend/packages/harness/deerflow",
    "backend/scripts",
)

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Map repo-relative path -> set of added line numbers in the new file.

    Accepts any unified diff (with or without `--unified=0`): context lines
    advance the new-file counter, deletions (`-`) and `\\ No newline` markers
    do not. Records only added lines (`+`, not the `+++` header), numbered
    from each hunk's new-file start line; deleted files (`+++ /dev/null`) are
    skipped.
    """
    changed: dict[str, set[int]] = defaultdict(set)
    current_path: str | None = None
    next_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            if target == "/dev/null":
                current_path = None
            else:
                current_path = target[2:] if target.startswith("b/") else target
            next_line = 0
            continue
        match = _HUNK_RE.match(raw)
        if match:
            next_line = int(match.group(1))
            continue
        if not current_path:
            continue
        if raw.startswith("+"):
            changed[current_path].add(next_line)
            next_line += 1
        elif raw.startswith(" ") or raw == "":
            next_line += 1
    return dict(changed)


def changed_python_lines(base: str, repo_root: Path = REPO_ROOT) -> dict[str, set[int]]:
    """Diff `base...HEAD` over scan roots and return added .py lines."""
    cmd = [
        "git",
        "-C",
        str(repo_root),
        "diff",
        "--unified=0",
        "--no-color",
        f"{base}...HEAD",
        "--",
        *SCAN_ROOTS,
    ]
    diff_text = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return {path: lines for path, lines in parse_changed_lines(diff_text).items() if path.endswith(".py")}


def select_findings_on_changed_lines(
    findings: Sequence[dict[str, object]],
    changed_lines: dict[str, set[int]],
) -> list[dict[str, object]]:
    """Keep findings whose (path, line) falls on a changed line."""
    selected: list[dict[str, object]] = []
    for finding in findings:
        location = finding["location"]  # type: ignore[index]
        path = location["path"]  # type: ignore[index]
        line = location["line"]  # type: ignore[index]
        if line in changed_lines.get(path, set()):
            selected.append(finding)
    return selected


def base_python_contents(base: str, paths: Sequence[str], repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """Return each path's content at the merge base of `base` and HEAD.

    Files absent at the merge base (newly added) are omitted, so every head
    finding in them counts as new.
    """
    merge_base = subprocess.run(
        ["git", "-C", str(repo_root), "merge-base", base, "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    contents: dict[str, str] = {}
    for path in paths:
        shown = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"{merge_base}:{path}"],
            capture_output=True,
            text=True,
        )
        if shown.returncode == 0:
            contents[path] = shown.stdout
    return contents


def scan_python_contents(contents: dict[str, str]) -> list[dict[str, object]]:
    """Run the static detector over in-memory sources (repo-relative path -> code)."""
    findings: list[dict[str, object]] = []
    for rel_path in sorted(contents):
        findings.extend(finding.to_dict() for finding in static.scan_source(contents[rel_path], rel_path))
    return findings


def _stable_key(finding: dict[str, object]) -> tuple[str, str, str]:
    location = finding["location"]  # type: ignore[index]
    call = finding["blocking_call"]  # type: ignore[index]
    return (location["path"], location["function"], call["symbol"])  # type: ignore[index]


def select_findings_new_vs_base(
    head_findings: Sequence[dict[str, object]],
    base_findings: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    """Keep head findings whose stable key (path, function, symbol) is absent at base.

    Line numbers shift between revisions, so matching is by stable key only.
    A second identical symbol added inside a function that already had a
    finding collides on the key and is NOT reported here — that case is
    covered by the changed-line selection instead.
    """
    base_keys = {_stable_key(finding) for finding in base_findings}
    return [finding for finding in head_findings if _stable_key(finding) not in base_keys]


def find_changed_blocking_io(base: str, repo_root: Path = REPO_ROOT) -> list[dict[str, object]]:
    """Return static findings this change introduces or touches.

    Union over the changed files of:
    - findings whose blocking line is on an added line of the diff;
    - findings new versus the merge base (a new async caller can expose an
      untouched sync helper — the blocking line itself is not in the diff).
    """
    changed_lines = changed_python_lines(base, repo_root)
    if not changed_lines:
        return []
    files = [repo_root / path for path in changed_lines]
    head_findings = [finding.to_dict() for finding in static.scan_paths(files, repo_root=repo_root)]
    on_changed_lines = select_findings_on_changed_lines(head_findings, changed_lines)
    base_findings = scan_python_contents(base_python_contents(base, sorted(changed_lines), repo_root))
    new_vs_base = select_findings_new_vs_base(head_findings, base_findings)
    selected_keys = {_stable_key(finding) for finding in (*on_changed_lines, *new_vs_base)}
    return [finding for finding in head_findings if _stable_key(finding) in selected_keys]


def format_report(findings: Sequence[dict[str, object]], base: str) -> str:
    if not findings:
        return (
            f"No blocking-IO candidates introduced by this change (base: {base}).\n"
            "Note: async reachability is resolved within each file only. If this change\n"
            "adds an async call into a sync helper defined in another file, check that\n"
            "helper manually (codegraph or git grep) before relying on this empty result."
        )
    lines = [
        f"Blocking-IO candidates introduced/touched by this change (base: {base}): {len(findings)}",
        "",
    ]
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for finding in sorted(findings, key=lambda f: order.get(str(f["priority"]), 9)):
        location = finding["location"]  # type: ignore[index]
        call = finding["blocking_call"]  # type: ignore[index]
        lines.append(f"{finding['priority']} {call['category']}/{call['operation']} {location['path']}:{location['line']} in {location['function']} exposure={finding['event_loop_exposure']}")
        lines.append(f"  symbol: {call['symbol']}")
        if finding.get("code"):
            lines.append(f"  code: {finding['code']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List blocking-IO candidates this change introduces: findings on added lines plus findings new versus the merge base (diff against --base).")
    parser.add_argument("--base", default="origin/main", help="Base ref to diff against (default: origin/main).")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")
    args = parser.parse_args(argv)

    findings = find_changed_blocking_io(args.base)
    if args.format == "json":
        print(json.dumps(findings, indent=2))
    else:
        print(format_report(findings, args.base))
    return 0
