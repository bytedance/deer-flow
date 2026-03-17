"""Capability catalog and scoring model for research-writing workflows."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from src.research_writing.citation_registry import CitationRecord
from src.research_writing.claim_graph import Claim
from src.research_writing.evidence_store import EvidenceUnit
from src.research_writing.project_state import HitlDecision, ResearchProject, SectionDraft
from src.research_writing.source_of_truth import NumericFact

CAPABILITY_CATALOG_SCHEMA_VERSION = "deerflow.capability_catalog.v1"
CAPABILITY_SNAPSHOT_SCHEMA_VERSION = "deerflow.capability_snapshot.v1"
_NUMERIC_RE = re.compile(r"\d+(?:\.\d+)?")
_MEAL_CARS_HINTS = ("however", "therefore", "because", "in contrast", "gap", "we propose", "we show")


class CapabilityMetricResult(BaseModel):
    metric_id: str
    description: str
    value: float = Field(ge=0.0, le=1.0)
    target: float = Field(ge=0.0, le=1.0)
    status: str
    rationale: str


class CapabilityScorecard(BaseModel):
    capability_id: str
    capability_name: str
    score: float = Field(ge=0.0, le=1.0)
    status: str
    metrics: list[CapabilityMetricResult] = Field(default_factory=list)
    triggered_failure_modes: list[dict[str, str]] = Field(default_factory=list)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _status_from_ratio(value: float, target: float) -> str:
    if value >= target:
        return "pass"
    if value >= (target * 0.7):
        return "warn"
    return "fail"


def capability_catalog() -> dict[str, Any]:
    """Return static capability->metric->failure-mode catalog."""
    return {
        "schema_version": CAPABILITY_CATALOG_SCHEMA_VERSION,
        "capabilities": [
            {
                "capability_id": "research_problem_and_contribution",
                "name": "研究问题与贡献定位",
                "metrics": [
                    {"metric_id": "rq_defined", "target": 1.0},
                    {"metric_id": "hypothesis_falsifiable", "target": 1.0},
                    {"metric_id": "venue_contract_bound", "target": 1.0},
                ],
                "failure_modes": [
                    {"failure_mode_id": "topic_scope_drift", "description": "选题持续发散，无法收敛为最小可发表单元。"},
                    {"failure_mode_id": "hypothesis_not_testable", "description": "假设不可证伪，评审无法判断真伪。"},
                    {"failure_mode_id": "venue_story_mismatch", "description": "叙事与目标 venue 审稿偏好不匹配。"},
                ],
            },
            {
                "capability_id": "evidence_engineering",
                "name": "文献与证据工程",
                "metrics": [
                    {"metric_id": "evidence_density", "target": 0.7},
                    {"metric_id": "citation_verification", "target": 0.6},
                    {"metric_id": "dispute_graph_coverage", "target": 0.5},
                ],
                "failure_modes": [
                    {"failure_mode_id": "single_source_bias", "description": "证据来源单一，缺少 support/refute/reconcile 平衡。"},
                    {"failure_mode_id": "uncited_evidence", "description": "证据单元无法追溯到可核验引用。"},
                    {"failure_mode_id": "broken_evidence_chain", "description": "结论无法回溯到结构化证据链。"},
                ],
            },
            {
                "capability_id": "claim_engineering",
                "name": "主张工程",
                "metrics": [
                    {"metric_id": "claim_binding_ratio", "target": 0.9},
                    {"metric_id": "numeric_claim_binding", "target": 0.8},
                    {"metric_id": "section_grounding_tags", "target": 0.8},
                ],
                "failure_modes": [
                    {"failure_mode_id": "floating_claim", "description": "关键主张缺少 data_id/citation_id 绑定。"},
                    {"failure_mode_id": "numeric_without_source", "description": "数值句子缺少事实或证据锚定。"},
                    {"failure_mode_id": "causal_overreach", "description": "因果/比较语句超出证据支持强度。"},
                ],
            },
            {
                "capability_id": "narrative_and_craft",
                "name": "叙事与写作工艺",
                "metrics": [
                    {"metric_id": "narrative_plan_exists", "target": 1.0},
                    {"metric_id": "paragraph_structure_checkable", "target": 0.6},
                    {"metric_id": "self_questioning_rounds", "target": 0.6},
                ],
                "failure_modes": [
                    {"failure_mode_id": "draft_before_plan", "description": "未形成 narrative plan 就直接出段落。"},
                    {"failure_mode_id": "logic_chain_break", "description": "段落缺少可检验逻辑链。"},
                    {"failure_mode_id": "weak_storyboard", "description": "图故事板与段落 takeaways 脱节。"},
                ],
            },
            {
                "capability_id": "reviewer_game",
                "name": "审稿人对抗与修订",
                "metrics": [
                    {"metric_id": "review_comment_closure", "target": 0.75},
                    {"metric_id": "rebuttal_action_traceability", "target": 0.75},
                    {"metric_id": "unresolved_issue_control", "target": 0.7},
                ],
                "failure_modes": [
                    {"failure_mode_id": "comment_plan_gap", "description": "评审意见未映射为修订计划与责任动作。"},
                    {"failure_mode_id": "revision_without_evidence", "description": "修订动作缺少证据补齐。"},
                    {"failure_mode_id": "response_letter_drift", "description": "回应信与实际改稿不一致。"},
                ],
            },
            {
                "capability_id": "compliance_and_reproducibility",
                "name": "伦理与可复现",
                "metrics": [
                    {"metric_id": "compliance_risk_control", "target": 0.8},
                    {"metric_id": "repro_evidence_presence", "target": 0.6},
                    {"metric_id": "risk_template_trigger", "target": 1.0},
                ],
                "failure_modes": [
                    {"failure_mode_id": "ethics_gap_ignored", "description": "伦理风险未被识别或被弱化。"},
                    {"failure_mode_id": "irreproducible_result", "description": "缺失原始数据/脚本导致不可复现。"},
                    {"failure_mode_id": "unsafe_strong_conclusion", "description": "高风险下仍输出强结论。"},
                ],
            },
            {
                "capability_id": "latex_and_delivery",
                "name": "LaTeX 与交付",
                "metrics": [
                    {"metric_id": "tex_artifact_ready", "target": 1.0},
                    {"metric_id": "pdf_compile_success", "target": 0.8},
                    {"metric_id": "diagnostic_report_ready", "target": 1.0},
                ],
                "failure_modes": [
                    {"failure_mode_id": "tex_compile_flaky", "description": ".tex/PDF 产出不稳定，构建随机失败。"},
                    {"failure_mode_id": "missing_diagnostics", "description": "失败后缺少可复现诊断报告。"},
                    {"failure_mode_id": "delivery_artifact_mismatch", "description": "最终交付与文稿版本不一致。"},
                ],
            },
            {
                "capability_id": "long_horizon_consistency",
                "name": "长期一致性",
                "metrics": [
                    {"metric_id": "term_stability", "target": 0.7},
                    {"metric_id": "citation_library_stability", "target": 0.7},
                    {"metric_id": "versioned_traceability", "target": 0.8},
                ],
                "failure_modes": [
                    {"failure_mode_id": "terminology_drift", "description": "多轮迭代中术语定义漂移。"},
                    {"failure_mode_id": "number_strength_drift", "description": "数字或结论强度跨版本不一致。"},
                    {"failure_mode_id": "citation_pool_fragmentation", "description": "引用库反复切换，证据语义断裂。"},
                ],
            },
        ],
    }


def evaluate_capabilities(
    *,
    project: ResearchProject,
    section: SectionDraft | None,
    claims: list[Claim],
    evidence_units: list[EvidenceUnit],
    citations: list[CitationRecord],
    facts: list[NumericFact],
    hitl_decisions: list[HitlDecision],
    compliance_payload: dict[str, Any] | None = None,
    latex_payload: dict[str, Any] | None = None,
    section_versions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build capability scorecards from current structured runtime artifacts."""
    catalog = capability_catalog()
    section_text = (section.content if section is not None else "").strip()
    numeric_claims = [c for c in claims if _NUMERIC_RE.search(c.text or "")]
    claims_with_binding = [c for c in claims if c.evidence_ids or c.citation_ids]
    verified_citations = [c for c in citations if c.verified]
    evidence_with_citation = [e for e in evidence_units if e.citation_ids]
    rebuttal_closed = [item for item in project.rebuttal_actions if item.status == "completed"]
    unresolved_ratio = 0.0
    if project.reviewer_comments:
        unresolved_ratio = 1.0 - (_clip(float(len(rebuttal_closed)) / float(len(project.reviewer_comments))))

    compliance_report = (compliance_payload or {}).get("compliance_audit") if isinstance(compliance_payload, dict) else {}
    if not isinstance(compliance_report, dict):
        compliance_report = {}
    risk_level = str(compliance_report.get("risk_level") or "unknown").lower()
    safety_valve_triggered = bool((compliance_payload or {}).get("safety_valve_triggered"))
    compile_status = str((latex_payload or {}).get("compile_status") or "").lower()
    versions = (section_versions or {}).get("versions")
    if not isinstance(versions, list):
        versions = []

    metric_map: dict[str, CapabilityMetricResult] = {
        "rq_defined": CapabilityMetricResult(
            metric_id="rq_defined",
            description="研究问题定义清晰度",
            value=_clip(len(project.research_questions)),
            target=1.0,
            status=_status_from_ratio(_clip(len(project.research_questions)), 1.0),
            rationale=f"research_questions={len(project.research_questions)}",
        ),
        "hypothesis_falsifiable": CapabilityMetricResult(
            metric_id="hypothesis_falsifiable",
            description="可证伪假设覆盖",
            value=_clip(len(project.hypotheses)),
            target=1.0,
            status=_status_from_ratio(_clip(len(project.hypotheses)), 1.0),
            rationale=f"hypotheses={len(project.hypotheses)}",
        ),
        "venue_contract_bound": CapabilityMetricResult(
            metric_id="venue_contract_bound",
            description="目标 venue 叙事契约绑定",
            value=1.0 if (project.target_venue or "").strip() else 0.0,
            target=1.0,
            status="pass" if (project.target_venue or "").strip() else "fail",
            rationale=f"target_venue={project.target_venue!r}",
        ),
        "evidence_density": CapabilityMetricResult(
            metric_id="evidence_density",
            description="证据密度",
            value=_clip(float(len(evidence_units)) / 8.0),
            target=0.7,
            status=_status_from_ratio(_clip(float(len(evidence_units)) / 8.0), 0.7),
            rationale=f"evidence_units={len(evidence_units)}",
        ),
        "citation_verification": CapabilityMetricResult(
            metric_id="citation_verification",
            description="引用核验率",
            value=_clip(float(len(verified_citations)) / float(len(citations))) if citations else 0.0,
            target=0.6,
            status=_status_from_ratio(_clip(float(len(verified_citations)) / float(len(citations))) if citations else 0.0, 0.6),
            rationale=f"verified={len(verified_citations)}/{len(citations)}",
        ),
        "dispute_graph_coverage": CapabilityMetricResult(
            metric_id="dispute_graph_coverage",
            description="争议图覆盖度（support/refute/reconcile 代理）",
            value=_clip(float(len(evidence_with_citation)) / float(len(evidence_units))) if evidence_units else 0.0,
            target=0.5,
            status=_status_from_ratio(_clip(float(len(evidence_with_citation)) / float(len(evidence_units))) if evidence_units else 0.0, 0.5),
            rationale=f"evidence_with_citation={len(evidence_with_citation)}",
        ),
        "claim_binding_ratio": CapabilityMetricResult(
            metric_id="claim_binding_ratio",
            description="主张绑定率（evidence/citation）",
            value=_clip(float(len(claims_with_binding)) / float(len(claims))) if claims else 0.0,
            target=0.9,
            status=_status_from_ratio(_clip(float(len(claims_with_binding)) / float(len(claims))) if claims else 0.0, 0.9),
            rationale=f"claims_with_binding={len(claims_with_binding)}/{len(claims)}",
        ),
        "numeric_claim_binding": CapabilityMetricResult(
            metric_id="numeric_claim_binding",
            description="数值主张绑定率",
            value=_clip(float(len([c for c in numeric_claims if c.evidence_ids or c.citation_ids])) / float(len(numeric_claims))) if numeric_claims else 1.0,
            target=0.8,
            status=_status_from_ratio(_clip(float(len([c for c in numeric_claims if c.evidence_ids or c.citation_ids])) / float(len(numeric_claims))) if numeric_claims else 1.0, 0.8),
            rationale=f"numeric_claims={len(numeric_claims)}",
        ),
        "section_grounding_tags": CapabilityMetricResult(
            metric_id="section_grounding_tags",
            description="段落 grounding 标签覆盖",
            value=1.0 if ("[data:" in section_text and "[citation:" in section_text) else (0.5 if ("[data:" in section_text or "[citation:" in section_text) else 0.0),
            target=0.8,
            status=_status_from_ratio(1.0 if ("[data:" in section_text and "[citation:" in section_text) else (0.5 if ("[data:" in section_text or "[citation:" in section_text) else 0.0), 0.8),
            rationale="require [data:*] + [citation:*] markers in compiled section",
        ),
        "narrative_plan_exists": CapabilityMetricResult(
            metric_id="narrative_plan_exists",
            description="是否存在 narrative plan",
            value=1.0 if bool(section and section.content.strip()) else 0.0,
            target=1.0,
            status="pass" if bool(section and section.content.strip()) else "fail",
            rationale="section content presence used as runtime proxy",
        ),
        "paragraph_structure_checkable": CapabilityMetricResult(
            metric_id="paragraph_structure_checkable",
            description="段落结构可检验性（MEAL/CARS 代理）",
            value=_clip(float(sum(1 for token in _MEAL_CARS_HINTS if token in section_text.lower())) / 4.0),
            target=0.6,
            status=_status_from_ratio(_clip(float(sum(1 for token in _MEAL_CARS_HINTS if token in section_text.lower())) / 4.0), 0.6),
            rationale="transition/hook lexical hints",
        ),
        "self_questioning_rounds": CapabilityMetricResult(
            metric_id="self_questioning_rounds",
            description="自我追问痕迹",
            value=1.0 if ("?" in section_text or "?" in section_text) else 0.0,
            target=0.6,
            status=_status_from_ratio(1.0 if ("?" in section_text or "?" in section_text) else 0.0, 0.6),
            rationale="question-mark heuristic in section text",
        ),
        "review_comment_closure": CapabilityMetricResult(
            metric_id="review_comment_closure",
            description="审稿意见闭环率",
            value=_clip(float(len(rebuttal_closed)) / float(len(project.reviewer_comments))) if project.reviewer_comments else 1.0,
            target=0.75,
            status=_status_from_ratio(_clip(float(len(rebuttal_closed)) / float(len(project.reviewer_comments))) if project.reviewer_comments else 1.0, 0.75),
            rationale=f"closed_actions={len(rebuttal_closed)}/{len(project.reviewer_comments)}",
        ),
        "rebuttal_action_traceability": CapabilityMetricResult(
            metric_id="rebuttal_action_traceability",
            description="修订动作证据可追溯率",
            value=_clip(
                float(len([a for a in project.rebuttal_actions if a.evidence_ids or a.section_ids])) / float(len(project.rebuttal_actions))
            )
            if project.rebuttal_actions
            else 1.0,
            target=0.75,
            status=_status_from_ratio(
                _clip(float(len([a for a in project.rebuttal_actions if a.evidence_ids or a.section_ids])) / float(len(project.rebuttal_actions)))
                if project.rebuttal_actions
                else 1.0,
                0.75,
            ),
            rationale=f"rebuttal_actions={len(project.rebuttal_actions)}",
        ),
        "unresolved_issue_control": CapabilityMetricResult(
            metric_id="unresolved_issue_control",
            description="未解决问题控制",
            value=_clip(1.0 - unresolved_ratio),
            target=0.7,
            status=_status_from_ratio(_clip(1.0 - unresolved_ratio), 0.7),
            rationale=f"unresolved_ratio={round(unresolved_ratio, 4)}",
        ),
        "compliance_risk_control": CapabilityMetricResult(
            metric_id="compliance_risk_control",
            description="伦理与合规风险控制",
            value={"low": 1.0, "medium": 0.7, "high": 0.2, "critical": 0.0}.get(risk_level, 0.4),
            target=0.8,
            status=_status_from_ratio({"low": 1.0, "medium": 0.7, "high": 0.2, "critical": 0.0}.get(risk_level, 0.4), 0.8),
            rationale=f"risk_level={risk_level}",
        ),
        "repro_evidence_presence": CapabilityMetricResult(
            metric_id="repro_evidence_presence",
            description="可复现证据存在性",
            value=_clip(float(len([e for e in evidence_units if e.evidence_type in {'raw_data', 'image_report'}])) / max(float(len(evidence_units)), 1.0)),
            target=0.6,
            status=_status_from_ratio(
                _clip(float(len([e for e in evidence_units if e.evidence_type in {'raw_data', 'image_report'}])) / max(float(len(evidence_units)), 1.0)),
                0.6,
            ),
            rationale="ratio of raw_data/image_report evidence units",
        ),
        "risk_template_trigger": CapabilityMetricResult(
            metric_id="risk_template_trigger",
            description="高风险自动降级模板触发",
            value=1.0 if (risk_level in {"high", "critical"} and safety_valve_triggered) or (risk_level not in {"high", "critical"}) else 0.0,
            target=1.0,
            status="pass"
            if ((risk_level in {"high", "critical"} and safety_valve_triggered) or (risk_level not in {"high", "critical"}))
            else "fail",
            rationale=f"safety_valve_triggered={safety_valve_triggered}",
        ),
        "tex_artifact_ready": CapabilityMetricResult(
            metric_id="tex_artifact_ready",
            description="tex 交付准备度",
            value=1.0 if str((latex_payload or {}).get("tex_path") or "").strip() else 0.0,
            target=1.0,
            status="pass" if str((latex_payload or {}).get("tex_path") or "").strip() else "fail",
            rationale="tex_path exists in latest latex payload",
        ),
        "pdf_compile_success": CapabilityMetricResult(
            metric_id="pdf_compile_success",
            description="PDF 编译成功率代理",
            value=1.0 if compile_status == "success" else (0.5 if compile_status == "skipped" else 0.0),
            target=0.8,
            status=_status_from_ratio(1.0 if compile_status == "success" else (0.5 if compile_status == "skipped" else 0.0), 0.8),
            rationale=f"compile_status={compile_status}",
        ),
        "diagnostic_report_ready": CapabilityMetricResult(
            metric_id="diagnostic_report_ready",
            description="失败诊断报告可用",
            value=1.0 if str((latex_payload or {}).get("compile_log_path") or "").strip() else 0.0,
            target=1.0,
            status="pass" if str((latex_payload or {}).get("compile_log_path") or "").strip() else "fail",
            rationale="compile_log_path exists in latest latex payload",
        ),
        "term_stability": CapabilityMetricResult(
            metric_id="term_stability",
            description="术语稳定性",
            value=_clip(float(len(set(project.research_questions + project.hypotheses))) / max(float(len(project.research_questions) + len(project.hypotheses)), 1.0)),
            target=0.7,
            status=_status_from_ratio(
                _clip(float(len(set(project.research_questions + project.hypotheses))) / max(float(len(project.research_questions) + len(project.hypotheses)), 1.0)),
                0.7,
            ),
            rationale="unique-term ratio over question/hypothesis pool",
        ),
        "citation_library_stability": CapabilityMetricResult(
            metric_id="citation_library_stability",
            description="引用库稳定性",
            value=_clip(float(len(set(c.citation_id for c in citations))) / max(float(len(citations)), 1.0)),
            target=0.7,
            status=_status_from_ratio(_clip(float(len(set(c.citation_id for c in citations))) / max(float(len(citations)), 1.0)), 0.7),
            rationale=f"unique_citations={len(set(c.citation_id for c in citations))}",
        ),
        "versioned_traceability": CapabilityMetricResult(
            metric_id="versioned_traceability",
            description="版本化可追溯性",
            value=1.0 if len(versions) >= 1 else 0.0,
            target=0.8,
            status=_status_from_ratio(1.0 if len(versions) >= 1 else 0.0, 0.8),
            rationale=f"section_versions={len(versions)}",
        ),
    }

    scorecards: list[CapabilityScorecard] = []
    for item in catalog["capabilities"]:
        metric_ids = [m["metric_id"] for m in item["metrics"]]
        metrics = [metric_map[mid] for mid in metric_ids if mid in metric_map]
        capability_score = _clip(sum(m.value for m in metrics) / max(float(len(metrics)), 1.0))
        capability_status = _status_from_ratio(capability_score, 0.75)
        failures = item["failure_modes"] if capability_status != "pass" else []
        scorecards.append(
            CapabilityScorecard(
                capability_id=item["capability_id"],
                capability_name=item["name"],
                score=capability_score,
                status=capability_status,
                metrics=metrics,
                triggered_failure_modes=failures,
            )
        )

    overall = _clip(sum(card.score for card in scorecards) / max(float(len(scorecards)), 1.0))
    return {
        "schema_version": CAPABILITY_SNAPSHOT_SCHEMA_VERSION,
        "catalog_schema_version": CAPABILITY_CATALOG_SCHEMA_VERSION,
        "overall_score": round(overall, 4),
        "status": _status_from_ratio(overall, 0.75),
        "scorecards": [card.model_dump() for card in scorecards],
        "inputs": {
            "project_id": project.project_id,
            "section_id": section.section_id if section is not None else None,
            "claim_count": len(claims),
            "evidence_count": len(evidence_units),
            "citation_count": len(citations),
            "fact_count": len(facts),
            "hitl_decision_count": len(hitl_decisions),
        },
    }
