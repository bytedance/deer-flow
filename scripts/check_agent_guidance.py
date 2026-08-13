#!/usr/bin/env python3
"""Validate DeerFlow's automatically loaded agent guidance.

The checker intentionally uses only the Python standard library so it can run
before project dependencies are installed. Budgets are measured after newline
normalization as UTF-8 bytes; ordinary linked docs are loaded on demand and do
not count toward an AGENTS.md inheritance chain.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Literal, NamedTuple
from urllib.parse import unquote, urlsplit

ROOT_AGENT_SOFT = 12 * 1024
ROOT_AGENT_HARD = 16 * 1024
MODULE_AGENT_SOFT = 24 * 1024
MODULE_AGENT_HARD = 32 * 1024
NESTED_AGENT_SOFT = 12 * 1024
NESTED_AGENT_HARD = 16 * 1024
CHAIN_SOFT = 40 * 1024
CHAIN_HARD = 48 * 1024
CLAUDE_HARD = 1024
LONG_LINE_CHARS = 500

_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))")
_MALFORMED_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+#{1,6}(?:\s|$)")
_IMPORT_RE = re.compile(r"^@\S+\.md$")


class Finding(NamedTuple):
    severity: Literal["error", "warning"]
    code: str
    path: PurePosixPath
    line: int
    message: str


def normalized_utf8_size(text: str) -> int:
    """Return UTF-8 bytes after normalizing CRLF/CR newlines to LF."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return len(normalized.encode("utf-8"))


def agent_budget(path: PurePosixPath) -> tuple[int, int]:
    """Return the soft and hard byte limits for one AGENTS.md."""

    if path == PurePosixPath("AGENTS.md"):
        return ROOT_AGENT_SOFT, ROOT_AGENT_HARD
    if len(path.parts) == 2:
        return MODULE_AGENT_SOFT, MODULE_AGENT_HARD
    return NESTED_AGENT_SOFT, NESTED_AGENT_HARD


def guidance_paths(paths: Iterable[PurePosixPath]) -> set[PurePosixPath]:
    """Keep exact guidance basenames, excluding names such as GITHUB_AGENTS.md."""

    return {path for path in paths if path.name in {"AGENTS.md", "CLAUDE.md"}}


def _is_descendant_or_same(path: PurePosixPath, parent: PurePosixPath) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _ancestor_agent_paths(
    target: PurePosixPath,
    agent_paths: Iterable[PurePosixPath],
) -> list[PurePosixPath]:
    target_dir = target.parent
    ancestors = [
        candidate
        for candidate in agent_paths
        if _is_descendant_or_same(target_dir, candidate.parent)
    ]
    return sorted(ancestors, key=lambda item: (len(item.parts), item.as_posix()))


def _chain_size(target: PurePosixPath, files: Mapping[PurePosixPath, str]) -> int:
    agents = [path for path in files if path.name == "AGENTS.md"]
    return sum(normalized_utf8_size(files[path]) for path in _ancestor_agent_paths(target, agents))


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
        grows_legacy_violation = base_actual is None or actual > base_actual
        if grows_legacy_violation:
            return Finding(
                "error",
                code,
                path,
                1,
                f"{label} is {actual} bytes; hard limit is {hard}. Remove or move details before adding more guidance.",
            )
        if relevant_change:
            return Finding(
                "warning",
                code,
                path,
                1,
                f"{label} remains above the {hard}-byte hard limit at {actual} bytes, but did not grow from {base_actual}.",
            )
        return None
    if actual > soft and relevant_change:
        return Finding(
            "warning",
            code,
            path,
            1,
            f"{label} is {actual} bytes; soft limit is {soft} and hard limit is {hard}. Split before the next substantive expansion.",
        )
    return None


def _non_fenced_lines(text: str) -> Iterable[tuple[int, str]]:
    fence_char: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[0]
            if fence_char is None:
                fence_char = marker
            elif fence_char == marker:
                fence_char = None
            continue
        if fence_char is None:
            yield line_number, line


def _validate_wrapper(path: PurePosixPath, text: str) -> list[Finding]:
    imports = [
        line.strip()
        for _, line in _non_fenced_lines(text)
        if _IMPORT_RE.fullmatch(line.strip())
    ]
    if imports == ["@AGENTS.md"]:
        return []
    return [
        Finding(
            "error",
            "AG005",
            path,
            1,
            "CLAUDE.md must contain exactly one standalone @AGENTS.md import and no other Markdown imports.",
        )
    ]


def _validate_local_links(repo_root: Path, path: PurePosixPath, text: str) -> list[Finding]:
    findings: list[Finding] = []
    resolved_root = repo_root.resolve()
    source_dir = (repo_root / Path(path.parent.as_posix())).resolve()
    for line_number, line in _non_fenced_lines(text):
        for match in _MARKDOWN_LINK_RE.finditer(line):
            raw_target = (match.group(1) or match.group(2) or "").strip()
            parsed = urlsplit(raw_target)
            if (
                not raw_target
                or raw_target.startswith(("#", "/"))
                or parsed.scheme
                or parsed.netloc
            ):
                continue
            target_path = unquote(parsed.path)
            if not target_path:
                continue
            resolved_target = (source_dir / target_path).resolve()
            if not resolved_target.is_relative_to(resolved_root):
                findings.append(
                    Finding(
                        "error",
                        "AG003",
                        path,
                        line_number,
                        f"Local link escapes the repository: {raw_target}",
                    )
                )
            elif not resolved_target.exists():
                findings.append(
                    Finding(
                        "error",
                        "AG003",
                        path,
                        line_number,
                        f"Local link target does not exist: {raw_target}",
                    )
                )
    return findings


def _validate_changed_markdown(
    path: PurePosixPath,
    text: str,
    *,
    check_long_lines: bool,
) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in _non_fenced_lines(text):
        if check_long_lines and len(line) > LONG_LINE_CHARS:
            findings.append(
                Finding(
                    "warning",
                    "AG007",
                    path,
                    line_number,
                    f"Non-code line has {len(line)} characters; split lines longer than {LONG_LINE_CHARS} characters for reviewability.",
                )
            )
        if _MALFORMED_HEADING_RE.match(line):
            findings.append(
                Finding(
                    "error",
                    "AG008",
                    path,
                    line_number,
                    "Malformed Markdown heading contains a second heading marker.",
                )
            )
    return findings


def analyze(
    repo_root: Path,
    head_files: Mapping[PurePosixPath, str],
    *,
    base_files: Mapping[PurePosixPath, str] | None = None,
    changed_paths: set[PurePosixPath] | None = None,
) -> list[Finding]:
    """Analyze one repository snapshot and return deterministic findings."""

    findings: list[Finding] = []
    head_guidance = guidance_paths(head_files)
    head_agents = {path for path in head_guidance if path.name == "AGENTS.md"}
    head_claude = {path for path in head_guidance if path.name == "CLAUDE.md"}
    base_files = base_files or {}

    root_agent = PurePosixPath("AGENTS.md")
    root_wrapper = PurePosixPath("CLAUDE.md")
    if root_agent not in head_agents and root_wrapper not in head_claude:
        findings.append(
            Finding(
                "error",
                "AG004",
                root_agent,
                1,
                "Repository root must keep an AGENTS.md and CLAUDE.md guidance pair.",
            )
        )

    for agent_path in sorted(head_agents):
        wrapper = agent_path.with_name("CLAUDE.md")
        if wrapper not in head_claude:
            findings.append(
                Finding("error", "AG004", agent_path, 1, f"Missing sibling wrapper: {wrapper.as_posix()}")
            )
    for wrapper_path in sorted(head_claude):
        agent = wrapper_path.with_name("AGENTS.md")
        if agent not in head_agents:
            findings.append(
                Finding("error", "AG004", wrapper_path, 1, f"Missing sibling guidance: {agent.as_posix()}")
            )
        findings.extend(_validate_wrapper(wrapper_path, head_files[wrapper_path]))
        wrapper_size = normalized_utf8_size(head_files[wrapper_path])
        if wrapper_size > CLAUDE_HARD:
            findings.append(
                Finding(
                    "error",
                    "AG006",
                    wrapper_path,
                    1,
                    f"CLAUDE.md is {wrapper_size} bytes; thin-wrapper hard limit is {CLAUDE_HARD}.",
                )
            )

    base_agent_paths = {path for path in base_files if path.name == "AGENTS.md"}
    for agent_path in sorted(head_agents):
        actual = normalized_utf8_size(head_files[agent_path])
        soft, hard = agent_budget(agent_path)
        base_actual = (
            normalized_utf8_size(base_files[agent_path])
            if agent_path in base_files
            else None
        )
        finding = _budget_finding(
            code="AG001",
            path=agent_path,
            actual=actual,
            soft=soft,
            hard=hard,
            base_actual=base_actual,
            relevant_change=_relevant_change([agent_path], changed_paths),
            label="AGENTS.md",
        )
        if finding:
            findings.append(finding)

        chain_paths = _ancestor_agent_paths(agent_path, head_agents)
        chain_actual = sum(normalized_utf8_size(head_files[path]) for path in chain_paths)
        base_chain_paths = _ancestor_agent_paths(agent_path, base_agent_paths)
        base_chain_actual = (
            sum(normalized_utf8_size(base_files[path]) for path in base_chain_paths)
            if base_files
            else None
        )
        chain_finding = _budget_finding(
            code="AG002",
            path=agent_path,
            actual=chain_actual,
            soft=CHAIN_SOFT,
            hard=CHAIN_HARD,
            base_actual=base_chain_actual,
            relevant_change=_relevant_change(chain_paths, changed_paths),
            label="Inherited AGENTS.md chain",
        )
        if chain_finding:
            findings.append(chain_finding)

    markdown_paths = {
        path
        for path in head_files
        if path.suffix.lower() == ".md"
        and (path in head_guidance or changed_paths is None or path in changed_paths)
    }
    for path in sorted(markdown_paths):
        text = head_files[path]
        findings.extend(_validate_local_links(repo_root, path, text))
        if changed_paths is None or path in changed_paths:
            findings.extend(
                _validate_changed_markdown(
                    path,
                    text,
                    check_long_lines=path in head_guidance,
                )
            )

    return sorted(findings, key=lambda finding: (finding.path.as_posix(), finding.line, finding.code, finding.severity))


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


def _parse_nul_paths(output: bytes) -> set[PurePosixPath]:
    return {
        PurePosixPath(item.decode("utf-8", errors="surrogateescape"))
        for item in output.split(b"\0")
        if item
    }


def _worktree_paths(repo_root: Path) -> set[PurePosixPath]:
    return _parse_nul_paths(
        _run_git(repo_root, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    )


def _changed_paths(
    repo_root: Path,
    base_ref: str | None,
    head_ref: str | None,
    *,
    use_merge_base: bool,
) -> set[PurePosixPath]:
    if base_ref and head_ref:
        if set(base_ref) == {"0"}:
            return _worktree_paths(repo_root)
        revision_range = (
            f"{base_ref}...{head_ref}" if use_merge_base else f"{base_ref}..{head_ref}"
        )
        return _parse_nul_paths(
            _run_git(repo_root, ["diff", "--name-only", "-z", revision_range, "--"])
        )
    tracked_changes = _parse_nul_paths(
        _run_git(repo_root, ["diff", "--name-only", "-z", "HEAD", "--"])
    )
    untracked = _parse_nul_paths(
        _run_git(repo_root, ["ls-files", "--others", "--exclude-standard", "-z"])
    )
    return tracked_changes | untracked


def _load_worktree_files(
    repo_root: Path,
    all_paths: set[PurePosixPath],
    changed_paths: set[PurePosixPath],
) -> dict[PurePosixPath, str]:
    selected = guidance_paths(all_paths) | {
        path for path in changed_paths if path.suffix.lower() == ".md"
    }
    files: dict[PurePosixPath, str] = {}
    for path in selected:
        local_path = repo_root / Path(path.as_posix())
        if local_path.is_file():
            files[path] = local_path.read_text(encoding="utf-8")
    return files


def _load_ref_guidance(repo_root: Path, ref: str | None) -> dict[PurePosixPath, str]:
    if not ref or set(ref) == {"0"}:
        return {}
    paths = guidance_paths(
        _parse_nul_paths(_run_git(repo_root, ["ls-tree", "-r", "--name-only", "-z", ref]))
    )
    files: dict[PurePosixPath, str] = {}
    for path in paths:
        raw = _run_git(repo_root, ["show", f"{ref}:{path.as_posix()}"])
        files[path] = raw.decode("utf-8")
    return files


def _annotation_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _print_finding(finding: Finding, github_annotations: bool) -> None:
    location = f"{finding.path.as_posix()}:{finding.line}"
    if github_annotations:
        level = "error" if finding.severity == "error" else "warning"
        print(
            f"::{level} file={_annotation_escape(finding.path.as_posix())},line={finding.line},title={finding.code}::{_annotation_escape(finding.message)}"
        )
    print(f"{finding.severity.upper()} {finding.code} {location} — {finding.message}")


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
        all_paths = _worktree_paths(repo_root)
        changed = _changed_paths(
            repo_root,
            base_ref,
            head_ref,
            use_merge_base=bool(args.base_ref),
        )
        head_files = _load_worktree_files(repo_root, all_paths, changed)
        base_files = _load_ref_guidance(repo_root, base_ref)
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
    agents = sum(path.name == "AGENTS.md" for path in guidance_paths(head_files))
    wrappers = sum(path.name == "CLAUDE.md" for path in guidance_paths(head_files))
    print(f"Agent guidance check: {agents} AGENTS.md, {wrappers} CLAUDE.md, {errors} errors, {warnings} warnings.")
    return 1 if errors or (warnings and args.strict_warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
