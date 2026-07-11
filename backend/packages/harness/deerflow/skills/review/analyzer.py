"""Deterministic skill package analyzer."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from deerflow.skills.frontmatter import ALLOWED_FRONTMATTER_PROPERTIES, split_skill_markdown
from deerflow.skills.package_paths import is_eval_fixture_path, is_eval_fixture_skill_md
from deerflow.skills.parser import parse_allowed_tools, parse_required_secrets
from deerflow.skills.review.digest import compute_package_digest
from deerflow.skills.review.eval_schema import analyze_eval_manifests
from deerflow.skills.review.models import (
    FACTS_SCHEMA_VERSION,
    SKILLSCAN_SEVERITY_MAP,
    ProfileName,
    make_finding,
    sort_findings,
    summarize_findings,
)
from deerflow.skills.review.resource_graph import build_resource_graph
from deerflow.skills.skillscan.orchestrator import scan_skill_dir


def analyze_skill_package(snapshot: dict[str, Any], *, profile: ProfileName = "deerflow") -> dict[str, Any]:
    """Produce review-facts.v1 from a PackageSnapshot."""
    findings: list[dict[str, Any]] = []
    analyzer_errors: list[dict[str, Any]] = []
    files = {str(entry["path"]): entry for entry in snapshot.get("files", [])}

    skill_entries = [path for path in files if PurePosixPath(path).name == "SKILL.md"]
    root_skill = files.get("SKILL.md")
    declared_name = None
    text_complete = not snapshot.get("truncated")
    not_assessed: list[str] = []

    if not root_skill:
        findings.append(
            make_finding(
                "structure.missing-skill-md",
                severity="blocker",
                message="Package root does not contain SKILL.md.",
                remediation="Add exactly one SKILL.md at the package root.",
            )
        )
    elif root_skill.get("kind") != "text":
        findings.append(
            make_finding(
                "structure.skill-md-not-text",
                severity="blocker",
                path="SKILL.md",
                message="Root SKILL.md is not readable UTF-8 text.",
                remediation="Store SKILL.md as UTF-8 Markdown with YAML frontmatter.",
            )
        )
    else:
        declared_name = _analyze_skill_md(str(root_skill.get("content") or ""), profile=profile, findings=findings)

    for nested in sorted(path for path in skill_entries if path != "SKILL.md" and not is_eval_fixture_skill_md(path)):
        findings.append(
            make_finding(
                "structure.nested-skill-md",
                severity="blocker",
                path=nested,
                message="Nested SKILL.md files are not allowed in a single skill package.",
                remediation="Keep exactly one SKILL.md at the package root.",
            )
        )

    for path, entry in files.items():
        if entry.get("kind") == "symlink":
            findings.append(
                make_finding(
                    "package.symlink",
                    severity="warning",
                    path=path,
                    message="Package contains a symlink entry.",
                    remediation="Replace symlinks with ordinary files inside the skill package.",
                    evidence=entry.get("target"),
                )
            )
        if _is_nested_archive(path):
            findings.append(
                make_finding(
                    "package.nested-archive",
                    severity="warning",
                    path=path,
                    message="Package contains a nested archive.",
                    remediation="Unpack and review nested archives before packaging the skill.",
                )
            )
        if _is_hidden_sensitive_path(path):
            findings.append(
                make_finding(
                    "package.hidden-sensitive-file",
                    severity="warning",
                    path=path,
                    message="Package contains a hidden sensitive file.",
                    remediation="Remove hidden credential or package-manager config files.",
                )
            )

    resource_graph, resource_findings = build_resource_graph(snapshot)
    findings.extend(resource_findings)

    evals, eval_findings = analyze_eval_manifests(snapshot)
    findings.extend(eval_findings)

    try:
        findings.extend(_scan_with_skillscan(snapshot))
    except Exception as exc:
        analyzer_errors.append({"code": "skillscan_failed", "path": None, "message": type(exc).__name__})
        not_assessed.append("skillscan")

    if snapshot.get("truncated"):
        not_assessed.append("full_package")

    findings = sort_findings(findings)
    package_digest = compute_package_digest(snapshot)
    subject = {
        "display_ref": snapshot.get("subject", {}).get("display_ref"),
        "source": snapshot.get("subject", {}).get("source"),
        "category": snapshot.get("subject", {}).get("category"),
        "declared_name": declared_name,
        "package_digest": package_digest,
    }
    return {
        "schema_version": FACTS_SCHEMA_VERSION,
        "subject": subject,
        "profile": profile,
        "completeness": {
            "package_enumerated": not any(error.get("code") == "root_not_found" for error in snapshot.get("reader_errors", [])),
            "text_content_complete": text_complete,
            "truncated": bool(snapshot.get("truncated")),
            "not_assessed": sorted(set(not_assessed)),
        },
        "summary": summarize_findings(findings),
        "findings": findings,
        "resources": resource_graph,
        "evals": evals,
        "reader_errors": snapshot.get("reader_errors", []),
        "analyzer_errors": analyzer_errors,
    }


def _analyze_skill_md(content: str, *, profile: ProfileName, findings: list[dict[str, Any]]) -> str | None:
    parts, error = split_skill_markdown(content)
    if error or parts is None:
        findings.append(
            make_finding(
                "structure.invalid-frontmatter",
                severity="blocker",
                path="SKILL.md",
                message=error or "Invalid frontmatter format.",
                remediation="Use YAML frontmatter bounded by --- fences with name and description fields.",
            )
        )
        return None

    metadata = parts.metadata
    unexpected = sorted(set(metadata) - ALLOWED_FRONTMATTER_PROPERTIES)
    if unexpected:
        findings.append(
            make_finding(
                "structure.unknown-frontmatter-field",
                severity="warning",
                path="SKILL.md",
                message=f"Unknown frontmatter field(s): {', '.join(unexpected)}",
                remediation="Remove unsupported fields or add them to the shared DeerFlow frontmatter schema.",
                evidence=unexpected,
            )
        )

    name = metadata.get("name")
    declared_name = name.strip() if isinstance(name, str) else None
    if not declared_name:
        findings.append(
            make_finding(
                "structure.missing-name",
                severity="blocker",
                path="SKILL.md",
                message="Frontmatter is missing a non-empty name.",
                remediation="Add a hyphen-case skill name.",
            )
        )
    elif not _valid_skill_name(declared_name):
        findings.append(
            make_finding(
                "structure.invalid-name",
                severity="error",
                path="SKILL.md",
                message="Skill name must be hyphen-case using lowercase letters, digits, and hyphens.",
                remediation="Rename the skill using lowercase hyphen-case.",
                evidence=declared_name,
            )
        )

    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        findings.append(
            make_finding(
                "structure.missing-description",
                severity="blocker",
                path="SKILL.md",
                message="Frontmatter is missing a non-empty description.",
                remediation="Add a concise description that states what the skill does and when to invoke it.",
            )
        )
    elif len(description.strip()) > 1024:
        findings.append(
            make_finding(
                "structure.description-too-long",
                severity="error",
                path="SKILL.md",
                message="Description exceeds DeerFlow's 1024 character limit.",
                remediation="Shorten the description and move detailed guidance into the body.",
            )
        )

    body = parts.body.strip()
    if not body:
        findings.append(
            make_finding(
                "structure.empty-body",
                severity="error",
                path="SKILL.md",
                message="SKILL.md has no instruction body after frontmatter.",
                remediation="Add executable workflow instructions after the frontmatter.",
            )
        )

    try:
        parse_allowed_tools(metadata.get("allowed-tools"), Path("SKILL.md"))
    except ValueError as exc:
        findings.append(
            make_finding(
                "structure.invalid-allowed-tools",
                severity="error",
                path="SKILL.md",
                message=str(exc),
                remediation="Declare allowed-tools as a YAML list of non-empty strings.",
            )
        )

    try:
        parse_required_secrets(metadata.get("required-secrets"), Path("SKILL.md"))
    except ValueError as exc:
        findings.append(
            make_finding(
                "structure.invalid-required-secrets",
                severity="error",
                path="SKILL.md",
                message=str(exc),
                remediation="Declare required-secrets as a YAML list.",
            )
        )

    if "secrets-autonomous" in metadata and not isinstance(metadata.get("secrets-autonomous"), bool):
        findings.append(
            make_finding(
                "structure.invalid-secrets-autonomous",
                severity="error",
                path="SKILL.md",
                message="secrets-autonomous must be a boolean.",
                remediation="Use true or false for secrets-autonomous.",
            )
        )

    if profile == "agentskills":
        _add_agentskills_findings(metadata, declared_name, findings)

    return declared_name


def _add_agentskills_findings(metadata: dict[str, Any], declared_name: str | None, findings: list[dict[str, Any]]) -> None:
    description = metadata.get("description")
    if isinstance(description, str) and len(description.strip()) > 200:
        findings.append(
            make_finding(
                "agentskills.description-length",
                severity="warning",
                source="review-core",
                profile="agentskills",
                path="SKILL.md",
                message="Description is longer than the Agent Skills recommended display length.",
                remediation="Keep the description concise and move detail into the body.",
            )
        )
    if declared_name and len(declared_name) > 64:
        findings.append(
            make_finding(
                "agentskills.name-length",
                severity="warning",
                source="review-core",
                profile="agentskills",
                path="SKILL.md",
                message="Skill name is longer than the portability profile recommends.",
                remediation="Use a shorter package name for cross-client portability.",
            )
        )


def _scan_with_skillscan(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    files = [entry for entry in snapshot.get("files", []) if entry.get("kind") == "text" and not is_eval_fixture_path(str(entry.get("path") or ""))]
    if not files:
        return []
    with tempfile.TemporaryDirectory(prefix="skill-review-") as tmp:
        root = Path(tmp)
        for entry in files:
            rel = str(entry["path"])
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(entry.get("content") or ""), encoding="utf-8")
        result = scan_skill_dir(root)
    findings: list[dict[str, Any]] = []
    for finding in result.get("findings", []):
        severity = SKILLSCAN_SEVERITY_MAP.get(str(finding.get("severity")), "warning")
        findings.append(
            make_finding(
                str(finding.get("rule_id")),
                source="skillscan",
                profile="deerflow",
                severity=severity,
                path=finding.get("file"),
                line=finding.get("line"),
                message=str(finding.get("message")),
                remediation=str(finding.get("remediation")),
                evidence=finding.get("evidence"),
                extra={"skillscan_severity": finding.get("severity")},
            )
        )
    for error in result.get("scanner_errors", []):
        findings.append(
            make_finding(
                "skillscan.scanner-error",
                source="skillscan",
                severity="warning",
                message="SkillScan reported an analyzer error.",
                remediation="Inspect the referenced file and rerun the review.",
                evidence=str(error),
            )
        )
    return findings


def _valid_skill_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)) and len(name) <= 64


def _is_nested_archive(path: str) -> bool:
    lowered = path.lower()
    return lowered.endswith((".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".7z", ".rar", ".whl"))


def _is_hidden_sensitive_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return any(part in {".env", ".npmrc", ".pypirc", ".netrc"} for part in parts)
