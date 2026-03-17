"""Scientific ethics/compliance auditor for manuscript drafts."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

ComplianceIssueType = Literal[
    "over_causal_claim",
    "sample_bias_risk",
    "missing_ethics_statement",
    "missing_reproducibility_statement",
]
ComplianceSeverity = Literal["critical", "major", "minor"]
ComplianceRiskLevel = Literal["low", "medium", "high"]

_OVER_CAUSAL_RE = re.compile(
    r"\b("
    r"prove|proves|proved|proven|"
    r"cause|causes|caused|causal|"
    r"definitive|certainly|always|guarantee|guarantees|"
    r"irrefutable|conclusive"
    r")\b",
    flags=re.IGNORECASE,
)
_UNCERTAINTY_RE = re.compile(r"\b(association|associated|suggests?|correlat|may|might|potentially|preliminary)\b", flags=re.IGNORECASE)

_SAMPLE_BIAS_RISK_RE = re.compile(
    r"\b("
    r"single[- ]center|single[- ]site|single institution|"
    r"small sample|limited cohort|n\s*[<≤]\s*\d{2,3}|"
    r"convenience sample|selection bias|demographic skew|"
    r"unbalanced cohort|class imbalance"
    r")\b",
    flags=re.IGNORECASE,
)
_SAMPLE_BIAS_MITIGATION_RE = re.compile(
    r"\b("
    r"limitation|bias|debias|reweight|stratif|external validation|"
    r"multi[- ]center|multi[- ]site|sensitivity analysis"
    r")\b",
    flags=re.IGNORECASE,
)

_ETHICS_STATEMENT_RE = re.compile(r"\b(ethics|ethical|irb|institutional review board|consent|approved protocol)\b", flags=re.IGNORECASE)
_REPRO_STATEMENT_RE = re.compile(
    r"\b("
    r"reproduc|code availability|data availability|open[- ]source|"
    r"github|seed|random seed|protocol|supplementary|materials"
    r")\b",
    flags=re.IGNORECASE,
)


class ComplianceFinding(BaseModel):
    """One compliance finding from the scientific auditor."""

    issue_type: ComplianceIssueType
    severity: ComplianceSeverity
    message: str
    recommendation: str
    evidence_spans: list[str] = Field(default_factory=list)


class ComplianceAuditReport(BaseModel):
    """Structured ethics/compliance report."""

    findings: list[ComplianceFinding] = Field(default_factory=list)
    compliance_score: float = Field(default=1.0, ge=0.0, le=1.0)
    risk_level: ComplianceRiskLevel = "low"
    blocked_by_critical: bool = False


def _snippet_around(text: str, match: re.Match[str], *, width: int = 72) -> str:
    start = max(0, match.start() - width)
    end = min(len(text), match.end() + width)
    return text[start:end].strip()


def _risk_level(score: float, *, blocked: bool) -> ComplianceRiskLevel:
    if blocked or score < 0.45:
        return "high"
    if score < 0.72:
        return "medium"
    return "low"


def audit_scientific_compliance(
    text: str,
    *,
    require_ethics_statement: bool = True,
    require_reproducibility_statement: bool = True,
) -> ComplianceAuditReport:
    """Audit manuscript text for ethics/compliance gaps."""
    normalized = text or ""
    findings: list[ComplianceFinding] = []

    over_causal_hits = list(_OVER_CAUSAL_RE.finditer(normalized))
    if over_causal_hits:
        uncertainty_hits = list(_UNCERTAINTY_RE.finditer(normalized))
        severity: ComplianceSeverity = "major" if not uncertainty_hits else "minor"
        findings.append(
            ComplianceFinding(
                issue_type="over_causal_claim",
                severity=severity,
                message="Detected over-strong causal language that may exceed current evidence strength.",
                recommendation="Downgrade to association/trend wording and explicitly state uncertainty boundaries.",
                evidence_spans=[_snippet_around(normalized, hit) for hit in over_causal_hits[:3]],
            )
        )

    sample_bias_hits = list(_SAMPLE_BIAS_RISK_RE.finditer(normalized))
    if sample_bias_hits and not _SAMPLE_BIAS_MITIGATION_RE.search(normalized):
        findings.append(
            ComplianceFinding(
                issue_type="sample_bias_risk",
                severity="major",
                message="Potential sample bias risk detected without explicit mitigation/limitation statements.",
                recommendation="Add bias analysis, representativeness discussion, and external validation or sensitivity checks.",
                evidence_spans=[_snippet_around(normalized, hit) for hit in sample_bias_hits[:3]],
            )
        )

    if require_ethics_statement and not _ETHICS_STATEMENT_RE.search(normalized):
        findings.append(
            ComplianceFinding(
                issue_type="missing_ethics_statement",
                severity="critical",
                message="Missing ethics/compliance statement (e.g., IRB/consent/protocol disclosure).",
                recommendation="Add an explicit ethics statement describing approvals, consent, and governance controls.",
                evidence_spans=[],
            )
        )

    if require_reproducibility_statement and not _REPRO_STATEMENT_RE.search(normalized):
        findings.append(
            ComplianceFinding(
                issue_type="missing_reproducibility_statement",
                severity="major",
                message="Missing reproducibility statement (code/data/protocol/seed availability).",
                recommendation="Add reproducibility disclosure with code/data access, environment, and seed/protocol details.",
                evidence_spans=[],
            )
        )

    penalties = {
        "critical": 0.35,
        "major": 0.2,
        "minor": 0.1,
    }
    penalty = sum(penalties[item.severity] for item in findings)
    score = max(0.0, min(1.0, 1.0 - penalty))
    blocked = any(item.severity == "critical" for item in findings)
    return ComplianceAuditReport(
        findings=findings,
        compliance_score=round(score, 4),
        risk_level=_risk_level(score, blocked=blocked),
        blocked_by_critical=blocked,
    )

