"""Data contracts for DeerFlow SkillScan.

Every ``SecurityFinding`` field has a Phase 1 consumer: the blocking policy
reads ``severity``; the Gateway rejection response, the agent tool error, and
the LLM scanner context read the rest. The rule category and owning analyzer
are encoded in the ``rule_id`` prefix (``package-``, ``secret-``,
``declaration-``, ``python-``, ``shell-``, ``network-``/``resource-``), not
duplicated as separate fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

FindingSeverity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class SecurityFinding(TypedDict):
    rule_id: str
    severity: FindingSeverity
    file: str | None
    line: int | None
    message: str
    remediation: str
    evidence: str | None


class ScanResult(TypedDict):
    findings: list[SecurityFinding]
    blocked: bool
    scanner_errors: list[str]


@dataclass(frozen=True)
class RuleSpec:
    """Static definition of one SkillScan rule; ``remediation`` is authored here once and copied into findings."""

    rule_id: str
    severity: FindingSeverity
    message: str
    remediation: str


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
