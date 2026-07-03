"""Data contracts for DeerFlow SkillScan."""

from __future__ import annotations

from typing import Literal, TypedDict

FindingCategory = Literal["package", "secret", "declaration", "code", "network_resource", "supply_chain", "runtime", "policy"]
FindingSeverity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
FindingConfidence = Literal["HIGH", "MEDIUM", "LOW"]
ScanEntrypoint = Literal["archive_install", "archive_update", "agent_create", "agent_edit", "agent_patch", "agent_write_file", "cli", "ci", "rescan"]


class SecurityFinding(TypedDict):
    rule_id: str
    category: FindingCategory
    severity: FindingSeverity
    confidence: FindingConfidence
    file: str | None
    line: int | None
    column: int | None
    message: str
    remediation: str
    evidence: str | None
    fingerprint: str
    analyzer: str
    metadata: dict[str, str]


class ScanResult(TypedDict):
    findings: list[SecurityFinding]
    blocked: bool
    warnings: list[SecurityFinding]
    scanner_errors: list[str]


class ScanContext(TypedDict):
    entrypoint: ScanEntrypoint
    skill_name: str | None
    skill_root: str | None
    existing_skill: bool
    strict: bool


class SkillScanPolicy(TypedDict):
    enabled: bool
    block_severities: list[FindingSeverity]
    warn_severities: list[FindingSeverity]
    fail_on_scanner_error: bool
    allow_override: bool
    allow_network_backends: bool


DEFAULT_SKILLSCAN_POLICY: SkillScanPolicy = {
    "enabled": True,
    "block_severities": ["CRITICAL"],
    "warn_severities": ["HIGH", "MEDIUM", "LOW"],
    "fail_on_scanner_error": False,
    "allow_override": False,
    "allow_network_backends": False,
}


class StaticScannerError(RuntimeError):
    """Raised when SkillScan cannot evaluate its input at the package boundary."""


class StaticScanBlockedError(ValueError):
    """Raised when deterministic findings block a skill write or install."""

    findings: list[SecurityFinding]
    skill_name: str | None

    def __init__(self, findings: list[SecurityFinding], *, skill_name: str | None = None, message: str | None = None) -> None:
        self.findings = [dict(finding) for finding in findings]  # type: ignore[list-item]
        self.skill_name = skill_name
        subject = f"skill '{skill_name}'" if skill_name else "skill content"
        super().__init__(message or f"Static security scan blocked {subject}")
