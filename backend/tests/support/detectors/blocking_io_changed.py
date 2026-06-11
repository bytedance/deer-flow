"""Intersect a git diff with static blocking-IO findings.

Wraps the static detector (`blocking_io_static`) to answer a narrower question:
which blocking-IO candidates does THIS change introduce or touch on its added
lines? Used by the `blocking-io-guard` skill as the deterministic L1 scope step.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from support.detectors import blocking_io_static as static

REPO_ROOT = Path(__file__).resolve().parents[4]
SCAN_ROOTS = (
    "backend/app",
    "backend/packages/harness/deerflow",
    "backend/scripts",
)

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Map repo-relative path -> set of added line numbers in the new file.

    Expects `git diff --unified=0` output. Records only added lines (`+`, not
    the `+++` header), numbered from each hunk's new-file start line. Deletions
    (`-`) do not advance the new-file counter; deleted files (`+++ /dev/null`)
    are skipped.
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
            continue
        match = _HUNK_RE.match(raw)
        if match:
            next_line = int(match.group(1))
            continue
        if current_path and raw.startswith("+") and not raw.startswith("+++"):
            changed[current_path].add(next_line)
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


def find_changed_blocking_io(base: str, repo_root: Path = REPO_ROOT) -> list[dict[str, object]]:
    """Return static findings that land on lines this change added/modified."""
    changed_lines = changed_python_lines(base, repo_root)
    if not changed_lines:
        return []
    files = [repo_root / path for path in changed_lines]
    findings = [finding.to_dict() for finding in static.scan_paths(files, repo_root=repo_root)]
    return select_findings_on_changed_lines(findings, changed_lines)


def format_report(findings: Sequence[dict[str, object]], base: str) -> str:
    if not findings:
        return f"No blocking-IO candidates on changed lines (base: {base})."
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
    parser = argparse.ArgumentParser(description="List blocking-IO candidates on this change's added lines (diff against --base).")
    parser.add_argument("--base", default="origin/main", help="Base ref to diff against (default: origin/main).")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")
    args = parser.parse_args(argv)

    findings = find_changed_blocking_io(args.base)
    if args.format == "json":
        print(json.dumps(findings, indent=2))
    else:
        print(format_report(findings, args.base))
    return 0


if __name__ == "__main__":
    sys.exit(main())
