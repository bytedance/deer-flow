"""CLI entry point for deterministic skill review facts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from deerflow.skills.review.analyzer import analyze_skill_package
from deerflow.skills.review.models import DEFAULT_PACKAGE_LIMITS, SEVERITY_RANK, PackageLimits, stable_json_dumps
from deerflow.skills.review.readers import ArchivePackageReader, LocalDirectoryReader


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a skill package without executing it.")
    parser.add_argument("target", help="Skill directory or .skill archive to review")
    parser.add_argument("--profile", choices=["deerflow", "agentskills"], default="deerflow")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument(
        "--fail-on",
        choices=["never", "warning", "error", "blocker"],
        default="never",
        help="Exit non-zero when findings are at this severity or worse.",
    )
    parser.add_argument(
        "--fail-on-incomplete",
        action="store_true",
        help="Exit non-zero when package completeness indicates content was not assessed.",
    )
    parser.add_argument("--max-files", type=int, default=DEFAULT_PACKAGE_LIMITS.max_files)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_PACKAGE_LIMITS.max_file_bytes)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_PACKAGE_LIMITS.max_total_bytes)
    args = parser.parse_args(argv)

    limits = PackageLimits(args.max_files, args.max_file_bytes, args.max_total_bytes)
    target = Path(args.target)
    reader = ArchivePackageReader(target, limits=limits) if target.suffix == ".skill" else LocalDirectoryReader(target, limits=limits)
    facts = analyze_skill_package(reader.read(), profile=args.profile)

    if args.format == "json":
        print(stable_json_dumps(facts))
    else:
        _print_text(facts)

    return _exit_code(facts, args.fail_on, fail_on_incomplete=args.fail_on_incomplete)


def _print_text(facts: dict[str, Any]) -> None:
    subject = facts.get("subject", {})
    summary = facts.get("summary", {})
    completeness = facts.get("completeness", {})
    print(f"Subject: {subject.get('display_ref')}")
    print(f"Digest: {subject.get('package_digest')}")
    print(f"Summary: {summary.get('blockers')} blocker(s), {summary.get('errors')} error(s), {summary.get('warnings')} warning(s), {summary.get('infos')} info(s)")
    print(f"Completeness: truncated={completeness.get('truncated')}, not_assessed={','.join(completeness.get('not_assessed') or []) or '(none)'}")
    for finding in facts.get("findings", []):
        location = finding.get("path") or "<package>"
        if finding.get("line") is not None:
            location = f"{location}:{finding['line']}"
        print(f"- {finding.get('severity')} {finding.get('rule_id')} at {location}: {finding.get('message')}")


def _exit_code(facts: dict[str, Any], fail_on: str, *, fail_on_incomplete: bool = False) -> int:
    if fail_on_incomplete and facts.get("completeness", {}).get("not_assessed"):
        return 1
    if fail_on == "never":
        return 0
    threshold = SEVERITY_RANK[fail_on]
    for finding in facts.get("findings", []):
        if SEVERITY_RANK.get(str(finding.get("severity")), 99) <= threshold:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
