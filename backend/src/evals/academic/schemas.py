"""Schemas for academic evaluation framework."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ManuscriptDecision = Literal["accepted", "rejected", "revise", "unknown"]


class AcademicEvalCase(BaseModel):
    """Single benchmark case for academic writing evaluation."""

    case_id: str
    domain: str
    venue: str
    generated_citations: list[str] = Field(default_factory=list)
    verified_citations: list[str] = Field(default_factory=list)
    claims: list[dict] = Field(default_factory=list)
    abstract_numbers: list[float] = Field(default_factory=list)
    body_numbers: list[float] = Field(default_factory=list)
    reviewer_comment_ids: list[str] = Field(default_factory=list)
    rebuttal_addressed_ids: list[str] = Field(default_factory=list)
    venue_checklist_items: list[str] = Field(default_factory=list)
    venue_satisfied_items: list[str] = Field(default_factory=list)
    cross_modal_items_expected: int = 0
    cross_modal_items_used: int = 0
    revision_terms: list[list[str]] = Field(default_factory=list)
    revision_numbers: list[list[float]] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    safety_valve_triggered: bool = False
    manuscript_text: str | None = None
    decision: ManuscriptDecision = "unknown"
    benchmark_split: str = "unspecified"
    source_name: str | None = None


class AcademicEvalResult(BaseModel):
    """Per-case evaluation metrics."""

    case_id: str
    citation_fidelity: float
    claim_grounding: float
    abstract_body_consistency: float
    reviewer_rebuttal_completeness: float
    venue_fit: float
    cross_modality_synthesis: float
    long_horizon_consistency: float
    overall_score: float
    metric_weights: dict[str, float] = Field(default_factory=dict)
    predicted_accept_prob: float = 0.0
    calibration_residual: float = 0.0


class AcademicEvalSummary(BaseModel):
    """Dataset-level summary metrics."""

    case_count: int
    average_overall_score: float
    average_citation_fidelity: float
    average_claim_grounding: float
    average_abstract_body_consistency: float
    average_reviewer_rebuttal_completeness: float
    average_venue_fit: float
    average_cross_modality_synthesis: float
    average_long_horizon_consistency: float
    accepted_case_count: int = 0
    rejected_case_count: int = 0
    accepted_average_overall_score: float = 0.0
    rejected_average_overall_score: float = 0.0
    accept_reject_score_gap: float = 0.0
    label_ranking_accuracy: float = 0.0
    auc_accept_reject: float = 0.0
    ece: float = 0.0
    brier_score: float = 0.0
    safety_valve_triggered_count: int = 0
    safety_valve_triggered_rate: float = 0.0
    overall_score_ci_low: float = 0.0
    overall_score_ci_high: float = 0.0
    auc_ci_low: float = 0.0
    auc_ci_high: float = 0.0
    dynamic_weighting_enabled: bool = True
    calibration_bins: int = 10
    weighting_profiles: dict[str, dict[str, float]] = Field(default_factory=dict)
    benchmark_split: str = "unspecified"
    source_name: str | None = None
    results: list[AcademicEvalResult] = Field(default_factory=list)
