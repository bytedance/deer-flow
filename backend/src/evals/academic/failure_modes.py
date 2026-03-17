"""Failure-mode library gates for red-team regression."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .evaluator import evaluate_case
from .schemas import AcademicEvalCase, AcademicEvalResult

FailureMode = Literal[
    "citation_hallucination",
    "overclaim",
    "numeric_drift",
    "evidence_chain_break",
    "style_mismatch",
    "superficial_rebuttal",
    "ethics_gap",
]

FAILURE_MODE_GATES_SCHEMA_VERSION = "deerflow.failure_mode_gates.v1"

_FAILURE_MODE_KEYS: tuple[FailureMode, ...] = (
    "citation_hallucination",
    "overclaim",
    "numeric_drift",
    "evidence_chain_break",
    "style_mismatch",
    "superficial_rebuttal",
    "ethics_gap",
)
_FAILURE_MODE_SET = set(_FAILURE_MODE_KEYS)

_MODE_ALIASES: dict[str, FailureMode] = {
    "citation_hallucination": "citation_hallucination",
    "hallucinated_citation": "citation_hallucination",
    "引用幻觉": "citation_hallucination",
    "overclaim": "overclaim",
    "over_claim": "overclaim",
    "过度主张": "overclaim",
    "numeric_drift": "numeric_drift",
    "数字漂移": "numeric_drift",
    "evidence_chain_break": "evidence_chain_break",
    "evidence_break": "evidence_chain_break",
    "证据断链": "evidence_chain_break",
    "style_mismatch": "style_mismatch",
    "风格错配": "style_mismatch",
    "superficial_rebuttal": "superficial_rebuttal",
    "surface_rebuttal": "superficial_rebuttal",
    "审稿表面回应": "superficial_rebuttal",
    "伦理缺口": "ethics_gap",
    "ethics_gap": "ethics_gap",
}

_OVERCLAIM_TOKENS = ("demonstrates", "demonstrate", "proves", "prove", "causes", "causal")
_ETHICS_CHECKLIST_TOKENS = ("ethics", "irb", "consent", "bias", "reproducibility", "data availability")


class FailureModeThresholds(BaseModel):
    citation_fidelity_max: float = 0.75
    overclaim_claim_grounding_max: float = 0.65
    numeric_drift_abstract_body_max: float = 0.8
    evidence_chain_claim_grounding_max: float = 0.55
    style_mismatch_venue_fit_max: float = 0.7
    superficial_rebuttal_completeness_max: float = 0.7
    min_target_recall: float = 0.95
    max_control_false_positive_rate: float = 0.2


class FailureModeCaseAssessment(BaseModel):
    case_id: str
    targeted_modes: list[str] = Field(default_factory=list)
    detected_modes: list[str] = Field(default_factory=list)
    detection_by_mode: dict[str, bool] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    ethics_audit: dict[str, Any] | None = None


class FailureModeModeSummary(BaseModel):
    mode: str
    targeted_case_count: int = 0
    detected_targeted_case_count: int = 0
    target_recall: float = 1.0
    control_case_count: int = 0
    control_false_positive_count: int = 0
    control_false_positive_rate: float = 0.0
    status: Literal["pass", "fail"] = "pass"
    targeted_case_ids: list[str] = Field(default_factory=list)
    missed_case_ids: list[str] = Field(default_factory=list)


class FailureModeGateReport(BaseModel):
    schema_version: str = FAILURE_MODE_GATES_SCHEMA_VERSION
    case_count: int = 0
    targeted_case_count: int = 0
    control_case_count: int = 0
    status: Literal["pass", "fail"] = "pass"
    failed_modes: list[str] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)
    by_mode: dict[str, FailureModeModeSummary] = Field(default_factory=dict)
    cases: list[FailureModeCaseAssessment] = Field(default_factory=list)


def _normalize_mode_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    if not token:
        return None
    return _MODE_ALIASES.get(token)


def _as_lower_set(values: list[str]) -> set[str]:
    return {str(item).strip().lower() for item in values if isinstance(item, str) and str(item).strip()}


def _iter_claims(case: AcademicEvalCase) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for item in case.claims:
        if isinstance(item, dict):
            claims.append(item)
    return claims


def _detect_citation_hallucination(case: AcademicEvalCase, result: AcademicEvalResult, thresholds: FailureModeThresholds) -> bool:
    generated = _as_lower_set(case.generated_citations)
    verified = _as_lower_set(case.verified_citations)
    hallucinated = generated - verified
    if hallucinated:
        return True
    return float(result.citation_fidelity) < float(thresholds.citation_fidelity_max)


def _detect_overclaim(case: AcademicEvalCase, result: AcademicEvalResult, thresholds: FailureModeThresholds) -> bool:
    if float(result.claim_grounding) < float(thresholds.overclaim_claim_grounding_max):
        return True
    for claim in _iter_claims(case):
        claim_type = str(claim.get("type") or "").strip().lower()
        text = str(claim.get("text") or "").strip().lower()
        has_evidence = bool(claim.get("has_evidence"))
        has_citation = bool(claim.get("has_citation"))
        strong_like = claim_type in {"strong", "result", "causal"}
        lexical_overclaim = any(token in text for token in _OVERCLAIM_TOKENS)
        if (strong_like or lexical_overclaim) and not (has_evidence and has_citation):
            return True
    return False


def _detect_numeric_drift(case: AcademicEvalCase, result: AcademicEvalResult, thresholds: FailureModeThresholds) -> bool:
    if float(result.abstract_body_consistency) < float(thresholds.numeric_drift_abstract_body_max):
        return True
    abstract = [float(value) for value in case.abstract_numbers]
    body = [float(value) for value in case.body_numbers]
    if abstract and body and len(abstract) == len(body):
        drift_count = sum(1 for left, right in zip(abstract, body, strict=False) if abs(left - right) > max(1e-4, abs(left) * 0.05))
        if drift_count > 0:
            return True
    return False


def _detect_evidence_chain_break(case: AcademicEvalCase, result: AcademicEvalResult, thresholds: FailureModeThresholds) -> bool:
    if float(result.claim_grounding) < float(thresholds.evidence_chain_claim_grounding_max):
        return True
    for claim in _iter_claims(case):
        if bool(claim.get("references_missing_id")) or bool(claim.get("artifact_drift")):
            return True
        claim_type = str(claim.get("type") or "").strip().lower()
        has_evidence = bool(claim.get("has_evidence"))
        has_citation = bool(claim.get("has_citation"))
        if claim_type in {"strong", "result", "numeric", "comparative", "causal"} and (not has_evidence or not has_citation):
            return True
        explicit_data = claim.get("data_id") or claim.get("evidence_id")
        explicit_citation = claim.get("citation_id")
        if explicit_data and not has_evidence:
            return True
        if explicit_citation and not has_citation:
            return True
    return False


def _detect_style_mismatch(case: AcademicEvalCase, result: AcademicEvalResult, thresholds: FailureModeThresholds) -> bool:
    if float(result.venue_fit) < float(thresholds.style_mismatch_venue_fit_max):
        return True
    required = _as_lower_set(case.venue_checklist_items)
    satisfied = _as_lower_set(case.venue_satisfied_items)
    if required and len(required & satisfied) < max(1, int(len(required) * 0.5)):
        return True
    return False


def _detect_superficial_rebuttal(case: AcademicEvalCase, result: AcademicEvalResult, thresholds: FailureModeThresholds) -> bool:
    if not case.reviewer_comment_ids:
        return False
    if float(result.reviewer_rebuttal_completeness) < float(thresholds.superficial_rebuttal_completeness_max):
        return True
    comments = _as_lower_set(case.reviewer_comment_ids)
    addressed = _as_lower_set(case.rebuttal_addressed_ids)
    return len(comments & addressed) < len(comments)


def _detect_ethics_gap(case: AcademicEvalCase) -> tuple[bool, dict[str, Any] | None]:
    text = (case.manuscript_text or "").strip()
    if text:
        from src.research_writing.ethics_compliance import audit_scientific_compliance

        report = audit_scientific_compliance(text)
        finding_types = {item.issue_type for item in report.findings}
        has_gap = (
            report.blocked_by_critical
            or report.risk_level == "high"
            or bool(finding_types & {"missing_ethics_statement", "missing_reproducibility_statement", "sample_bias_risk"})
        )
        return has_gap, report.model_dump()

    required = _as_lower_set(case.venue_checklist_items)
    satisfied = _as_lower_set(case.venue_satisfied_items)
    missing = [item for item in required if item not in satisfied and any(token in item for token in _ETHICS_CHECKLIST_TOKENS)]
    return bool(missing), None


def _detect_modes_for_case(case: AcademicEvalCase, result: AcademicEvalResult, thresholds: FailureModeThresholds) -> tuple[dict[str, bool], dict[str, Any] | None]:
    ethics_hit, ethics_audit = _detect_ethics_gap(case)
    detection = {
        "citation_hallucination": _detect_citation_hallucination(case, result, thresholds),
        "overclaim": _detect_overclaim(case, result, thresholds),
        "numeric_drift": _detect_numeric_drift(case, result, thresholds),
        "evidence_chain_break": _detect_evidence_chain_break(case, result, thresholds),
        "style_mismatch": _detect_style_mismatch(case, result, thresholds),
        "superficial_rebuttal": _detect_superficial_rebuttal(case, result, thresholds),
        "ethics_gap": ethics_hit,
    }
    return detection, ethics_audit


def evaluate_failure_mode_library(
    cases: list[AcademicEvalCase],
    *,
    case_results: dict[str, AcademicEvalResult] | None = None,
    thresholds: FailureModeThresholds | None = None,
) -> dict[str, Any]:
    """Evaluate failure-mode red-team detection coverage and gating status."""
    resolved_thresholds = thresholds or FailureModeThresholds()
    result_lookup = case_results or {}
    assessments: list[FailureModeCaseAssessment] = []

    for case in cases:
        result = result_lookup.get(case.case_id) or evaluate_case(case)
        detection, ethics_audit = _detect_modes_for_case(case, result, resolved_thresholds)
        targeted_modes: list[str] = []
        for token in case.failure_modes:
            normalized = _normalize_mode_token(token)
            if normalized is None:
                continue
            if normalized not in targeted_modes:
                targeted_modes.append(normalized)

        detected_modes = [mode for mode, hit in detection.items() if hit]
        assessments.append(
            FailureModeCaseAssessment(
                case_id=case.case_id,
                targeted_modes=targeted_modes,
                detected_modes=detected_modes,
                detection_by_mode=detection,
                metrics={
                    "citation_fidelity": float(result.citation_fidelity),
                    "claim_grounding": float(result.claim_grounding),
                    "abstract_body_consistency": float(result.abstract_body_consistency),
                    "reviewer_rebuttal_completeness": float(result.reviewer_rebuttal_completeness),
                    "venue_fit": float(result.venue_fit),
                    "cross_modality_synthesis": float(result.cross_modality_synthesis),
                    "long_horizon_consistency": float(result.long_horizon_consistency),
                    "overall_score": float(result.overall_score),
                },
                ethics_audit=ethics_audit,
            )
        )

    control_cases = [item for item in assessments if not item.targeted_modes]
    by_mode: dict[str, FailureModeModeSummary] = {}
    failed_modes: list[str] = []

    for mode in _FAILURE_MODE_KEYS:
        targeted = [item for item in assessments if mode in item.targeted_modes]
        detected_targeted = [item for item in targeted if bool(item.detection_by_mode.get(mode))]
        missed = [item for item in targeted if not bool(item.detection_by_mode.get(mode))]
        control_fp = [item for item in control_cases if bool(item.detection_by_mode.get(mode))]

        targeted_count = len(targeted)
        detected_count = len(detected_targeted)
        control_count = len(control_cases)
        control_fp_count = len(control_fp)
        target_recall = float(detected_count) / float(targeted_count) if targeted_count > 0 else 1.0
        control_fpr = float(control_fp_count) / float(control_count) if control_count > 0 else 0.0

        status: Literal["pass", "fail"] = "pass"
        if target_recall < float(resolved_thresholds.min_target_recall):
            status = "fail"
        if control_fpr > float(resolved_thresholds.max_control_false_positive_rate):
            status = "fail"
        if status == "fail":
            failed_modes.append(mode)

        by_mode[mode] = FailureModeModeSummary(
            mode=mode,
            targeted_case_count=targeted_count,
            detected_targeted_case_count=detected_count,
            target_recall=round(target_recall, 4),
            control_case_count=control_count,
            control_false_positive_count=control_fp_count,
            control_false_positive_rate=round(control_fpr, 4),
            status=status,
            targeted_case_ids=[item.case_id for item in targeted],
            missed_case_ids=[item.case_id for item in missed],
        )

    report = FailureModeGateReport(
        case_count=len(cases),
        targeted_case_count=len([item for item in assessments if item.targeted_modes]),
        control_case_count=len(control_cases),
        status="fail" if failed_modes else "pass",
        failed_modes=failed_modes,
        thresholds=resolved_thresholds.model_dump(),
        by_mode=by_mode,
        cases=assessments,
    )
    return report.model_dump()

