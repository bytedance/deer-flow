"""Gateway router for research-writing and academic-eval runtime workflows."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, model_validator

from src.evals.academic.loader import load_builtin_eval_cases, load_eval_cases
from src.evals.academic.schemas import AcademicEvalCase
from src.gateway.path_utils import resolve_thread_virtual_path, validate_thread_id
from src.research_writing.api_contract import (
    RESEARCH_API_SCHEMA_VERSION,
    UnsupportedResearchSchemaVersionError,
    resolve_schema_contract,
)
from src.research_writing.citation_registry import CitationRecord
from src.research_writing.claim_graph import Claim
from src.research_writing.evidence_store import EvidenceUnit
from src.research_writing.fulltext_ingest import LiteratureSource
from src.research_writing.project_state import HitlDecision, ResearchProject, SectionDraft
from src.research_writing.runtime_service import (
    assess_project_capabilities,
    audit_project_section_compliance,
    build_latex_manuscript,
    compile_project_section,
    evaluate_academic_and_persist,
    generate_project_hypotheses,
    get_capability_catalog,
    get_engineering_gates_metrics,
    get_peer_review_ab_metrics,
    get_project,
    get_project_hitl_decisions,
    get_project_policy_snapshot,
    get_section_traceability,
    get_weekly_academic_leaderboard,
    import_academic_eval_dataset,
    ingest_fulltext_evidence,
    list_projects,
    list_section_versions,
    plan_project_section_narrative,
    rollback_section_to_version,
    run_prompt_layer_optimizer,
    run_agentic_research_graph,
    run_peer_self_play_training,
    simulate_peer_review_cycle,
    simulate_review_and_plan,
    upsert_citation,
    upsert_claim,
    upsert_evidence,
    upsert_fact,
    upsert_project,
    upsert_project_hitl_decisions,
    upsert_section,
    verify_project_section_claim_map,
)
from src.research_writing.source_of_truth import NumericFact

logger = logging.getLogger(__name__)


Reviewer2Style = Literal["statistical_tyrant", "methodology_fundamentalist", "domain_traditionalist"]
PeerReviewABVariant = Literal["off", "A", "B"]
_AUTO_CLAIM_MAP_REQUIRED_TOKENS: tuple[str, ...] = (
    "discussion",
    "result",
    "results",
    "conclusion",
    "analysis",
    "findings",
)
_AUTO_CLAIM_MAP_OPTIONAL_TOKENS: tuple[str, ...] = (
    "intro",
    "introduction",
    "background",
    "related work",
    "related_work",
    "relatedwork",
)


def _research_schema_dependency(
    request: Request,
    response: Response,
    x_research_schema_version: str | None = Header(default=None, alias="X-Research-Schema-Version"),
) -> None:
    try:
        contract = resolve_schema_contract(x_research_schema_version)
    except UnsupportedResearchSchemaVersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.state.research_schema_contract = contract
    response.headers["X-Research-Schema-Version"] = contract.response_version
    if contract.migration_applied and contract.migrated_from:
        response.headers["X-Research-Schema-Migrated-From"] = contract.migrated_from


def _contract_dict(request: Request) -> dict[str, Any]:
    contract = getattr(request.state, "research_schema_contract", None)
    if contract is None:
        return {}
    if not contract.migration_applied:
        return {}
    return {
        "requested_version": contract.requested_version,
        "response_version": contract.response_version,
        "migrated_from": contract.migrated_from,
        "migration_applied": contract.migration_applied,
    }


def _with_contract(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    return {
        **payload,
        "schema_version": RESEARCH_API_SCHEMA_VERSION,
        "schema_migration": _contract_dict(request) or None,
    }


def _auto_require_claim_map_submission(*, thread_id: str, project_id: str, section_id: str) -> bool:
    """Gateway-side auto policy: results/discussion-like sections are hard-required; intro-like sections are optional."""
    descriptor_parts: list[str] = [section_id]
    try:
        project = get_project(thread_id, project_id)
    except Exception:
        project = None
    if project is not None:
        section = next((item for item in project.sections if item.section_id == section_id), None)
        if section is not None and section.section_name:
            descriptor_parts.append(section.section_name)
    descriptor = " ".join(part for part in descriptor_parts if isinstance(part, str)).strip().lower()
    if any(token in descriptor for token in _AUTO_CLAIM_MAP_REQUIRED_TOKENS):
        return True
    if any(token in descriptor for token in _AUTO_CLAIM_MAP_OPTIONAL_TOKENS):
        return False
    # Default fail-close for unknown section types.
    return True


router = APIRouter(
    prefix="/api/threads/{thread_id}/research",
    tags=["research"],
    dependencies=[Depends(_research_schema_dependency)],
)


class ContractAwareResponse(BaseModel):
    schema_version: str = Field(default=RESEARCH_API_SCHEMA_VERSION)
    schema_migration: dict[str, Any] | None = None
    prompt_pack_id: str | None = None
    prompt_pack_hash: str | None = None
    prompt_layer_diff_summary: dict[str, Any] | None = None
    prompt_registry_schema_version: str | None = None
    runtime_strategy: dict[str, Any] | None = None
    runtime_strategy_hash: str | None = None
    eval_impact: dict[str, Any] | None = None
    eval_attribution_key: str | None = None


class ProjectResponse(ContractAwareResponse):
    project: dict[str, Any]


class ProjectsListResponse(ContractAwareResponse):
    projects: list[dict[str, Any]]


class SectionCompileResponse(ContractAwareResponse):
    section_id: str
    compiled_text: str
    issues: list[dict[str, Any]]
    artifact_path: str
    details_artifact_path: str | None = None
    claim_map: dict[str, Any] | None = None
    claim_map_artifact_path: str | None = None
    claim_map_validation: dict[str, Any] | None = None
    resolved_venue: str | None = None
    narrative_strategy: dict[str, Any] | None = None
    dynamic_few_shot_context: list[dict[str, Any]] = Field(default_factory=list)
    dynamic_few_shot_retrieval: dict[str, Any] | None = None
    narrative_sentence_count: int = 0
    journal_style: dict[str, Any] | None = None
    journal_style_alignment_applied: bool = False
    adaptive_role_contract: dict[str, Any] | None = None
    adaptive_role_contract_tone_applied: bool = False
    task_complexity_score: float | None = None
    analysis_confidence: float | None = None
    complexity_confidence_diagnostics: dict[str, Any] | None = None
    peer_review: dict[str, Any] | None = None
    hypothesis_bundle: dict[str, Any] | None = None
    hypothesis_reasoning_mode: str | None = None
    min_competing_hypotheses: int | None = None
    min_survivors_required: int | None = None
    falsification_fail_close: str | None = None
    hitl_checkpoints: dict[str, Any] | None = None
    hitl_blocking: bool = False
    hitl_impact_preview: dict[str, Any] | None = None
    policy_snapshot: dict[str, Any] | None = None
    policy_snapshot_auto_adjust_narrative: bool = True
    policy_snapshot_adjustment_applied: bool = False
    policy_snapshot_artifact_path: str | None = None
    narrative_plan: dict[str, Any] | None = None
    narrative_plan_artifact_path: str | None = None
    narrative_self_question_rounds: int = 3
    narrative_include_storyboard: bool = True
    compliance_audit: dict[str, Any] | None = None
    compliance_audit_artifact_path: str | None = None
    capability_assessment: dict[str, Any] | None = None
    capability_assessment_artifact_path: str | None = None
    capability_gate_failed: bool = False
    capability_gate_reasons: list[str] = Field(default_factory=list)
    safety_valve_triggered: bool = False
    safety_valve_reasons: list[str] = Field(default_factory=list)
    engineering_gates: dict[str, Any] | None = None
    engineering_gate_artifact_path: str | None = None
    risk_conclusion_template: str | None = None
    version_diff: dict[str, Any] | None = None
    version_diff_artifact_path: str | None = None
    trace: dict[str, Any] | None = None
    trace_artifact_path: str | None = None
    reviewer2_styles: list[Reviewer2Style] = Field(default_factory=list)
    peer_review_ab_variant: PeerReviewABVariant = "off"
    peer_review_max_rounds: int = 3
    peer_review_strategy: dict[str, Any] | None = None
    peer_review_strategy_config: dict[str, Any] | None = None
    peer_review_ab_metrics: dict[str, Any] | None = None
    peer_review_ab_metrics_artifact_path: str | None = None
    claim_grounding: dict[str, Any] | None = None
    claim_grounding_alerts: list[str] = Field(default_factory=list)
    claim_grounding_artifact_path: str | None = None
    hard_grounding_sentence_check: dict[str, Any] | None = None
    literature_alignment_check: dict[str, Any] | None = None


class SectionVersionsResponse(ContractAwareResponse):
    version_schema_version: str | None = None
    project_id: str
    section_id: str
    total_count: int
    versions: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: str | None = None
    artifact_path: str


class SectionRollbackRequest(BaseModel):
    version_id: str = Field(min_length=1)


class SectionRollbackResponse(ContractAwareResponse):
    project_id: str
    section_id: str
    rolled_back_to_version_id: str | None = None
    rolled_back_to_version_number: int | None = None
    new_section_version: int
    new_history_version_id: str | None = None
    diff: dict[str, Any]
    section: dict[str, Any]
    artifact_path: str


class SectionTraceabilityResponse(ContractAwareResponse):
    trace_schema_version: str
    project_id: str
    section_id: str
    generated_at: str
    compiled_artifact_path: str | None = None
    sentence_links: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    claim_grounding: dict[str, Any] | None = None
    claim_grounding_artifact_path: str | None = None
    artifact_path: str


class CapabilityCatalogResponse(ContractAwareResponse):
    catalog_schema_version: str | None = None
    generated_at: str
    capabilities: list[dict[str, Any]] = Field(default_factory=list)


class CapabilityAssessmentRequest(BaseModel):
    project_id: str
    section_id: str | None = None


class CapabilityAssessmentResponse(ContractAwareResponse):
    generated_at: str
    project_id: str
    section_id: str | None = None
    catalog: dict[str, Any]
    assessment: dict[str, Any]
    artifact_path: str


class FulltextIngestRequest(BaseModel):
    source: LiteratureSource
    external_id: str
    persist: bool = True


class FulltextIngestResponse(ContractAwareResponse):
    record: dict[str, Any]
    evidence_count: int
    persisted_evidence_ids: list[str]
    persisted_citation_ids: list[str] = Field(default_factory=list)
    citation_graph: dict[str, Any] | None = None
    literature_graph: dict[str, Any] | None = None
    citation_graph_node_count: int = 0
    co_citation_edge_count: int = 0
    literature_graph_claim_count: int = 0
    literature_graph_edge_count: int = 0
    narrative_threads: list[str] = Field(default_factory=list)
    literature_synthesis_threads: list[str] = Field(default_factory=list)
    graph_evidence_ids: list[str] = Field(default_factory=list)
    artifact_path: str


class ReviewSimulateRequest(BaseModel):
    venue_name: str
    manuscript_text: str
    evidence_map: dict[str, list[str]] | None = None
    section_map: dict[str, list[str]] | None = None


class ReviewSimulateResponse(ContractAwareResponse):
    venue: str
    overall_assessment: str
    comments: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    rebuttal_letter: str
    artifact_path: str
    letter_path: str


class PeerReviewLoopRequest(BaseModel):
    venue_name: str
    manuscript_text: str
    section_id: str | None = None
    max_rounds: int = Field(default=3, ge=1, le=5)
    reviewer2_styles: list[Reviewer2Style] | None = None
    peer_review_ab_variant: str | None = Field(default=None, description="off | A | B | auto")


class PeerReviewLoopResponse(ContractAwareResponse):
    venue: str
    section_id: str | None = None
    red_team_agents: list[str]
    blue_team_agents: list[str]
    rounds: list[dict[str, Any]]
    final_text: str
    final_decision: str
    unresolved_issue_count: int
    artifact_path: str
    final_text_path: str
    reviewer2_styles: list[Reviewer2Style] = Field(default_factory=list)
    peer_review_ab_variant: PeerReviewABVariant = "off"
    peer_review_max_rounds: int = 3
    peer_review_strategy: dict[str, Any] | None = None
    peer_review_strategy_config: dict[str, Any] | None = None
    peer_review_ab_metrics: dict[str, Any] | None = None
    peer_review_ab_metrics_artifact_path: str | None = None


class PeerReviewABMetricsResponse(ContractAwareResponse):
    metrics_schema_version: str = "deerflow.peer_review_ab_metrics.v1"
    thread_id: str
    updated_at: str | None = None
    total_runs: int = 0
    window_size: int = 0
    by_variant_total: dict[str, dict[str, float]] = Field(default_factory=dict)
    by_variant_window: dict[str, dict[str, float]] = Field(default_factory=dict)
    recent_runs: list[dict[str, Any]] = Field(default_factory=list)
    strategy_config: dict[str, Any] = Field(default_factory=dict)
    artifact_path: str | None = None


class EngineeringGatesMetricsResponse(ContractAwareResponse):
    metrics_schema_version: str = "deerflow.engineering_gates_runtime_metrics.v1"
    thread_id: str
    project_id: str | None = None
    run_limit: int = 60
    updated_at: str | None = None
    compile_runs: list[dict[str, Any]] = Field(default_factory=list)
    latex_runs: list[dict[str, Any]] = Field(default_factory=list)
    compile_summary: dict[str, Any] = Field(default_factory=dict)
    latex_summary: dict[str, Any] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["pass", "warn"] = "pass"
    counters: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)


class PromptLayerOptimizerConfigRequest(BaseModel):
    enabled: bool = True
    optimizer_mode: Literal["rules", "llm_structured_patch"] = "rules"
    model_name: str | None = None
    thinking_enabled: bool = False
    temperature: float = 0.0
    max_candidate_count: int = Field(default=3, ge=1, le=8)
    fallback_to_rules: bool = True


class PromptLayerOptimizerRequest(BaseModel):
    compile_metrics_path: str | None = None
    offline_regression_report_path: str | None = None
    prompt_layers_path: str | None = None
    apply_prompt_patch: bool = False
    run_offline_validation: bool = True
    dataset_version: str = "optimizer-candidate"
    optimizer_config: PromptLayerOptimizerConfigRequest | None = None
    optimizer_mode: Literal["rules", "llm_structured_patch"] | None = None
    llm_model_name: str | None = None
    llm_thinking_enabled: bool | None = None
    llm_temperature: float | None = None

    @model_validator(mode="after")
    def _backfill_optimizer_config(self) -> PromptLayerOptimizerRequest:
        if self.optimizer_config is not None:
            return self
        if self.optimizer_mode is None and self.llm_model_name is None and self.llm_thinking_enabled is None and self.llm_temperature is None:
            return self
        self.optimizer_config = PromptLayerOptimizerConfigRequest(
            optimizer_mode=self.optimizer_mode or "rules",
            model_name=self.llm_model_name,
            thinking_enabled=bool(self.llm_thinking_enabled),
            temperature=float(self.llm_temperature or 0.0),
        )
        return self


class PromptLayerOptimizerResponse(ContractAwareResponse):
    optimizer_schema_version: str = "deerflow.prompt_optimizer.v1"
    thread_id: str
    generated_at: str | None = None
    status: str = "no_change"
    optimizer_config: dict[str, Any] = Field(default_factory=dict)
    optimizer_mode_requested: str = "rules"
    optimizer_mode_used: str = "rules"
    fallback_reason: str | None = None
    signals: dict[str, Any] = Field(default_factory=dict)
    changes: list[dict[str, Any]] = Field(default_factory=list)
    change_count: int = 0
    candidate_prompt_layers_path: str | None = None
    candidate_prompt_patch_path: str | None = None
    applied_prompt_patch: bool = False
    applied_prompt_layers_path: str | None = None
    source_paths: dict[str, Any] = Field(default_factory=dict)
    llm_candidate: dict[str, Any] | None = None
    validation_issues: list[str] = Field(default_factory=list)
    offline_validation: dict[str, Any] | None = None


class HypothesisGenerateRequest(BaseModel):
    project_id: str
    section_id: str | None = None
    max_hypotheses: int = Field(default=5, ge=3, le=5)
    reasoning_mode: Literal["tot", "got", "auto"] | None = None
    min_competing_hypotheses: int | None = Field(default=None, ge=3, le=8)
    min_survivors_required: int | None = Field(default=None, ge=1, le=5)
    falsification_fail_close: Literal["strict", "lenient"] | None = None


class HypothesisGenerateResponse(ContractAwareResponse):
    project_id: str
    section_id: str | None = None
    feature_summary: list[str]
    hypotheses: list[dict[str, Any]]
    synthesis_paragraph: str
    reasoning_mode: str | None = None
    min_competing_hypotheses: int | None = None
    min_survivors_required: int | None = None
    falsification_fail_close: str | None = None
    claim_map_gate_blocked: bool = False
    surviving_hypothesis_ids: list[str] = Field(default_factory=list)
    excluded_hypothesis_ids: list[str] = Field(default_factory=list)
    claim_map_ready_hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    reasoning_audit_traces: list[dict[str, Any]] = Field(default_factory=list)
    historical_hypothesis_context: list[dict[str, Any]] = Field(default_factory=list)
    historical_failed_attempts: list[dict[str, Any]] = Field(default_factory=list)
    artifact_path: str


class HitlDecisionsUpsertRequest(BaseModel):
    decisions: list[HitlDecision] = Field(min_length=1)
    section_id: str | None = None


class HitlDecisionsResponse(ContractAwareResponse):
    project_id: str
    section_id: str | None = None
    decisions: list[HitlDecision]
    total_count: int
    updated_at: str | None = None
    impact_preview: dict[str, Any] | None = None
    policy_snapshot: dict[str, Any] | None = None
    policy_snapshot_artifact_path: str | None = None
    artifact_path: str | None = None


class EvalAcademicRequest(BaseModel):
    cases: list[AcademicEvalCase] | None = None
    dataset_path: str | None = Field(default=None, description="Optional virtual path to eval dataset JSON")
    dataset_name: str | None = Field(default=None, description="Optional builtin dataset name under src/evals/academic/datasets")
    artifact_name: str = "academic-eval"
    model_label: str = "deerflow-runtime"


class EvalAcademicResponse(ContractAwareResponse):
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
    failure_mode_gate_status: str | None = None
    failure_mode_gate_failed_modes: list[str] = Field(default_factory=list)
    failure_mode_gate_schema_version: str | None = None
    failure_mode_gate_targeted_case_count: int = 0
    failure_mode_gate_control_case_count: int = 0
    failure_mode_gate_by_mode: dict[str, Any] = Field(default_factory=dict)
    failure_mode_gate_artifact_path: str | None = None
    leaderboard_artifact_path: str | None = None
    leaderboard_entries_updated: int = 0
    leaderboard_schema_version: str | None = None
    results: list[dict[str, Any]]
    artifact_path: str


class PolicySnapshotResponse(ContractAwareResponse):
    project_id: str
    section_id: str | None = None
    policy_snapshot: dict[str, Any]
    artifact_path: str


class SelfPlayTrainingEpisodeRequest(BaseModel):
    manuscript_text: str = Field(min_length=1)
    venue_name: str | None = None
    section_id: str | None = None
    episode_id: str | None = None


class SelfPlayTrainingRequest(BaseModel):
    episodes: list[SelfPlayTrainingEpisodeRequest] = Field(min_length=1)
    max_rounds: int = Field(default=3, ge=1, le=5)
    default_venue_name: str = "NeurIPS"
    default_section_id: str | None = "discussion"
    run_name: str = "peer-self-play"


class SelfPlayTrainingResponse(ContractAwareResponse):
    schema_version: str
    self_play_schema_version: str | None = None
    generated_at: str
    run_name: str
    total_episodes: int
    accepted_episodes: int
    hard_negative_count: int
    hard_negative_rate: float
    episodes: list[dict[str, Any]] = Field(default_factory=list)
    hard_negatives: list[dict[str, Any]] = Field(default_factory=list)
    artifact_path: str
    hard_negatives_artifact_path: str


class ComplianceAuditRequest(BaseModel):
    project_id: str
    section_id: str
    manuscript_text: str | None = None


class ComplianceAuditResponse(ContractAwareResponse):
    project_id: str
    section_id: str
    compliance_audit: dict[str, Any]
    artifact_path: str


class AcademicLeaderboardResponse(ContractAwareResponse):
    schema_version: str
    leaderboard_schema_version: str | None = None
    cadence: str
    updated_at: str
    buckets: list[dict[str, Any]] = Field(default_factory=list)
    artifact_path: str


class EvalAcademicImportRequest(BaseModel):
    source_dataset_path: str = Field(description="Virtual path to raw accept/reject dataset JSON")
    dataset_name: str = Field(description="Canonical dataset name, e.g. top_tier_accept_reject_real")
    dataset_version: str = Field(default="v1", description="Dataset version label, e.g. 2026.03")
    benchmark_split: str | None = Field(default=None, description="Optional split override")
    source_name: str | None = Field(default=None, description="Optional source identifier shown in metadata")
    anonymize: bool = Field(default=True, description="Whether to anonymize sensitive text/id fields")
    strict: bool = Field(default=False, description="Fail fast if any record cannot be normalized")
    autofix: bool = Field(default=False, description="Apply low-risk field auto-fixes before validation/import")
    autofix_level: Literal["safe", "balanced", "aggressive"] = Field(
        default="balanced",
        description="Auto-fix whitelist level: safe|balanced|aggressive",
    )


class EvalAcademicImportResponse(ContractAwareResponse):
    dataset_name: str
    dataset_version: str
    benchmark_split: str
    source_name: str
    anonymized: bool
    imported_case_count: int
    accepted_case_count: int
    rejected_case_count: int
    skipped_case_count: int
    warnings: list[str] = Field(default_factory=list)
    source_dataset_path: str
    dataset_path: str
    manifest_path: str
    validation_status: str = "unknown"
    validation_error_count: int = 0
    validation_warning_count: int = 0
    validation_report_path: str | None = None
    validation_markdown_path: str | None = None
    autofix_applied: bool = False
    autofix_level: str | None = None
    autofix_modified_record_count: int = 0
    autofix_report_path: str | None = None
    autofix_markdown_path: str | None = None


@router.post("/projects/upsert", response_model=ProjectResponse)
async def upsert_project_endpoint(thread_id: str, project: ResearchProject, request: Request) -> ProjectResponse:
    validate_thread_id(thread_id)
    saved = upsert_project(thread_id, project)
    return ProjectResponse(**_with_contract({"project": saved.model_dump()}, request))


@router.get("/projects", response_model=ProjectsListResponse)
async def list_projects_endpoint(thread_id: str, request: Request) -> ProjectsListResponse:
    validate_thread_id(thread_id)
    projects = list_projects(thread_id)
    return ProjectsListResponse(**_with_contract({"projects": [p.model_dump() for p in projects]}, request))


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project_endpoint(thread_id: str, project_id: str, request: Request) -> ProjectResponse:
    validate_thread_id(thread_id)
    project = get_project(thread_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return ProjectResponse(**_with_contract({"project": project.model_dump()}, request))


@router.post("/projects/{project_id}/sections/upsert", response_model=dict)
async def upsert_section_endpoint(thread_id: str, project_id: str, section: SectionDraft, request: Request) -> dict:
    validate_thread_id(thread_id)
    try:
        saved = upsert_section(thread_id, project_id, section)
        return _with_contract({"section": saved.model_dump()}, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/claims/upsert", response_model=dict)
async def upsert_claim_endpoint(thread_id: str, claim: Claim, request: Request) -> dict:
    validate_thread_id(thread_id)
    saved = upsert_claim(thread_id, claim)
    return _with_contract({"claim": saved.model_dump()}, request)


@router.post("/evidence/upsert", response_model=dict)
async def upsert_evidence_endpoint(thread_id: str, evidence: EvidenceUnit, request: Request) -> dict:
    validate_thread_id(thread_id)
    saved = upsert_evidence(thread_id, evidence)
    return _with_contract({"evidence": saved.model_dump()}, request)


@router.post("/citations/upsert", response_model=dict)
async def upsert_citation_endpoint(thread_id: str, citation: CitationRecord, request: Request) -> dict:
    validate_thread_id(thread_id)
    saved = upsert_citation(thread_id, citation)
    return _with_contract({"citation": saved.model_dump()}, request)


@router.post("/facts/upsert", response_model=dict)
async def upsert_fact_endpoint(thread_id: str, fact: NumericFact, request: Request) -> dict:
    validate_thread_id(thread_id)
    saved = upsert_fact(thread_id, fact)
    return _with_contract({"fact": saved.model_dump()}, request)


@router.post("/ingest/fulltext", response_model=FulltextIngestResponse)
async def ingest_fulltext_endpoint(thread_id: str, payload: FulltextIngestRequest, request: Request) -> FulltextIngestResponse:
    validate_thread_id(thread_id)
    try:
        result = ingest_fulltext_evidence(
            thread_id,
            source=payload.source,
            external_id=payload.external_id,
            persist=payload.persist,
        )
        return FulltextIngestResponse(**_with_contract(result, request))
    except Exception as exc:
        logger.exception("Failed fulltext ingest (thread_id=%s, source=%s, external_id=%s): %s", thread_id, payload.source, payload.external_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class SectionCompileRequest(BaseModel):
    project_id: str
    section_id: str
    mode: Literal["strict", "lenient"] = "strict"
    auto_peer_review: bool = True
    auto_hypothesis: bool = True
    peer_review_max_rounds: int = Field(default=3, ge=1, le=5)
    max_hypotheses: int = Field(default=5, ge=3, le=5)
    narrative_style: Literal["auto", "conservative", "balanced", "aggressive"] = "auto"
    narrative_max_templates: int | None = Field(default=None, ge=1, le=5)
    narrative_evidence_density: Literal["low", "medium", "high"] | None = None
    narrative_auto_by_section_type: bool = True
    narrative_paragraph_tones: list[Literal["conservative", "balanced", "aggressive"]] | None = None
    narrative_paragraph_evidence_densities: list[Literal["low", "medium", "high"]] | None = None
    journal_style_enabled: bool | None = None
    journal_style_force_refresh: bool = False
    journal_style_sample_size: int | None = Field(default=None, ge=1, le=10)
    journal_style_recent_year_window: int | None = Field(default=None, ge=1, le=15)
    dynamic_retrieval_top_k: int | None = Field(default=None, ge=1, le=8)
    dynamic_retrieval_min_score: float | None = Field(default=None, ge=0.0, le=1.0)
    task_complexity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    analysis_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    role_contract_auto_tighten: bool = True
    policy_snapshot_auto_adjust_narrative: bool = True
    narrative_self_question_rounds: int = Field(default=3, ge=1, le=8)
    narrative_include_storyboard: bool = True
    hypothesis_reasoning_mode: Literal["tot", "got", "auto"] | None = None
    min_competing_hypotheses: int | None = Field(default=None, ge=3, le=8)
    min_survivors_required: int | None = Field(default=None, ge=1, le=5)
    falsification_fail_close: Literal["strict", "lenient"] | None = None
    reviewer2_styles: list[Reviewer2Style] | None = None
    peer_review_ab_variant: str | None = Field(default=None, description="off | A | B | auto")
    claim_map_json: dict[str, Any] | list[dict[str, Any]] | str | None = Field(
        default=None,
        description="Model-produced Claim Map JSON payload (object/list/stringified JSON).",
    )
    claim_map_artifact_path: str | None = Field(
        default=None,
        description="Optional sandbox path to Claim Map JSON artifact.",
    )
    require_claim_map_submission: bool | None = Field(
        default=None,
        description="If null, gateway auto-enforces by section type (discussion/results force, intro optional).",
    )

    @model_validator(mode="after")
    def _validate_claim_map_gate(self) -> SectionCompileRequest:
        has_inline = self.claim_map_json is not None and (not isinstance(self.claim_map_json, str) or bool(self.claim_map_json.strip()))
        has_artifact = isinstance(self.claim_map_artifact_path, str) and bool(self.claim_map_artifact_path.strip())
        if self.require_claim_map_submission is True and not (has_inline or has_artifact):
            raise ValueError("claim_map_json or claim_map_artifact_path is required when require_claim_map_submission=true")
        return self


class ClaimMapVerifyRequest(BaseModel):
    project_id: str
    section_id: str
    claim_map_json: dict[str, Any] | list[dict[str, Any]] | str | None = Field(
        default=None,
        description="Model-produced Claim Map JSON payload (object/list/stringified JSON).",
    )
    claim_map_artifact_path: str | None = Field(
        default=None,
        description="Optional sandbox path to Claim Map JSON artifact.",
    )
    require_claim_map_submission: bool | None = Field(
        default=None,
        description="If null, gateway auto-enforces by section type (discussion/results force, intro optional).",
    )

    @model_validator(mode="after")
    def _validate_claim_map_gate(self) -> ClaimMapVerifyRequest:
        has_inline = self.claim_map_json is not None and (not isinstance(self.claim_map_json, str) or bool(self.claim_map_json.strip()))
        has_artifact = isinstance(self.claim_map_artifact_path, str) and bool(self.claim_map_artifact_path.strip())
        if self.require_claim_map_submission is True and not (has_inline or has_artifact):
            raise ValueError("claim_map_json or claim_map_artifact_path is required when require_claim_map_submission=true")
        if self.claim_map_json is not None and has_artifact:
            raise ValueError("Provide either claim_map_json or claim_map_artifact_path, not both")
        return self


class ClaimMapVerifyResponse(ContractAwareResponse):
    project_id: str
    section_id: str
    claim_map: dict[str, Any]
    claim_map_artifact_path: str | None = None
    claim_map_validation: dict[str, Any]


class NarrativePlanRequest(BaseModel):
    project_id: str
    section_id: str
    self_question_rounds: int = Field(default=3, ge=1, le=8)
    include_storyboard: bool = True


class NarrativePlanResponse(ContractAwareResponse):
    project_id: str
    section_id: str
    section_name: str
    planner_version: str
    takeaway_message: str
    gap_statement: str
    disruption_statement: str
    logical_flow: list[str] = Field(default_factory=list)
    figure_storyboard: list[dict[str, Any]] = Field(default_factory=list)
    self_questioning: list[dict[str, Any]] = Field(default_factory=list)
    introduction_hook: str
    discussion_pivot: str
    introduction_cars: list[dict[str, str]] = Field(default_factory=list)
    meal_outline: list[dict[str, str]] = Field(default_factory=list)
    discussion_five_layers: list[dict[str, str]] = Field(default_factory=list)
    self_question_rounds: int = 3
    include_storyboard: bool = True
    claim_map: dict[str, Any] | None = None
    claim_map_artifact_path: str | None = None
    artifact_path: str


class AgenticGraphRunRequest(BaseModel):
    project_id: str
    section_id: str | None = None
    seed_idea: str | None = None
    max_rounds: int = Field(default=3, ge=1, le=8)


class AgenticGraphRunResponse(ContractAwareResponse):
    orchestrator_version: str
    project_id: str
    section_id: str | None = None
    seed_idea: str | None = None
    max_rounds: int
    rounds_executed: int
    reroute_count: int
    converged: bool
    open_gaps: list[str] = Field(default_factory=list)
    proposed_actions: list[str] = Field(default_factory=list)
    final_writer_draft: str
    route_trace: list[str] = Field(default_factory=list)
    blackboard: list[dict[str, Any]] = Field(default_factory=list)
    historical_failed_attempts: list[dict[str, Any]] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    artifact_path: str


class LatexCompileRequest(BaseModel):
    project_id: str | None = None
    section_ids: list[str] = Field(default_factory=list)
    markdown_text: str | None = None
    title: str | None = None
    abstract_text: str | None = None
    authors: list[str] = Field(default_factory=list)
    compile_pdf: bool | None = None
    engine: Literal["auto", "none", "latexmk", "pdflatex", "xelatex"] | None = None
    output_name: str | None = None


class LatexCompileResponse(ContractAwareResponse):
    project_id: str | None = None
    section_ids: list[str] = Field(default_factory=list)
    title: str
    source_markdown_path: str
    tex_path: str
    pdf_path: str | None = None
    compile_log_path: str
    compile_status: Literal["success", "failed", "skipped"]
    compiler: str | None = None
    engine_requested: str
    compile_pdf_requested: bool
    citation_keys: list[str] = Field(default_factory=list)
    citation_count: int = 0
    warning: str | None = None
    latex_quality_gate: dict[str, Any] | None = None
    latex_quality_gate_artifact_path: str | None = None
    artifact_path: str
    summary_artifact_path: str


@router.post("/compile/section", response_model=SectionCompileResponse)
async def compile_section_endpoint(thread_id: str, payload: SectionCompileRequest, request: Request) -> SectionCompileResponse:
    validate_thread_id(thread_id)
    try:
        resolved_require_claim_map = (
            payload.require_claim_map_submission
            if payload.require_claim_map_submission is not None
            else _auto_require_claim_map_submission(
                thread_id=thread_id,
                project_id=payload.project_id,
                section_id=payload.section_id,
            )
        )
        result = compile_project_section(
            thread_id=thread_id,
            project_id=payload.project_id,
            section_id=payload.section_id,
            mode=payload.mode,
            auto_peer_review=payload.auto_peer_review,
            auto_hypothesis=payload.auto_hypothesis,
            peer_review_max_rounds=payload.peer_review_max_rounds,
            max_hypotheses=payload.max_hypotheses,
            narrative_style=payload.narrative_style,
            narrative_max_templates=payload.narrative_max_templates,
            narrative_evidence_density=payload.narrative_evidence_density,
            narrative_auto_by_section_type=payload.narrative_auto_by_section_type,
            narrative_paragraph_tones=payload.narrative_paragraph_tones,
            narrative_paragraph_evidence_densities=payload.narrative_paragraph_evidence_densities,
            journal_style_enabled=payload.journal_style_enabled,
            journal_style_force_refresh=payload.journal_style_force_refresh,
            journal_style_sample_size=payload.journal_style_sample_size,
            journal_style_recent_year_window=payload.journal_style_recent_year_window,
            dynamic_retrieval_top_k=payload.dynamic_retrieval_top_k,
            dynamic_retrieval_min_score=payload.dynamic_retrieval_min_score,
            task_complexity_score=payload.task_complexity_score,
            analysis_confidence=payload.analysis_confidence,
            role_contract_auto_tighten=payload.role_contract_auto_tighten,
            policy_snapshot_auto_adjust_narrative=payload.policy_snapshot_auto_adjust_narrative,
            narrative_self_question_rounds=payload.narrative_self_question_rounds,
            narrative_include_storyboard=payload.narrative_include_storyboard,
            hypothesis_reasoning_mode=payload.hypothesis_reasoning_mode,
            min_competing_hypotheses=payload.min_competing_hypotheses,
            min_survivors_required=payload.min_survivors_required,
            falsification_fail_close=payload.falsification_fail_close,
            reviewer2_styles=payload.reviewer2_styles,
            peer_review_ab_variant=payload.peer_review_ab_variant,
            claim_map_json=payload.claim_map_json,
            claim_map_artifact_path=payload.claim_map_artifact_path,
            require_claim_map_submission=resolved_require_claim_map,
        )
        return SectionCompileResponse(**_with_contract(result, request))
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/verify/claim-map", response_model=ClaimMapVerifyResponse)
async def verify_claim_map_endpoint(thread_id: str, payload: ClaimMapVerifyRequest, request: Request) -> ClaimMapVerifyResponse:
    validate_thread_id(thread_id)
    try:
        resolved_require_claim_map = (
            payload.require_claim_map_submission
            if payload.require_claim_map_submission is not None
            else _auto_require_claim_map_submission(
                thread_id=thread_id,
                project_id=payload.project_id,
                section_id=payload.section_id,
            )
        )
        result = verify_project_section_claim_map(
            thread_id=thread_id,
            project_id=payload.project_id,
            section_id=payload.section_id,
            claim_map_json=payload.claim_map_json,
            claim_map_artifact_path=payload.claim_map_artifact_path,
            require_claim_map_submission=resolved_require_claim_map,
        )
        return ClaimMapVerifyResponse(**_with_contract(result, request))
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/plan/narrative", response_model=NarrativePlanResponse)
async def plan_narrative_endpoint(thread_id: str, payload: NarrativePlanRequest, request: Request) -> NarrativePlanResponse:
    validate_thread_id(thread_id)
    try:
        result = plan_project_section_narrative(
            thread_id=thread_id,
            project_id=payload.project_id,
            section_id=payload.section_id,
            self_question_rounds=payload.self_question_rounds,
            include_storyboard=payload.include_storyboard,
        )
        return NarrativePlanResponse(**_with_contract(result, request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/orchestration/agentic-graph/run", response_model=AgenticGraphRunResponse)
async def run_agentic_graph_endpoint(
    thread_id: str,
    payload: AgenticGraphRunRequest,
    request: Request,
) -> AgenticGraphRunResponse:
    validate_thread_id(thread_id)
    try:
        result = run_agentic_research_graph(
            thread_id=thread_id,
            project_id=payload.project_id,
            section_id=payload.section_id,
            seed_idea=payload.seed_idea,
            max_rounds=payload.max_rounds,
        )
        return AgenticGraphRunResponse(**_with_contract(result, request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/sections/{section_id}/versions", response_model=SectionVersionsResponse)
async def list_section_versions_endpoint(
    thread_id: str,
    project_id: str,
    section_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
) -> SectionVersionsResponse:
    validate_thread_id(thread_id)
    payload = list_section_versions(
        thread_id=thread_id,
        project_id=project_id,
        section_id=section_id,
        limit=limit,
    )
    return SectionVersionsResponse(**_with_contract(payload, request))


@router.post("/projects/{project_id}/sections/{section_id}/rollback", response_model=SectionRollbackResponse)
async def rollback_section_endpoint(
    thread_id: str,
    project_id: str,
    section_id: str,
    payload: SectionRollbackRequest,
    request: Request,
) -> SectionRollbackResponse:
    validate_thread_id(thread_id)
    try:
        result = rollback_section_to_version(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
            version_id=payload.version_id,
        )
        return SectionRollbackResponse(**_with_contract(result, request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/sections/{section_id}/trace", response_model=SectionTraceabilityResponse)
async def section_traceability_endpoint(
    thread_id: str,
    project_id: str,
    section_id: str,
    request: Request,
) -> SectionTraceabilityResponse:
    validate_thread_id(thread_id)
    try:
        result = get_section_traceability(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
        )
        return SectionTraceabilityResponse(**_with_contract(result, request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/capabilities/catalog", response_model=CapabilityCatalogResponse)
async def capability_catalog_endpoint(thread_id: str, request: Request) -> CapabilityCatalogResponse:
    validate_thread_id(thread_id)
    payload = get_capability_catalog(thread_id)
    return CapabilityCatalogResponse(**_with_contract(payload, request))


@router.post("/capabilities/assess", response_model=CapabilityAssessmentResponse)
async def capability_assessment_endpoint(
    thread_id: str,
    payload: CapabilityAssessmentRequest,
    request: Request,
) -> CapabilityAssessmentResponse:
    validate_thread_id(thread_id)
    try:
        result = assess_project_capabilities(
            thread_id=thread_id,
            project_id=payload.project_id,
            section_id=payload.section_id,
        )
        return CapabilityAssessmentResponse(**_with_contract(result, request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/latex/compile", response_model=LatexCompileResponse)
async def compile_latex_endpoint(thread_id: str, payload: LatexCompileRequest, request: Request) -> LatexCompileResponse:
    validate_thread_id(thread_id)
    try:
        result = build_latex_manuscript(
            thread_id=thread_id,
            project_id=payload.project_id,
            section_ids=payload.section_ids,
            markdown_text=payload.markdown_text,
            title=payload.title,
            abstract_text=payload.abstract_text,
            authors=payload.authors,
            compile_pdf=payload.compile_pdf,
            engine=payload.engine,
            output_name=payload.output_name,
        )
        return LatexCompileResponse(**_with_contract(result, request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/review/simulate", response_model=ReviewSimulateResponse)
async def review_simulate_endpoint(thread_id: str, payload: ReviewSimulateRequest, request: Request) -> ReviewSimulateResponse:
    validate_thread_id(thread_id)
    try:
        result = simulate_review_and_plan(
            thread_id=thread_id,
            venue_name=payload.venue_name,
            manuscript_text=payload.manuscript_text,
            evidence_map=payload.evidence_map,
            section_map=payload.section_map,
        )
        return ReviewSimulateResponse(**_with_contract(result, request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/review/peer-loop", response_model=PeerReviewLoopResponse)
async def review_peer_loop_endpoint(thread_id: str, payload: PeerReviewLoopRequest, request: Request) -> PeerReviewLoopResponse:
    validate_thread_id(thread_id)
    try:
        result = simulate_peer_review_cycle(
            thread_id=thread_id,
            venue_name=payload.venue_name,
            manuscript_text=payload.manuscript_text,
            section_id=payload.section_id,
            max_rounds=payload.max_rounds,
            reviewer2_styles=payload.reviewer2_styles,
            peer_review_ab_variant=payload.peer_review_ab_variant,
        )
        return PeerReviewLoopResponse(**_with_contract(result, request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/review/ab-metrics", response_model=PeerReviewABMetricsResponse)
async def review_ab_metrics_endpoint(thread_id: str, request: Request) -> PeerReviewABMetricsResponse:
    validate_thread_id(thread_id)
    result = get_peer_review_ab_metrics(thread_id=thread_id)
    return PeerReviewABMetricsResponse(**_with_contract(result, request))


@router.get("/metrics/engineering-gates", response_model=EngineeringGatesMetricsResponse)
async def engineering_gates_metrics_endpoint(
    thread_id: str,
    request: Request,
    project_id: str | None = Query(default=None),
    run_limit: int = Query(default=60, ge=10, le=500),
    max_constraint_violation_rate: float = Query(default=0.2, ge=0.0, le=1.0),
    max_safety_valve_trigger_rate: float = Query(default=0.4, ge=0.0, le=1.0),
    max_hitl_block_rate: float = Query(default=0.35, ge=0.0, le=1.0),
    min_traceability_coverage_rate: float = Query(default=0.8, ge=0.0, le=1.0),
    min_delivery_completeness_rate: float = Query(default=1.0, ge=0.0, le=1.0),
    min_latex_success_rate: float = Query(default=0.75, ge=0.0, le=1.0),
) -> EngineeringGatesMetricsResponse:
    validate_thread_id(thread_id)
    result = get_engineering_gates_metrics(
        thread_id=thread_id,
        project_id=project_id,
        run_limit=run_limit,
        max_constraint_violation_rate=max_constraint_violation_rate,
        max_safety_valve_trigger_rate=max_safety_valve_trigger_rate,
        max_hitl_block_rate=max_hitl_block_rate,
        min_traceability_coverage_rate=min_traceability_coverage_rate,
        min_delivery_completeness_rate=min_delivery_completeness_rate,
        min_latex_success_rate=min_latex_success_rate,
    )
    return EngineeringGatesMetricsResponse(**_with_contract(result, request))


@router.post("/metrics/prompt-optimizer", response_model=PromptLayerOptimizerResponse)
async def prompt_layer_optimizer_endpoint(
    thread_id: str,
    payload: PromptLayerOptimizerRequest,
    request: Request,
) -> PromptLayerOptimizerResponse:
    validate_thread_id(thread_id)
    try:
        result = run_prompt_layer_optimizer(
            thread_id=thread_id,
            compile_metrics_path=payload.compile_metrics_path,
            offline_regression_report_path=payload.offline_regression_report_path,
            prompt_layers_path=payload.prompt_layers_path,
            apply_prompt_patch=payload.apply_prompt_patch,
            run_offline_validation=payload.run_offline_validation,
            dataset_version=payload.dataset_version,
            optimizer_config=payload.optimizer_config.model_dump() if payload.optimizer_config is not None else None,
            optimizer_mode=payload.optimizer_mode or "rules",
            llm_model_name=payload.llm_model_name,
            llm_thinking_enabled=bool(payload.llm_thinking_enabled) if payload.llm_thinking_enabled is not None else False,
            llm_temperature=float(payload.llm_temperature or 0.0),
        )
        return PromptLayerOptimizerResponse(**_with_contract(result, request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/review/self-play", response_model=SelfPlayTrainingResponse)
async def review_self_play_endpoint(
    thread_id: str,
    payload: SelfPlayTrainingRequest,
    request: Request,
) -> SelfPlayTrainingResponse:
    validate_thread_id(thread_id)
    try:
        result = run_peer_self_play_training(
            thread_id=thread_id,
            episodes=[item.model_dump() for item in payload.episodes],
            max_rounds=payload.max_rounds,
            default_venue_name=payload.default_venue_name,
            default_section_id=payload.default_section_id,
            run_name=payload.run_name,
        )
        return SelfPlayTrainingResponse(**_with_contract(result, request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/hypotheses/generate", response_model=HypothesisGenerateResponse)
async def hypothesis_generate_endpoint(thread_id: str, payload: HypothesisGenerateRequest, request: Request) -> HypothesisGenerateResponse:
    validate_thread_id(thread_id)
    try:
        result = generate_project_hypotheses(
            thread_id=thread_id,
            project_id=payload.project_id,
            section_id=payload.section_id,
            max_hypotheses=payload.max_hypotheses,
            reasoning_mode=payload.reasoning_mode,
            min_competing_hypotheses=payload.min_competing_hypotheses,
            min_survivors_required=payload.min_survivors_required,
            falsification_fail_close=payload.falsification_fail_close,
        )
        return HypothesisGenerateResponse(**_with_contract(result, request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/compliance/audit", response_model=ComplianceAuditResponse)
async def compliance_audit_endpoint(
    thread_id: str,
    payload: ComplianceAuditRequest,
    request: Request,
) -> ComplianceAuditResponse:
    validate_thread_id(thread_id)
    try:
        result = audit_project_section_compliance(
            thread_id=thread_id,
            project_id=payload.project_id,
            section_id=payload.section_id,
            manuscript_text=payload.manuscript_text,
        )
        return ComplianceAuditResponse(**_with_contract(result, request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/hitl-decisions", response_model=HitlDecisionsResponse)
async def get_project_hitl_decisions_endpoint(
    thread_id: str,
    project_id: str,
    request: Request,
    section_id: str | None = None,
) -> HitlDecisionsResponse:
    validate_thread_id(thread_id)
    try:
        payload = get_project_hitl_decisions(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
        )
        return HitlDecisionsResponse(**_with_contract(payload, request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/policy-snapshot", response_model=PolicySnapshotResponse)
async def get_project_policy_snapshot_endpoint(
    thread_id: str,
    project_id: str,
    request: Request,
    section_id: str | None = None,
) -> PolicySnapshotResponse:
    validate_thread_id(thread_id)
    try:
        payload = get_project_policy_snapshot(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
        )
        return PolicySnapshotResponse(**_with_contract(payload, request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/projects/{project_id}/hitl-decisions", response_model=HitlDecisionsResponse)
async def upsert_project_hitl_decisions_endpoint(
    thread_id: str,
    project_id: str,
    payload: HitlDecisionsUpsertRequest,
    request: Request,
) -> HitlDecisionsResponse:
    validate_thread_id(thread_id)
    try:
        result = upsert_project_hitl_decisions(
            thread_id=thread_id,
            project_id=project_id,
            decisions=payload.decisions,
            section_id=payload.section_id,
        )
        return HitlDecisionsResponse(**_with_contract(result, request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/evals/academic", response_model=EvalAcademicResponse)
async def eval_academic_endpoint(thread_id: str, payload: EvalAcademicRequest, request: Request) -> EvalAcademicResponse:
    validate_thread_id(thread_id)
    cases: list[AcademicEvalCase]
    if payload.cases is not None:
        cases = payload.cases
    elif payload.dataset_name:
        try:
            cases = load_builtin_eval_cases(payload.dataset_name)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid dataset_name: {exc}") from exc
    elif payload.dataset_path:
        dataset_file = resolve_thread_virtual_path(thread_id, payload.dataset_path)
        try:
            cases = load_eval_cases(dataset_file)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid dataset_path payload: {exc}") from exc
    else:
        raise HTTPException(status_code=400, detail="Either cases, dataset_path, or dataset_name must be provided")

    result = evaluate_academic_and_persist(
        thread_id,
        cases=cases,
        name=payload.artifact_name,
        model_label=payload.model_label,
        dataset_name=payload.dataset_name,
    )
    return EvalAcademicResponse(**_with_contract(result, request))


@router.get("/evals/academic/leaderboard", response_model=AcademicLeaderboardResponse)
async def eval_academic_leaderboard_endpoint(
    thread_id: str,
    request: Request,
) -> AcademicLeaderboardResponse:
    validate_thread_id(thread_id)
    result = get_weekly_academic_leaderboard(thread_id)
    return AcademicLeaderboardResponse(**_with_contract(result, request))


@router.post("/evals/academic/import", response_model=EvalAcademicImportResponse)
async def import_eval_academic_endpoint(
    thread_id: str,
    payload: EvalAcademicImportRequest,
    request: Request,
) -> EvalAcademicImportResponse:
    validate_thread_id(thread_id)
    source_file = resolve_thread_virtual_path(thread_id, payload.source_dataset_path)
    try:
        result = import_academic_eval_dataset(
            thread_id,
            source_dataset_file=source_file,
            source_dataset_virtual_path=payload.source_dataset_path,
            dataset_name=payload.dataset_name,
            dataset_version=payload.dataset_version,
            benchmark_split=payload.benchmark_split,
            source_name=payload.source_name,
            anonymize=payload.anonymize,
            strict=payload.strict,
            autofix=payload.autofix,
            autofix_level=payload.autofix_level,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Academic dataset import failed: {exc}") from exc
    return EvalAcademicImportResponse(**_with_contract(result, request))
