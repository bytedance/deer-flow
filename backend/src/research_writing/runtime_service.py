"""Runtime service layer for research-writing workflows."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from src.config.failure_mode_gate_config import get_failure_mode_gate_config
from src.config.journal_style_config import get_journal_style_config
from src.config.latex_config import get_latex_config
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.config.reviewer2_strategy_config import get_reviewer2_strategy_config
from src.evals.academic import (
    FAILURE_MODE_GATES_SCHEMA_VERSION,
    FailureModeThresholds,
    evaluate_case,
    evaluate_dataset,
    evaluate_failure_mode_library,
)
from src.evals.academic.importer import import_accept_reject_payload
from src.evals.academic.leaderboard import (
    LEADERBOARD_SCHEMA_VERSION,
    WeeklyLeaderboard,
    build_weekly_entries,
    merge_weekly_leaderboard,
)
from src.evals.academic.preprocessor import (
    preprocess_accept_reject_payload,
    render_autofix_report_markdown,
)
from src.evals.academic.schemas import AcademicEvalCase, AcademicEvalSummary
from src.evals.academic.validator import (
    render_validation_report_markdown,
    validate_accept_reject_payload,
)
from src.research_writing.agentic_graph import run_agentic_blackboard_graph
from src.research_writing.capability_framework import capability_catalog, evaluate_capabilities
from src.research_writing.citation_registry import CitationRecord, CitationRegistry
from src.research_writing.claim_graph import Claim, ClaimGraph
from src.research_writing.constraint_compiler import ClaimConstraintCompiler, classify_claim_sentence
from src.research_writing.ethics_compliance import audit_scientific_compliance
from src.research_writing.evidence_store import EvidenceStore, EvidenceUnit
from src.research_writing.fulltext_ingest import FullTextEvidenceIngestor, LiteratureSource
from src.research_writing.hypothesis_engine import generate_hypotheses
from src.research_writing.journal_style import build_journal_style_bundle
from src.research_writing.latex_pipeline import build_latex_artifacts
from src.research_writing.narrative_planner import NarrativePlan, NarrativePlannerAgent
from src.research_writing.peer_review_loop import run_peer_review_loop
from src.research_writing.policy_learning import learn_policy_from_hitl_decisions
from src.research_writing.project_state import HitlDecision, ResearchProject, ResearchProjectStateStore, SectionDraft
from src.research_writing.prompt_pack import (
    DEFAULT_PROMPT_PACK_ID,
    build_style_adapter_profile,
    get_prompt_pack_metadata,
    get_runtime_stage_recipe,
)
from src.research_writing.reviewer_rebuttal import build_rebuttal_plan, render_rebuttal_letter, simulate_reviewer_comments
from src.research_writing.section_compiler import (
    CompileMode,
    NarrativeEvidenceDensity,
    NarrativeSectionType,
    NarrativeTone,
    NarrativeWritingStrategy,
    SectionCompiler,
)
from src.research_writing.self_play_trainer import SelfPlayEpisodeInput, run_self_play_training
from src.research_writing.source_of_truth import NumericFact, SourceOfTruthStore
from src.research_writing.venue_profiles import VENUE_PROFILES

NarrativeStyleOverride = Literal["auto", "conservative", "balanced", "aggressive"]
NarrativeToneOverride = Literal["conservative", "balanced", "aggressive"]
NarrativeDensityOverride = Literal["low", "medium", "high"]
LatexEngineOverride = Literal["auto", "none", "latexmk", "pdflatex", "xelatex"]
Reviewer2StyleOverride = Literal["statistical_tyrant", "methodology_fundamentalist", "domain_traditionalist"]
PeerReviewABVariantOverride = Literal["off", "A", "B"]
PeerReviewABVariantInputOverride = Literal["off", "A", "B", "auto"]


def _outputs_dir(thread_id: str) -> Path:
    outputs = get_paths().sandbox_outputs_dir(thread_id)
    outputs.mkdir(parents=True, exist_ok=True)
    return outputs


def _research_root(thread_id: str) -> Path:
    root = _outputs_dir(thread_id) / "research-writing"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _to_virtual_path(thread_id: str, path: Path) -> str:
    rel = path.resolve().relative_to(_outputs_dir(thread_id).resolve())
    return f"{VIRTUAL_PATH_PREFIX}/outputs/{rel.as_posix()}"


def _dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


SECTION_VERSION_SCHEMA_VERSION = "deerflow.section_versions.v1"
SECTION_DIFF_SCHEMA_VERSION = "deerflow.section_change_diff.v1"
SECTION_TRACE_SCHEMA_VERSION = "deerflow.section_trace.v1"
SELF_PLAY_SCHEMA_VERSION = "deerflow.self_play_training.v1"
COMPLIANCE_AUDIT_SCHEMA_VERSION = "deerflow.compliance_audit.v1"
POLICY_SNAPSHOT_SCHEMA_VERSION = "deerflow.policy_snapshot.v1"
POLICY_WRITING_DIRECTIVES_SCHEMA_VERSION = "deerflow.policy_writing_directives.v1"
PEER_REVIEW_AB_METRICS_SCHEMA_VERSION = "deerflow.peer_review_ab_metrics.v1"
AGENTIC_GRAPH_SCHEMA_VERSION = "deerflow.agentic_graph.v1"
CAPABILITY_ASSESSMENT_SCHEMA_VERSION = "deerflow.capability_assessment.v1"
ENGINEERING_GATES_SCHEMA_VERSION = "deerflow.engineering_gates.v1"
COMPILE_GATES_METRICS_SCHEMA_VERSION = "deerflow.compile_gates_metrics.v1"
LATEX_GATES_METRICS_SCHEMA_VERSION = "deerflow.latex_gates_metrics.v1"
ENGINEERING_GATES_RUNTIME_METRICS_SCHEMA_VERSION = "deerflow.engineering_gates_runtime_metrics.v1"
CLAIM_MAP_SCHEMA_VERSION = "deerflow.claim_map.v1"
PROMPT_REGISTRY_METADATA_SCHEMA_VERSION = "deerflow.prompt_registry_metadata.v1"
SELF_PLAY_FEW_SHOT_LIBRARY_SCHEMA_VERSION = "deerflow.self_play_fewshot_library.v1"


def _resolve_prompt_pack_metadata() -> dict[str, Any]:
    raw = get_prompt_pack_metadata()
    prompt_pack_id = str(raw.get("prompt_pack_id") or DEFAULT_PROMPT_PACK_ID).strip() or DEFAULT_PROMPT_PACK_ID
    prompt_pack_hash = str(raw.get("prompt_pack_hash") or "").strip()
    if not prompt_pack_hash:
        prompt_pack_hash = hashlib.sha256(prompt_pack_id.encode("utf-8")).hexdigest()[:16]
    prompt_layer_versions = raw.get("prompt_layer_versions") or {}
    prompt_layer_rollbacks = raw.get("prompt_layer_rollbacks") or {}
    prompt_layer_signatures = raw.get("prompt_layer_signatures") or {}
    prompt_layer_compare_ready_layers = raw.get("prompt_layer_compare_ready_layers") or []
    prompt_layer_diff_summary = raw.get("prompt_layer_diff_summary")
    if not isinstance(prompt_layer_diff_summary, dict):
        baseline_signatures: dict[str, str] = {}
        prompt_layers_raw = raw.get("prompt_layers")
        prompt_layers = prompt_layers_raw if isinstance(prompt_layers_raw, list) else []
        for row in prompt_layers:
            if not isinstance(row, dict):
                continue
            layer_id = str(row.get("layer_id") or "").strip()
            if not layer_id:
                continue
            baseline_signatures[layer_id] = str(row.get("baseline_signature") or "").strip()
        compare_ready_layers = (
            set(prompt_layer_compare_ready_layers) if isinstance(prompt_layer_compare_ready_layers, list) else set()
        )
        layer_ids = sorted({*prompt_layer_versions.keys(), *prompt_layer_rollbacks.keys()})
        layer_entries: list[dict[str, Any]] = []
        changed_layers: list[dict[str, Any]] = []
        for layer_id in layer_ids:
            active_version = str(prompt_layer_versions.get(layer_id) or "").strip()
            rollback_version = str(prompt_layer_rollbacks.get(layer_id) or "").strip()
            if not active_version and not rollback_version:
                continue
            changed = active_version != rollback_version
            compare_ready = layer_id in compare_ready_layers or changed
            compare_ready_source = (
                "prompt_layer_compare_ready_layers"
                if layer_id in compare_ready_layers
                else "computed_active_vs_rollback"
            )
            entry = {
                "layer_id": layer_id,
                "active_version": active_version,
                "rollback_version": rollback_version,
                "active_signature": str(prompt_layer_signatures.get(layer_id) or "").strip(),
                "rollback_signature": str(baseline_signatures.get(layer_id) or "").strip(),
                "compare_ready": compare_ready,
                "compare_ready_source": compare_ready_source,
                "changed": changed,
            }
            layer_entries.append(entry)
            if changed:
                changed_layers.append(entry)
        prompt_layer_diff_summary = {
            "total_layers": len(layer_ids),
            "changed_layer_count": len(changed_layers),
            "layer_entries": layer_entries,
            "changed_layers": changed_layers,
            "has_diff": len(changed_layers) > 0,
        }
    return {
        "prompt_pack_id": prompt_pack_id,
        "prompt_pack_hash": prompt_pack_hash,
        "prompt_pack_hash_source": raw.get("prompt_pack_hash_source") or "auto_computed",
        "prompt_pack_source_files": raw.get("prompt_pack_source_files") or [],
        "prompt_layer_schema_version": raw.get("prompt_layer_schema_version") or "",
        "prompt_layers": raw.get("prompt_layers") or [],
        "prompt_layer_overrides_applied": raw.get("prompt_layer_overrides_applied") or {},
        "prompt_layer_versions": prompt_layer_versions,
        "prompt_layer_rollbacks": prompt_layer_rollbacks,
        "prompt_layer_signatures": prompt_layer_signatures,
        "prompt_layer_compare_ready_layers": prompt_layer_compare_ready_layers,
        "prompt_layer_diff_summary": prompt_layer_diff_summary,
        "runtime_stage_recipe_schema_version": raw.get("runtime_stage_recipe_schema_version") or "",
        "runtime_stage_recipe_stages": raw.get("runtime_stage_recipe_stages") or [],
    }


def _inject_prompt_pack_fields(payload: dict[str, Any]) -> dict[str, Any]:
    prompt_pack = _resolve_prompt_pack_metadata()
    for key, value in prompt_pack.items():
        payload[key] = value
    prompt_registry = _build_prompt_registry_metadata(payload, prompt_pack_metadata=prompt_pack)
    payload["runtime_strategy"] = prompt_registry["runtime_strategy"]
    payload["runtime_strategy_hash"] = prompt_registry["runtime_strategy_hash"]
    payload["eval_impact"] = prompt_registry["eval_impact"]
    payload["prompt_registry_schema_version"] = prompt_registry["schema_version"]
    payload["eval_attribution_key"] = prompt_registry["eval_attribution_key"]
    return payload


def _resolve_runtime_strategy_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    existing = source.get("runtime_strategy")
    if isinstance(existing, dict) and all(key in existing for key in ("narrative", "peer_review", "journal_style", "policy_snapshot")):
        return existing

    narrative_strategy = source.get("narrative_strategy") if isinstance(source.get("narrative_strategy"), dict) else {}
    peer_review_strategy = source.get("peer_review_strategy") if isinstance(source.get("peer_review_strategy"), dict) else {}
    peer_review_payload = source.get("peer_review") if isinstance(source.get("peer_review"), dict) else {}
    venue_style_adapter = source.get("venue_style_adapter") if isinstance(source.get("venue_style_adapter"), dict) else {}
    has_policy_snapshot = isinstance(source.get("policy_snapshot"), dict) and len(source.get("policy_snapshot") or {}) > 0
    has_journal_style = isinstance(source.get("journal_style"), dict) and len(source.get("journal_style") or {}) > 0

    peer_review_variant = str(
        source.get("peer_review_ab_variant")
        or peer_review_strategy.get("ab_variant")
        or ""
    ).strip()
    return {
        "narrative": {
            "enabled": bool(narrative_strategy),
            "tone": narrative_strategy.get("tone"),
            "evidence_density": narrative_strategy.get("evidence_density"),
            "max_templates": narrative_strategy.get("max_templates"),
            "auto_by_section_type": bool(narrative_strategy.get("auto_by_section_type")),
        },
        "peer_review": {
            "enabled": bool(peer_review_payload) or bool(peer_review_strategy) or peer_review_variant not in {"", "off"},
            "ab_variant": peer_review_variant or None,
            "max_rounds": source.get("peer_review_max_rounds"),
            "style_source": peer_review_strategy.get("style_source"),
            "round_source": peer_review_strategy.get("round_source"),
        },
        "journal_style": {
            "enabled": has_journal_style or bool(source.get("journal_style_alignment_applied")),
            "alignment_applied": bool(source.get("journal_style_alignment_applied")),
            "source": venue_style_adapter.get("source"),
        },
        "policy_snapshot": {
            "enabled": has_policy_snapshot or ("policy_snapshot_auto_adjust_narrative" in source),
            "auto_adjust_narrative": bool(source.get("policy_snapshot_auto_adjust_narrative")),
            "adjustment_applied": bool(source.get("policy_snapshot_adjustment_applied")),
        },
    }


def _resolve_eval_impact_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    existing = source.get("eval_impact")
    if isinstance(existing, dict):
        return existing

    peer_review_payload = source.get("peer_review") if isinstance(source.get("peer_review"), dict) else {}
    engineering_gates = source.get("engineering_gates") if isinstance(source.get("engineering_gates"), dict) else {}
    constraint_violation = engineering_gates.get("constraint_violation") if isinstance(engineering_gates.get("constraint_violation"), dict) else {}
    traceability_coverage = engineering_gates.get("traceability_coverage") if isinstance(engineering_gates.get("traceability_coverage"), dict) else {}
    delivery_completeness = engineering_gates.get("delivery_completeness") if isinstance(engineering_gates.get("delivery_completeness"), dict) else {}
    payload: dict[str, Any] = {
        "peer_review_final_decision": peer_review_payload.get("final_decision"),
        "peer_review_unresolved_issue_count": peer_review_payload.get("unresolved_issue_count"),
        "peer_review_ab_variant": source.get("peer_review_ab_variant"),
        "safety_valve_triggered": bool(source.get("safety_valve_triggered")),
        "constraint_violation_ratio": constraint_violation.get("issues_error_ratio"),
        "traceability_coverage_ratio": traceability_coverage.get("full_covered_sentence_ratio"),
        "delivery_completeness_ratio": delivery_completeness.get("completeness_ratio"),
        "academic_eval_score": source.get("score"),
        "leaderboard_entries_updated": source.get("leaderboard_entries_updated"),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _build_prompt_registry_metadata(
    payload: dict[str, Any] | None,
    *,
    prompt_pack_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt_pack = prompt_pack_metadata if isinstance(prompt_pack_metadata, dict) else _resolve_prompt_pack_metadata()
    runtime_strategy = _resolve_runtime_strategy_metadata(payload)
    runtime_strategy_json = json.dumps(runtime_strategy, sort_keys=True, ensure_ascii=False)
    runtime_strategy_hash = hashlib.sha256(runtime_strategy_json.encode("utf-8")).hexdigest()[:16]
    eval_impact = _resolve_eval_impact_metadata(payload)
    attribution_seed = {
        "prompt_pack_id": prompt_pack.get("prompt_pack_id"),
        "prompt_pack_hash": prompt_pack.get("prompt_pack_hash"),
        "runtime_strategy_hash": runtime_strategy_hash,
    }
    eval_attribution_key = hashlib.sha256(
        json.dumps(attribution_seed, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:20]
    return {
        "schema_version": PROMPT_REGISTRY_METADATA_SCHEMA_VERSION,
        "prompt_pack_id": prompt_pack.get("prompt_pack_id"),
        "prompt_pack_hash": prompt_pack.get("prompt_pack_hash"),
        "runtime_strategy": runtime_strategy,
        "runtime_strategy_hash": runtime_strategy_hash,
        "eval_impact": eval_impact,
        "eval_attribution_key": eval_attribution_key,
    }


def _resolve_runtime_stage_context(
    *,
    operation: Literal["plan_narrative", "compile_section", "simulate_review", "simulate_peer_review", "latex_submit"],
    auto_peer_review: bool = False,
    auto_hypothesis: bool = False,
) -> dict[str, Any]:
    recipe_all = get_runtime_stage_recipe()
    rows = recipe_all.get("stages")
    if not isinstance(rows, list):
        rows = []
    by_stage: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        stage = str(row.get("stage") or "").strip()
        if not stage:
            continue
        by_stage[stage] = row
    if operation == "plan_narrative":
        active_stage_ids = ["plan"]
    elif operation == "compile_section":
        active_stage_ids = ["plan", "draft"]
        if auto_peer_review or auto_hypothesis:
            active_stage_ids.append("verify")
        if auto_peer_review:
            active_stage_ids.append("revise")
    elif operation == "simulate_review":
        active_stage_ids = ["verify", "revise"]
    elif operation == "simulate_peer_review":
        active_stage_ids = ["verify", "revise"]
    else:
        active_stage_ids = ["submit"]
    active_stages = [by_stage[stage] for stage in active_stage_ids if stage in by_stage]
    return {
        "schema_version": recipe_all.get("schema_version"),
        "operation": operation,
        "active_stage_ids": active_stage_ids,
        "active_stages": active_stages,
        "full_pipeline_stages": [str(row.get("stage") or "") for row in rows if isinstance(row, dict)],
    }


def _prompt_layer_snapshot() -> dict[str, Any]:
    prompt_pack = _resolve_prompt_pack_metadata()
    return {
        "schema_version": prompt_pack.get("prompt_layer_schema_version") or "",
        "versions": prompt_pack.get("prompt_layer_versions") or {},
        "rollbacks": prompt_pack.get("prompt_layer_rollbacks") or {},
        "signatures": prompt_pack.get("prompt_layer_signatures") or {},
        "compare_ready_layers": prompt_pack.get("prompt_layer_compare_ready_layers") or [],
    }


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    denom = float(denominator)
    if denom <= 0:
        return 0.0
    return round(float(numerator) / denom, 6)


def _safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)


def _coerce_ratio(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric < 0:
        return 0.0
    if numeric > 1:
        return 1.0
    return round(numeric, 6)


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s+|\n{2,}")
_CLAIM_TAG_RE = re.compile(r"\[claim:([^\]]+)\]", flags=re.IGNORECASE)
_DATA_TAG_RE = re.compile(r"\[data:([^\]]+)\]", flags=re.IGNORECASE)
_CITATION_TAG_RE = re.compile(r"\[citation:([^\]]+)\]", flags=re.IGNORECASE)
_FIGURE_HINT_KEYS = (
    "figure_path",
    "figure_paths",
    "image_path",
    "image_paths",
    "plot_path",
    "plot_paths",
    "chart_path",
    "chart_paths",
    "artifact_path",
    "artifact_paths",
    "overlay_path",
    "overlay_paths",
)
CLAIM_GROUNDING_SCHEMA_VERSION = "deerflow.claim_grounding_ast.v1"
_NUMERIC_LITERAL_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_P_VALUE_AST_RE = re.compile(r"\bp\s*[<=>]\s*\d+(?:\.\d+)?", flags=re.IGNORECASE)
_CI_AST_RE = re.compile(r"\b(?:ci|confidence interval)\b", flags=re.IGNORECASE)
_EFFECT_SIZE_AST_RE = re.compile(r"\b(?:effect size|cohen'?s d|odds ratio|hazard ratio)\b", flags=re.IGNORECASE)
_FACT_TAG_RE = re.compile(r"\[fact:([^\]]+)\]", flags=re.IGNORECASE)
_STAT_EVIDENCE_KEYS: tuple[str, ...] = (
    "p_value",
    "pvalue",
    "confidence_interval",
    "ci",
    "effect_size",
    "t_stat",
    "f_stat",
    "anova",
    "wilcoxon",
)
_ROI_EVIDENCE_KEYS: tuple[str, ...] = (
    "roi_id",
    "roi_ids",
    "roi",
    "roi_bbox",
    "regions_of_interest",
    "mask_path",
)
_CONCLUSION_TRIGGER_RE = re.compile(
    r"\b("
    r"therefore|thus|in summary|overall|we conclude|our finding|our findings|"
    r"demonstrates?|prove[sd]?|shows?|indicates?|confirms?|establishes?"
    r")\b",
    flags=re.IGNORECASE,
)
_LIMITATION_SENTENCE_RE = re.compile(r"\b(limitation|caveat|uncertain|future work)\b", flags=re.IGNORECASE)
_MECHANISM_CONFLICT_HINT_RE = re.compile(
    r"\b(conflict|discrepancy|reconcile|reconciliation|mechanism|while|whereas|however)\b",
    flags=re.IGNORECASE,
)


def _dedup_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = raw.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _build_constraint_violation_metrics(*, issues: list[Any], compiled_text: str) -> dict[str, Any]:
    total_issues = len(issues)
    error_count = 0
    for issue in issues:
        severity = ""
        if isinstance(issue, dict):
            severity = str(issue.get("severity") or "")
        else:
            severity = str(getattr(issue, "severity", "") or "")
        if severity == "error":
            error_count += 1
    sentences = _split_sentences(compiled_text)
    sentence_count = len(sentences)
    marker_counter = Counter({"grounding_required": 0, "insufficient_data": 0, "citation_needed": 0})
    for sentence in sentences:
        lowered = sentence.lower()
        if "[grounding required]" in lowered:
            marker_counter["grounding_required"] += 1
        if "[insufficient data]" in lowered:
            marker_counter["insufficient_data"] += 1
        if "[citation needed]" in lowered:
            marker_counter["citation_needed"] += 1
    marker_sentence_total = sum(marker_counter.values())
    return {
        "issues_total": total_issues,
        "issues_error_count": error_count,
        "issues_error_ratio": _safe_ratio(error_count, total_issues),
        "compiled_sentence_count": sentence_count,
        "marker_sentence_total": marker_sentence_total,
        "marker_sentence_ratio": _safe_ratio(marker_sentence_total, sentence_count),
        "marker_sentence_counts": dict(marker_counter),
        "marker_sentence_ratios": {
            "grounding_required": _safe_ratio(marker_counter["grounding_required"], sentence_count),
            "insufficient_data": _safe_ratio(marker_counter["insufficient_data"], sentence_count),
            "citation_needed": _safe_ratio(marker_counter["citation_needed"], sentence_count),
        },
    }


def _build_traceability_coverage_metrics(trace_payload: dict[str, Any]) -> dict[str, Any]:
    sentence_rows = trace_payload.get("sentence_links")
    if not isinstance(sentence_rows, list):
        sentence_rows = []
    total_sentences = len(sentence_rows)
    full_covered = 0
    missing_claim = 0
    missing_evidence = 0
    missing_citation = 0
    gaps: list[dict[str, Any]] = []
    for row in sentence_rows:
        if not isinstance(row, dict):
            continue
        sentence_id = str(row.get("sentence_id") or "").strip() or "unknown"
        claim_ids = row.get("claim_ids") if isinstance(row.get("claim_ids"), list) else []
        evidence_ids = row.get("evidence_ids") if isinstance(row.get("evidence_ids"), list) else []
        citation_ids = row.get("citation_ids") if isinstance(row.get("citation_ids"), list) else []
        has_claim = len(claim_ids) > 0
        has_evidence = len(evidence_ids) > 0
        has_citation = len(citation_ids) > 0
        if has_claim and has_evidence and has_citation:
            full_covered += 1
            continue
        row_gaps: list[str] = []
        if not has_claim:
            missing_claim += 1
            row_gaps.append("claim")
        if not has_evidence:
            missing_evidence += 1
            row_gaps.append("evidence")
        if not has_citation:
            missing_citation += 1
            row_gaps.append("citation")
        gaps.append({"sentence_id": sentence_id, "missing": row_gaps})
    return {
        "sentence_total": total_sentences,
        "full_covered_sentence_count": full_covered,
        "full_covered_sentence_ratio": _safe_ratio(full_covered, total_sentences),
        "missing_claim_sentence_count": missing_claim,
        "missing_evidence_sentence_count": missing_evidence,
        "missing_citation_sentence_count": missing_citation,
        "gaps": gaps[:64],
    }


def _build_delivery_completeness_metrics(*, artifact_paths: dict[str, str | None]) -> dict[str, Any]:
    required_keys = (
        "compiled_md",
        "details_json",
        "trace_json",
        "version_diff_json",
        "policy_snapshot_json",
        "compliance_audit_json",
    )
    present_keys: list[str] = []
    missing_keys: list[str] = []
    for key in required_keys:
        raw = artifact_paths.get(key)
        if isinstance(raw, str) and raw.strip():
            present_keys.append(key)
        else:
            missing_keys.append(key)
    return {
        "required_artifacts": list(required_keys),
        "present_artifacts": present_keys,
        "missing_artifacts": missing_keys,
        "present_count": len(present_keys),
        "required_count": len(required_keys),
        "completeness_ratio": _safe_ratio(len(present_keys), len(required_keys)),
        "is_complete": len(missing_keys) == 0,
    }


def _build_safety_valve_metrics(*, triggered: bool, reasons: list[str]) -> dict[str, Any]:
    reason_counter = Counter([str(item).strip() for item in reasons if str(item).strip()])
    return {
        "triggered": bool(triggered),
        "reason_count": len(reasons),
        "reason_distribution": dict(reason_counter),
    }


def _metrics_path(thread_id: str, name: str) -> Path:
    return _research_root(thread_id) / "metrics" / f"{name}.json"


def _load_or_init_metrics(path: Path, *, schema_version: str, defaults: dict[str, Any]) -> dict[str, Any]:
    payload = _load_json_dict(path)
    if not payload:
        payload = {}
    merged = {"schema_version": schema_version, **defaults, **payload}
    merged["schema_version"] = schema_version
    return merged


def _persist_metrics(path: Path, payload: dict[str, Any]) -> str:
    payload["updated_at"] = _now_iso()
    _dump_json(path, payload)
    return payload["updated_at"]


def _record_compile_attempt_metrics(
    *,
    thread_id: str,
    strict_mode: bool,
    hitl_blocking: bool,
    count_attempt: bool = True,
    safety_valve_triggered: bool | None = None,
    safety_valve_reasons: list[str] | None = None,
) -> dict[str, Any]:
    path = _metrics_path(thread_id, "compile-gates")
    payload = _load_or_init_metrics(
        path,
        schema_version=COMPILE_GATES_METRICS_SCHEMA_VERSION,
        defaults={
            "total_compile_attempts": 0,
            "successful_compile_runs": 0,
            "strict_compile_attempts": 0,
            "strict_hitl_blocked_count": 0,
            "safety_valve_triggered_count": 0,
            "safety_valve_reason_distribution": {},
        },
    )
    if count_attempt:
        payload["total_compile_attempts"] = int(payload.get("total_compile_attempts") or 0) + 1
        if strict_mode:
            payload["strict_compile_attempts"] = int(payload.get("strict_compile_attempts") or 0) + 1
        if strict_mode and hitl_blocking:
            payload["strict_hitl_blocked_count"] = int(payload.get("strict_hitl_blocked_count") or 0) + 1
    if safety_valve_triggered is not None:
        payload["successful_compile_runs"] = int(payload.get("successful_compile_runs") or 0) + 1
        if safety_valve_triggered:
            payload["safety_valve_triggered_count"] = int(payload.get("safety_valve_triggered_count") or 0) + 1
        dist = payload.get("safety_valve_reason_distribution")
        if not isinstance(dist, dict):
            dist = {}
        for reason in safety_valve_reasons or []:
            key = str(reason).strip()
            if not key:
                continue
            dist[key] = int(dist.get(key) or 0) + 1
        payload["safety_valve_reason_distribution"] = dist
    _persist_metrics(path, payload)
    return payload


def _classify_latex_failure(*, compile_status: str, warning: str | None, compile_log_text: str) -> str:
    status = compile_status.strip().lower()
    if status == "success":
        return "success"
    if status == "skipped":
        return "skipped"
    lowered = (compile_log_text or "").lower()
    warning_text = (warning or "").lower()
    if "no latex engine found" in lowered:
        return "missing_engine"
    if "timeout" in lowered:
        return "timeout"
    if "return code=" in lowered:
        return "compile_error"
    if "pdf file is missing" in lowered:
        return "missing_pdf"
    if "did not produce pdf" in warning_text:
        return "no_pdf_output"
    return "other_failure"


def _record_latex_compile_metrics(
    *,
    thread_id: str,
    compile_status: str,
    warning: str | None,
    compile_log_text: str,
) -> dict[str, Any]:
    path = _metrics_path(thread_id, "latex-gates")
    payload = _load_or_init_metrics(
        path,
        schema_version=LATEX_GATES_METRICS_SCHEMA_VERSION,
        defaults={
            "total_runs": 0,
            "compile_status_distribution": {"success": 0, "failed": 0, "skipped": 0},
            "compile_failure_type_clusters": {},
        },
    )
    payload["total_runs"] = int(payload.get("total_runs") or 0) + 1
    distribution = payload.get("compile_status_distribution")
    if not isinstance(distribution, dict):
        distribution = {"success": 0, "failed": 0, "skipped": 0}
    status_key = compile_status.strip().lower()
    if status_key not in {"success", "failed", "skipped"}:
        status_key = "failed"
    distribution[status_key] = int(distribution.get(status_key) or 0) + 1
    payload["compile_status_distribution"] = distribution
    if status_key == "failed":
        failure_key = _classify_latex_failure(
            compile_status=compile_status,
            warning=warning,
            compile_log_text=compile_log_text,
        )
        clusters = payload.get("compile_failure_type_clusters")
        if not isinstance(clusters, dict):
            clusters = {}
        clusters[failure_key] = int(clusters.get(failure_key) or 0) + 1
        payload["compile_failure_type_clusters"] = clusters
    _persist_metrics(path, payload)
    return payload


def _section_versions_path(thread_id: str, project_id: str, section_id: str) -> Path:
    return _research_root(thread_id) / "section-versions" / f"{project_id}-{section_id}.json"


def _load_section_versions(thread_id: str, project_id: str, section_id: str) -> dict[str, Any]:
    path = _section_versions_path(thread_id, project_id, section_id)
    if not path.exists():
        return {
            "schema_version": SECTION_VERSION_SCHEMA_VERSION,
            "project_id": project_id,
            "section_id": section_id,
            "versions": [],
            "updated_at": None,
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    versions = raw.get("versions")
    if not isinstance(versions, list):
        versions = []
    normalized_versions = [item for item in versions if isinstance(item, dict)]
    return {
        "schema_version": raw.get("schema_version") or SECTION_VERSION_SCHEMA_VERSION,
        "project_id": raw.get("project_id") or project_id,
        "section_id": raw.get("section_id") or section_id,
        "versions": normalized_versions,
        "updated_at": raw.get("updated_at"),
    }


def _save_section_versions(thread_id: str, project_id: str, section_id: str, payload: dict[str, Any]) -> str:
    path = _section_versions_path(thread_id, project_id, section_id)
    payload["updated_at"] = _now_iso()
    _dump_json(path, payload)
    return _to_virtual_path(thread_id, path)


def _extract_tag_ids(text: str, *, tag: Literal["claim", "data", "citation"]) -> list[str]:
    if not text:
        return []
    if tag == "claim":
        matches = _CLAIM_TAG_RE.findall(text)
    elif tag == "data":
        matches = _DATA_TAG_RE.findall(text)
    else:
        matches = _CITATION_TAG_RE.findall(text)
    return _dedup_keep_order([str(item).strip() for item in matches])


def _normalize_line(line: str) -> str:
    compact = line.strip()
    compact = re.sub(r"^#{1,6}\s+", "", compact)
    compact = re.sub(r"^[-*+]\s+", "", compact)
    compact = re.sub(r"^\d+\.\s+", "", compact)
    compact = re.sub(r"\s+", " ", compact)
    return compact.strip()


def _split_sentences(text: str) -> list[str]:
    if not text.strip():
        return []
    chunks: list[str] = []
    for block in _SENTENCE_SPLIT_RE.split(text):
        normalized = _normalize_line(block)
        if normalized:
            chunks.append(normalized)
    if chunks:
        return chunks
    fallback = [_normalize_line(line) for line in text.splitlines() if _normalize_line(line)]
    return fallback


def _is_conclusion_like_sentence(sentence: str) -> bool:
    text = str(sentence or "").strip()
    if not text:
        return False
    if _LIMITATION_SENTENCE_RE.search(text):
        return False
    sentence_type = classify_claim_sentence(text)
    if sentence_type in {"numeric", "comparative", "causal", "novelty"}:
        return True
    return bool(_CONCLUSION_TRIGGER_RE.search(text))


def _collect_hard_grounding_sentence_gaps(text: str, *, max_examples: int = 12) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    sentences = _split_sentences(text)
    for index, sentence in enumerate(sentences, start=1):
        if not _is_conclusion_like_sentence(sentence):
            continue
        has_data = bool(_DATA_TAG_RE.search(sentence))
        has_citation = bool(_CITATION_TAG_RE.search(sentence))
        if has_data and has_citation:
            continue
        missing: list[str] = []
        if not has_data:
            missing.append("data")
        if not has_citation:
            missing.append("citation")
        rows.append(
            {
                "sentence_index": index,
                "sentence_text": sentence,
                "sentence_type": classify_claim_sentence(sentence),
                "has_data_binding": has_data,
                "has_citation_binding": has_citation,
                "missing_bindings": missing,
            }
        )
    missing_data_count = sum(1 for row in rows if "data" in row.get("missing_bindings", []))
    missing_citation_count = sum(1 for row in rows if "citation" in row.get("missing_bindings", []))
    return {
        "checked_sentence_count": len(sentences),
        "flagged_sentence_count": len(rows),
        "missing_data_binding_count": missing_data_count,
        "missing_citation_binding_count": missing_citation_count,
        "flagged_examples": rows[: max(1, int(max_examples))],
    }


def _collect_literature_alignment_gaps(text: str, *, max_examples: int = 8) -> dict[str, Any]:
    sentences = _split_sentences(text)
    triad_present = ("[支持]" in text) or ("[反驳]" in text) or ("[调和]" in text)
    citation_sentences = [sentence for sentence in sentences if _CITATION_TAG_RE.search(sentence)]
    mechanism_conflict_sentences = [sentence for sentence in citation_sentences if _MECHANISM_CONFLICT_HINT_RE.search(sentence)]
    listing_like: list[str] = []
    for sentence in citation_sentences:
        citation_count = len(_CITATION_TAG_RE.findall(sentence))
        if citation_count < 1:
            continue
        if _MECHANISM_CONFLICT_HINT_RE.search(sentence):
            continue
        listing_like.append(sentence)
    likely_listing = len(citation_sentences) >= 2 and not triad_present and len(mechanism_conflict_sentences) == 0 and len(listing_like) > 0
    return {
        "citation_sentence_count": len(citation_sentences),
        "triad_marker_present": triad_present,
        "mechanism_conflict_sentence_count": len(mechanism_conflict_sentences),
        "listing_like_sentence_count": len(listing_like),
        "likely_listing_without_alignment": likely_listing,
        "listing_examples": listing_like[: max(1, int(max_examples))],
    }


def _build_triplet_reason(change_type: str, *, source: str) -> str:
    if change_type == "added":
        return f"Added content during {source} to improve coverage of grounded evidence."
    if change_type == "removed":
        return f"Removed low-confidence or redundant statement during {source}."
    if change_type == "unchanged":
        return f"No textual change detected during {source}; evidence links were preserved."
    return f"Updated wording during {source} to align claim with evidence and review constraints."


def _build_change_evidence_reason_triplets(
    *,
    before_text: str,
    after_text: str,
    evidence_ids: list[str],
    citation_ids: list[str],
    source: str,
    max_triplets: int = 24,
) -> list[dict[str, Any]]:
    before_lines = [_normalize_line(line) for line in before_text.splitlines() if _normalize_line(line)]
    after_lines = [_normalize_line(line) for line in after_text.splitlines() if _normalize_line(line)]
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines)
    triplets: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if len(triplets) >= max_triplets:
            break
        change_type = {"replace": "modified", "insert": "added", "delete": "removed"}.get(tag, "modified")
        before_chunk = " ".join(before_lines[i1:i2]).strip()
        after_chunk = " ".join(after_lines[j1:j2]).strip()
        triplets.append(
            {
                "change_type": change_type,
                "before": before_chunk[:1200],
                "after": after_chunk[:1200],
                "evidence_ids": evidence_ids,
                "citation_ids": citation_ids,
                "reason": _build_triplet_reason(change_type, source=source),
            }
        )
    if triplets:
        return triplets
    if before_text.strip() != after_text.strip():
        return [
            {
                "change_type": "modified",
                "before": before_text.strip()[:1200],
                "after": after_text.strip()[:1200],
                "evidence_ids": evidence_ids,
                "citation_ids": citation_ids,
                "reason": _build_triplet_reason("modified", source=source),
            }
        ]
    return [
        {
            "change_type": "unchanged",
            "before": before_text.strip()[:1200],
            "after": after_text.strip()[:1200],
            "evidence_ids": evidence_ids,
            "citation_ids": citation_ids,
            "reason": _build_triplet_reason("unchanged", source=source),
        }
    ]


def _latest_section_version_content(thread_id: str, project_id: str, section_id: str) -> str | None:
    payload = _load_section_versions(thread_id, project_id, section_id)
    versions = payload.get("versions", [])
    if not versions:
        return None
    latest = versions[-1]
    if not isinstance(latest, dict):
        return None
    content = latest.get("content")
    return content if isinstance(content, str) else None


def _resolve_prompt_layer_snapshot() -> dict[str, Any]:
    metadata = _resolve_prompt_pack_metadata()
    versions = metadata.get("prompt_layer_versions")
    rollbacks = metadata.get("prompt_layer_rollbacks")
    signatures = metadata.get("prompt_layer_signatures")
    compare_ready_layers = metadata.get("prompt_layer_compare_ready_layers")
    return {
        "schema_version": metadata.get("prompt_layer_schema_version") or "",
        "versions": versions if isinstance(versions, dict) else {},
        "rollbacks": rollbacks if isinstance(rollbacks, dict) else {},
        "signatures": signatures if isinstance(signatures, dict) else {},
        "compare_ready_layers": compare_ready_layers if isinstance(compare_ready_layers, list) else [],
    }


def _build_prompt_layer_deltas(
    *,
    previous_snapshot: dict[str, Any] | None,
    current_snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    previous_versions = previous_snapshot.get("versions") if isinstance(previous_snapshot, dict) else {}
    current_versions = current_snapshot.get("versions") if isinstance(current_snapshot, dict) else {}
    previous_rollbacks = previous_snapshot.get("rollbacks") if isinstance(previous_snapshot, dict) else {}
    current_rollbacks = current_snapshot.get("rollbacks") if isinstance(current_snapshot, dict) else {}
    if not isinstance(previous_versions, dict):
        previous_versions = {}
    if not isinstance(current_versions, dict):
        current_versions = {}
    if not isinstance(previous_rollbacks, dict):
        previous_rollbacks = {}
    if not isinstance(current_rollbacks, dict):
        current_rollbacks = {}
    layer_ids = sorted({*previous_versions.keys(), *current_versions.keys()})
    deltas: list[dict[str, Any]] = []
    for layer_id in layer_ids:
        before_version = str(previous_versions.get(layer_id) or "")
        after_version = str(current_versions.get(layer_id) or "")
        before_rollback = str(previous_rollbacks.get(layer_id) or "")
        after_rollback = str(current_rollbacks.get(layer_id) or "")
        if before_version == after_version and before_rollback == after_rollback:
            continue
        deltas.append(
            {
                "layer_id": layer_id,
                "from_version": before_version or None,
                "to_version": after_version or None,
                "from_rollback": before_rollback or None,
                "to_rollback": after_rollback or None,
            }
        )
    return deltas


def _append_section_version_event(
    *,
    thread_id: str,
    project_id: str,
    section: SectionDraft,
    before_text: str,
    source: Literal["upsert_section", "compile_section", "rollback"],
    rollback_from_version_id: str | None = None,
    prompt_layer_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _load_section_versions(thread_id, project_id, section.section_id)
    versions = payload["versions"]
    last_version = versions[-1] if versions else {}
    if not isinstance(last_version, dict):
        last_version = {}
    previous_version_number = int(last_version.get("version_number") or 0)
    previous_version_id = last_version.get("version_id")
    previous_prompt_layer_snapshot = last_version.get("prompt_layers") if isinstance(last_version.get("prompt_layers"), dict) else {}
    resolved_prompt_layer_snapshot = prompt_layer_snapshot if isinstance(prompt_layer_snapshot, dict) else _resolve_prompt_layer_snapshot()
    prompt_layer_deltas = _build_prompt_layer_deltas(
        previous_snapshot=previous_prompt_layer_snapshot if isinstance(previous_prompt_layer_snapshot, dict) else {},
        current_snapshot=resolved_prompt_layer_snapshot,
    )
    next_version_number = max(previous_version_number + 1, int(section.version or 1))
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    version_id = f"{section.section_id}-v{next_version_number}-{timestamp}"
    evidence_ids = _dedup_keep_order([str(item) for item in section.evidence_ids])
    citation_ids = _dedup_keep_order([str(item) for item in section.citation_ids])
    claim_ids = _dedup_keep_order([str(item) for item in section.claim_ids])
    triplets = _build_change_evidence_reason_triplets(
        before_text=before_text,
        after_text=section.content,
        evidence_ids=evidence_ids,
        citation_ids=citation_ids,
        source=source,
    )
    entry = {
        "version_id": version_id,
        "version_number": next_version_number,
        "section_version": int(section.version or 1),
        "source": source,
        "created_at": _now_iso(),
        "rollback_from_version_id": rollback_from_version_id,
        "content": section.content,
        "claim_ids": claim_ids,
        "evidence_ids": evidence_ids,
        "citation_ids": citation_ids,
        "triplets": triplets,
        "prompt_layers": resolved_prompt_layer_snapshot,
        "prompt_layer_deltas": prompt_layer_deltas,
    }
    versions.append(entry)
    versions_artifact_path = _save_section_versions(thread_id, project_id, section.section_id, payload)
    diff_payload = {
        "schema_version": SECTION_DIFF_SCHEMA_VERSION,
        "project_id": project_id,
        "section_id": section.section_id,
        "source": source,
        "from_version_id": previous_version_id,
        "to_version_id": version_id,
        "version_number": next_version_number,
        "triplets": triplets,
        "versions_artifact_path": versions_artifact_path,
        "rollback_from_version_id": rollback_from_version_id,
        "prompt_layers": resolved_prompt_layer_snapshot,
        "prompt_layer_deltas": prompt_layer_deltas,
    }
    return diff_payload


def _to_virtual_output_path_if_possible(thread_id: str, raw_path: str) -> str:
    candidate = raw_path.strip()
    if not candidate:
        return candidate
    if candidate.startswith(f"{VIRTUAL_PATH_PREFIX}/outputs/"):
        return candidate
    path = Path(candidate)
    if not path.is_absolute():
        return candidate
    outputs_root = _outputs_dir(thread_id).resolve()
    try:
        rel = path.resolve().relative_to(outputs_root)
    except Exception:
        return candidate
    return f"{VIRTUAL_PATH_PREFIX}/outputs/{rel.as_posix()}"


def _claim_grounding_path(thread_id: str, project_id: str, section_id: str) -> Path:
    return _research_root(thread_id) / "grounding" / f"{project_id}-{section_id}.json"


def _load_claim_grounding_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 256)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _resolve_artifact_path(thread_id: str, source_artifact: str) -> Path | None:
    ref = (source_artifact or "").strip()
    if not ref:
        return None
    try:
        if ref.startswith(VIRTUAL_PATH_PREFIX):
            resolved = get_paths().resolve_virtual_path(thread_id, ref)
            return resolved if resolved.exists() else None
    except Exception:
        return None
    candidate = Path(ref)
    if candidate.is_absolute():
        return candidate if candidate.exists() else None
    outputs_candidate = (_outputs_dir(thread_id) / ref.lstrip("/")).resolve()
    return outputs_candidate if outputs_candidate.exists() else None


def _artifact_fingerprint(thread_id: str, source_artifact: str) -> dict[str, Any] | None:
    physical = _resolve_artifact_path(thread_id, source_artifact)
    if physical is None or not physical.is_file():
        return None
    try:
        stat = physical.stat()
        return {
            "source_artifact": source_artifact,
            "physical_path": str(physical),
            "sha256": _sha256_file(physical),
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }
    except Exception:
        return None


def _is_local_artifact_ref(source_artifact: str) -> bool:
    ref = (source_artifact or "").strip()
    if not ref:
        return False
    if ref.startswith(f"{VIRTUAL_PATH_PREFIX}/outputs/"):
        return True
    return ref.startswith("/")


def _contains_statistical_payload(evidence: EvidenceUnit) -> bool:
    metadata = evidence.metadata if isinstance(evidence.metadata, dict) else {}
    if any(key in metadata for key in _STAT_EVIDENCE_KEYS):
        return True
    text = f"{evidence.summary} {evidence.quote or ''} {json.dumps(metadata, ensure_ascii=False)}"
    return bool(_P_VALUE_AST_RE.search(text) or _CI_AST_RE.search(text) or _EFFECT_SIZE_AST_RE.search(text))


def _contains_roi_payload(evidence: EvidenceUnit) -> bool:
    metadata = evidence.metadata if isinstance(evidence.metadata, dict) else {}
    if any(key in metadata for key in _ROI_EVIDENCE_KEYS):
        return True
    if evidence.evidence_type == "image_report":
        return True
    text = f"{evidence.summary} {evidence.quote or ''} {json.dumps(metadata, ensure_ascii=False)}".lower()
    return any(token in text for token in ("roi", "region of interest", "bounding box", "bbox"))


def _build_claim_ast(text: str) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for idx, raw in enumerate(_NUMERIC_LITERAL_RE.findall(text), start=1):
        nodes.append({"node_id": f"num-{idx}", "node_type": "numeric_literal", "value": raw, "text": raw})
    if _P_VALUE_AST_RE.search(text):
        nodes.append({"node_id": "stat-p", "node_type": "stat_test", "value": "p_value", "text": "p-value constraint"})
    if _CI_AST_RE.search(text):
        nodes.append({"node_id": "stat-ci", "node_type": "stat_test", "value": "confidence_interval", "text": "confidence interval"})
    if _EFFECT_SIZE_AST_RE.search(text):
        nodes.append({"node_id": "stat-es", "node_type": "stat_test", "value": "effect_size", "text": "effect size"})
    for data_id in _extract_tag_ids(text, tag="data"):
        nodes.append({"node_id": f"data-{data_id}", "node_type": "binding_ref", "value": data_id, "binding_kind": "data"})
    for citation_id in _extract_tag_ids(text, tag="citation"):
        nodes.append({"node_id": f"citation-{citation_id}", "node_type": "binding_ref", "value": citation_id, "binding_kind": "citation"})
    for fact_id in _FACT_TAG_RE.findall(text):
        normalized = str(fact_id).strip()
        if normalized:
            nodes.append({"node_id": f"fact-{normalized}", "node_type": "binding_ref", "value": normalized, "binding_kind": "fact"})
    return {
        "schema_version": "deerflow.claim_ast.v1",
        "raw_text": text,
        "nodes": nodes,
    }


def _fact_matches_claim(*, claim_text: str, claim_numbers: list[float], fact: NumericFact, explicit_fact_ids: set[str]) -> bool:
    if fact.fact_id in explicit_fact_ids:
        return True
    lowered = claim_text.lower()
    metric_hit = bool(fact.metric and fact.metric.lower() in lowered)
    value_hit = any(abs(float(fact.value) - n) <= max(1e-5, abs(float(fact.value)) * 0.05) for n in claim_numbers)
    return metric_hit or value_hit


def _link_fingerprint_key(*, claim_id: str, binding_kind: str, target_id: str, source_artifact: str) -> str:
    return f"{claim_id}::{binding_kind}::{target_id}::{source_artifact}"


def _previous_fingerprint_index(previous_snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    claims = previous_snapshot.get("claims")
    if not isinstance(claims, list):
        return out
    for claim_row in claims:
        if not isinstance(claim_row, dict):
            continue
        claim_id = str(claim_row.get("claim_id") or "").strip()
        if not claim_id:
            continue
        links = claim_row.get("links")
        if not isinstance(links, list):
            continue
        for link in links:
            if not isinstance(link, dict):
                continue
            key = _link_fingerprint_key(
                claim_id=claim_id,
                binding_kind=str(link.get("binding_kind") or ""),
                target_id=str(link.get("target_id") or ""),
                source_artifact=str(link.get("source_artifact") or ""),
            )
            fp = link.get("fingerprint")
            if isinstance(fp, dict):
                out[key] = fp
    return out


def _build_claim_grounding_snapshot(
    *,
    thread_id: str,
    project_id: str,
    section: SectionDraft,
    claim_graph: ClaimGraph,
    evidence_store: EvidenceStore,
    source_of_truth_store: SourceOfTruthStore,
) -> dict[str, Any]:
    grounding_path = _claim_grounding_path(thread_id, project_id, section.section_id)
    previous_index = _previous_fingerprint_index(_load_claim_grounding_snapshot(grounding_path))
    claims_payload: list[dict[str, Any]] = []
    target_index: dict[str, dict[str, Any]] = {}

    for claim_id in section.claim_ids:
        claim = claim_graph.get(claim_id)
        if claim is None:
            claims_payload.append(
                {
                    "claim_id": claim_id,
                    "status": "invalid",
                    "hard_grounded": False,
                    "invalid_reasons": ["Claim not found in claim graph."],
                    "stale_reasons": [],
                    "links": [],
                    "ast": _build_claim_ast(""),
                }
            )
            continue

        sentence_type = classify_claim_sentence(claim.text)
        explicit_data_ids = _extract_tag_ids(claim.text, tag="data")
        explicit_fact_ids = {item.strip() for item in _FACT_TAG_RE.findall(claim.text) if str(item).strip()}
        evidence_ids = _dedup_keep_order([*claim.evidence_ids, *explicit_data_ids])
        links: list[dict[str, Any]] = []
        invalid_reasons: list[str] = []
        stale_reasons: list[str] = []

        for evidence_id in evidence_ids:
            evidence = evidence_store.get(evidence_id)
            if evidence is None:
                invalid_reasons.append(f"Unknown evidence_id '{evidence_id}'.")
                continue
            binding_kind = "evidence"
            if _contains_statistical_payload(evidence):
                binding_kind = "stat_test"
            elif _contains_roi_payload(evidence):
                binding_kind = "figure_roi"
            source_artifact = evidence.source_ref
            fingerprint = _artifact_fingerprint(thread_id, source_artifact)
            if _is_local_artifact_ref(source_artifact) and fingerprint is None:
                stale_reasons.append(f"Artifact unavailable for evidence '{evidence_id}' ({source_artifact}).")
            key = _link_fingerprint_key(
                claim_id=claim.claim_id,
                binding_kind=binding_kind,
                target_id=evidence_id,
                source_artifact=source_artifact,
            )
            previous_fp = previous_index.get(key)
            if previous_fp and fingerprint and (
                str(previous_fp.get("sha256") or "") != str(fingerprint.get("sha256") or "")
                or int(previous_fp.get("mtime_ns") or 0) != int(fingerprint.get("mtime_ns") or 0)
                or int(previous_fp.get("size") or 0) != int(fingerprint.get("size") or 0)
            ):
                stale_reasons.append(f"Artifact fingerprint drift detected for evidence '{evidence_id}'.")
            links.append(
                {
                    "binding_kind": binding_kind,
                    "target_id": evidence_id,
                    "source_type": "evidence",
                    "source_artifact": source_artifact,
                    "fingerprint": fingerprint,
                }
            )

        claim_numbers = [float(raw) for raw in _NUMERIC_LITERAL_RE.findall(claim.text)]
        fact_candidates: list[NumericFact] = []
        if section.fact_ids:
            for fact_id in section.fact_ids:
                fact = source_of_truth_store.get_fact(fact_id)
                if fact is not None:
                    fact_candidates.append(fact)
        else:
            fact_candidates = source_of_truth_store.list_facts()
        for fact in fact_candidates:
            if not _fact_matches_claim(claim_text=claim.text, claim_numbers=claim_numbers, fact=fact, explicit_fact_ids=explicit_fact_ids):
                continue
            binding_kind = "stat_test" if (fact.p_value is not None or bool(fact.ci)) else "fact"
            source_artifact = fact.source_artifact
            fingerprint = _artifact_fingerprint(thread_id, source_artifact)
            if _is_local_artifact_ref(source_artifact) and fingerprint is None:
                stale_reasons.append(f"Artifact unavailable for fact '{fact.fact_id}' ({source_artifact}).")
            key = _link_fingerprint_key(
                claim_id=claim.claim_id,
                binding_kind=binding_kind,
                target_id=fact.fact_id,
                source_artifact=source_artifact,
            )
            previous_fp = previous_index.get(key)
            if previous_fp and fingerprint and (
                str(previous_fp.get("sha256") or "") != str(fingerprint.get("sha256") or "")
                or int(previous_fp.get("mtime_ns") or 0) != int(fingerprint.get("mtime_ns") or 0)
                or int(previous_fp.get("size") or 0) != int(fingerprint.get("size") or 0)
            ):
                stale_reasons.append(f"Artifact fingerprint drift detected for fact '{fact.fact_id}'.")
            links.append(
                {
                    "binding_kind": binding_kind,
                    "target_id": fact.fact_id,
                    "source_type": "fact",
                    "source_artifact": source_artifact,
                    "fingerprint": fingerprint,
                }
            )

        requires_hard = claim.claim_type in {"strong", "result"} or sentence_type in {"numeric", "comparative", "causal", "novelty"}
        hard_links = [row for row in links if row.get("binding_kind") in {"stat_test", "figure_roi"}]
        if not links:
            invalid_reasons.append("Claim has no grounding links to evidence/fact artifacts.")
        if requires_hard and not hard_links:
            invalid_reasons.append("Hard grounding requires at least one stat_test or figure_roi link.")

        if invalid_reasons:
            status = "invalid"
        elif stale_reasons:
            status = "stale"
        else:
            status = "valid"

        for link in links:
            target_key = f"{link.get('binding_kind')}::{link.get('target_id')}"
            row = target_index.setdefault(
                target_key,
                {
                    "binding_kind": link.get("binding_kind"),
                    "target_id": link.get("target_id"),
                    "source_artifact": link.get("source_artifact"),
                    "linked_claim_ids": [],
                },
            )
            row["linked_claim_ids"] = _dedup_keep_order(row["linked_claim_ids"] + [claim.claim_id])

        claims_payload.append(
            {
                "claim_id": claim.claim_id,
                "claim_text": claim.text,
                "claim_type": claim.claim_type,
                "sentence_type": sentence_type,
                "ast": _build_claim_ast(claim.text),
                "links": links,
                "hard_grounded": bool(hard_links),
                "status": status,
                "invalid_reasons": _dedup_keep_order(invalid_reasons),
                "stale_reasons": _dedup_keep_order(stale_reasons),
            }
        )

    summary = {
        "total_claims": len(claims_payload),
        "valid_claims": sum(1 for row in claims_payload if row.get("status") == "valid"),
        "stale_claims": sum(1 for row in claims_payload if row.get("status") == "stale"),
        "invalid_claims": sum(1 for row in claims_payload if row.get("status") == "invalid"),
        "hard_grounded_claims": sum(1 for row in claims_payload if bool(row.get("hard_grounded"))),
    }
    return {
        "schema_version": CLAIM_GROUNDING_SCHEMA_VERSION,
        "project_id": project_id,
        "section_id": section.section_id,
        "generated_at": _now_iso(),
        "claims": claims_payload,
        "targets": list(target_index.values()),
        "summary": summary,
    }


def _apply_claim_grounding_overlays(compiled_text: str, grounding_payload: dict[str, Any]) -> tuple[str, list[str]]:
    claims = grounding_payload.get("claims")
    if not isinstance(claims, list):
        return compiled_text, []
    output = compiled_text
    alerts: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        status = str(claim.get("status") or "valid")
        if status == "valid":
            continue
        claim_id = str(claim.get("claim_id") or "").strip()
        if not claim_id:
            continue
        marker = f"[claim:{claim_id}]"
        badge = f"<span style=\"color:#d00000\">[{status.upper()}-CLAIM:{claim_id}]</span>"
        if marker in output and badge not in output:
            output = output.replace(marker, f"{marker} {badge}")
        reasons = claim.get("invalid_reasons") if status == "invalid" else claim.get("stale_reasons")
        if not isinstance(reasons, list):
            reasons = []
        reason = str(reasons[0]) if reasons else "Grounding chain requires manual review."
        alerts.append(f"<span style=\"color:#d00000\">{status.upper()}</span> `{claim_id}` - {reason}")
    if not alerts:
        return output, []
    alert_block = "\n".join(["## Claim Grounding Alerts", *[f"- {item}" for item in alerts]])
    return f"{alert_block}\n\n{output}".strip(), alerts


def _revalidate_claim_grounding_snapshot(*, thread_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    claims = snapshot.get("claims")
    if not isinstance(claims, list):
        return snapshot
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        links = claim.get("links")
        if not isinstance(links, list):
            links = []
        stale_reasons = list(claim.get("stale_reasons") or []) if isinstance(claim.get("stale_reasons"), list) else []
        invalid_reasons = list(claim.get("invalid_reasons") or []) if isinstance(claim.get("invalid_reasons"), list) else []
        for link in links:
            if not isinstance(link, dict):
                continue
            source_artifact = str(link.get("source_artifact") or "")
            current_fp = _artifact_fingerprint(thread_id, source_artifact)
            stored_fp = link.get("fingerprint") if isinstance(link.get("fingerprint"), dict) else None
            link["current_fingerprint"] = current_fp
            if _is_local_artifact_ref(source_artifact) and current_fp is None:
                stale_reasons.append(f"Artifact unavailable ({source_artifact}).")
            if stored_fp and current_fp and (
                str(stored_fp.get("sha256") or "") != str(current_fp.get("sha256") or "")
                or int(stored_fp.get("mtime_ns") or 0) != int(current_fp.get("mtime_ns") or 0)
                or int(stored_fp.get("size") or 0) != int(current_fp.get("size") or 0)
            ):
                stale_reasons.append(f"Artifact fingerprint drift ({source_artifact}).")
        claim["stale_reasons"] = _dedup_keep_order([str(item) for item in stale_reasons if str(item).strip()])
        claim["invalid_reasons"] = _dedup_keep_order([str(item) for item in invalid_reasons if str(item).strip()])
        if claim["invalid_reasons"]:
            claim["status"] = "invalid"
        elif claim["stale_reasons"]:
            claim["status"] = "stale"
        else:
            claim["status"] = "valid"
    snapshot["summary"] = {
        "total_claims": len([row for row in claims if isinstance(row, dict)]),
        "valid_claims": sum(1 for row in claims if isinstance(row, dict) and row.get("status") == "valid"),
        "stale_claims": sum(1 for row in claims if isinstance(row, dict) and row.get("status") == "stale"),
        "invalid_claims": sum(1 for row in claims if isinstance(row, dict) and row.get("status") == "invalid"),
        "hard_grounded_claims": sum(1 for row in claims if isinstance(row, dict) and bool(row.get("hard_grounded"))),
    }
    snapshot["validated_at"] = _now_iso()
    return snapshot


def _extract_figure_paths_from_evidence(thread_id: str, evidence: EvidenceUnit) -> list[str]:
    candidates: list[str] = []
    if evidence.source_ref:
        candidates.append(evidence.source_ref)
    metadata = evidence.metadata if isinstance(evidence.metadata, dict) else {}
    for key in _FIGURE_HINT_KEYS:
        value = metadata.get(key)
        if isinstance(value, str):
            candidates.append(value)
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    candidates.append(item)
    resolved = [_to_virtual_output_path_if_possible(thread_id, item) for item in candidates]
    return _dedup_keep_order([item for item in resolved if item])


def _build_section_traceability_payload(
    *,
    thread_id: str,
    project_id: str,
    section: SectionDraft,
    compiled_text: str,
    compiled_artifact_path: str | None = None,
) -> dict[str, Any]:
    claim_graph = _claim_graph(thread_id)
    evidence_store = _evidence_store(thread_id)

    claim_lookup: dict[str, Claim] = {}
    for claim_id in section.claim_ids:
        claim = claim_graph.get(claim_id)
        if claim is not None:
            claim_lookup[claim_id] = claim

    sentence_rows: list[dict[str, Any]] = []
    evidence_index: dict[str, dict[str, Any]] = {}
    claim_index: dict[str, dict[str, Any]] = {}

    for idx, sentence in enumerate(_split_sentences(compiled_text), start=1):
        claim_ids = _extract_tag_ids(sentence, tag="claim")
        if not claim_ids:
            claim_ids = _dedup_keep_order([cid for cid in section.claim_ids if cid in sentence])[:3]
        if not claim_ids and len(section.claim_ids) == 1:
            claim_ids = [section.claim_ids[0]]

        evidence_ids = _extract_tag_ids(sentence, tag="data")
        if not evidence_ids:
            from_claims: list[str] = []
            for claim_id in claim_ids:
                claim = claim_lookup.get(claim_id)
                if claim is not None:
                    from_claims.extend(claim.evidence_ids)
            evidence_ids = _dedup_keep_order(from_claims + section.evidence_ids)[:8]

        citation_ids = _extract_tag_ids(sentence, tag="citation")
        if not citation_ids:
            from_claims: list[str] = []
            for claim_id in claim_ids:
                claim = claim_lookup.get(claim_id)
                if claim is not None:
                    from_claims.extend(claim.citation_ids)
            citation_ids = _dedup_keep_order(from_claims + section.citation_ids)[:8]

        linked_evidence: list[dict[str, Any]] = []
        figure_paths: list[str] = []
        for evidence_id in evidence_ids:
            evidence = evidence_store.get(evidence_id)
            if evidence is None:
                continue
            evidence_figures = _extract_figure_paths_from_evidence(thread_id, evidence)
            linked_evidence.append(
                {
                    "evidence_id": evidence.evidence_id,
                    "summary": evidence.summary,
                    "evidence_type": evidence.evidence_type,
                    "source_ref": _to_virtual_output_path_if_possible(thread_id, evidence.source_ref),
                    "figure_paths": evidence_figures,
                }
            )
            figure_paths.extend(evidence_figures)
            row = evidence_index.setdefault(
                evidence.evidence_id,
                {
                    "evidence_id": evidence.evidence_id,
                    "summary": evidence.summary,
                    "evidence_type": evidence.evidence_type,
                    "source_ref": _to_virtual_output_path_if_possible(thread_id, evidence.source_ref),
                    "figure_paths": evidence_figures,
                    "linked_sentence_ids": [],
                    "linked_claim_ids": [],
                },
            )
            row["linked_sentence_ids"] = _dedup_keep_order(row["linked_sentence_ids"] + [f"s{idx}"])
            row["linked_claim_ids"] = _dedup_keep_order(row["linked_claim_ids"] + claim_ids)

        for claim_id in claim_ids:
            claim = claim_lookup.get(claim_id)
            row = claim_index.setdefault(
                claim_id,
                {
                    "claim_id": claim_id,
                    "claim_text": claim.text if claim is not None else "",
                    "linked_sentence_ids": [],
                    "evidence_ids": claim.evidence_ids if claim is not None else [],
                    "citation_ids": claim.citation_ids if claim is not None else [],
                },
            )
            row["linked_sentence_ids"] = _dedup_keep_order(row["linked_sentence_ids"] + [f"s{idx}"])

        sentence_rows.append(
            {
                "sentence_id": f"s{idx}",
                "sentence": sentence,
                "claim_ids": claim_ids,
                "evidence_ids": evidence_ids,
                "citation_ids": citation_ids,
                "figure_paths": _dedup_keep_order(figure_paths),
                "evidence": linked_evidence,
            }
        )

    return {
        "trace_schema_version": SECTION_TRACE_SCHEMA_VERSION,
        "project_id": project_id,
        "section_id": section.section_id,
        "generated_at": _now_iso(),
        "compiled_artifact_path": compiled_artifact_path,
        "sentence_links": sentence_rows,
        "claims": list(claim_index.values()),
        "evidence": list(evidence_index.values()),
    }


def _get_section_from_project(project: ResearchProject, section_id: str) -> SectionDraft | None:
    return next((item for item in project.sections if item.section_id == section_id), None)


def _project_store(thread_id: str) -> ResearchProjectStateStore:
    return ResearchProjectStateStore(_research_root(thread_id) / "projects.json")


def _evidence_store(thread_id: str) -> EvidenceStore:
    return EvidenceStore(_research_root(thread_id) / "evidence.json")


def _citation_registry(thread_id: str) -> CitationRegistry:
    return CitationRegistry(_research_root(thread_id) / "citations.json")


def _claim_graph(thread_id: str) -> ClaimGraph:
    return ClaimGraph(_research_root(thread_id) / "claims.json")


def _source_of_truth_store(thread_id: str) -> SourceOfTruthStore:
    return SourceOfTruthStore(_research_root(thread_id) / "source_of_truth.json")


def _leaderboard_path(thread_id: str) -> Path:
    return _research_root(thread_id) / "evals" / "leaderboard" / "weekly.json"


def _policy_snapshot_path(thread_id: str, project_id: str, section_id: str | None = None) -> Path:
    section_suffix = f"-{section_id}" if section_id else ""
    return _research_root(thread_id) / "policy" / f"policy-{project_id}{section_suffix}.json"


def _self_play_run_path(thread_id: str, run_name: str) -> Path:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return _research_root(thread_id) / "self-play" / f"{_slugify(run_name, default='peer-self-play')}-{ts}.json"


def _self_play_few_shot_library_path(thread_id: str) -> Path:
    return _research_root(thread_id) / "self-play" / "writer-l3-fewshot-library.json"


def _compliance_audit_path(thread_id: str, project_id: str, section_id: str) -> Path:
    return _research_root(thread_id) / "compliance" / f"audit-{project_id}-{section_id}.json"


def _peer_review_ab_metrics_path(thread_id: str) -> Path:
    return _research_root(thread_id) / "review" / "peer-review-ab-metrics.json"


def _capability_assessment_path(thread_id: str, project_id: str, section_id: str | None = None) -> Path:
    suffix = f"-{section_id}" if section_id else ""
    return _research_root(thread_id) / "capabilities" / f"assessment-{project_id}{suffix}.json"


def _is_core_section(section: SectionDraft) -> bool:
    section_key = f"{section.section_id} {section.section_name}".lower()
    core_tokens = ("discussion", "results", "conclusion", "analysis", "findings")
    return any(token in section_key for token in core_tokens)


def _fallback_venue_for_discipline(discipline: str) -> str:
    lowered = discipline.lower()
    if any(token in lowered for token in ("ai", "cs", "ml", "nlp", "vision", "robotics")):
        return "NeurIPS"
    return "Nature"


def _resolve_supported_venue(target_venue: str | None, discipline: str) -> str:
    candidate = (target_venue or "").strip()
    if candidate in VENUE_PROFILES:
        return candidate
    return _fallback_venue_for_discipline(discipline)


def _resolve_style_venue_name(target_venue: str | None, fallback_venue: str) -> str:
    candidate = (target_venue or "").strip()
    return candidate or fallback_venue


def _normalize_reviewer2_style_list(styles: list[str] | None) -> list[Reviewer2StyleOverride]:
    deduped: list[Reviewer2StyleOverride] = []
    for item in styles or []:
        normalized = str(item).strip()
        if normalized == "statistical_tyrant":
            typed: Reviewer2StyleOverride = "statistical_tyrant"
        elif normalized == "methodology_fundamentalist":
            typed = "methodology_fundamentalist"
        elif normalized == "domain_traditionalist":
            typed = "domain_traditionalist"
        else:
            continue
        if typed in deduped:
            continue
        deduped.append(typed)
    return deduped


def _normalize_peer_review_ab_variant(value: str | None) -> PeerReviewABVariantInputOverride:
    raw = str(value or "").strip()
    if not raw:
        return "off"
    lowered = raw.lower()
    if lowered == "auto":
        return "auto"
    if lowered in {"off", "none", "default"}:
        return "off"
    upper = raw.upper()
    if upper == "A":
        return "A"
    if upper == "B":
        return "B"
    return "off"


def _thread_hash_ratio(*, thread_id: str, salt: str) -> float:
    digest = hashlib.sha256(f"{salt}:{thread_id}".encode()).digest()
    # Use first 8 bytes for deterministic ratio in [0, 1).
    bucket = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return float(bucket / 2**64)


def _assign_ab_variant_for_thread(*, thread_id: str, salt: str, ratio_a: float) -> tuple[PeerReviewABVariantOverride, float]:
    normalized_ratio = max(0.0, min(float(ratio_a), 1.0))
    thread_ratio = _thread_hash_ratio(thread_id=thread_id, salt=salt)
    variant: PeerReviewABVariantOverride = "A" if thread_ratio < normalized_ratio else "B"
    return variant, thread_ratio


def _init_peer_review_ab_metrics_payload(thread_id: str) -> dict[str, Any]:
    return {
        "schema_version": PEER_REVIEW_AB_METRICS_SCHEMA_VERSION,
        "thread_id": thread_id,
        "updated_at": None,
        "total_runs": 0,
        "variant_totals": {},
        "by_variant_total": {},
        "window_size": 0,
        "by_variant_window": {},
        "recent_runs": [],
    }


def _coerce_variant_counters(raw: dict[str, Any] | None) -> dict[str, dict[str, float]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, float]] = {}
    for variant, item in raw.items():
        if not isinstance(item, dict):
            continue
        key = str(variant).strip()
        if not key:
            continue
        out[key] = {
            "runs": float(item.get("runs") or 0.0),
            "accepts": float(item.get("accepts") or 0.0),
            "unresolved_sum": float(item.get("unresolved_sum") or 0.0),
            "round_count_sum": float(item.get("round_count_sum") or 0.0),
        }
    return out


def _rows_to_variant_counters(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    counters: dict[str, dict[str, float]] = {}
    for row in rows:
        variant = str(row.get("ab_variant") or "off")
        bucket = counters.setdefault(
            variant,
            {
                "runs": 0.0,
                "accepts": 0.0,
                "unresolved_sum": 0.0,
                "round_count_sum": 0.0,
            },
        )
        bucket["runs"] += 1.0
        if str(row.get("final_decision") or "") == "accept":
            bucket["accepts"] += 1.0
        bucket["unresolved_sum"] += float(row.get("unresolved_issue_count") or 0.0)
        bucket["round_count_sum"] += float(row.get("round_count") or 0.0)
    return counters


def _render_variant_stats(counters: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}
    for variant, bucket in counters.items():
        runs = float(bucket.get("runs") or 0.0)
        accepts = float(bucket.get("accepts") or 0.0)
        unresolved_sum = float(bucket.get("unresolved_sum") or 0.0)
        round_count_sum = float(bucket.get("round_count_sum") or 0.0)
        stats[variant] = {
            "runs": runs,
            "accepts": accepts,
            "accept_rate": (accepts / runs) if runs > 0 else 0.0,
            "avg_unresolved_issue_count": (unresolved_sum / runs) if runs > 0 else 0.0,
            "avg_round_count": (round_count_sum / runs) if runs > 0 else 0.0,
        }
    return stats


def _load_peer_review_ab_metrics(thread_id: str) -> dict[str, Any]:
    path = _peer_review_ab_metrics_path(thread_id)
    if not path.exists():
        return _init_peer_review_ab_metrics_payload(thread_id)
    raw = _load_json_dict(path)
    payload = _init_peer_review_ab_metrics_payload(thread_id)
    payload["updated_at"] = raw.get("updated_at")
    payload["total_runs"] = int(raw.get("total_runs") or 0)
    payload["variant_totals"] = _coerce_variant_counters(raw.get("variant_totals"))
    recent_runs_raw = raw.get("recent_runs")
    if isinstance(recent_runs_raw, list):
        payload["recent_runs"] = [row for row in recent_runs_raw if isinstance(row, dict)]
    payload["window_size"] = len(payload["recent_runs"])
    payload["by_variant_total"] = _render_variant_stats(payload["variant_totals"])
    payload["by_variant_window"] = _render_variant_stats(_rows_to_variant_counters(payload["recent_runs"]))
    return payload


def _record_peer_review_ab_metrics(*, thread_id: str, event: dict[str, Any]) -> dict[str, Any]:
    cfg = get_reviewer2_strategy_config()
    payload = _load_peer_review_ab_metrics(thread_id)
    metrics_enabled = bool(getattr(cfg, "ab_metrics_enabled", True))
    if not metrics_enabled:
        payload["metrics_enabled"] = False
        return payload

    event_row = {
        "timestamp": _now_iso(),
        **event,
    }
    recent_runs = list(payload.get("recent_runs") or [])
    recent_runs.append(event_row)
    max_recent = max(20, min(int(getattr(cfg, "ab_metrics_max_recent_runs", 120)), 1000))
    if len(recent_runs) > max_recent:
        recent_runs = recent_runs[-max_recent:]
    payload["recent_runs"] = recent_runs
    payload["window_size"] = len(recent_runs)

    total_runs = int(payload.get("total_runs") or 0) + 1
    payload["total_runs"] = total_runs

    variant = str(event_row.get("ab_variant") or "off")
    totals = _coerce_variant_counters(payload.get("variant_totals"))
    bucket = totals.setdefault(
        variant,
        {
            "runs": 0.0,
            "accepts": 0.0,
            "unresolved_sum": 0.0,
            "round_count_sum": 0.0,
        },
    )
    bucket["runs"] += 1.0
    if str(event_row.get("final_decision") or "") == "accept":
        bucket["accepts"] += 1.0
    bucket["unresolved_sum"] += float(event_row.get("unresolved_issue_count") or 0.0)
    bucket["round_count_sum"] += float(event_row.get("round_count") or 0.0)
    payload["variant_totals"] = totals

    payload["by_variant_total"] = _render_variant_stats(totals)
    payload["by_variant_window"] = _render_variant_stats(_rows_to_variant_counters(recent_runs))
    payload["updated_at"] = _now_iso()
    payload["metrics_enabled"] = True
    _dump_json(_peer_review_ab_metrics_path(thread_id), payload)
    return payload


def _build_peer_review_strategy_config_snapshot(*, thread_id: str) -> dict[str, Any]:
    cfg = get_reviewer2_strategy_config()
    auto_split_salt = str(getattr(cfg, "ab_auto_split_salt", "reviewer2-ab-v1"))
    auto_split_ratio_a = float(getattr(cfg, "ab_auto_split_ratio_a", 0.5))
    preview_variant, preview_ratio = _assign_ab_variant_for_thread(
        thread_id=thread_id,
        salt=auto_split_salt,
        ratio_a=auto_split_ratio_a,
    )
    return {
        "default_styles": list(getattr(cfg, "default_styles", [])),
        "venue_style_overrides": dict(getattr(cfg, "venue_style_overrides", {}) or {}),
        "ab_enabled": bool(getattr(cfg, "ab_enabled", True)),
        "ab_default_variant": str(getattr(cfg, "ab_default_variant", "off")),
        "ab_variant_a_max_rounds": int(getattr(cfg, "ab_variant_a_max_rounds", 2)),
        "ab_variant_a_styles": list(getattr(cfg, "ab_variant_a_styles", [])),
        "ab_variant_b_max_rounds": int(getattr(cfg, "ab_variant_b_max_rounds", 4)),
        "ab_variant_b_styles": list(getattr(cfg, "ab_variant_b_styles", [])),
        "ab_auto_split_enabled": bool(getattr(cfg, "ab_auto_split_enabled", False)),
        "ab_auto_split_ratio_a": auto_split_ratio_a,
        "ab_auto_split_salt": auto_split_salt,
        "ab_metrics_enabled": bool(getattr(cfg, "ab_metrics_enabled", True)),
        "ab_metrics_max_recent_runs": int(getattr(cfg, "ab_metrics_max_recent_runs", 120)),
        "thread_assignment_preview": {
            "ab_variant": preview_variant,
            "thread_hash_ratio": preview_ratio,
        },
    }


def _resolve_peer_review_strategy(
    *,
    thread_id: str,
    venue_name: str,
    requested_max_rounds: int,
    reviewer2_styles: list[Reviewer2StyleOverride] | None,
    peer_review_ab_variant: str | None,
) -> dict[str, Any]:
    cfg = get_reviewer2_strategy_config()
    ab_enabled = bool(getattr(cfg, "ab_enabled", True))
    ab_auto_split_enabled = bool(getattr(cfg, "ab_auto_split_enabled", False))
    ab_auto_split_ratio_a = float(getattr(cfg, "ab_auto_split_ratio_a", 0.5))
    ab_auto_split_salt = str(getattr(cfg, "ab_auto_split_salt", "reviewer2-ab-v1"))
    requested_styles = _normalize_reviewer2_style_list(list(reviewer2_styles or []))
    venue_key = venue_name.strip().lower()
    venue_override_map = getattr(cfg, "venue_style_overrides", {}) or {}
    venue_styles = _normalize_reviewer2_style_list(list(venue_override_map.get(venue_key, [])))
    default_styles = _normalize_reviewer2_style_list(list(getattr(cfg, "default_styles", [])))

    resolved_styles = requested_styles or venue_styles or default_styles
    style_source = "request" if requested_styles else ("venue_default" if venue_styles else "global_default")
    resolved_max_rounds = max(1, min(int(requested_max_rounds), 5))
    round_source = "request"

    explicit_variant = str(peer_review_ab_variant or "").strip() != ""
    requested_variant = _normalize_peer_review_ab_variant(peer_review_ab_variant)
    resolved_variant: PeerReviewABVariantOverride = "off"
    variant_source = "none"
    auto_split_applied = False
    thread_hash_ratio: float | None = None

    if ab_enabled:
        if requested_variant in {"A", "B"}:
            resolved_variant = requested_variant
            variant_source = "request"
        elif explicit_variant and requested_variant == "off":
            resolved_variant = "off"
            variant_source = "request"
        else:
            use_auto_split = requested_variant == "auto" or (not explicit_variant and ab_auto_split_enabled)
            if use_auto_split:
                resolved_variant, thread_hash_ratio = _assign_ab_variant_for_thread(
                    thread_id=thread_id,
                    salt=ab_auto_split_salt,
                    ratio_a=ab_auto_split_ratio_a,
                )
                auto_split_applied = True
                variant_source = "request:auto" if requested_variant == "auto" else "config:auto_split"
            elif not explicit_variant:
                default_variant = _normalize_peer_review_ab_variant(str(getattr(cfg, "ab_default_variant", "off")))
                if default_variant in {"A", "B"}:
                    resolved_variant = default_variant
                    variant_source = "config:default"

    if ab_enabled and resolved_variant in {"A", "B"}:
        if resolved_variant == "A":
            resolved_styles = _normalize_reviewer2_style_list(list(getattr(cfg, "ab_variant_a_styles", []))) or resolved_styles
            resolved_max_rounds = max(1, min(int(getattr(cfg, "ab_variant_a_max_rounds", 2)), 5))
        else:
            resolved_styles = _normalize_reviewer2_style_list(list(getattr(cfg, "ab_variant_b_styles", []))) or resolved_styles
            resolved_max_rounds = max(1, min(int(getattr(cfg, "ab_variant_b_max_rounds", 4)), 5))
        style_source = f"ab:{resolved_variant}"
        round_source = f"ab:{resolved_variant}"
    else:
        resolved_variant = "off"

    return {
        "ab_variant": resolved_variant,
        "ab_variant_requested": requested_variant if explicit_variant else None,
        "ab_variant_source": variant_source,
        "ab_enabled": ab_enabled,
        "ab_auto_split_enabled": ab_auto_split_enabled,
        "ab_auto_split_ratio_a": ab_auto_split_ratio_a,
        "ab_auto_split_salt": ab_auto_split_salt,
        "auto_split_applied": auto_split_applied,
        "thread_hash_ratio": thread_hash_ratio,
        "resolved_max_rounds": resolved_max_rounds,
        "resolved_reviewer2_styles": resolved_styles,
        "requested_reviewer2_styles": requested_styles,
        "venue_default_styles": venue_styles,
        "global_default_styles": default_styles,
        "style_source": style_source,
        "round_source": round_source,
        "venue_name": venue_name,
    }


def _resolve_section_type(section: SectionDraft) -> NarrativeSectionType:
    key = f"{section.section_id} {section.section_name}".lower()
    if any(token in key for token in ("intro", "background", "related work", "motivation")):
        return "introduction"
    if any(token in key for token in ("result", "finding", "experiment", "ablation")):
        return "results"
    if any(token in key for token in ("discussion", "conclusion", "analysis", "limitations")):
        return "discussion"
    return "general"


def _default_narrative_strategy_for_style(style: NarrativeTone) -> NarrativeWritingStrategy:
    if style == "conservative":
        return NarrativeWritingStrategy(tone="conservative", max_templates=1, evidence_density="high")
    if style == "aggressive":
        return NarrativeWritingStrategy(tone="aggressive", max_templates=3, evidence_density="medium")
    return NarrativeWritingStrategy(tone="balanced", max_templates=2, evidence_density="medium")


def _default_narrative_strategy_for_venue(venue_name: str) -> NarrativeWritingStrategy:
    if venue_name in {"Nature", "Cell"}:
        return _default_narrative_strategy_for_style("conservative")
    if venue_name in {"NeurIPS", "ICML"}:
        return _default_narrative_strategy_for_style("aggressive")
    return _default_narrative_strategy_for_style("balanced")


def _default_narrative_strategy_for_section_type(section_type: NarrativeSectionType) -> NarrativeWritingStrategy:
    if section_type == "introduction":
        return NarrativeWritingStrategy(tone="conservative", max_templates=1, evidence_density="medium")
    if section_type == "results":
        return NarrativeWritingStrategy(tone="balanced", max_templates=2, evidence_density="high")
    if section_type == "discussion":
        return NarrativeWritingStrategy(tone="aggressive", max_templates=3, evidence_density="medium")
    return NarrativeWritingStrategy(tone="balanced", max_templates=2, evidence_density="medium")


def _positioned_paragraph_tones(*, max_templates: int) -> list[NarrativeTone]:
    if max_templates <= 0:
        return []
    if max_templates == 1:
        return ["conservative"]
    if max_templates == 2:
        return ["conservative", "balanced"]
    return ["conservative", *(["aggressive"] * (max_templates - 2)), "balanced"]


def _positioned_paragraph_densities(
    section_type: NarrativeSectionType,
    *,
    max_templates: int,
) -> list[NarrativeEvidenceDensity]:
    if max_templates <= 0:
        return []
    if section_type == "introduction":
        if max_templates == 1:
            return ["medium"]
        if max_templates == 2:
            return ["medium", "low"]
        return ["medium", *(["medium"] * (max_templates - 2)), "low"]
    if max_templates == 1:
        return ["medium"]
    if max_templates == 2:
        return ["medium", "medium"]
    return ["medium", *(["high"] * (max_templates - 2)), "medium"]


def _normalize_paragraph_tones(values: list[NarrativeToneOverride] | None) -> list[NarrativeTone]:
    if not values:
        return []
    allowed = {"conservative", "balanced", "aggressive"}
    return [value for value in values if value in allowed]


def _normalize_paragraph_densities(values: list[NarrativeDensityOverride] | None) -> list[NarrativeEvidenceDensity]:
    if not values:
        return []
    allowed = {"low", "medium", "high"}
    return [value for value in values if value in allowed]


def _resolve_narrative_strategy(
    *,
    venue_name: str,
    section: SectionDraft,
    narrative_style: NarrativeStyleOverride = "auto",
    narrative_max_templates: int | None = None,
    narrative_evidence_density: NarrativeDensityOverride | None = None,
    narrative_auto_by_section_type: bool = True,
    narrative_paragraph_tones: list[NarrativeToneOverride] | None = None,
    narrative_paragraph_evidence_densities: list[NarrativeDensityOverride] | None = None,
) -> NarrativeWritingStrategy:
    section_type = _resolve_section_type(section)
    if narrative_style == "auto":
        strategy = _default_narrative_strategy_for_venue(venue_name)
    else:
        strategy = _default_narrative_strategy_for_style(narrative_style)

    if narrative_style == "auto" and narrative_auto_by_section_type:
        by_section_type = _default_narrative_strategy_for_section_type(section_type)
        strategy.tone = by_section_type.tone
        if narrative_max_templates is None:
            strategy.max_templates = by_section_type.max_templates
        if narrative_evidence_density is None:
            strategy.evidence_density = by_section_type.evidence_density

    if narrative_max_templates is not None:
        strategy.max_templates = max(1, min(5, int(narrative_max_templates)))
    if narrative_evidence_density is not None:
        strategy.evidence_density = narrative_evidence_density

    paragraph_tones = _normalize_paragraph_tones(narrative_paragraph_tones)
    if not paragraph_tones and narrative_style == "auto" and narrative_auto_by_section_type:
        paragraph_tones = _positioned_paragraph_tones(max_templates=strategy.max_templates)

    paragraph_densities = _normalize_paragraph_densities(narrative_paragraph_evidence_densities)
    if not paragraph_densities and narrative_style == "auto" and narrative_auto_by_section_type:
        paragraph_densities = _positioned_paragraph_densities(section_type, max_templates=strategy.max_templates)

    strategy.auto_by_section_type = narrative_auto_by_section_type and narrative_style == "auto"
    strategy.section_type = section_type
    strategy.paragraph_tones = paragraph_tones[: strategy.max_templates]
    strategy.paragraph_evidence_densities = paragraph_densities[: strategy.max_templates]
    return strategy


def _collect_section_claims(section: SectionDraft, claim_graph: ClaimGraph) -> list[Claim]:
    claims: list[Claim] = []
    for claim_id in section.claim_ids:
        claim = claim_graph.get(claim_id)
        if claim is not None:
            claims.append(claim)
    return claims


def _build_section_claim_map(
    *,
    section: SectionDraft,
    claim_graph: ClaimGraph,
    evidence_store: EvidenceStore,
    citation_registry: CitationRegistry,
) -> dict[str, Any]:
    """Build claim map before drafting: claim -> bindings -> sentence draft."""

    compiler = ClaimConstraintCompiler(
        evidence_store=evidence_store,
        citation_registry=citation_registry,
        mode="strict",
    )
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    rewrite_required_claim_ids: list[str] = []
    for claim_id in section.claim_ids:
        claim = claim_graph.get(claim_id)
        if claim is None:
            issues.append(
                {
                    "claim_id": claim_id,
                    "severity": "error",
                    "message": "Claim ID not found in claim graph.",
                }
            )
            continue
        row_model = compiler.build_claim_map_entry(claim, max_markers=2)
        row = row_model.model_dump()
        validation_issues = compiler.validate_claim_map_entry(row_model)
        if row_model.rewrite_required:
            rewrite_required_claim_ids.append(claim_id)
        for issue in validation_issues:
            issues.append(
                {
                    "claim_id": issue.claim_id,
                    "severity": issue.severity,
                    "message": issue.message,
                }
            )
        rows.append(row)
        if int(row.get("marker_count") or 0) == 0:
            issues.append(
                {
                    "claim_id": claim_id,
                    "severity": "warning",
                    "message": "Claim Map row has no valid [data:]/[citation:] marker candidates.",
                }
            )
    return {
        "schema_version": CLAIM_MAP_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "section_id": section.section_id,
        "claim_ids": list(section.claim_ids),
        "table_columns": [
            "Claim ID",
            "核心主张",
            "支撑 Data ID",
            "支撑 Citation ID",
            "局限性/Caveat",
        ],
        "claims": rows,
        "issues": issues,
        "summary": {
            "total_claim_ids": len(section.claim_ids),
            "mapped_claims": len(rows),
            "rows_with_markers": sum(1 for row in rows if int(row.get("marker_count") or 0) > 0),
            "rewrite_required_claims": len(rewrite_required_claim_ids),
            "rewrite_required_claim_ids": rewrite_required_claim_ids,
        },
    }


def _collect_section_evidence_units(
    section: SectionDraft,
    claims: list[Claim],
    evidence_store: EvidenceStore,
) -> list[EvidenceUnit]:
    evidence_ids = _dedup_keep_order(
        list(section.evidence_ids)
        + [evidence_id for claim in claims for evidence_id in claim.evidence_ids]
    )
    units: list[EvidenceUnit] = []
    for evidence_id in evidence_ids:
        unit = evidence_store.get(evidence_id)
        if unit is not None:
            units.append(unit)
    if units:
        return units
    # Fallback to latest graph-oriented evidence so planner can still reason about literature conflict.
    graph_units = [
        item
        for item in evidence_store.list_by_type("manual_note")
        if isinstance(item.location, dict) and str(item.location.get("kind") or "").startswith(("citation_graph_", "literature_graph_"))
    ]
    return graph_units[-6:]


def _collect_section_citations(
    section: SectionDraft,
    claims: list[Claim],
    evidence_units: list[EvidenceUnit],
    citation_registry: CitationRegistry,
) -> list[CitationRecord]:
    citation_ids = _dedup_keep_order(
        list(section.citation_ids)
        + [citation_id for claim in claims for citation_id in claim.citation_ids]
        + [citation_id for unit in evidence_units for citation_id in unit.citation_ids]
    )
    citations: list[CitationRecord] = []
    for citation_id in citation_ids:
        citation = citation_registry.get(citation_id)
        if citation is not None:
            citations.append(citation)
    return citations


def _plan_section_narrative(
    *,
    project: ResearchProject,
    section: SectionDraft,
    claim_graph: ClaimGraph,
    evidence_store: EvidenceStore,
    citation_registry: CitationRegistry,
    self_question_rounds: int,
    include_storyboard: bool,
) -> NarrativePlan:
    claims = _collect_section_claims(section, claim_graph)
    evidence_units = _collect_section_evidence_units(section, claims, evidence_store)
    citations = _collect_section_citations(section, claims, evidence_units, citation_registry)
    return NarrativePlannerAgent.plan(
        project=project,
        section=section,
        claims=claims,
        evidence_units=evidence_units,
        citations=citations,
        self_question_rounds=max(1, min(int(self_question_rounds), 8)),
        include_storyboard=include_storyboard,
    )


def _slugify(value: str, *, default: str = "artifact") -> str:
    lowered = (value or "").strip().lower()
    lowered = re.sub(r"[^a-z0-9\-_.]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return lowered or default


def _journal_style_cache_path(thread_id: str, venue_name: str) -> Path:
    return _research_root(thread_id) / "style-cache" / f"{_slugify(venue_name, default='venue')}.json"


def _apply_journal_style_alignment_to_narrative(
    strategy: NarrativeWritingStrategy,
    *,
    journal_style_bundle: dict[str, Any] | None,
    narrative_style: NarrativeStyleOverride,
    narrative_max_templates: int | None,
    narrative_evidence_density: NarrativeDensityOverride | None,
) -> bool:
    if narrative_style != "auto":
        return False
    if not isinstance(journal_style_bundle, dict):
        return False
    summary = journal_style_bundle.get("style_summary")
    if not isinstance(summary, dict):
        return False
    avg_sentence_words = summary.get("avg_sentence_words")
    if not isinstance(avg_sentence_words, (int, float)) or avg_sentence_words <= 0:
        return False

    applied = False
    # Keep explicit user overrides intact; only tune auto defaults.
    if narrative_max_templates is None:
        if avg_sentence_words <= 18:
            strategy.max_templates = min(strategy.max_templates, 2)
            applied = True
        elif avg_sentence_words >= 26:
            strategy.max_templates = max(strategy.max_templates, 3)
            applied = True

    if narrative_evidence_density is None:
        if avg_sentence_words <= 18:
            strategy.evidence_density = "high"
            applied = True
        elif avg_sentence_words >= 26:
            strategy.evidence_density = "medium"
            applied = True

    if avg_sentence_words <= 18 and strategy.tone != "conservative":
        strategy.tone = "balanced"
        applied = True
    elif avg_sentence_words >= 26 and strategy.tone == "conservative":
        strategy.tone = "balanced"
        applied = True

    strategy.paragraph_tones = strategy.paragraph_tones[: strategy.max_templates]
    strategy.paragraph_evidence_densities = strategy.paragraph_evidence_densities[: strategy.max_templates]
    return applied


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _hitl_key(action_id: str, section_id: str | None) -> str:
    return f"{section_id or ''}::{action_id}"


def _load_hitl_decision_map(project: ResearchProject) -> dict[str, HitlDecision]:
    metadata = project.metadata if isinstance(project.metadata, dict) else {}
    hitl_raw = metadata.get("hitl_decisions", {})
    items = hitl_raw.get("items", []) if isinstance(hitl_raw, dict) else []
    decision_map: dict[str, HitlDecision] = {}
    if not isinstance(items, list):
        return decision_map
    for raw in items:
        try:
            decision = HitlDecision.model_validate(raw)
        except Exception:
            continue
        key = _hitl_key(decision.action_id, decision.section_id)
        existing = decision_map.get(key)
        if existing is None:
            decision_map[key] = decision
            continue
        if (decision.updated_at or "") >= (existing.updated_at or ""):
            decision_map[key] = decision
    return decision_map


def _serialize_hitl_metadata(decision_map: dict[str, HitlDecision]) -> dict[str, Any]:
    decisions = sorted(
        decision_map.values(),
        key=lambda item: ((item.section_id or ""), item.action_id),
    )
    updated_at = max((item.updated_at or "" for item in decisions), default="")
    return {
        "schema_version": 1,
        "updated_at": updated_at or None,
        "items": [item.model_dump() for item in decisions],
    }


_KEY_HITL_ACTIONS: tuple[tuple[str, str], ...] = (
    ("hitl.confirm_outline", "confirm_outline"),
    ("hitl.select_core_hypothesis", "select_core_hypothesis"),
    ("hitl.lock_figure_set", "lock_figure_set"),
)


_POLICY_DIRECTIVE_TOKEN_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("soften", "tone down", "hedge", "conservative", "谨慎", "弱化"),
        "Use conservative claim modality (suggest/may/associated) and avoid definitive causal verbs unless hard evidence is complete.",
    ),
    (
        ("causal", "因果", "mechanism", "机制", "hypothesis", "假设"),
        "For mechanism-sensitive claims, include one causal hypothesis and at least one alternative explanation with falsification conditions.",
    ),
    (
        ("ablation", "baseline", "control", "对照", "验证"),
        "For core claims, include explicit ablation/baseline/control evidence and surface any missing validation as unresolved.",
    ),
    (
        ("p-value", "p <", "confidence interval", "effect size", "统计"),
        "Quantitative statements should report uncertainty signals (effect size/CI/p-value) before high-confidence conclusions.",
    ),
    (
        ("ethics", "irb", "consent", "bias", "伦理", "偏差"),
        "Add explicit ethics, bias-risk, and consent/governance statements for claim sections with practical impact.",
    ),
    (
        ("reproducibility", "reproducible", "code", "data availability", "复现"),
        "Include reproducibility directives: code/data/protocol availability and seed/environment details.",
    ),
)


_SOFTEN_SIGNAL_TOKENS: tuple[str, ...] = ("prove", "proves", "demonstrates", "definitive", "always", "causal", "cause")


def _token_presence_count(text: str, tokens: tuple[str, ...]) -> int:
    lowered = str(text or "").lower()
    return sum(1 for token in tokens if token in lowered)


def _infer_writing_directives_from_section_edit(before_text: str, after_text: str) -> list[str]:
    before = str(before_text or "").strip()
    after = str(after_text or "").strip()
    if not before or not after or before == after:
        return []

    directives: list[str] = []
    before_soften = _token_presence_count(before, _SOFTEN_SIGNAL_TOKENS)
    after_soften = _token_presence_count(after, _SOFTEN_SIGNAL_TOKENS)
    if after_soften < before_soften:
        directives.append(
            "When evidence is limited, prefer conservative language and avoid definitive causal phrasing."
        )

    before_validation = _token_presence_count(before, ("ablation", "baseline", "control", "validation"))
    after_validation = _token_presence_count(after, ("ablation", "baseline", "control", "validation"))
    if after_validation > before_validation:
        directives.append(
            "Include explicit validation anchors (ablation/baseline/control) in claim-sensitive paragraphs."
        )

    before_mechanism = _token_presence_count(before, ("mechanism", "hypothesis", "alternative explanation"))
    after_mechanism = _token_presence_count(after, ("mechanism", "hypothesis", "alternative explanation"))
    if after_mechanism > before_mechanism:
        directives.append(
            "For mechanism claims, include a primary hypothesis and at least one alternative explanation."
        )

    before_ethics = _token_presence_count(before, ("ethics", "irb", "consent", "bias", "reproducibility"))
    after_ethics = _token_presence_count(after, ("ethics", "irb", "consent", "bias", "reproducibility"))
    if after_ethics > before_ethics:
        directives.append(
            "Preserve explicit ethics/bias/reproducibility statements when drafting revised sections."
        )

    return _dedup_text_rows(directives, limit=6)


def _dedup_text_rows(rows: list[str], *, limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        token = str(row or "").strip()
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
        if len(out) >= max(1, int(limit)):
            break
    return out


def _collect_decision_explicit_directives(decision: HitlDecision) -> list[str]:
    rows: list[str] = []
    metadata = decision.metadata if isinstance(decision.metadata, dict) else {}
    explicit = metadata.get("writing_directives")
    if isinstance(explicit, list):
        rows.extend([str(item) for item in explicit if str(item).strip()])
    one = metadata.get("writing_directive")
    if isinstance(one, str) and one.strip():
        rows.append(one.strip())
    return _dedup_text_rows(rows, limit=6)


def _collect_decision_keyword_directives(decision: HitlDecision) -> list[str]:
    text_blob = " ".join(
        [
            str(decision.action_id or ""),
            str(decision.source or ""),
            str(decision.label or ""),
        ]
    ).strip()
    lowered = text_blob.lower()
    rows: list[str] = []
    for keywords, directive in _POLICY_DIRECTIVE_TOKEN_MAP:
        if any(keyword in lowered for keyword in keywords):
            rows.append(directive)
    return _dedup_text_rows(rows, limit=6)


def _build_policy_writing_directives(
    *,
    policy: dict[str, Any],
    decisions: list[HitlDecision],
    section_id: str | None,
) -> dict[str, Any]:
    scoped: list[HitlDecision] = []
    for decision in decisions:
        if section_id is None:
            scoped.append(decision)
            continue
        if decision.section_id in {None, section_id}:
            scoped.append(decision)

    rows: list[str] = []
    # Priority 1: explicit researcher directives from metadata.
    for decision in scoped:
        rows.extend(_collect_decision_explicit_directives(decision))
    # Priority 2: infer directives from edited labels/sources.
    for decision in scoped:
        rows.extend(_collect_decision_keyword_directives(decision))

    # Priority 3: policy-level defaults inferred from aggregate HITL signals.
    recommended_tone = str(policy.get("recommended_tone") or "").strip().lower()
    if recommended_tone == "conservative" or bool(policy.get("prefer_conservative_claims")):
        rows.append(
            "Prefer conservative tone for claim-sensitive sentences; downgrade certainty when evidence is incomplete or contradictory."
        )
    if bool(policy.get("require_stronger_validation")):
        rows.append(
            "Strengthen validation chain: add baseline/ablation/control references and avoid summary-only conclusions."
        )
    if bool(policy.get("require_ethics_reproducibility")):
        rows.append(
            "Ensure ethics/reproducibility clauses are explicitly present (ethics statement, bias caveat, reproducibility artifacts)."
        )

    directives = _dedup_text_rows(rows, limit=8)
    return {
        "schema_version": POLICY_WRITING_DIRECTIVES_SCHEMA_VERSION,
        "section_id": section_id,
        "directive_count": len(directives),
        "writing_directives": directives,
        "source_decision_count": len(scoped),
    }


def _resolve_key_hitl_checkpoints(project: ResearchProject, *, section_id: str | None) -> dict[str, dict[str, Any]]:
    decision_map = _load_hitl_decision_map(project)
    out: dict[str, dict[str, Any]] = {}
    for action_id, alias in _KEY_HITL_ACTIONS:
        section_key = _hitl_key(action_id, section_id)
        global_key = _hitl_key(action_id, None)
        decision = decision_map.get(section_key) or decision_map.get(global_key)
        out[alias] = {
            "action_id": action_id,
            "decision": decision.decision if decision is not None else "pending",
            "updated_at": decision.updated_at if decision is not None else None,
            "source": decision.source if decision is not None else "",
            "label": decision.label if decision is not None else "",
            "metadata": decision.metadata if decision is not None else {},
        }
    return out


def _build_hitl_impact_preview(hitl_checkpoints: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Summarize which compile actions are blocked by current HITL decisions."""
    rejected = [
        {
            "alias": alias,
            "action_id": item.get("action_id"),
            "label": item.get("label") or alias,
            "decision": item.get("decision"),
        }
        for alias, item in hitl_checkpoints.items()
        if item.get("decision") == "rejected"
    ]
    strict_blocked = len(rejected) > 0
    blocked_actions: list[str] = []
    if strict_blocked:
        blocked_actions = [
            "compile_section(mode=strict)",
            "compile_section(mode=strict, auto_peer_review=true)",
            "compile_section(mode=strict, auto_hypothesis=true)",
        ]
    return {
        "strict_compile_blocked": strict_blocked,
        "lenient_compile_blocked": False,
        "blocked_actions": blocked_actions,
        "blocking_reasons": rejected,
        "advice": (
            "将被驳回的关键节点改为 approved，或使用 lenient 模式进行非阻断编译。"
            if strict_blocked
            else "当前关键节点不会阻断编译。"
        ),
    }


def _build_policy_snapshot(
    *,
    project: ResearchProject,
    section_id: str | None = None,
) -> dict[str, Any]:
    decision_map = _load_hitl_decision_map(project)
    decisions = list(decision_map.values())
    policy = learn_policy_from_hitl_decisions(decisions, section_id=section_id)
    directive_payload = _build_policy_writing_directives(
        policy=policy.model_dump(),
        decisions=decisions,
        section_id=section_id,
    )
    return {
        "schema_version": POLICY_SNAPSHOT_SCHEMA_VERSION,
        "project_id": project.project_id,
        "section_id": section_id,
        "generated_at": _now_iso(),
        "policy": policy.model_dump(),
        "writing_directives": directive_payload["writing_directives"],
        "writing_directives_metadata": directive_payload,
    }


_STRONG_CLAIM_REWRITES: tuple[tuple[str, str], ...] = (
    (r"\b(demonstrates|demonstrate|demonstrated)\b", "suggests"),
    (r"\b(proves|prove|proved)\b", "is consistent with"),
    (r"\b(definitive|certainly|always)\b", "preliminary"),
    (r"\b(guarantees|guarantee)\b", "supports"),
    (r"\b(causes|cause|caused)\b", "is associated with"),
)


def _downgrade_strong_conclusions(text: str) -> str:
    output = text
    for pattern, replacement in _STRONG_CLAIM_REWRITES:
        output = re.sub(pattern, replacement, output, flags=re.IGNORECASE)
    return output


def _render_risk_conclusion_template(
    *,
    base_text: str,
    reasons: list[str],
    section_id: str,
    peer_review_payload: dict[str, Any] | None = None,
) -> str:
    unresolved = 0
    if isinstance(peer_review_payload, dict):
        unresolved = int(peer_review_payload.get("unresolved_issue_count") or 0)
    lines = [
        _downgrade_strong_conclusions(base_text.strip()),
        "",
        "## 风险结论模板",
        "- 结论状态: 风险保守（fail-close 已触发）",
        f"- 章节: {section_id}",
        f"- 未解决审稿问题数: {unresolved}",
        "- 风险原因:",
    ]
    lines.extend([f"  - {reason}" for reason in reasons])
    lines.extend(
        [
            "- 合规动作:",
            "  - 禁止输出强因果或确定性结论。",
            "  - 仅允许给出“相关性/趋势性/待验证”表述。",
            "  - 必须补齐缺失证据或通过 HITL 审批后再解除风险模板。",
        ]
    )
    return "\n".join(lines).strip()


def upsert_project(thread_id: str, project: ResearchProject) -> ResearchProject:
    return _project_store(thread_id).upsert_project(project)


def get_project(thread_id: str, project_id: str) -> ResearchProject | None:
    return _project_store(thread_id).get_project(project_id)


def list_projects(thread_id: str) -> list[ResearchProject]:
    return _project_store(thread_id).list_projects()


def upsert_section(thread_id: str, project_id: str, section: SectionDraft) -> SectionDraft:
    store = _project_store(thread_id)
    project = store.get_project(project_id)
    if project is None:
        raise ValueError(f"Project '{project_id}' not found")
    existing = _get_section_from_project(project, section.section_id)
    saved = store.upsert_section(project_id, section)
    # Auto-capture human edit intent as policy feedback directives.
    if existing is not None:
        directives = _infer_writing_directives_from_section_edit(existing.content, section.content)
        if directives:
            latest_project = store.get_project(project_id)
            if latest_project is not None:
                decision_map = _load_hitl_decision_map(latest_project)
                now = _now_iso()
                auto_decision = HitlDecision(
                    action_id="hitl.auto_section_edit_feedback",
                    source="section_edit_diff",
                    label="auto captured section edit feedback",
                    decision="approved",
                    section_id=section.section_id,
                    updated_at=now,
                    metadata={
                        "auto_captured": True,
                        "writing_directives": directives,
                    },
                )
                decision_map[_hitl_key(auto_decision.action_id, auto_decision.section_id)] = auto_decision
                hitl_metadata = _serialize_hitl_metadata(decision_map)
                hitl_metadata["updated_at"] = now
                base_metadata = latest_project.metadata if isinstance(latest_project.metadata, dict) else {}
                latest_project.metadata = {
                    **base_metadata,
                    "hitl_decisions": hitl_metadata,
                }
                store.upsert_project(latest_project)
    _append_section_version_event(
        thread_id=thread_id,
        project_id=project_id,
        section=saved,
        before_text=existing.content if existing is not None else "",
        source="upsert_section",
    )
    return saved


def list_section_versions(
    thread_id: str,
    project_id: str,
    section_id: str,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    payload = _load_section_versions(thread_id, project_id, section_id)
    versions = payload.get("versions", [])
    if not isinstance(versions, list):
        versions = []
    rows = [item for item in versions if isinstance(item, dict)]
    if limit > 0:
        rows = rows[-limit:]
    return {
        "version_schema_version": payload.get("schema_version") or SECTION_VERSION_SCHEMA_VERSION,
        "project_id": project_id,
        "section_id": section_id,
        "total_count": len(versions),
        "versions": rows,
        "updated_at": payload.get("updated_at"),
        "artifact_path": _to_virtual_path(thread_id, _section_versions_path(thread_id, project_id, section_id)),
    }


def rollback_section_to_version(
    thread_id: str,
    project_id: str,
    section_id: str,
    *,
    version_id: str,
) -> dict[str, Any]:
    store = _project_store(thread_id)
    project = store.get_project(project_id)
    if project is None:
        raise ValueError(f"Project '{project_id}' not found")
    current_section = _get_section_from_project(project, section_id)
    if current_section is None:
        raise ValueError(f"Section '{section_id}' not found in project '{project_id}'")

    payload = _load_section_versions(thread_id, project_id, section_id)
    versions = payload.get("versions", [])
    if not isinstance(versions, list) or not versions:
        raise ValueError(f"No version history available for section '{section_id}'")

    selected_entry: dict[str, Any] | None = None
    normalized_version = version_id.strip()
    for item in versions:
        if not isinstance(item, dict):
            continue
        if str(item.get("version_id") or "") == normalized_version:
            selected_entry = item
            break
    if selected_entry is None and normalized_version.isdigit():
        target_number = int(normalized_version)
        for item in versions:
            if not isinstance(item, dict):
                continue
            if int(item.get("version_number") or 0) == target_number:
                selected_entry = item
                break
    if selected_entry is None:
        raise ValueError(
            f"Version '{version_id}' not found for section '{section_id}'. "
            "Use list_section_versions to inspect available versions."
        )

    rollback_content = str(selected_entry.get("content") or "")
    rolled_section = current_section.model_copy(
        update={
            "content": rollback_content,
            "version": max(int(current_section.version or 1) + 1, int(selected_entry.get("version_number") or 1) + 1),
        }
    )
    saved = store.upsert_section(project_id, rolled_section)
    diff_payload = _append_section_version_event(
        thread_id=thread_id,
        project_id=project_id,
        section=saved,
        before_text=current_section.content,
        source="rollback",
        rollback_from_version_id=str(selected_entry.get("version_id") or normalized_version),
    )
    rollback_record = {
        "project_id": project_id,
        "section_id": section_id,
        "rolled_back_to_version_id": selected_entry.get("version_id"),
        "rolled_back_to_version_number": selected_entry.get("version_number"),
        "new_section_version": saved.version,
        "new_history_version_id": diff_payload.get("to_version_id"),
        "diff": diff_payload,
        "section": saved.model_dump(),
    }
    rollback_path = (
        _research_root(thread_id)
        / "section-versions"
        / f"{project_id}-{section_id}-rollback-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    )
    _dump_json(rollback_path, rollback_record)
    rollback_record["artifact_path"] = _to_virtual_path(thread_id, rollback_path)
    return rollback_record


def get_section_traceability(thread_id: str, project_id: str, section_id: str) -> dict[str, Any]:
    project = _project_store(thread_id).get_project(project_id)
    if project is None:
        raise ValueError(f"Project '{project_id}' not found")
    section = _get_section_from_project(project, section_id)
    if section is None:
        raise ValueError(f"Section '{section_id}' not found in project '{project_id}'")

    compiled_path = _research_root(thread_id) / "compiled" / f"{project_id}-{section_id}.md"
    if compiled_path.exists():
        compiled_text = compiled_path.read_text(encoding="utf-8")
        compiled_artifact_path = _to_virtual_path(thread_id, compiled_path)
    else:
        compiled_text = section.content
        compiled_artifact_path = None

    trace_payload = _build_section_traceability_payload(
        thread_id=thread_id,
        project_id=project_id,
        section=section,
        compiled_text=compiled_text,
        compiled_artifact_path=compiled_artifact_path,
    )
    grounding_path = _claim_grounding_path(thread_id, project_id, section_id)
    grounding_payload = _load_claim_grounding_snapshot(grounding_path)
    if grounding_payload:
        grounding_payload = _revalidate_claim_grounding_snapshot(thread_id=thread_id, snapshot=grounding_payload)
        _dump_json(grounding_path, grounding_payload)
        status_map: dict[str, dict[str, Any]] = {}
        for claim_row in grounding_payload.get("claims", []):
            if not isinstance(claim_row, dict):
                continue
            cid = str(claim_row.get("claim_id") or "").strip()
            if not cid:
                continue
            status_map[cid] = claim_row
        for claim_row in trace_payload.get("claims", []):
            if not isinstance(claim_row, dict):
                continue
            cid = str(claim_row.get("claim_id") or "").strip()
            status = status_map.get(cid)
            if status is None:
                continue
            claim_row["grounding_status"] = status.get("status") or "valid"
            claim_row["hard_grounded"] = bool(status.get("hard_grounded"))
            claim_row["invalid_reasons"] = status.get("invalid_reasons") or []
            claim_row["stale_reasons"] = status.get("stale_reasons") or []
        for sentence_row in trace_payload.get("sentence_links", []):
            if not isinstance(sentence_row, dict):
                continue
            claim_ids = sentence_row.get("claim_ids")
            if not isinstance(claim_ids, list):
                continue
            sentence_row["invalid_claim_ids"] = [
                cid for cid in claim_ids if isinstance(status_map.get(str(cid)), dict) and status_map[str(cid)].get("status") == "invalid"
            ]
            sentence_row["stale_claim_ids"] = [
                cid for cid in claim_ids if isinstance(status_map.get(str(cid)), dict) and status_map[str(cid)].get("status") == "stale"
            ]
        trace_payload["claim_grounding"] = grounding_payload
        trace_payload["claim_grounding_artifact_path"] = _to_virtual_path(thread_id, grounding_path)
    trace_path = _research_root(thread_id) / "compiled" / f"{project_id}-{section_id}.trace.json"
    _dump_json(trace_path, trace_payload)
    trace_payload["artifact_path"] = _to_virtual_path(thread_id, trace_path)
    return trace_payload


def upsert_claim(thread_id: str, claim: Claim) -> Claim:
    return _claim_graph(thread_id).upsert(claim)


def upsert_evidence(thread_id: str, evidence: EvidenceUnit) -> EvidenceUnit:
    return _evidence_store(thread_id).upsert(evidence)


def upsert_citation(thread_id: str, citation: CitationRecord) -> CitationRecord:
    return _citation_registry(thread_id).upsert(citation)


def upsert_fact(thread_id: str, fact: NumericFact) -> NumericFact:
    return _source_of_truth_store(thread_id).upsert_fact(fact)


def _citation_id_from_graph_node(node: dict[str, Any]) -> str | None:
    doi = node.get("doi")
    if isinstance(doi, str) and doi.strip():
        return doi.strip()
    node_id = node.get("node_id")
    if not isinstance(node_id, str) or not node_id.strip():
        return None
    source = node.get("source")
    if source == "semantic_scholar":
        return f"s2:{node_id}"
    return node_id.strip()


def _extract_graph_citation_ids(citation_graph_payload: dict[str, Any] | None, *, max_ids: int = 4) -> list[str]:
    if not isinstance(citation_graph_payload, dict):
        return []
    ids: list[str] = []
    for node in citation_graph_payload.get("nodes", []):
        if not isinstance(node, dict):
            continue
        citation_id = _citation_id_from_graph_node(node)
        if citation_id and citation_id not in ids:
            ids.append(citation_id)
            if len(ids) >= max_ids:
                break
    return ids


def _build_graph_evidence_units(
    *,
    source: LiteratureSource,
    external_id: str,
    title: str,
    citation_graph_payload: dict[str, Any] | None,
    literature_graph_payload: dict[str, Any] | None,
    artifact_virtual_path: str,
) -> list[EvidenceUnit]:
    graph_nodes = citation_graph_payload.get("nodes", []) if isinstance(citation_graph_payload, dict) else []
    graph_edges = citation_graph_payload.get("edges", []) if isinstance(citation_graph_payload, dict) else []
    narrative_threads = citation_graph_payload.get("narrative_threads", []) if isinstance(citation_graph_payload, dict) else []
    graph_claims = literature_graph_payload.get("claims", []) if isinstance(literature_graph_payload, dict) else []
    graph_synthesis = literature_graph_payload.get("synthesis_threads", []) if isinstance(literature_graph_payload, dict) else []
    if not isinstance(graph_nodes, list):
        graph_nodes = []
    if not isinstance(graph_edges, list):
        graph_edges = []
    if not isinstance(graph_claims, list):
        graph_claims = []
    if not isinstance(graph_synthesis, list):
        graph_synthesis = []
    if len(graph_nodes) == 0 and len(graph_claims) == 0:
        return []

    co_citation_count = len(
        [
            edge
            for edge in graph_edges
            if isinstance(edge, dict) and edge.get("relation") == "co_citation"
        ]
    )
    citation_ids = _extract_graph_citation_ids(citation_graph_payload if isinstance(citation_graph_payload, dict) else None)
    graph_key = f"{source}:{external_id}"

    units: list[EvidenceUnit] = [
        EvidenceUnit(
            evidence_id=f"graph:{graph_key}:overview",
            evidence_type="manual_note",
            summary=f"Dynamic citation graph overview for {title}",
            source_ref=artifact_virtual_path,
            quote=(
                f"Citation graph contains {len(graph_nodes)} node(s), "
                f"{len(graph_edges)} edge(s), and {co_citation_count} co-citation signal(s)."
            ),
            location={
                "source": source,
                "external_id": external_id,
                "kind": "citation_graph_overview",
            },
            citation_ids=citation_ids,
            confidence=0.72,
            metadata={
                "node_count": len(graph_nodes),
                "edge_count": len(graph_edges),
                "co_citation_edge_count": co_citation_count,
            },
        )
    ]

    if isinstance(narrative_threads, list):
        for idx, thread_text in enumerate(narrative_threads[:3], start=1):
            if not isinstance(thread_text, str) or not thread_text.strip():
                continue
            units.append(
                EvidenceUnit(
                    evidence_id=f"graph:{graph_key}:thread{idx}",
                    evidence_type="manual_note",
                    summary=f"Citation narrative thread {idx} for {title}",
                    source_ref=artifact_virtual_path,
                    quote=thread_text.strip(),
                    location={
                        "source": source,
                        "external_id": external_id,
                        "kind": "citation_graph_narrative",
                        "thread_index": idx,
                    },
                    citation_ids=citation_ids,
                    confidence=0.7,
                    metadata={"thread_index": idx},
                )
            )
    for idx, claim in enumerate(graph_claims[:3], start=1):
        if not isinstance(claim, dict):
            continue
        claim_text = str(claim.get("claim_text") or "").strip()
        if not claim_text:
            continue
        support_ids = claim.get("support_paper_ids") if isinstance(claim.get("support_paper_ids"), list) else []
        refute_ids = claim.get("refute_paper_ids") if isinstance(claim.get("refute_paper_ids"), list) else []
        reconcile_ids = claim.get("reconcile_paper_ids") if isinstance(claim.get("reconcile_paper_ids"), list) else []
        units.append(
            EvidenceUnit(
                evidence_id=f"graph:{graph_key}:claim{idx}",
                evidence_type="manual_note",
                summary=f"Literature claim cluster {idx} for {title}",
                source_ref=artifact_virtual_path,
                quote=(
                    f"Claim cluster '{claim_text}': "
                    f"support={len(support_ids)}, refute={len(refute_ids)}, reconcile={len(reconcile_ids)}."
                ),
                location={
                    "source": source,
                    "external_id": external_id,
                    "kind": "literature_graph_claim_cluster",
                    "claim_index": idx,
                },
                citation_ids=citation_ids,
                confidence=0.68,
                metadata={
                    "claim_text": claim_text,
                    "support_paper_ids": support_ids,
                    "refute_paper_ids": refute_ids,
                    "reconcile_paper_ids": reconcile_ids,
                },
            )
        )
    for idx, thread_text in enumerate(graph_synthesis[:3], start=1):
        if not isinstance(thread_text, str) or not thread_text.strip():
            continue
        units.append(
            EvidenceUnit(
                evidence_id=f"graph:{graph_key}:synthesis{idx}",
                evidence_type="manual_note",
                summary=f"Literature synthesis thread {idx} for {title}",
                source_ref=artifact_virtual_path,
                quote=thread_text.strip(),
                location={
                    "source": source,
                    "external_id": external_id,
                    "kind": "literature_graph_synthesis",
                    "thread_index": idx,
                },
                citation_ids=citation_ids,
                confidence=0.7,
                metadata={"thread_index": idx},
            )
        )
    return units


def ingest_fulltext_evidence(thread_id: str, source: LiteratureSource, external_id: str, *, persist: bool = True) -> dict[str, Any]:
    result = FullTextEvidenceIngestor.ingest(source, external_id)
    evidence_store = _evidence_store(thread_id)
    citation_registry = _citation_registry(thread_id)
    citation_graph_payload = asdict(result.citation_graph) if result.citation_graph is not None else None
    literature_graph_payload = asdict(result.literature_graph) if result.literature_graph is not None else None
    artifact_path = _research_root(thread_id) / "artifacts" / f"ingest-{source}-{external_id}.json"
    artifact_virtual_path = _to_virtual_path(thread_id, artifact_path)

    persisted_ids: list[str] = []
    persisted_citation_ids: list[str] = []
    for unit in result.evidence_units:
        if persist:
            evidence_store.upsert(unit)
            persisted_ids.append(unit.evidence_id)

    if persist and result.record.doi:
        citation_registry.upsert(
            CitationRecord(
                citation_id=result.record.doi,
                doi=result.record.doi,
                title=result.record.title,
                authors=[],
                year=result.record.year,
                source=result.record.source,
                verified=False,
                metadata={"external_id": result.record.external_id, "url": result.record.url},
            )
        )
        persisted_citation_ids.append(result.record.doi)

    if persist and citation_graph_payload is not None:
        for node in citation_graph_payload.get("nodes", []):
            if not isinstance(node, dict):
                continue
            citation_id = _citation_id_from_graph_node(node)
            if citation_id is None:
                continue
            citation_registry.upsert(
                CitationRecord(
                    citation_id=citation_id,
                    doi=node.get("doi") if isinstance(node.get("doi"), str) else None,
                    title=str(node.get("title") or citation_id),
                    authors=[],
                    year=node.get("year") if isinstance(node.get("year"), int) else None,
                    source=str(node.get("source") or "dynamic_graph"),
                    verified=False,
                    metadata={
                        "dynamic_graph": True,
                        "node_id": node.get("node_id"),
                        "url": node.get("url"),
                        "seed_external_id": result.record.external_id,
                    },
                )
            )
            if citation_id not in persisted_citation_ids:
                persisted_citation_ids.append(citation_id)

    graph_nodes = citation_graph_payload.get("nodes", []) if isinstance(citation_graph_payload, dict) else []
    graph_edges = citation_graph_payload.get("edges", []) if isinstance(citation_graph_payload, dict) else []
    co_citation_edges = [
        edge for edge in graph_edges if isinstance(edge, dict) and edge.get("relation") == "co_citation"
    ]
    graph_evidence_units = _build_graph_evidence_units(
        source=source,
        external_id=external_id,
        title=result.record.title,
        citation_graph_payload=citation_graph_payload,
        literature_graph_payload=literature_graph_payload,
        artifact_virtual_path=artifact_virtual_path,
    )
    graph_evidence_ids = [unit.evidence_id for unit in graph_evidence_units]
    if persist:
        for unit in graph_evidence_units:
            evidence_store.upsert(unit)
            if unit.evidence_id not in persisted_ids:
                persisted_ids.append(unit.evidence_id)

    artifact = {
        "record": {
            "source": result.record.source,
            "external_id": result.record.external_id,
            "title": result.record.title,
            "abstract": result.record.abstract,
            "year": result.record.year,
            "url": result.record.url,
            "doi": result.record.doi,
        },
        "evidence_count": len(result.evidence_units),
        "persisted_evidence_ids": persisted_ids,
        "persisted_citation_ids": persisted_citation_ids,
        "citation_graph": citation_graph_payload,
        "literature_graph": literature_graph_payload,
        "citation_graph_node_count": len(graph_nodes),
        "co_citation_edge_count": len(co_citation_edges),
        "literature_graph_claim_count": len(literature_graph_payload.get("claims", [])) if isinstance(literature_graph_payload, dict) else 0,
        "literature_graph_edge_count": len(literature_graph_payload.get("edges", [])) if isinstance(literature_graph_payload, dict) else 0,
        "narrative_threads": citation_graph_payload.get("narrative_threads", []) if isinstance(citation_graph_payload, dict) else [],
        "literature_synthesis_threads": literature_graph_payload.get("synthesis_threads", []) if isinstance(literature_graph_payload, dict) else [],
        "graph_evidence_ids": graph_evidence_ids,
    }
    _dump_json(artifact_path, artifact)
    return {
        **artifact,
        "artifact_path": artifact_virtual_path,
    }


def plan_project_section_narrative(
    thread_id: str,
    project_id: str,
    section_id: str,
    *,
    self_question_rounds: int = 3,
    include_storyboard: bool = True,
) -> dict[str, Any]:
    """Generate pre-writing narrative plan: takeaway, logic chain, storyboard, self-questioning."""
    store = _project_store(thread_id)
    project = store.get_project(project_id)
    if project is None:
        raise ValueError(f"Project '{project_id}' not found")
    section = next((s for s in project.sections if s.section_id == section_id), None)
    if section is None:
        raise ValueError(f"Section '{section_id}' not found in project '{project_id}'")

    claim_graph = _claim_graph(thread_id)
    evidence_store = _evidence_store(thread_id)
    citation_registry = _citation_registry(thread_id)
    claim_map_payload = _build_section_claim_map(
        section=section,
        claim_graph=claim_graph,
        evidence_store=evidence_store,
        citation_registry=citation_registry,
    )
    claim_map_path = _research_root(thread_id) / "claim-maps" / f"{project_id}-{section_id}.json"
    _dump_json(claim_map_path, claim_map_payload)
    narrative_plan = _plan_section_narrative(
        project=project,
        section=section,
        claim_graph=claim_graph,
        evidence_store=evidence_store,
        citation_registry=citation_registry,
        self_question_rounds=self_question_rounds,
        include_storyboard=include_storyboard,
    )
    payload = narrative_plan.model_dump()
    payload["self_question_rounds"] = max(1, min(int(self_question_rounds), 8))
    payload["include_storyboard"] = bool(include_storyboard)
    payload["claim_map"] = claim_map_payload
    payload["claim_map_artifact_path"] = _to_virtual_path(thread_id, claim_map_path)
    payload["runtime_stage_context"] = _resolve_runtime_stage_context(operation="plan_narrative")
    _inject_prompt_pack_fields(payload)
    artifact_path = _research_root(thread_id) / "narrative-plans" / f"{project_id}-{section_id}.json"
    _dump_json(artifact_path, payload)
    payload["artifact_path"] = _to_virtual_path(thread_id, artifact_path)
    return payload


def compile_project_section(
    thread_id: str,
    project_id: str,
    section_id: str,
    *,
    mode: CompileMode = "strict",
    auto_peer_review: bool = False,
    auto_hypothesis: bool = False,
    peer_review_max_rounds: int = 3,
    reviewer2_styles: list[Reviewer2StyleOverride] | None = None,
    peer_review_ab_variant: str | None = None,
    max_hypotheses: int = 5,
    narrative_style: NarrativeStyleOverride = "auto",
    narrative_max_templates: int | None = None,
    narrative_evidence_density: NarrativeDensityOverride | None = None,
    narrative_auto_by_section_type: bool = True,
    narrative_paragraph_tones: list[NarrativeToneOverride] | None = None,
    narrative_paragraph_evidence_densities: list[NarrativeDensityOverride] | None = None,
    journal_style_enabled: bool | None = None,
    journal_style_force_refresh: bool = False,
    journal_style_sample_size: int | None = None,
    journal_style_recent_year_window: int | None = None,
    policy_snapshot_auto_adjust_narrative: bool = True,
    narrative_self_question_rounds: int = 3,
    narrative_include_storyboard: bool = True,
) -> dict[str, Any]:
    store = _project_store(thread_id)
    project = store.get_project(project_id)
    if project is None:
        raise ValueError(f"Project '{project_id}' not found")
    section = next((s for s in project.sections if s.section_id == section_id), None)
    if section is None:
        raise ValueError(f"Section '{section_id}' not found in project '{project_id}'")
    hitl_checkpoints = _resolve_key_hitl_checkpoints(project, section_id=section.section_id)
    hitl_impact_preview = _build_hitl_impact_preview(hitl_checkpoints)
    policy_snapshot_payload = _build_policy_snapshot(project=project, section_id=section.section_id)
    policy_snapshot = policy_snapshot_payload.get("policy") if isinstance(policy_snapshot_payload, dict) else {}
    if not isinstance(policy_snapshot, dict):
        policy_snapshot = {}
    policy_writing_directives = policy_snapshot_payload.get("writing_directives") if isinstance(policy_snapshot_payload, dict) else []
    if not isinstance(policy_writing_directives, list):
        policy_writing_directives = []
    policy_writing_directives = [str(item).strip() for item in policy_writing_directives if str(item).strip()]
    policy_snapshot_artifact_path = _policy_snapshot_path(thread_id, project_id, section.section_id)
    _dump_json(policy_snapshot_artifact_path, policy_snapshot_payload)
    hitl_blocking = bool(hitl_impact_preview.get("strict_compile_blocked"))
    _record_compile_attempt_metrics(
        thread_id=thread_id,
        strict_mode=(mode == "strict"),
        hitl_blocking=hitl_blocking,
    )
    if mode == "strict" and hitl_blocking:
        raise ValueError("PI has rejected one or more key HITL checkpoints. Resolve HITL decisions before strict compile.")

    claim_graph = _claim_graph(thread_id)
    evidence_store = _evidence_store(thread_id)
    citation_registry = _citation_registry(thread_id)
    source_of_truth_store = _source_of_truth_store(thread_id)
    claim_map_payload = _build_section_claim_map(
        section=section,
        claim_graph=claim_graph,
        evidence_store=evidence_store,
        citation_registry=citation_registry,
    )
    claim_map_path = _research_root(thread_id) / "claim-maps" / f"{project_id}-{section_id}.json"
    _dump_json(claim_map_path, claim_map_payload)
    narrative_plan = _plan_section_narrative(
        project=project,
        section=section,
        claim_graph=claim_graph,
        evidence_store=evidence_store,
        citation_registry=citation_registry,
        self_question_rounds=narrative_self_question_rounds,
        include_storyboard=narrative_include_storyboard,
    )
    narrative_plan_payload = narrative_plan.model_dump()
    narrative_plan_payload["self_question_rounds"] = max(1, min(int(narrative_self_question_rounds), 8))
    narrative_plan_payload["include_storyboard"] = bool(narrative_include_storyboard)
    narrative_plan_path = _research_root(thread_id) / "narrative-plans" / f"{project_id}-{section_id}.json"
    _dump_json(narrative_plan_path, narrative_plan_payload)
    resolved_venue = _resolve_supported_venue(project.target_venue, project.discipline)
    peer_review_strategy = _resolve_peer_review_strategy(
        thread_id=thread_id,
        venue_name=resolved_venue,
        requested_max_rounds=peer_review_max_rounds,
        reviewer2_styles=reviewer2_styles,
        peer_review_ab_variant=peer_review_ab_variant,
    )
    peer_review_strategy_config = _build_peer_review_strategy_config_snapshot(thread_id=thread_id)
    resolved_reviewer2_styles = list(peer_review_strategy["resolved_reviewer2_styles"])
    resolved_peer_review_max_rounds = int(peer_review_strategy["resolved_max_rounds"])
    resolved_peer_review_ab_variant = str(peer_review_strategy["ab_variant"])
    style_venue_name = _resolve_style_venue_name(project.target_venue, resolved_venue)
    narrative_strategy = _resolve_narrative_strategy(
        venue_name=resolved_venue,
        section=section,
        narrative_style=narrative_style,
        narrative_max_templates=narrative_max_templates,
        narrative_evidence_density=narrative_evidence_density,
        narrative_auto_by_section_type=narrative_auto_by_section_type,
        narrative_paragraph_tones=narrative_paragraph_tones,
        narrative_paragraph_evidence_densities=narrative_paragraph_evidence_densities,
    )
    policy_snapshot_adjustment_applied = False
    # Convert HITL approve/reject signals into runtime strategy guidance.
    if narrative_style == "auto" and policy_snapshot_auto_adjust_narrative:
        original_tone = narrative_strategy.tone
        original_density = narrative_strategy.evidence_density
        original_max_templates = narrative_strategy.max_templates
        recommended_tone = policy_snapshot.get("recommended_tone")
        if isinstance(recommended_tone, str) and recommended_tone in {"conservative", "balanced", "aggressive"}:
            narrative_strategy.tone = recommended_tone
        if bool(policy_snapshot.get("prefer_conservative_claims")):
            narrative_strategy.tone = "conservative"
        if bool(policy_snapshot.get("require_stronger_validation")):
            narrative_strategy.evidence_density = "high"
            narrative_strategy.max_templates = max(narrative_strategy.max_templates, 2)
        if bool(policy_snapshot.get("require_ethics_reproducibility")) and narrative_strategy.evidence_density == "low":
            narrative_strategy.evidence_density = "medium"
        policy_snapshot_adjustment_applied = (
            narrative_strategy.tone != original_tone
            or narrative_strategy.evidence_density != original_density
            or narrative_strategy.max_templates != original_max_templates
        )
    journal_style_cfg = get_journal_style_config()
    resolved_journal_style_enabled = journal_style_cfg.enabled if journal_style_enabled is None else journal_style_enabled
    journal_style_bundle: dict[str, Any] | None = None
    journal_style_alignment_applied = False
    if resolved_journal_style_enabled:
        journal_style_bundle = build_journal_style_bundle(
            venue_name=style_venue_name,
            cache_path=_journal_style_cache_path(thread_id, style_venue_name),
            force_refresh=journal_style_force_refresh,
            sample_size=journal_style_sample_size,
            recent_year_window=journal_style_recent_year_window,
            config=journal_style_cfg,
        )
        journal_style_alignment_applied = _apply_journal_style_alignment_to_narrative(
            narrative_strategy,
            journal_style_bundle=journal_style_bundle,
            narrative_style=narrative_style,
            narrative_max_templates=narrative_max_templates,
            narrative_evidence_density=narrative_evidence_density,
        )
    venue_style_adapter = build_style_adapter_profile(
        journal_style_bundle=journal_style_bundle,
        claim_tone=narrative_strategy.tone,
        evidence_density=narrative_strategy.evidence_density,
        max_templates=narrative_strategy.max_templates,
        runtime_writing_directives=policy_writing_directives,
    )
    runtime_stage_context = _resolve_runtime_stage_context(
        operation="compile_section",
        auto_peer_review=auto_peer_review,
        auto_hypothesis=auto_hypothesis,
    )

    result = SectionCompiler.compile_section(
        section=section,
        claim_graph=claim_graph,
        evidence_store=evidence_store,
        citation_registry=citation_registry,
        source_of_truth_store=source_of_truth_store,
        mode=mode,
        narrative_strategy=narrative_strategy,
    )

    compiled_text = result.compiled_text
    claim_map_rows = [item.model_dump() for item in result.claim_map]
    claim_map_summary = claim_map_payload.get("summary") if isinstance(claim_map_payload.get("summary"), dict) else {}
    claim_map_summary["mapped_claims"] = len(claim_map_rows)
    claim_map_summary["rows_with_markers"] = sum(1 for item in claim_map_rows if int(item.get("marker_count") or 0) > 0)
    rewrite_required_rows = [item for item in claim_map_rows if bool(item.get("rewrite_required"))]
    claim_map_summary["rewrite_required_claims"] = len(rewrite_required_rows)
    claim_map_summary["rewrite_required_claim_ids"] = [
        str(item.get("claim_id") or "")
        for item in rewrite_required_rows
        if str(item.get("claim_id") or "").strip()
    ]
    claim_map_payload["summary"] = claim_map_summary
    claim_map_payload["claims"] = claim_map_rows
    claim_map_payload["generated_at"] = _now_iso()
    _dump_json(claim_map_path, claim_map_payload)
    hypothesis_bundle_payload: dict[str, Any] | None = None
    peer_review_payload: dict[str, Any] | None = None
    peer_review_ab_metrics_payload: dict[str, Any] = _load_peer_review_ab_metrics(thread_id)
    peer_review_ab_metrics_payload["strategy_config"] = peer_review_strategy_config
    peer_review_ab_metrics_artifact_path: str | None = None
    metrics_path = _peer_review_ab_metrics_path(thread_id)
    if metrics_path.exists():
        peer_review_ab_metrics_artifact_path = _to_virtual_path(thread_id, metrics_path)
    is_core = _is_core_section(section)

    if is_core and auto_hypothesis:
        hypothesis_bundle = generate_hypotheses(
            evidence_store=evidence_store,
            citation_registry=citation_registry,
            source_of_truth_store=source_of_truth_store,
            focus_evidence_ids=section.evidence_ids or None,
            focus_fact_ids=section.fact_ids or None,
            max_hypotheses=max_hypotheses,
        )
        hypothesis_bundle_payload = hypothesis_bundle.model_dump()
        if hypothesis_bundle.synthesis_paragraph.strip():
            compiled_text = f"{compiled_text}\n\n### Hypothesis-Driven Interpretation\n{hypothesis_bundle.synthesis_paragraph}".strip()

    if is_core and auto_peer_review:
        peer_review_result = run_peer_review_loop(
            manuscript_text=compiled_text,
            venue_name=resolved_venue,
            section_id=section.section_id,
            max_rounds=resolved_peer_review_max_rounds,
            reviewer2_styles=resolved_reviewer2_styles,
        )
        compiled_text = peer_review_result.final_text
        peer_review_payload = peer_review_result.model_dump()
        peer_review_ab_metrics_payload = _record_peer_review_ab_metrics(
            thread_id=thread_id,
            event={
                "source": "compile_section",
                "project_id": project_id,
                "section_id": section.section_id,
                "venue_name": resolved_venue,
                "ab_variant": resolved_peer_review_ab_variant,
                "reviewer2_styles": resolved_reviewer2_styles,
                "peer_review_max_rounds": resolved_peer_review_max_rounds,
                "style_source": peer_review_strategy.get("style_source"),
                "round_source": peer_review_strategy.get("round_source"),
                "ab_variant_source": peer_review_strategy.get("ab_variant_source"),
                "auto_split_applied": bool(peer_review_strategy.get("auto_split_applied")),
                "thread_hash_ratio": peer_review_strategy.get("thread_hash_ratio"),
                "final_decision": peer_review_payload.get("final_decision"),
                "unresolved_issue_count": int(peer_review_payload.get("unresolved_issue_count") or 0),
                "round_count": len(peer_review_payload.get("rounds") or []),
            },
        )
        peer_review_ab_metrics_payload["strategy_config"] = peer_review_strategy_config
        peer_review_ab_metrics_artifact_path = _to_virtual_path(thread_id, _peer_review_ab_metrics_path(thread_id))

    claim_grounding_payload = _build_claim_grounding_snapshot(
        thread_id=thread_id,
        project_id=project_id,
        section=section,
        claim_graph=claim_graph,
        evidence_store=evidence_store,
        source_of_truth_store=source_of_truth_store,
    )
    claim_grounding_payload = _revalidate_claim_grounding_snapshot(
        thread_id=thread_id,
        snapshot=claim_grounding_payload,
    )
    claim_grounding_artifact_path = _claim_grounding_path(thread_id, project_id, section.section_id)
    _dump_json(claim_grounding_artifact_path, claim_grounding_payload)
    overlay_compiled_text, claim_grounding_alerts = _apply_claim_grounding_overlays(compiled_text, claim_grounding_payload)
    hard_grounding_sentence_check = _collect_hard_grounding_sentence_gaps(overlay_compiled_text)
    literature_alignment_check = _collect_literature_alignment_gaps(overlay_compiled_text)

    compliance_report = audit_scientific_compliance(compiled_text)
    compliance_payload = {
        "schema_version": COMPLIANCE_AUDIT_SCHEMA_VERSION,
        "project_id": project_id,
        "section_id": section_id,
        "generated_at": _now_iso(),
        "report": compliance_report.model_dump(),
    }
    compliance_artifact_path = _compliance_audit_path(thread_id, project_id, section_id)
    _dump_json(compliance_artifact_path, compliance_payload)

    section_claims = _collect_section_claims(section, claim_graph)
    section_evidence = _collect_section_evidence_units(section, section_claims, evidence_store)
    section_citations = _collect_section_citations(section, section_claims, section_evidence, citation_registry)
    section_facts = source_of_truth_store.list_facts()
    if section.fact_ids:
        scoped_fact_ids = set(section.fact_ids)
        section_facts = [item for item in section_facts if item.fact_id in scoped_fact_ids]
    section_versions_payload = _load_section_versions(thread_id, project_id, section_id)
    hitl_decisions = list(_load_hitl_decision_map(project).values())
    capability_assessment = evaluate_capabilities(
        project=project,
        section=section.model_copy(update={"content": overlay_compiled_text}),
        claims=section_claims,
        evidence_units=section_evidence,
        citations=section_citations,
        facts=section_facts,
        hitl_decisions=hitl_decisions,
        compliance_payload={
            "compliance_audit": compliance_report.model_dump(),
            "safety_valve_triggered": False,
        },
        latex_payload=None,
        section_versions=section_versions_payload,
    )
    capability_assessment_payload = {
        "schema_version": CAPABILITY_ASSESSMENT_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "project_id": project_id,
        "section_id": section.section_id,
        "catalog": capability_catalog(),
        "assessment": capability_assessment,
    }
    _inject_prompt_pack_fields(capability_assessment_payload)
    capability_assessment_artifact_path = _capability_assessment_path(thread_id, project_id, section.section_id)
    _dump_json(capability_assessment_artifact_path, capability_assessment_payload)
    capability_gate_reasons: list[str] = []
    for card in capability_assessment.get("scorecards", []):
        if not isinstance(card, dict):
            continue
        card_id = str(card.get("capability_id") or "")
        if card_id not in {"claim_engineering", "compliance_and_reproducibility"}:
            continue
        if str(card.get("status") or "").lower() != "fail":
            continue
        card_name = str(card.get("capability_name") or card_id)
        capability_gate_reasons.append(f"Capability gate failed: {card_name}.")
    capability_gate_failed = len(capability_gate_reasons) > 0

    safety_valve_reasons: list[str] = []
    if hitl_blocking:
        safety_valve_reasons.append("One or more key HITL checkpoints are rejected.")
    compile_errors = [issue for issue in result.issues if issue.severity == "error"]
    if compile_errors:
        safety_valve_reasons.append(f"Section compiler found {len(compile_errors)} blocking grounding issue(s).")
    rewrite_required_claims = int(claim_map_summary.get("rewrite_required_claims") or 0)
    if rewrite_required_claims > 0:
        safety_valve_reasons.append(
            f"Claim Map validation requires rewrite for {rewrite_required_claims} claim(s) with invalid bindings."
        )
    if section.claim_ids and not (section.evidence_ids or section.fact_ids or section.citation_ids):
        safety_valve_reasons.append("Claims exist but key evidence/fact/citation bindings are missing.")
    if is_core:
        if int(hard_grounding_sentence_check.get("missing_data_binding_count") or 0) > 0:
            safety_valve_reasons.append(
                "Hard grounding check detected conclusion sentences without [data:*] binding."
            )
        if int(hard_grounding_sentence_check.get("missing_citation_binding_count") or 0) > 0:
            safety_valve_reasons.append(
                "Hard grounding check detected conclusion sentences without [citation:*] binding."
            )
        if bool(literature_alignment_check.get("likely_listing_without_alignment")):
            safety_valve_reasons.append(
                "Literature alignment check detected citation listing without [支持]/[反驳]/[调和] mechanism-conflict synthesis."
            )
    grounding_summary = claim_grounding_payload.get("summary") if isinstance(claim_grounding_payload.get("summary"), dict) else {}
    invalid_claims = int(grounding_summary.get("invalid_claims") or 0)
    stale_claims = int(grounding_summary.get("stale_claims") or 0)
    if invalid_claims > 0:
        safety_valve_reasons.append(f"Claim grounding AST detected {invalid_claims} invalid claim(s) without hard data linkage.")
    if stale_claims > 0:
        safety_valve_reasons.append(f"Claim grounding AST detected {stale_claims} stale claim(s) due to artifact drift.")
    if isinstance(peer_review_payload, dict):
        if str(peer_review_payload.get("final_decision")) != "accept":
            safety_valve_reasons.append("Peer-review loop did not reach accept decision.")
        if int(peer_review_payload.get("unresolved_issue_count") or 0) > 0:
            safety_valve_reasons.append("Peer-review loop still reports unresolved reviewer issues.")
    if compliance_report.blocked_by_critical:
        safety_valve_reasons.append("Scientific compliance audit found critical ethics gaps.")
    if compliance_report.risk_level == "high":
        safety_valve_reasons.append("Scientific compliance audit risk level is high.")
    if compliance_report.findings:
        major_plus = [item for item in compliance_report.findings if item.severity in {"critical", "major"}]
        if major_plus:
            safety_valve_reasons.append(f"Scientific compliance audit found {len(major_plus)} major/critical issue(s).")
    safety_valve_reasons.extend(capability_gate_reasons)
    safety_valve_triggered = len(safety_valve_reasons) > 0
    risk_conclusion_template: str | None = None
    if safety_valve_triggered:
        risk_conclusion_template = _render_risk_conclusion_template(
            base_text=overlay_compiled_text,
            reasons=safety_valve_reasons,
            section_id=section.section_id,
            peer_review_payload=peer_review_payload,
        )
        compiled_text = risk_conclusion_template
    else:
        compiled_text = overlay_compiled_text

    artifact_path = _research_root(thread_id) / "compiled" / f"{project_id}-{section_id}.md"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(compiled_text, encoding="utf-8")
    compiled_section = section.model_copy(update={"content": compiled_text, "version": int(section.version or 1) + 1})
    store.upsert_section(project_id, compiled_section)
    version_diff_payload = _append_section_version_event(
        thread_id=thread_id,
        project_id=project_id,
        section=compiled_section,
        before_text=_latest_section_version_content(thread_id, project_id, section_id) or section.content,
        source="compile_section",
    )
    diff_artifact_path = _research_root(thread_id) / "compiled" / f"{project_id}-{section_id}.diff.json"
    _dump_json(diff_artifact_path, version_diff_payload)
    trace_payload = _build_section_traceability_payload(
        thread_id=thread_id,
        project_id=project_id,
        section=compiled_section,
        compiled_text=compiled_text,
        compiled_artifact_path=_to_virtual_path(thread_id, artifact_path),
    )
    trace_payload["claim_grounding"] = claim_grounding_payload
    trace_payload["claim_grounding_artifact_path"] = _to_virtual_path(thread_id, claim_grounding_artifact_path)
    trace_artifact_path = _research_root(thread_id) / "compiled" / f"{project_id}-{section_id}.trace.json"
    _dump_json(trace_artifact_path, trace_payload)
    constraint_violation = _build_constraint_violation_metrics(
        issues=[issue.model_dump() for issue in result.issues],
        compiled_text=overlay_compiled_text,
    )
    traceability_coverage = _build_traceability_coverage_metrics(trace_payload)
    delivery_completeness = _build_delivery_completeness_metrics(
        artifact_paths={
            "compiled_md": _to_virtual_path(thread_id, artifact_path),
            "details_json": None,
            "trace_json": _to_virtual_path(thread_id, trace_artifact_path),
            "version_diff_json": _to_virtual_path(thread_id, diff_artifact_path),
            "policy_snapshot_json": _to_virtual_path(thread_id, policy_snapshot_artifact_path),
            "compliance_audit_json": _to_virtual_path(thread_id, compliance_artifact_path),
        }
    )
    compile_gate_counters = _record_compile_attempt_metrics(
        thread_id=thread_id,
        strict_mode=(mode == "strict"),
        hitl_blocking=hitl_blocking,
        count_attempt=False,
        safety_valve_triggered=safety_valve_triggered,
        safety_valve_reasons=safety_valve_reasons,
    )
    engineering_gates = {
        "schema_version": ENGINEERING_GATES_SCHEMA_VERSION,
        "constraint_violation": constraint_violation,
        "safety_valve": {
            **_build_safety_valve_metrics(
                triggered=safety_valve_triggered,
                reasons=safety_valve_reasons,
            ),
            "triggered_count": int(compile_gate_counters.get("safety_valve_triggered_count") or 0),
            "successful_compile_runs": int(compile_gate_counters.get("successful_compile_runs") or 0),
            "trigger_rate": _safe_ratio(
                int(compile_gate_counters.get("safety_valve_triggered_count") or 0),
                int(compile_gate_counters.get("successful_compile_runs") or 0),
            ),
            "cumulative_reason_distribution": compile_gate_counters.get("safety_valve_reason_distribution") or {},
        },
        "compile_attempts": {
            "total_compile_attempts": int(compile_gate_counters.get("total_compile_attempts") or 0),
            "successful_compile_runs": int(compile_gate_counters.get("successful_compile_runs") or 0),
        },
        "hitl_blocking": {
            "strict_mode_requested": mode == "strict",
            "blocked_this_run": hitl_blocking,
            "strict_hitl_blocked_count": int(compile_gate_counters.get("strict_hitl_blocked_count") or 0),
            "strict_compile_attempts": int(compile_gate_counters.get("strict_compile_attempts") or 0),
            "strict_hitl_block_rate": _safe_ratio(
                int(compile_gate_counters.get("strict_hitl_blocked_count") or 0),
                int(compile_gate_counters.get("strict_compile_attempts") or 0),
            ),
        },
        "traceability_coverage": traceability_coverage,
        "delivery_completeness": delivery_completeness,
        "hard_grounding_sentence_check": hard_grounding_sentence_check,
        "literature_alignment_check": literature_alignment_check,
    }
    engineering_gate_metrics_path = _metrics_path(thread_id, "compile-gates")
    engineering_gates["compile_gate_counters_artifact_path"] = _to_virtual_path(thread_id, engineering_gate_metrics_path)
    engineering_gates["safety_valve"]["cumulative_reason_distribution"] = compile_gate_counters.get("safety_valve_reason_distribution") or {}
    engineering_gates["safety_valve"]["triggered"] = bool(engineering_gates["safety_valve"].get("triggered"))
    engineering_gates["safety_valve"]["reason_count"] = int(engineering_gates["safety_valve"].get("reason_count") or 0)
    engineering_gates["safety_valve"]["reason_distribution"] = engineering_gates["safety_valve"].get("reason_distribution") or {}
    engineering_gate_artifact_path = _research_root(thread_id) / "compiled" / f"{project_id}-{section_id}.engineering-gates.json"
    _dump_json(engineering_gate_artifact_path, engineering_gates)

    detail_artifact_path = _research_root(thread_id) / "compiled" / f"{project_id}-{section_id}.json"
    delivery_completeness["present_artifacts"] = _dedup_keep_order(
        delivery_completeness["present_artifacts"] + ["details_json"]
    )
    delivery_completeness["missing_artifacts"] = [item for item in delivery_completeness["missing_artifacts"] if item != "details_json"]
    delivery_completeness["present_count"] = len(delivery_completeness["present_artifacts"])
    delivery_completeness["completeness_ratio"] = _safe_ratio(
        delivery_completeness["present_count"],
        delivery_completeness["required_count"],
    )
    delivery_completeness["is_complete"] = len(delivery_completeness["missing_artifacts"]) == 0
    _dump_json(engineering_gate_artifact_path, engineering_gates)
    detail_payload = {
        "section_id": section_id,
        "is_core_section": is_core,
        "claim_map": claim_map_payload,
        "claim_map_artifact_path": _to_virtual_path(thread_id, claim_map_path),
        "narrative_plan": narrative_plan_payload,
        "narrative_plan_artifact_path": _to_virtual_path(thread_id, narrative_plan_path),
        "resolved_venue": resolved_venue,
        "narrative_strategy": narrative_strategy.model_dump(),
        "venue_style_adapter": venue_style_adapter,
        "narrative_sentence_count": result.narrative_sentence_count,
        "runtime_stage_context": runtime_stage_context,
        "issues": [issue.model_dump() for issue in result.issues],
        "journal_style": journal_style_bundle,
        "journal_style_alignment_applied": journal_style_alignment_applied,
        "peer_review": peer_review_payload,
        "reviewer2_styles": resolved_reviewer2_styles,
        "peer_review_ab_variant": resolved_peer_review_ab_variant,
        "peer_review_max_rounds": resolved_peer_review_max_rounds,
        "peer_review_strategy": peer_review_strategy,
        "peer_review_strategy_config": peer_review_strategy_config,
        "peer_review_ab_metrics": peer_review_ab_metrics_payload,
        "peer_review_ab_metrics_artifact_path": peer_review_ab_metrics_artifact_path,
        "claim_grounding": claim_grounding_payload,
        "claim_grounding_alerts": claim_grounding_alerts,
        "claim_grounding_artifact_path": _to_virtual_path(thread_id, claim_grounding_artifact_path),
        "hard_grounding_sentence_check": hard_grounding_sentence_check,
        "literature_alignment_check": literature_alignment_check,
        "hypothesis_bundle": hypothesis_bundle_payload,
        "hitl_checkpoints": hitl_checkpoints,
        "hitl_blocking": hitl_blocking,
        "hitl_impact_preview": hitl_impact_preview,
        "policy_snapshot": policy_snapshot,
        "policy_writing_directives": policy_writing_directives,
        "policy_snapshot_auto_adjust_narrative": policy_snapshot_auto_adjust_narrative,
        "policy_snapshot_adjustment_applied": policy_snapshot_adjustment_applied,
        "policy_snapshot_artifact_path": _to_virtual_path(thread_id, policy_snapshot_artifact_path),
        "narrative_self_question_rounds": max(1, min(int(narrative_self_question_rounds), 8)),
        "narrative_include_storyboard": bool(narrative_include_storyboard),
        "compliance_audit": compliance_report.model_dump(),
        "compliance_audit_artifact_path": _to_virtual_path(thread_id, compliance_artifact_path),
        "capability_assessment": capability_assessment,
        "capability_assessment_artifact_path": _to_virtual_path(thread_id, capability_assessment_artifact_path),
        "capability_gate_failed": capability_gate_failed,
        "capability_gate_reasons": capability_gate_reasons,
        "safety_valve_triggered": safety_valve_triggered,
        "safety_valve_reasons": safety_valve_reasons,
        "engineering_gates": engineering_gates,
        "engineering_gate_artifact_path": _to_virtual_path(thread_id, engineering_gate_artifact_path),
        "risk_conclusion_template": risk_conclusion_template,
        "version_diff": version_diff_payload,
        "version_diff_artifact_path": _to_virtual_path(thread_id, diff_artifact_path),
        "trace_artifact_path": _to_virtual_path(thread_id, trace_artifact_path),
    }
    detail_payload["metadata"] = _build_prompt_registry_metadata(detail_payload)
    _inject_prompt_pack_fields(detail_payload)
    _dump_json(detail_artifact_path, detail_payload)
    return_payload = {
        "section_id": section_id,
        "compiled_text": compiled_text,
        "issues": [issue.model_dump() for issue in result.issues],
        "artifact_path": _to_virtual_path(thread_id, artifact_path),
        "details_artifact_path": _to_virtual_path(thread_id, detail_artifact_path),
        "claim_map": claim_map_payload,
        "claim_map_artifact_path": _to_virtual_path(thread_id, claim_map_path),
        "narrative_plan": narrative_plan_payload,
        "narrative_plan_artifact_path": _to_virtual_path(thread_id, narrative_plan_path),
        "resolved_venue": resolved_venue,
        "narrative_strategy": narrative_strategy.model_dump(),
        "venue_style_adapter": venue_style_adapter,
        "narrative_sentence_count": result.narrative_sentence_count,
        "runtime_stage_context": runtime_stage_context,
        "journal_style": journal_style_bundle,
        "journal_style_alignment_applied": journal_style_alignment_applied,
        "peer_review": peer_review_payload,
        "reviewer2_styles": resolved_reviewer2_styles,
        "peer_review_ab_variant": resolved_peer_review_ab_variant,
        "peer_review_max_rounds": resolved_peer_review_max_rounds,
        "peer_review_strategy": peer_review_strategy,
        "peer_review_strategy_config": peer_review_strategy_config,
        "peer_review_ab_metrics": peer_review_ab_metrics_payload,
        "peer_review_ab_metrics_artifact_path": peer_review_ab_metrics_artifact_path,
        "claim_grounding": claim_grounding_payload,
        "claim_grounding_alerts": claim_grounding_alerts,
        "claim_grounding_artifact_path": _to_virtual_path(thread_id, claim_grounding_artifact_path),
        "hard_grounding_sentence_check": hard_grounding_sentence_check,
        "literature_alignment_check": literature_alignment_check,
        "hypothesis_bundle": hypothesis_bundle_payload,
        "hitl_checkpoints": hitl_checkpoints,
        "hitl_blocking": hitl_blocking,
        "hitl_impact_preview": hitl_impact_preview,
        "policy_snapshot": policy_snapshot,
        "policy_writing_directives": policy_writing_directives,
        "policy_snapshot_auto_adjust_narrative": policy_snapshot_auto_adjust_narrative,
        "policy_snapshot_adjustment_applied": policy_snapshot_adjustment_applied,
        "policy_snapshot_artifact_path": _to_virtual_path(thread_id, policy_snapshot_artifact_path),
        "narrative_self_question_rounds": max(1, min(int(narrative_self_question_rounds), 8)),
        "narrative_include_storyboard": bool(narrative_include_storyboard),
        "compliance_audit": compliance_report.model_dump(),
        "compliance_audit_artifact_path": _to_virtual_path(thread_id, compliance_artifact_path),
        "capability_assessment": capability_assessment,
        "capability_assessment_artifact_path": _to_virtual_path(thread_id, capability_assessment_artifact_path),
        "capability_gate_failed": capability_gate_failed,
        "capability_gate_reasons": capability_gate_reasons,
        "safety_valve_triggered": safety_valve_triggered,
        "safety_valve_reasons": safety_valve_reasons,
        "engineering_gates": engineering_gates,
        "engineering_gate_artifact_path": _to_virtual_path(thread_id, engineering_gate_artifact_path),
        "risk_conclusion_template": risk_conclusion_template,
        "version_diff": version_diff_payload,
        "version_diff_artifact_path": _to_virtual_path(thread_id, diff_artifact_path),
        "trace": trace_payload,
        "trace_artifact_path": _to_virtual_path(thread_id, trace_artifact_path),
    }
    _inject_prompt_pack_fields(return_payload)
    return return_payload


def _collect_project_markdown_for_latex(project: ResearchProject, *, section_ids: list[str] | None = None) -> str:
    selected_sections = project.sections
    if section_ids:
        requested = {item for item in section_ids if item}
        selected_sections = [item for item in project.sections if item.section_id in requested]
    chunks: list[str] = []
    for section in selected_sections:
        heading = (section.section_name or section.section_id).strip() or section.section_id
        body = section.content.strip()
        if not body:
            body = "_(Section content is empty. Please enrich this section before final export.)_"
        chunks.append(f"## {heading}\n\n{body}")
    return "\n\n".join(chunks).strip()


def build_latex_manuscript(
    thread_id: str,
    *,
    project_id: str | None = None,
    section_ids: list[str] | None = None,
    markdown_text: str | None = None,
    title: str | None = None,
    abstract_text: str | None = None,
    authors: list[str] | None = None,
    compile_pdf: bool | None = None,
    engine: LatexEngineOverride | None = None,
    output_name: str | None = None,
) -> dict[str, Any]:
    """Build native `.tex` manuscript and optionally compile PDF."""
    cfg = get_latex_config()
    if not cfg.enabled:
        raise ValueError("LaTeX pipeline is disabled by configuration")

    project: ResearchProject | None = None
    if project_id is not None:
        project = _project_store(thread_id).get_project(project_id)
        if project is None:
            raise ValueError(f"Project '{project_id}' not found")

    source_markdown = (markdown_text or "").strip()
    if not source_markdown:
        if project is None:
            raise ValueError("Either markdown_text or project_id must be provided")
        source_markdown = _collect_project_markdown_for_latex(project, section_ids=section_ids)
    if not source_markdown:
        raise ValueError("No manuscript markdown content available for LaTeX build")

    resolved_title = (title or (project.title if project is not None else "") or "DeerFlow Manuscript").strip()
    now_ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    default_stem = f"{_slugify(project_id or 'manuscript', default='manuscript')}-{now_ts}"
    output_stem = _slugify(output_name or default_stem, default=default_stem)

    output_root = _outputs_dir(thread_id) / cfg.artifact_subdir
    output_root.mkdir(parents=True, exist_ok=True)
    source_markdown_path = output_root / f"{output_stem}.source.md"
    source_markdown_path.write_text(source_markdown, encoding="utf-8")

    resolved_engine = engine or cfg.default_engine
    resolved_compile_pdf = cfg.compile_pdf_by_default if compile_pdf is None else bool(compile_pdf)
    latex_result = build_latex_artifacts(
        output_dir=output_root,
        output_stem=output_stem,
        title=resolved_title,
        markdown_text=source_markdown,
        abstract_text=abstract_text,
        authors=authors,
        engine=resolved_engine,
        compile_pdf=resolved_compile_pdf,
        compile_timeout_seconds=cfg.compile_timeout_seconds,
    )
    compile_log_text = ""
    try:
        compile_log_text = latex_result.log_file.read_text(encoding="utf-8")
    except Exception:
        compile_log_text = ""
    latex_gate_metrics = _record_latex_compile_metrics(
        thread_id=thread_id,
        compile_status=latex_result.compile_status,
        warning=latex_result.warning,
        compile_log_text=compile_log_text,
    )
    latex_gate_metrics_path = _metrics_path(thread_id, "latex-gates")

    payload: dict[str, Any] = {
        "project_id": project_id,
        "section_ids": section_ids or [],
        "title": resolved_title,
        "runtime_stage_context": _resolve_runtime_stage_context(operation="latex_submit"),
        "source_markdown_path": _to_virtual_path(thread_id, source_markdown_path),
        "tex_path": _to_virtual_path(thread_id, latex_result.tex_file),
        "pdf_path": _to_virtual_path(thread_id, latex_result.pdf_file) if latex_result.pdf_file is not None else None,
        "compile_log_path": _to_virtual_path(thread_id, latex_result.log_file),
        "compile_status": latex_result.compile_status,
        "compiler": latex_result.compiler,
        "engine_requested": resolved_engine,
        "compile_pdf_requested": resolved_compile_pdf,
        "citation_keys": latex_result.citation_keys,
        "citation_count": len(latex_result.citation_keys),
        "warning": latex_result.warning,
        "latex_quality_gate": {
            "schema_version": ENGINEERING_GATES_SCHEMA_VERSION,
            "compile_status_distribution": latex_gate_metrics.get("compile_status_distribution") or {},
            "compile_failure_type_clusters": latex_gate_metrics.get("compile_failure_type_clusters") or {},
            "total_runs": int(latex_gate_metrics.get("total_runs") or 0),
        },
        "latex_quality_gate_artifact_path": _to_virtual_path(thread_id, latex_gate_metrics_path),
        "artifact_path": _to_virtual_path(thread_id, latex_result.tex_file),
    }
    _inject_prompt_pack_fields(payload)
    summary_path = output_root / f"{output_stem}.json"
    _dump_json(summary_path, payload)
    payload["summary_artifact_path"] = _to_virtual_path(thread_id, summary_path)
    return payload


def simulate_review_and_plan(
    thread_id: str,
    *,
    venue_name: str,
    manuscript_text: str,
    evidence_map: dict[str, list[str]] | None = None,
    section_map: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    simulation = simulate_reviewer_comments(manuscript_text=manuscript_text, venue_name=venue_name)
    actions = build_rebuttal_plan(simulation.comments, evidence_map=evidence_map, section_map=section_map)
    letter = render_rebuttal_letter(simulation.comments, actions)

    artifact = {
        "venue": simulation.venue,
        "overall_assessment": simulation.overall_assessment,
        "runtime_stage_context": _resolve_runtime_stage_context(operation="simulate_review"),
        "comments": [c.model_dump() for c in simulation.comments],
        "actions": [a.model_dump() for a in actions],
        "rebuttal_letter": letter,
    }
    artifact_path = _research_root(thread_id) / "review" / f"review-{venue_name.lower().replace(' ', '-')}.json"
    _inject_prompt_pack_fields(artifact)
    _dump_json(artifact_path, artifact)
    letter_path = artifact_path.with_suffix(".md")
    letter_path.write_text(letter, encoding="utf-8")
    return {
        **artifact,
        "artifact_path": _to_virtual_path(thread_id, artifact_path),
        "letter_path": _to_virtual_path(thread_id, letter_path),
    }


def simulate_peer_review_cycle(
    thread_id: str,
    *,
    venue_name: str,
    manuscript_text: str,
    section_id: str | None = None,
    max_rounds: int = 3,
    reviewer2_styles: list[Reviewer2StyleOverride] | None = None,
    peer_review_ab_variant: str | None = None,
) -> dict[str, Any]:
    """Run Reviewer/Author/Area-Chair loop and persist debate artifacts."""
    peer_review_strategy = _resolve_peer_review_strategy(
        thread_id=thread_id,
        venue_name=venue_name,
        requested_max_rounds=max_rounds,
        reviewer2_styles=reviewer2_styles,
        peer_review_ab_variant=peer_review_ab_variant,
    )
    peer_review_strategy_config = _build_peer_review_strategy_config_snapshot(thread_id=thread_id)
    resolved_reviewer2_styles = list(peer_review_strategy["resolved_reviewer2_styles"])
    resolved_peer_review_max_rounds = int(peer_review_strategy["resolved_max_rounds"])
    resolved_peer_review_ab_variant = str(peer_review_strategy["ab_variant"])
    result = run_peer_review_loop(
        manuscript_text=manuscript_text,
        venue_name=venue_name,
        section_id=section_id,
        max_rounds=resolved_peer_review_max_rounds,
        reviewer2_styles=resolved_reviewer2_styles,
    )
    result_payload = result.model_dump()
    result_payload["runtime_stage_context"] = _resolve_runtime_stage_context(operation="simulate_peer_review")
    result_payload["reviewer2_styles"] = resolved_reviewer2_styles
    result_payload["peer_review_ab_variant"] = resolved_peer_review_ab_variant
    result_payload["peer_review_max_rounds"] = resolved_peer_review_max_rounds
    result_payload["peer_review_strategy"] = peer_review_strategy
    result_payload["peer_review_strategy_config"] = peer_review_strategy_config
    peer_review_ab_metrics = _record_peer_review_ab_metrics(
        thread_id=thread_id,
        event={
            "source": "simulate_peer_review_cycle",
            "section_id": section_id,
            "venue_name": venue_name,
            "ab_variant": resolved_peer_review_ab_variant,
            "reviewer2_styles": resolved_reviewer2_styles,
            "peer_review_max_rounds": resolved_peer_review_max_rounds,
            "style_source": peer_review_strategy.get("style_source"),
            "round_source": peer_review_strategy.get("round_source"),
            "ab_variant_source": peer_review_strategy.get("ab_variant_source"),
            "auto_split_applied": bool(peer_review_strategy.get("auto_split_applied")),
            "thread_hash_ratio": peer_review_strategy.get("thread_hash_ratio"),
            "final_decision": result_payload.get("final_decision"),
            "unresolved_issue_count": int(result_payload.get("unresolved_issue_count") or 0),
            "round_count": len(result_payload.get("rounds") or []),
        },
    )
    peer_review_ab_metrics["strategy_config"] = peer_review_strategy_config
    result_payload["peer_review_ab_metrics"] = peer_review_ab_metrics
    result_payload["peer_review_ab_metrics_artifact_path"] = _to_virtual_path(
        thread_id,
        _peer_review_ab_metrics_path(thread_id),
    )
    _inject_prompt_pack_fields(result_payload)
    artifact_path = _research_root(thread_id) / "review" / f"peer-loop-{venue_name.lower().replace(' ', '-')}.json"
    _dump_json(artifact_path, result_payload)
    final_text_path = artifact_path.with_suffix(".md")
    final_text_path.write_text(result.final_text, encoding="utf-8")
    payload = result_payload
    payload["artifact_path"] = _to_virtual_path(thread_id, artifact_path)
    payload["final_text_path"] = _to_virtual_path(thread_id, final_text_path)
    return payload


def get_peer_review_ab_metrics(thread_id: str) -> dict[str, Any]:
    payload = _load_peer_review_ab_metrics(thread_id)
    payload["metrics_schema_version"] = payload.get("schema_version") or PEER_REVIEW_AB_METRICS_SCHEMA_VERSION
    payload["strategy_config"] = _build_peer_review_strategy_config_snapshot(thread_id=thread_id)
    metrics_path = _peer_review_ab_metrics_path(thread_id)
    payload["artifact_path"] = _to_virtual_path(thread_id, metrics_path) if metrics_path.exists() else None
    return payload


def _resolve_compile_run_context(
    *,
    artifact_path: Path,
    payload: dict[str, Any],
) -> tuple[str | None, str | None]:
    project_id = str(payload.get("project_id") or "").strip() or None
    section_id = str(payload.get("section_id") or "").strip() or None
    if project_id and section_id:
        return project_id, section_id

    stem = artifact_path.name
    suffix = ".engineering-gates.json"
    if stem.endswith(suffix):
        stem = stem[: -len(suffix)]

    detail_payload = _load_json_dict(artifact_path.with_name(f"{stem}.json"))
    if section_id is None:
        section_id = str(detail_payload.get("section_id") or "").strip() or None
    if project_id is None:
        project_id = str(detail_payload.get("project_id") or "").strip() or None
    if project_id is None and section_id and stem.endswith(f"-{section_id}"):
        project_id = stem[: -(len(section_id) + 1)].strip() or None
    if project_id is None:
        left, sep, right = stem.rpartition("-")
        if sep and left:
            project_id = left.strip() or None
            if section_id is None:
                section_id = right.strip() or None
    return project_id, section_id


def _collect_engineering_gate_compile_runs(
    *,
    thread_id: str,
    project_id: str | None,
    run_limit: int,
) -> list[dict[str, Any]]:
    compiled_root = _research_root(thread_id) / "compiled"
    artifacts = list(compiled_root.glob("*.engineering-gates.json"))
    rows: list[dict[str, Any]] = []
    for artifact in artifacts:
        payload = _load_json_dict(artifact)
        if not payload:
            continue
        run_project_id, run_section_id = _resolve_compile_run_context(
            artifact_path=artifact,
            payload=payload,
        )
        if project_id and run_project_id != project_id:
            continue

        stat = artifact.stat()
        run_at = _parse_iso_datetime(payload.get("generated_at")) or datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        constraint = payload.get("constraint_violation") if isinstance(payload.get("constraint_violation"), dict) else {}
        safety = payload.get("safety_valve") if isinstance(payload.get("safety_valve"), dict) else {}
        hitl = payload.get("hitl_blocking") if isinstance(payload.get("hitl_blocking"), dict) else {}
        traceability = payload.get("traceability_coverage") if isinstance(payload.get("traceability_coverage"), dict) else {}
        delivery = payload.get("delivery_completeness") if isinstance(payload.get("delivery_completeness"), dict) else {}
        reason_distribution_raw = safety.get("reason_distribution")
        reason_distribution: dict[str, int] = {}
        if isinstance(reason_distribution_raw, dict):
            for key, value in reason_distribution_raw.items():
                reason = str(key).strip()
                if not reason:
                    continue
                try:
                    reason_distribution[reason] = int(value)
                except (TypeError, ValueError):
                    reason_distribution[reason] = 0
        rows.append(
            {
                "timestamp": run_at.isoformat(),
                "timestamp_ms": int(run_at.timestamp() * 1000),
                "project_id": run_project_id,
                "section_id": run_section_id,
                "constraint_violation_rate": _coerce_ratio(constraint.get("issues_error_ratio")),
                "constraint_marker_rate": _coerce_ratio(constraint.get("marker_sentence_ratio")),
                "safety_valve_triggered": bool(safety.get("triggered")),
                "safety_valve_reason_distribution": reason_distribution,
                "hitl_blocked": bool(hitl.get("blocked_this_run")),
                "traceability_coverage_rate": _coerce_ratio(traceability.get("full_covered_sentence_ratio")),
                "delivery_completeness_rate": _coerce_ratio(delivery.get("completeness_ratio")),
                "artifact_path": _to_virtual_path(thread_id, artifact),
            }
        )
    rows.sort(key=lambda item: int(item.get("timestamp_ms") or 0))
    if run_limit > 0 and len(rows) > run_limit:
        rows = rows[-run_limit:]
    return rows


def _collect_engineering_gate_latex_runs(
    *,
    thread_id: str,
    project_id: str | None,
    run_limit: int,
) -> list[dict[str, Any]]:
    latex_root = _outputs_dir(thread_id) / get_latex_config().artifact_subdir
    artifacts = list(latex_root.glob("*.json"))
    rows: list[dict[str, Any]] = []
    for artifact in artifacts:
        payload = _load_json_dict(artifact)
        if not payload:
            continue
        compile_status = str(payload.get("compile_status") or "").strip().lower()
        if compile_status not in {"success", "failed", "skipped"}:
            continue
        run_project_id = str(payload.get("project_id") or "").strip() or None
        if project_id and run_project_id != project_id:
            continue
        warning = str(payload.get("warning") or "").strip() or None
        failure_type = compile_status
        if compile_status == "failed":
            failure_type = _classify_latex_failure(
                compile_status=compile_status,
                warning=warning,
                compile_log_text="",
            )
        stat = artifact.stat()
        run_at = _parse_iso_datetime(payload.get("generated_at")) or datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        rows.append(
            {
                "timestamp": run_at.isoformat(),
                "timestamp_ms": int(run_at.timestamp() * 1000),
                "project_id": run_project_id,
                "compile_status": compile_status,
                "failure_type": failure_type,
                "engine_requested": str(payload.get("engine_requested") or "auto"),
                "warning": warning,
                "artifact_path": _to_virtual_path(thread_id, artifact),
            }
        )
    rows.sort(key=lambda item: int(item.get("timestamp_ms") or 0))
    if run_limit > 0 and len(rows) > run_limit:
        rows = rows[-run_limit:]
    return rows


def _build_engineering_gate_alerts(
    *,
    compile_summary: dict[str, Any],
    latex_summary: dict[str, Any],
    thresholds: dict[str, float],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []

    def _add_max_alert(metric_id: str, label: str, actual: float, threshold: float) -> None:
        if actual <= threshold:
            return
        severity = "critical" if actual > (threshold * 1.25) else "warn"
        alerts.append(
            {
                "metric_id": metric_id,
                "label": label,
                "severity": severity,
                "comparator": "<=",
                "threshold": threshold,
                "actual": actual,
                "message": f"{label} {round(actual * 100, 2)}% 超出阈值 {round(threshold * 100, 2)}%",
            }
        )

    def _add_min_alert(metric_id: str, label: str, actual: float, threshold: float) -> None:
        if actual >= threshold:
            return
        severity = "critical" if actual < (threshold * 0.9) else "warn"
        alerts.append(
            {
                "metric_id": metric_id,
                "label": label,
                "severity": severity,
                "comparator": ">=",
                "threshold": threshold,
                "actual": actual,
                "message": f"{label} {round(actual * 100, 2)}% 低于阈值 {round(threshold * 100, 2)}%",
            }
        )

    _add_max_alert(
        "constraint_violation_rate",
        "约束违规率",
        _coerce_ratio(compile_summary.get("avg_constraint_violation_rate")),
        _coerce_ratio(thresholds.get("max_constraint_violation_rate")),
    )
    _add_max_alert(
        "safety_valve_trigger_rate",
        "安全阀触发率",
        _coerce_ratio(compile_summary.get("safety_valve_trigger_rate")),
        _coerce_ratio(thresholds.get("max_safety_valve_trigger_rate")),
    )
    _add_max_alert(
        "hitl_block_rate",
        "HITL 阻断率",
        _coerce_ratio(compile_summary.get("hitl_block_rate")),
        _coerce_ratio(thresholds.get("max_hitl_block_rate")),
    )
    _add_min_alert(
        "traceability_coverage_rate",
        "可追溯覆盖率",
        _coerce_ratio(compile_summary.get("avg_traceability_coverage_rate")),
        _coerce_ratio(thresholds.get("min_traceability_coverage_rate")),
    )
    _add_min_alert(
        "delivery_completeness_rate",
        "交付完整性",
        _coerce_ratio(compile_summary.get("avg_delivery_completeness_rate")),
        _coerce_ratio(thresholds.get("min_delivery_completeness_rate")),
    )

    latex_run_count = int(latex_summary.get("run_count") or 0)
    if latex_run_count > 0:
        _add_min_alert(
            "latex_success_rate",
            "LaTeX 成功率",
            _coerce_ratio(latex_summary.get("success_rate")),
            _coerce_ratio(thresholds.get("min_latex_success_rate")),
        )
    return alerts


def get_engineering_gates_metrics(
    thread_id: str,
    *,
    project_id: str | None = None,
    run_limit: int = 60,
    max_constraint_violation_rate: float = 0.2,
    max_safety_valve_trigger_rate: float = 0.4,
    max_hitl_block_rate: float = 0.35,
    min_traceability_coverage_rate: float = 0.8,
    min_delivery_completeness_rate: float = 1.0,
    min_latex_success_rate: float = 0.75,
) -> dict[str, Any]:
    normalized_project_id = (project_id or "").strip() or None
    normalized_limit = max(10, min(int(run_limit), 500))
    thresholds = {
        "max_constraint_violation_rate": _coerce_ratio(max_constraint_violation_rate),
        "max_safety_valve_trigger_rate": _coerce_ratio(max_safety_valve_trigger_rate),
        "max_hitl_block_rate": _coerce_ratio(max_hitl_block_rate),
        "min_traceability_coverage_rate": _coerce_ratio(min_traceability_coverage_rate),
        "min_delivery_completeness_rate": _coerce_ratio(min_delivery_completeness_rate),
        "min_latex_success_rate": _coerce_ratio(min_latex_success_rate),
    }
    compile_runs = _collect_engineering_gate_compile_runs(
        thread_id=thread_id,
        project_id=normalized_project_id,
        run_limit=normalized_limit,
    )
    latex_runs = _collect_engineering_gate_latex_runs(
        thread_id=thread_id,
        project_id=normalized_project_id,
        run_limit=normalized_limit,
    )

    compile_reason_counter: Counter[str] = Counter()
    constraint_violation_values: list[float] = []
    constraint_marker_values: list[float] = []
    traceability_values: list[float] = []
    delivery_values: list[float] = []
    safety_trigger_count = 0
    hitl_block_count = 0
    for row in compile_runs:
        constraint_violation_values.append(_coerce_ratio(row.get("constraint_violation_rate")))
        constraint_marker_values.append(_coerce_ratio(row.get("constraint_marker_rate")))
        traceability_values.append(_coerce_ratio(row.get("traceability_coverage_rate")))
        delivery_values.append(_coerce_ratio(row.get("delivery_completeness_rate")))
        if bool(row.get("safety_valve_triggered")):
            safety_trigger_count += 1
        if bool(row.get("hitl_blocked")):
            hitl_block_count += 1
        dist = row.get("safety_valve_reason_distribution")
        if isinstance(dist, dict):
            for key, value in dist.items():
                reason = str(key).strip()
                if not reason:
                    continue
                compile_reason_counter[reason] += max(int(value or 0), 0)

    compile_run_count = len(compile_runs)
    compile_summary = {
        "run_count": compile_run_count,
        "safety_valve_triggered_count": safety_trigger_count,
        "safety_valve_trigger_rate": _safe_ratio(safety_trigger_count, compile_run_count),
        "hitl_blocked_count": hitl_block_count,
        "hitl_block_rate": _safe_ratio(hitl_block_count, compile_run_count),
        "avg_constraint_violation_rate": _safe_mean(constraint_violation_values),
        "avg_constraint_marker_rate": _safe_mean(constraint_marker_values),
        "avg_traceability_coverage_rate": _safe_mean(traceability_values),
        "avg_delivery_completeness_rate": _safe_mean(delivery_values),
        "safety_valve_reason_distribution": dict(compile_reason_counter),
        "latest": compile_runs[-1] if compile_runs else None,
    }

    latex_run_count = len(latex_runs)
    latex_success_count = sum(1 for row in latex_runs if row.get("compile_status") == "success")
    latex_failed_count = sum(1 for row in latex_runs if row.get("compile_status") == "failed")
    latex_skipped_count = sum(1 for row in latex_runs if row.get("compile_status") == "skipped")
    latex_failure_counter: Counter[str] = Counter()
    for row in latex_runs:
        failure_type = str(row.get("failure_type") or "").strip()
        if failure_type and row.get("compile_status") == "failed":
            latex_failure_counter[failure_type] += 1
    latex_summary = {
        "run_count": latex_run_count,
        "success_count": latex_success_count,
        "failed_count": latex_failed_count,
        "skipped_count": latex_skipped_count,
        "success_rate": _safe_ratio(latex_success_count, latex_run_count),
        "failure_type_distribution": dict(latex_failure_counter),
        "latest": latex_runs[-1] if latex_runs else None,
    }

    compile_gate_counters_path = _metrics_path(thread_id, "compile-gates")
    latex_gate_counters_path = _metrics_path(thread_id, "latex-gates")
    compile_gate_counters = _load_json_dict(compile_gate_counters_path) if compile_gate_counters_path.exists() else {}
    latex_gate_counters = _load_json_dict(latex_gate_counters_path) if latex_gate_counters_path.exists() else {}

    alerts = _build_engineering_gate_alerts(
        compile_summary=compile_summary,
        latex_summary=latex_summary,
        thresholds=thresholds,
    )

    payload = {
        "metrics_schema_version": ENGINEERING_GATES_RUNTIME_METRICS_SCHEMA_VERSION,
        "thread_id": thread_id,
        "project_id": normalized_project_id,
        "run_limit": normalized_limit,
        "updated_at": _now_iso(),
        "compile_runs": compile_runs,
        "latex_runs": latex_runs,
        "compile_summary": compile_summary,
        "latex_summary": latex_summary,
        "thresholds": thresholds,
        "alerts": alerts,
        "status": "pass" if len(alerts) == 0 else "warn",
        "counters": {
            "compile_gate_counters": compile_gate_counters,
            "latex_gate_counters": latex_gate_counters,
        },
        "artifacts": {
            "compile_gate_counters_artifact_path": (
                _to_virtual_path(thread_id, compile_gate_counters_path)
                if compile_gate_counters_path.exists()
                else None
            ),
            "latex_gate_counters_artifact_path": (
                _to_virtual_path(thread_id, latex_gate_counters_path)
                if latex_gate_counters_path.exists()
                else None
            ),
        },
    }
    _inject_prompt_pack_fields(payload)
    return payload


def _classify_hypothesis_validation_status(candidate: Any) -> str:
    supporting = len(getattr(candidate, "supporting_evidence_ids", []) or [])
    contradicting = len(getattr(candidate, "contradicting_evidence_ids", []) or [])
    score = float(getattr(getattr(candidate, "score", None), "overall", 0.0) or 0.0)
    if contradicting > supporting:
        return "failed"
    if contradicting >= 2 and score < 0.6:
        return "failed"
    if supporting >= 2 and contradicting == 0 and score >= 0.75:
        return "supported"
    if score <= 0.35:
        return "failed"
    return "inconclusive"


def generate_project_hypotheses(
    thread_id: str,
    *,
    project_id: str,
    section_id: str | None = None,
    max_hypotheses: int = 5,
) -> dict[str, Any]:
    """Generate hypothesis bundle for project-level or section-level evidence."""
    project = _project_store(thread_id).get_project(project_id)
    if project is None:
        raise ValueError(f"Project '{project_id}' not found")

    section: SectionDraft | None = None
    if section_id:
        section = next((item for item in project.sections if item.section_id == section_id), None)
        if section is None:
            raise ValueError(f"Section '{section_id}' not found in project '{project_id}'")

    bundle = generate_hypotheses(
        evidence_store=_evidence_store(thread_id),
        citation_registry=_citation_registry(thread_id),
        source_of_truth_store=_source_of_truth_store(thread_id),
        focus_evidence_ids=section.evidence_ids if section else None,
        focus_fact_ids=section.fact_ids if section else None,
        max_hypotheses=max_hypotheses,
    )
    artifact_name = f"hypothesis-{project_id}" + (f"-{section_id}" if section_id else "")
    artifact_path = _research_root(thread_id) / "hypotheses" / f"{artifact_name}.json"
    payload = {
        "project_id": project_id,
        "section_id": section_id,
        "feature_summary": bundle.feature_summary,
        "hypotheses": [item.model_dump() for item in bundle.hypotheses],
        "synthesis_paragraph": bundle.synthesis_paragraph,
    }
    historical_hypothesis_context: list[dict[str, Any]] = []
    historical_failed_attempts: list[dict[str, Any]] = []
    try:
        from src.agents.memory.long_horizon_store import (
            query_hypothesis_validation_memory,
            record_hypothesis_validation_result,
        )

        for candidate in bundle.hypotheses:
            record_hypothesis_validation_result(
                thread_id=thread_id,
                project_id=project_id,
                section_id=section_id,
                hypothesis_id=candidate.hypothesis_id,
                statement=candidate.statement,
                validation_status=_classify_hypothesis_validation_status(candidate),
                rationale=candidate.mechanism_rationale,
                evidence_ids=[
                    *candidate.supporting_evidence_ids,
                    *candidate.contradicting_evidence_ids,
                ],
                citation_ids=candidate.supporting_citation_ids,
                source={
                    "origin": "runtime_service.generate_project_hypotheses",
                    "confidence": candidate.confidence,
                    "score_overall": float(candidate.score.overall),
                },
            )

        query_seed = " ".join(item.statement for item in bundle.hypotheses[:2]).strip()
        if not query_seed and section is not None:
            query_seed = section.content.strip()
        if not query_seed:
            query_seed = project.title
        historical_hypothesis_context = query_hypothesis_validation_memory(
            query_seed,
            thread_id=thread_id,
            project_id=project_id,
            top_k=3,
        )
        historical_failed_attempts = [
            item
            for item in historical_hypothesis_context
            if str(item.get("validation_status") or "").strip().lower() in {"failed", "reopened"}
        ][:3]
    except Exception:
        historical_hypothesis_context = []
        historical_failed_attempts = []

    payload["historical_hypothesis_context"] = historical_hypothesis_context
    payload["historical_failed_attempts"] = historical_failed_attempts
    _dump_json(artifact_path, payload)
    return {
        **payload,
        "artifact_path": _to_virtual_path(thread_id, artifact_path),
    }


def run_agentic_research_graph(
    thread_id: str,
    *,
    project_id: str,
    section_id: str | None = None,
    seed_idea: str | None = None,
    max_rounds: int = 3,
) -> dict[str, Any]:
    """Run non-linear blackboard collaboration across Data Scientist / Experiment Designer / Writer."""
    project = _project_store(thread_id).get_project(project_id)
    if project is None:
        raise ValueError(f"Project '{project_id}' not found")

    section: SectionDraft | None = None
    if section_id:
        section = next((item for item in project.sections if item.section_id == section_id), None)
        if section is None:
            raise ValueError(f"Section '{section_id}' not found in project '{project_id}'")

    evidence_store = _evidence_store(thread_id)
    if section is not None:
        evidence_units = [evidence_store.get(eid) for eid in section.evidence_ids]
        evidence_units = [item for item in evidence_units if item is not None]
    else:
        evidence_units = evidence_store.list()

    historical_failed_attempts: list[dict[str, Any]] = []
    try:
        from src.agents.memory.long_horizon_store import query_hypothesis_validation_memory

        query = str(seed_idea or "").strip()
        if not query and section is not None:
            query = section.content.strip()
        if not query:
            query = " ".join(project.research_questions).strip() or project.title

        hits = query_hypothesis_validation_memory(
            query,
            thread_id=thread_id,
            project_id=project_id,
            top_k=3,
            include_statuses=["failed", "reopened"],
        )
        historical_failed_attempts = [item for item in hits if isinstance(item, dict)][:3]
    except Exception:
        historical_failed_attempts = []

    payload = run_agentic_blackboard_graph(
        project=project,
        section=section,
        evidence_units=evidence_units,
        historical_failed_attempts=historical_failed_attempts,
        max_rounds=max_rounds,
        seed_idea=seed_idea,
    )
    payload["schema_version"] = AGENTIC_GRAPH_SCHEMA_VERSION
    _inject_prompt_pack_fields(payload)
    artifact_name = f"agentic-graph-{project_id}" + (f"-{section_id}" if section_id else "")
    artifact_path = _research_root(thread_id) / "agentic-graph" / f"{artifact_name}.json"
    _dump_json(artifact_path, payload)
    payload["artifact_path"] = _to_virtual_path(thread_id, artifact_path)
    return payload


def get_project_hitl_decisions(
    thread_id: str,
    *,
    project_id: str,
    section_id: str | None = None,
) -> dict[str, Any]:
    """Read HITL action decisions persisted under project.metadata."""
    project = _project_store(thread_id).get_project(project_id)
    if project is None:
        raise ValueError(f"Project '{project_id}' not found")

    decision_map = _load_hitl_decision_map(project)
    decisions = list(decision_map.values())
    if section_id is not None:
        decisions = [item for item in decisions if item.section_id == section_id]
    decisions.sort(key=lambda item: ((item.updated_at or ""), item.action_id), reverse=True)

    metadata = project.metadata if isinstance(project.metadata, dict) else {}
    hitl_raw = metadata.get("hitl_decisions", {})
    updated_at = hitl_raw.get("updated_at") if isinstance(hitl_raw, dict) else None
    checkpoints = _resolve_key_hitl_checkpoints(project, section_id=section_id)
    impact_preview = _build_hitl_impact_preview(checkpoints)
    policy_snapshot_payload = _build_policy_snapshot(project=project, section_id=section_id)
    policy_artifact_path = _policy_snapshot_path(thread_id, project_id, section_id)
    _dump_json(policy_artifact_path, policy_snapshot_payload)
    return {
        "project_id": project_id,
        "section_id": section_id,
        "decisions": [item.model_dump() for item in decisions],
        "total_count": len(decisions),
        "updated_at": updated_at,
        "impact_preview": impact_preview,
        "policy_snapshot": policy_snapshot_payload.get("policy") or {},
        "writing_directives": policy_snapshot_payload.get("writing_directives") or [],
        "policy_snapshot_artifact_path": _to_virtual_path(thread_id, policy_artifact_path),
    }


def upsert_project_hitl_decisions(
    thread_id: str,
    *,
    project_id: str,
    decisions: list[HitlDecision],
    section_id: str | None = None,
) -> dict[str, Any]:
    """Merge HITL decisions into project.metadata.hitl_decisions."""
    store = _project_store(thread_id)
    project = store.get_project(project_id)
    if project is None:
        raise ValueError(f"Project '{project_id}' not found")

    decision_map = _load_hitl_decision_map(project)
    now = _now_iso()
    for incoming in decisions:
        normalized_section = section_id if section_id is not None else incoming.section_id
        normalized = HitlDecision(
            action_id=incoming.action_id,
            source=incoming.source,
            label=incoming.label,
            decision=incoming.decision,
            section_id=normalized_section,
            updated_at=incoming.updated_at or now,
            metadata=incoming.metadata,
        )
        decision_map[_hitl_key(normalized.action_id, normalized.section_id)] = normalized

    hitl_metadata = _serialize_hitl_metadata(decision_map)
    hitl_metadata["updated_at"] = now
    base_metadata = project.metadata if isinstance(project.metadata, dict) else {}
    project.metadata = {
        **base_metadata,
        "hitl_decisions": hitl_metadata,
    }
    store.upsert_project(project)

    artifact_dir = _research_root(thread_id) / "hitl"
    artifact_path = artifact_dir / f"hitl-decisions-{project_id}.json"
    _dump_json(artifact_path, hitl_metadata)
    policy_snapshot_payload = _build_policy_snapshot(project=project, section_id=section_id)
    policy_artifact_path = _policy_snapshot_path(thread_id, project_id, section_id)
    _dump_json(policy_artifact_path, policy_snapshot_payload)
    result = get_project_hitl_decisions(thread_id, project_id=project_id, section_id=section_id)
    result["artifact_path"] = _to_virtual_path(thread_id, artifact_path)
    result["policy_snapshot"] = policy_snapshot_payload.get("policy") or {}
    result["writing_directives"] = policy_snapshot_payload.get("writing_directives") or []
    result["policy_snapshot_artifact_path"] = _to_virtual_path(thread_id, policy_artifact_path)
    return result


def get_project_policy_snapshot(
    thread_id: str,
    *,
    project_id: str,
    section_id: str | None = None,
) -> dict[str, Any]:
    """Compute policy-learning snapshot from persisted HITL decisions."""
    project = _project_store(thread_id).get_project(project_id)
    if project is None:
        raise ValueError(f"Project '{project_id}' not found")
    payload = _build_policy_snapshot(project=project, section_id=section_id)
    artifact_path = _policy_snapshot_path(thread_id, project_id, section_id)
    _dump_json(artifact_path, payload)
    return {
        "project_id": project_id,
        "section_id": section_id,
        "policy_snapshot": payload.get("policy") or {},
        "writing_directives": payload.get("writing_directives") or [],
        "artifact_path": _to_virtual_path(thread_id, artifact_path),
    }


def evaluate_academic_case(case: AcademicEvalCase) -> dict[str, Any]:
    result = evaluate_case(case)
    return result.model_dump()


def evaluate_academic_cases(cases: list[AcademicEvalCase]) -> AcademicEvalSummary:
    return evaluate_dataset(cases)


def _load_weekly_leaderboard(thread_id: str) -> WeeklyLeaderboard | None:
    payload = _load_json_dict(_leaderboard_path(thread_id))
    if not payload:
        return None
    try:
        return WeeklyLeaderboard.model_validate(payload)
    except Exception:
        return None


def get_weekly_academic_leaderboard(thread_id: str) -> dict[str, Any]:
    """Get weekly leaderboard snapshots grouped by discipline/venue."""
    leaderboard = _load_weekly_leaderboard(thread_id)
    if leaderboard is None:
        empty = WeeklyLeaderboard(updated_at=_now_iso(), buckets=[])
        artifact_path = _leaderboard_path(thread_id)
        _dump_json(artifact_path, empty.model_dump())
        return {
            "schema_version": LEADERBOARD_SCHEMA_VERSION,
            "leaderboard_schema_version": LEADERBOARD_SCHEMA_VERSION,
            "cadence": "weekly",
            "updated_at": empty.updated_at,
            "buckets": [],
            "artifact_path": _to_virtual_path(thread_id, artifact_path),
        }
    return {
        **leaderboard.model_dump(),
        "leaderboard_schema_version": LEADERBOARD_SCHEMA_VERSION,
        "artifact_path": _to_virtual_path(thread_id, _leaderboard_path(thread_id)),
    }


def evaluate_academic_and_persist(
    thread_id: str,
    *,
    cases: list[AcademicEvalCase],
    name: str = "academic-eval",
    model_label: str = "deerflow-runtime",
    dataset_name: str | None = None,
) -> dict[str, Any]:
    summary = evaluate_dataset(cases)
    summary_payload = summary.model_dump()
    _inject_prompt_pack_fields(summary_payload)
    artifact_path = _research_root(thread_id) / "evals" / f"{name}.json"
    _dump_json(artifact_path, summary_payload)
    artifact_virtual_path = _to_virtual_path(thread_id, artifact_path)
    case_result_lookup = {row.case_id: row for row in summary.results}
    gate_cfg = get_failure_mode_gate_config()
    gate_thresholds = FailureModeThresholds(
        citation_fidelity_max=gate_cfg.citation_fidelity_max,
        overclaim_claim_grounding_max=gate_cfg.overclaim_claim_grounding_max,
        numeric_drift_abstract_body_max=gate_cfg.numeric_drift_abstract_body_max,
        evidence_chain_claim_grounding_max=gate_cfg.evidence_chain_claim_grounding_max,
        style_mismatch_venue_fit_max=gate_cfg.style_mismatch_venue_fit_max,
        superficial_rebuttal_completeness_max=gate_cfg.superficial_rebuttal_completeness_max,
        min_target_recall=gate_cfg.min_target_recall,
        max_control_false_positive_rate=gate_cfg.max_control_false_positive_rate,
    )
    failure_mode_report = evaluate_failure_mode_library(
        cases,
        case_results=case_result_lookup,
        thresholds=gate_thresholds,
    )
    _inject_prompt_pack_fields(failure_mode_report)
    failure_mode_artifact_path = _research_root(thread_id) / "evals" / f"{name}.failure-modes.json"
    _dump_json(failure_mode_artifact_path, failure_mode_report)
    failed_modes_raw = failure_mode_report.get("failed_modes")
    failed_modes = [str(item) for item in failed_modes_raw] if isinstance(failed_modes_raw, list) else []
    by_mode = failure_mode_report.get("by_mode")
    failure_mode_targeted_case_count = int(failure_mode_report.get("targeted_case_count") or 0)
    failure_mode_control_case_count = int(failure_mode_report.get("control_case_count") or 0)

    weekly_entries = build_weekly_entries(
        cases=cases,
        summary=summary,
        model_label=model_label,
        run_name=name,
        artifact_path=artifact_virtual_path,
        dataset_name=dataset_name,
    )
    leaderboard = merge_weekly_leaderboard(
        existing=_load_weekly_leaderboard(thread_id),
        new_entries=weekly_entries,
    )
    leaderboard_path = _leaderboard_path(thread_id)
    _dump_json(leaderboard_path, leaderboard.model_dump())
    return {
        **summary_payload,
        "artifact_path": artifact_virtual_path,
        "failure_mode_gate_status": str(failure_mode_report.get("status") or "pass"),
        "failure_mode_gate_failed_modes": failed_modes,
        "failure_mode_gate_schema_version": FAILURE_MODE_GATES_SCHEMA_VERSION,
        "failure_mode_gate_targeted_case_count": failure_mode_targeted_case_count,
        "failure_mode_gate_control_case_count": failure_mode_control_case_count,
        "failure_mode_gate_by_mode": by_mode if isinstance(by_mode, dict) else {},
        "failure_mode_gate_artifact_path": _to_virtual_path(thread_id, failure_mode_artifact_path),
        "leaderboard_artifact_path": _to_virtual_path(thread_id, leaderboard_path),
        "leaderboard_entries_updated": len(weekly_entries),
        "leaderboard_schema_version": LEADERBOARD_SCHEMA_VERSION,
    }


def import_academic_eval_dataset(
    thread_id: str,
    *,
    source_dataset_file: Path,
    source_dataset_virtual_path: str,
    dataset_name: str,
    dataset_version: str,
    benchmark_split: str | None = None,
    source_name: str | None = None,
    anonymize: bool = True,
    strict: bool = False,
    autofix: bool = False,
    autofix_level: Literal["safe", "balanced", "aggressive"] = "balanced",
) -> dict[str, Any]:
    """Import raw accept/reject records and persist normalized eval dataset + manifest."""
    raw_payload = json.loads(source_dataset_file.read_text(encoding="utf-8"))

    effective_payload = raw_payload
    autofix_report: dict[str, Any] | None = None
    if autofix:
        preprocessed = preprocess_accept_reject_payload(
            raw_payload,
            apply_autofix=True,
            autofix_level=autofix_level,
        )
        effective_payload = preprocessed["fixed_payload"]
        autofix_report = preprocessed["report"]

    validation = validate_accept_reject_payload(
        effective_payload,
        source_path_label=source_dataset_virtual_path,
    )
    if strict and int(validation.get("error_count", 0)) > 0:
        raise ValueError(
            "Raw dataset validation failed in strict mode: "
            f"{validation.get('error_count', 0)} error(s), "
            f"{validation.get('warning_count', 0)} warning(s)."
        )

    imported = import_accept_reject_payload(
        effective_payload,
        source_path_label=source_dataset_virtual_path,
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        benchmark_split=benchmark_split,
        source_name=source_name,
        anonymize=anonymize,
        strict=strict,
    )
    output_dir = _research_root(thread_id) / "evals" / "datasets"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_base = _slugify(
        f"{imported['dataset_name']}-{imported['dataset_version']}",
        default="academic-accept-reject",
    )
    dataset_path = output_dir / f"{output_base}.json"
    manifest_path = output_dir / f"{output_base}.manifest.json"
    validation_json_path = output_dir / f"{output_base}.validation.json"
    validation_markdown_path = output_dir / f"{output_base}.validation.md"
    autofix_input_path = output_dir / f"{output_base}.autofix.input.json"
    autofix_report_path = output_dir / f"{output_base}.autofix.report.json"
    autofix_markdown_path = output_dir / f"{output_base}.autofix.report.md"
    _dump_json(dataset_path, imported["dataset_payload"])
    _dump_json(manifest_path, imported["manifest_payload"])
    _dump_json(validation_json_path, validation)
    validation_markdown_path.write_text(
        render_validation_report_markdown(validation),
        encoding="utf-8",
    )
    if autofix_report is not None:
        _dump_json(autofix_input_path, effective_payload)
        _dump_json(autofix_report_path, autofix_report)
        autofix_markdown_path.write_text(
            render_autofix_report_markdown(autofix_report),
            encoding="utf-8",
        )

    return {
        "dataset_name": imported["dataset_name"],
        "dataset_version": imported["dataset_version"],
        "benchmark_split": imported["benchmark_split"],
        "source_name": imported["source_name"],
        "anonymized": imported["anonymized"],
        "imported_case_count": imported["imported_case_count"],
        "accepted_case_count": imported["accepted_case_count"],
        "rejected_case_count": imported["rejected_case_count"],
        "skipped_case_count": imported["skipped_case_count"],
        "warnings": imported["warnings"],
        "source_dataset_path": source_dataset_virtual_path,
        "dataset_path": _to_virtual_path(thread_id, dataset_path),
        "manifest_path": _to_virtual_path(thread_id, manifest_path),
        "validation_status": str(validation.get("status") or "unknown"),
        "validation_error_count": int(validation.get("error_count") or 0),
        "validation_warning_count": int(validation.get("warning_count") or 0),
        "validation_report_path": _to_virtual_path(thread_id, validation_json_path),
        "validation_markdown_path": _to_virtual_path(thread_id, validation_markdown_path),
        "autofix_applied": autofix,
        "autofix_level": autofix_level if autofix else None,
        "autofix_modified_record_count": int(
            (autofix_report or {}).get("modified_record_count") or 0
        ),
        "autofix_report_path": _to_virtual_path(thread_id, autofix_report_path)
        if autofix_report is not None
        else None,
        "autofix_markdown_path": _to_virtual_path(thread_id, autofix_markdown_path)
        if autofix_report is not None
        else None,
    }


def _init_self_play_few_shot_library(thread_id: str) -> dict[str, Any]:
    return {
        "schema_version": SELF_PLAY_FEW_SHOT_LIBRARY_SCHEMA_VERSION,
        "thread_id": thread_id,
        "updated_at": _now_iso(),
        "total_examples": 0,
        "accepted_recovery_examples": 0,
        "examples": [],
    }


def _load_self_play_few_shot_library(thread_id: str) -> dict[str, Any]:
    path = _self_play_few_shot_library_path(thread_id)
    if not path.exists():
        return _init_self_play_few_shot_library(thread_id)
    payload = _load_json_dict(path)
    if not payload:
        return _init_self_play_few_shot_library(thread_id)
    payload.setdefault("schema_version", SELF_PLAY_FEW_SHOT_LIBRARY_SCHEMA_VERSION)
    payload.setdefault("thread_id", thread_id)
    payload.setdefault("updated_at", _now_iso())
    raw_examples = payload.get("examples")
    payload["examples"] = [item for item in raw_examples if isinstance(item, dict)] if isinstance(raw_examples, list) else []
    payload["total_examples"] = int(payload.get("total_examples") or len(payload["examples"]))
    payload["accepted_recovery_examples"] = int(payload.get("accepted_recovery_examples") or 0)
    return payload


def _build_hard_negative_few_shot_rows(result: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in getattr(result, "hard_negatives", []):
        reasons = [str(reason).strip() for reason in item.reasons if str(reason).strip()]
        accepted_recovery = (
            str(item.final_decision) == "accept"
            and "initial_major_rebuttal_then_accept" in reasons
        )
        revision_focus = [str(note).strip() for note in item.recommendations if str(note).strip()][:4]
        rows.append(
            {
                "example_id": str(item.hard_negative_id),
                "episode_id": str(item.episode_id),
                "venue_name": str(item.venue_name),
                "section_id": item.section_id,
                "final_decision": str(item.final_decision),
                "round_count": int(item.round_count),
                "initial_major_issue_count": int(item.initial_major_issue_count),
                "unresolved_issue_count": int(item.unresolved_issue_count),
                "accepted_recovery": accepted_recovery,
                "trigger_reasons": reasons,
                "issue_types": [str(mode).strip() for mode in item.issue_types if str(mode).strip()],
                "revision_focus": revision_focus,
                "draft_before": str(item.original_text).strip(),
                "draft_after": str(item.final_text).strip(),
                "created_at": _now_iso(),
            }
        )
    return rows


def _upsert_self_play_few_shot_library(
    *,
    thread_id: str,
    run_name: str,
    new_rows: list[dict[str, Any]],
    max_examples: int = 120,
) -> tuple[dict[str, Any], int, Path]:
    payload = _load_self_play_few_shot_library(thread_id)
    existing = payload.get("examples")
    rows = [item for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        example_id = str(row.get("example_id") or "").strip()
        if not example_id:
            continue
        index[example_id] = row
    added = 0
    for row in new_rows:
        example_id = str(row.get("example_id") or "").strip()
        if not example_id:
            continue
        if example_id not in index:
            added += 1
        row["run_name"] = run_name
        index[example_id] = row
    merged = list(index.values())
    merged.sort(
        key=lambda row: (
            bool(row.get("accepted_recovery")),
            int(row.get("initial_major_issue_count") or 0),
            int(row.get("round_count") or 0),
            str(row.get("created_at") or ""),
        ),
        reverse=True,
    )
    if max_examples > 0:
        merged = merged[:max_examples]

    payload["updated_at"] = _now_iso()
    payload["examples"] = merged
    payload["total_examples"] = len(merged)
    payload["accepted_recovery_examples"] = sum(1 for row in merged if bool(row.get("accepted_recovery")))
    path = _self_play_few_shot_library_path(thread_id)
    _dump_json(path, payload)
    return payload, added, path


def _truncate_for_prompt(value: str, *, max_chars: int = 280) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3].rstrip()}..."


def get_writer_l3_few_shot_addendum(thread_id: str, *, top_k: int = 3) -> str | None:
    """Build dynamic L3 few-shot addendum from mined self-play trajectories."""
    payload = _load_self_play_few_shot_library(thread_id)
    examples = payload.get("examples")
    if not isinstance(examples, list) or not examples:
        return None
    rows = [item for item in examples if isinstance(item, dict)]
    rows.sort(
        key=lambda row: (
            bool(row.get("accepted_recovery")),
            int(row.get("initial_major_issue_count") or 0),
            int(row.get("round_count") or 0),
        ),
        reverse=True,
    )
    selected = rows[: max(1, int(top_k))]
    if not selected:
        return None

    lines: list[str] = []
    lines.append("[L3 Dynamic Few-shot Contract Addendum]")
    lines.append("Use the following mined hard trajectories as behavioral anchors before drafting:")
    for idx, row in enumerate(selected, start=1):
        venue = str(row.get("venue_name") or "unknown")
        section_id = str(row.get("section_id") or "unknown")
        initial_major = int(row.get("initial_major_issue_count") or 0)
        final_decision = str(row.get("final_decision") or "unknown")
        reasons = [str(item).strip() for item in (row.get("trigger_reasons") or []) if str(item).strip()]
        revision_focus = [str(item).strip() for item in (row.get("revision_focus") or []) if str(item).strip()]
        before_text = _truncate_for_prompt(str(row.get("draft_before") or ""))
        after_text = _truncate_for_prompt(str(row.get("draft_after") or ""))
        lines.append(
            f"- Example {idx} ({venue}/{section_id}): initial_major={initial_major}, final={final_decision}, reasons={reasons[:2] or ['n/a']}."
        )
        if before_text:
            lines.append(f"  - Before: {before_text}")
        if after_text:
            lines.append(f"  - After: {after_text}")
        if revision_focus:
            lines.append(f"  - Revision focus: {revision_focus[:3]}")
    lines.append("Apply the same repair pattern: soften unsupported certainty, patch evidence chain, and close reviewer-critical gaps.")
    return "\n".join(lines).strip()


def run_peer_self_play_training(
    thread_id: str,
    *,
    episodes: list[dict[str, Any]] | list[SelfPlayEpisodeInput],
    max_rounds: int = 3,
    default_venue_name: str = "NeurIPS",
    default_section_id: str | None = "discussion",
    run_name: str = "peer-self-play",
) -> dict[str, Any]:
    """Run Reviewer/Author/Area-Chair self-play and mine hard negatives."""
    parsed_episodes: list[SelfPlayEpisodeInput] = []
    for item in episodes:
        if isinstance(item, SelfPlayEpisodeInput):
            parsed_episodes.append(item)
        else:
            parsed_episodes.append(SelfPlayEpisodeInput.model_validate(item))

    result = run_self_play_training(
        episodes=parsed_episodes,
        max_rounds=max_rounds,
        default_venue_name=default_venue_name,
        default_section_id=default_section_id,
        run_name=run_name,
    )
    artifact_path = _self_play_run_path(thread_id, run_name)
    payload = {
        "schema_version": SELF_PLAY_SCHEMA_VERSION,
        "self_play_schema_version": SELF_PLAY_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        **result.model_dump(),
    }
    _dump_json(artifact_path, payload)
    hard_negative_path = artifact_path.with_name(f"{artifact_path.stem}.hard-negatives.json")
    _dump_json(
        hard_negative_path,
        {
            "schema_version": SELF_PLAY_SCHEMA_VERSION,
            "run_name": run_name,
            "generated_at": _now_iso(),
            "hard_negative_count": result.hard_negative_count,
            "hard_negative_rate": result.hard_negative_rate,
            "hard_negatives": [item.model_dump() for item in result.hard_negatives],
        },
    )
    few_shot_rows = _build_hard_negative_few_shot_rows(result)
    few_shot_library_payload, few_shot_added_count, few_shot_library_path = _upsert_self_play_few_shot_library(
        thread_id=thread_id,
        run_name=run_name,
        new_rows=few_shot_rows,
    )
    return {
        **payload,
        "artifact_path": _to_virtual_path(thread_id, artifact_path),
        "hard_negatives_artifact_path": _to_virtual_path(thread_id, hard_negative_path),
        "few_shot_examples_added": few_shot_added_count,
        "few_shot_library": few_shot_library_payload,
        "few_shot_library_artifact_path": _to_virtual_path(thread_id, few_shot_library_path),
    }


def audit_project_section_compliance(
    thread_id: str,
    *,
    project_id: str,
    section_id: str,
    manuscript_text: str | None = None,
) -> dict[str, Any]:
    """Run scientific ethics/compliance audit for one section."""
    project = _project_store(thread_id).get_project(project_id)
    if project is None:
        raise ValueError(f"Project '{project_id}' not found")
    section = next((item for item in project.sections if item.section_id == section_id), None)
    if section is None:
        raise ValueError(f"Section '{section_id}' not found in project '{project_id}'")

    text = manuscript_text if manuscript_text is not None else section.content
    report = audit_scientific_compliance(text)
    payload = {
        "schema_version": COMPLIANCE_AUDIT_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "project_id": project_id,
        "section_id": section_id,
        "report": report.model_dump(),
    }
    artifact_path = _compliance_audit_path(thread_id, project_id, section_id)
    _dump_json(artifact_path, payload)
    return {
        "project_id": project_id,
        "section_id": section_id,
        "compliance_audit": report.model_dump(),
        "artifact_path": _to_virtual_path(thread_id, artifact_path),
    }


def get_capability_catalog() -> dict[str, Any]:
    payload = capability_catalog()
    payload["catalog_schema_version"] = payload.get("schema_version")
    payload["generated_at"] = _now_iso()
    return payload


def assess_project_capabilities(
    thread_id: str,
    *,
    project_id: str,
    section_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate capability scorecards and triggerable failure modes for one project/section."""
    project = _project_store(thread_id).get_project(project_id)
    if project is None:
        raise ValueError(f"Project '{project_id}' not found")
    section = _get_section_from_project(project, section_id) if section_id else None
    if section_id and section is None:
        raise ValueError(f"Section '{section_id}' not found in project '{project_id}'")

    claim_graph = _claim_graph(thread_id)
    evidence_store = _evidence_store(thread_id)
    citation_registry = _citation_registry(thread_id)
    source_of_truth = _source_of_truth_store(thread_id)

    claims = claim_graph.list()
    evidence_units = evidence_store.list()
    citations = citation_registry.list()
    facts = source_of_truth.list_facts()
    if section is not None:
        section_claim_ids = set(section.claim_ids)
        section_evidence_ids = set(section.evidence_ids)
        section_citation_ids = set(section.citation_ids)
        section_fact_ids = set(section.fact_ids)
        claims = [item for item in claims if item.claim_id in section_claim_ids] if section_claim_ids else claims
        evidence_units = [item for item in evidence_units if item.evidence_id in section_evidence_ids] if section_evidence_ids else evidence_units
        citations = [item for item in citations if item.citation_id in section_citation_ids] if section_citation_ids else citations
        facts = [item for item in facts if item.fact_id in section_fact_ids] if section_fact_ids else facts

    hitl_decisions = list(_load_hitl_decision_map(project).values())
    section_versions = _load_section_versions(thread_id, project_id, section.section_id) if section is not None else {}
    compliance_payload: dict[str, Any] = {}
    if section is not None and section.content.strip():
        compliance_report = audit_scientific_compliance(section.content)
        compliance_payload = {
            "compliance_audit": compliance_report.model_dump(),
            "safety_valve_triggered": compliance_report.blocked_by_critical or compliance_report.risk_level == "high",
        }

    latex_payload: dict[str, Any] | None = None
    latex_dir = _research_root(thread_id) / "latex"
    if latex_dir.exists():
        candidates = sorted(
            [item for item in latex_dir.glob("*.json") if item.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            loaded = _load_json_dict(candidates[0])
            if loaded:
                latex_payload = loaded

    assessment = evaluate_capabilities(
        project=project,
        section=section,
        claims=claims,
        evidence_units=evidence_units,
        citations=citations,
        facts=facts,
        hitl_decisions=hitl_decisions,
        compliance_payload=compliance_payload,
        latex_payload=latex_payload,
        section_versions=section_versions,
    )
    payload = {
        "schema_version": CAPABILITY_ASSESSMENT_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "project_id": project_id,
        "section_id": section.section_id if section is not None else None,
        "catalog": capability_catalog(),
        "assessment": assessment,
    }
    _inject_prompt_pack_fields(payload)
    artifact_path = _capability_assessment_path(thread_id, project_id, section.section_id if section is not None else None)
    _dump_json(artifact_path, payload)
    payload["artifact_path"] = _to_virtual_path(thread_id, artifact_path)
    return payload


class ArtifactLedger:
    """Unified append-only artifact ledger shared by runtime services."""

    def __init__(self, ledger_path: Path):
        self.ledger_path = ledger_path
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        try:
            data = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def record(self, *, service: str, operation: str, artifact_path: str, metadata: dict[str, Any] | None = None) -> None:
        rows = self._load()
        rows.append(
            {
                "timestamp": _now_iso(),
                "service": service,
                "operation": operation,
                "artifact_path": artifact_path,
                "metadata": metadata or {},
            }
        )
        self.ledger_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def _artifact_ledger(thread_id: str) -> ArtifactLedger:
    return ArtifactLedger(_research_root(thread_id) / "artifact-ledger.json")


def _collect_artifact_paths(payload: Any) -> list[str]:
    out: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            if node.startswith(f"{VIRTUAL_PATH_PREFIX}/outputs/"):
                out.append(node)
            return
        if isinstance(node, dict):
            for value in node.values():
                _walk(value)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    dedup: list[str] = []
    seen: set[str] = set()
    for path in out:
        if path in seen:
            continue
        seen.add(path)
        dedup.append(path)
    return dedup


class _BaseRuntimeService:
    service_name = "runtime"

    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.ledger = _artifact_ledger(thread_id)

    def _record_payload(self, *, operation: str, payload: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
        _inject_prompt_pack_fields(payload)
        record_metadata = dict(metadata or {})
        prompt_pack = _resolve_prompt_pack_metadata()
        for key, value in prompt_pack.items():
            record_metadata.setdefault(key, value)
        prompt_registry = _build_prompt_registry_metadata(payload, prompt_pack_metadata=prompt_pack)
        for key, value in prompt_registry.items():
            record_metadata.setdefault(key, value)
        record_metadata.setdefault("prompt_registry", prompt_registry)
        for artifact_path in _collect_artifact_paths(payload):
            self.ledger.record(
                service=self.service_name,
                operation=operation,
                artifact_path=artifact_path,
                metadata=record_metadata,
            )


class IngestService(_BaseRuntimeService):
    service_name = "ingest"

    def ingest_fulltext_evidence(self, source: LiteratureSource, external_id: str, *, persist: bool = True) -> dict[str, Any]:
        payload = _ingest_fulltext_evidence_impl(self.thread_id, source, external_id, persist=persist)
        self._record_payload(
            operation="ingest_fulltext_evidence",
            payload=payload,
            metadata={"source": source, "external_id": external_id, "persist": persist},
        )
        return payload


class CompileService(_BaseRuntimeService):
    service_name = "compile"

    def compile_project_section(
        self,
        project_id: str,
        section_id: str,
        *,
        mode: CompileMode = "strict",
        auto_peer_review: bool = False,
        auto_hypothesis: bool = False,
        peer_review_max_rounds: int = 3,
        reviewer2_styles: list[Reviewer2StyleOverride] | None = None,
        peer_review_ab_variant: str | None = None,
        max_hypotheses: int = 5,
        narrative_style: NarrativeStyleOverride = "auto",
        narrative_max_templates: int | None = None,
        narrative_evidence_density: NarrativeDensityOverride | None = None,
        narrative_auto_by_section_type: bool = True,
        narrative_paragraph_tones: list[NarrativeToneOverride] | None = None,
        narrative_paragraph_evidence_densities: list[NarrativeDensityOverride] | None = None,
        journal_style_enabled: bool | None = None,
        journal_style_force_refresh: bool = False,
        journal_style_sample_size: int | None = None,
        journal_style_recent_year_window: int | None = None,
        policy_snapshot_auto_adjust_narrative: bool = True,
        narrative_self_question_rounds: int = 3,
        narrative_include_storyboard: bool = True,
    ) -> dict[str, Any]:
        payload = _compile_project_section_impl(
            self.thread_id,
            project_id,
            section_id,
            mode=mode,
            auto_peer_review=auto_peer_review,
            auto_hypothesis=auto_hypothesis,
            peer_review_max_rounds=peer_review_max_rounds,
            reviewer2_styles=reviewer2_styles,
            peer_review_ab_variant=peer_review_ab_variant,
            max_hypotheses=max_hypotheses,
            narrative_style=narrative_style,
            narrative_max_templates=narrative_max_templates,
            narrative_evidence_density=narrative_evidence_density,
            narrative_auto_by_section_type=narrative_auto_by_section_type,
            narrative_paragraph_tones=narrative_paragraph_tones,
            narrative_paragraph_evidence_densities=narrative_paragraph_evidence_densities,
            journal_style_enabled=journal_style_enabled,
            journal_style_force_refresh=journal_style_force_refresh,
            journal_style_sample_size=journal_style_sample_size,
            journal_style_recent_year_window=journal_style_recent_year_window,
            policy_snapshot_auto_adjust_narrative=policy_snapshot_auto_adjust_narrative,
            narrative_self_question_rounds=narrative_self_question_rounds,
            narrative_include_storyboard=narrative_include_storyboard,
        )
        self._record_payload(
            operation="compile_project_section",
            payload=payload,
            metadata={
                "project_id": project_id,
                "section_id": section_id,
                "mode": mode,
                "reviewer2_styles": reviewer2_styles or [],
                "peer_review_ab_variant": peer_review_ab_variant,
                "policy_snapshot_auto_adjust_narrative": policy_snapshot_auto_adjust_narrative,
                "narrative_self_question_rounds": narrative_self_question_rounds,
                "safety_valve_triggered": bool(payload.get("safety_valve_triggered")),
            },
        )
        return payload

    def plan_project_section_narrative(
        self,
        project_id: str,
        section_id: str,
        *,
        self_question_rounds: int = 3,
        include_storyboard: bool = True,
    ) -> dict[str, Any]:
        payload = _plan_project_section_narrative_impl(
            self.thread_id,
            project_id,
            section_id,
            self_question_rounds=self_question_rounds,
            include_storyboard=include_storyboard,
        )
        self._record_payload(
            operation="plan_project_section_narrative",
            payload=payload,
            metadata={
                "project_id": project_id,
                "section_id": section_id,
                "self_question_rounds": self_question_rounds,
                "include_storyboard": include_storyboard,
            },
        )
        return payload

    def list_section_versions(
        self,
        project_id: str,
        section_id: str,
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        payload = _list_section_versions_impl(
            self.thread_id,
            project_id,
            section_id,
            limit=limit,
        )
        self._record_payload(
            operation="list_section_versions",
            payload=payload,
            metadata={
                "project_id": project_id,
                "section_id": section_id,
                "limit": limit,
            },
        )
        return payload

    def rollback_section_to_version(
        self,
        project_id: str,
        section_id: str,
        *,
        version_id: str,
    ) -> dict[str, Any]:
        payload = _rollback_section_to_version_impl(
            self.thread_id,
            project_id,
            section_id,
            version_id=version_id,
        )
        self._record_payload(
            operation="rollback_section_to_version",
            payload=payload,
            metadata={
                "project_id": project_id,
                "section_id": section_id,
                "version_id": version_id,
            },
        )
        return payload

    def get_section_traceability(self, project_id: str, section_id: str) -> dict[str, Any]:
        payload = _get_section_traceability_impl(self.thread_id, project_id, section_id)
        self._record_payload(
            operation="get_section_traceability",
            payload=payload,
            metadata={
                "project_id": project_id,
                "section_id": section_id,
            },
        )
        return payload

    def get_engineering_gates_metrics(
        self,
        *,
        project_id: str | None = None,
        run_limit: int = 60,
        max_constraint_violation_rate: float = 0.2,
        max_safety_valve_trigger_rate: float = 0.4,
        max_hitl_block_rate: float = 0.35,
        min_traceability_coverage_rate: float = 0.8,
        min_delivery_completeness_rate: float = 1.0,
        min_latex_success_rate: float = 0.75,
    ) -> dict[str, Any]:
        payload = _get_engineering_gates_metrics_impl(
            self.thread_id,
            project_id=project_id,
            run_limit=run_limit,
            max_constraint_violation_rate=max_constraint_violation_rate,
            max_safety_valve_trigger_rate=max_safety_valve_trigger_rate,
            max_hitl_block_rate=max_hitl_block_rate,
            min_traceability_coverage_rate=min_traceability_coverage_rate,
            min_delivery_completeness_rate=min_delivery_completeness_rate,
            min_latex_success_rate=min_latex_success_rate,
        )
        self._record_payload(
            operation="get_engineering_gates_metrics",
            payload=payload,
            metadata={
                "project_id": project_id,
                "run_limit": run_limit,
            },
        )
        return payload

    def get_capability_catalog(self) -> dict[str, Any]:
        payload = _get_capability_catalog_impl()
        self._record_payload(operation="get_capability_catalog", payload=payload, metadata={})
        return payload

    def assess_project_capabilities(self, *, project_id: str, section_id: str | None = None) -> dict[str, Any]:
        payload = _assess_project_capabilities_impl(
            self.thread_id,
            project_id=project_id,
            section_id=section_id,
        )
        self._record_payload(
            operation="assess_project_capabilities",
            payload=payload,
            metadata={"project_id": project_id, "section_id": section_id},
        )
        return payload


class OrchestrationService(_BaseRuntimeService):
    service_name = "orchestration"

    def run_agentic_research_graph(
        self,
        *,
        project_id: str,
        section_id: str | None = None,
        seed_idea: str | None = None,
        max_rounds: int = 3,
    ) -> dict[str, Any]:
        payload = _run_agentic_research_graph_impl(
            self.thread_id,
            project_id=project_id,
            section_id=section_id,
            seed_idea=seed_idea,
            max_rounds=max_rounds,
        )
        self._record_payload(
            operation="run_agentic_research_graph",
            payload=payload,
            metadata={
                "project_id": project_id,
                "section_id": section_id,
                "max_rounds": max_rounds,
                "reroute_count": int(payload.get("reroute_count") or 0),
                "converged": bool(payload.get("converged")),
            },
        )
        return payload


class ReviewService(_BaseRuntimeService):
    service_name = "review"

    def simulate_review_and_plan(
        self,
        *,
        venue_name: str,
        manuscript_text: str,
        evidence_map: dict[str, list[str]] | None = None,
        section_map: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        payload = _simulate_review_and_plan_impl(
            self.thread_id,
            venue_name=venue_name,
            manuscript_text=manuscript_text,
            evidence_map=evidence_map,
            section_map=section_map,
        )
        self._record_payload(operation="simulate_review_and_plan", payload=payload, metadata={"venue_name": venue_name})
        return payload

    def simulate_peer_review_cycle(
        self,
        *,
        venue_name: str,
        manuscript_text: str,
        section_id: str | None = None,
        max_rounds: int = 3,
        reviewer2_styles: list[Reviewer2StyleOverride] | None = None,
        peer_review_ab_variant: str | None = None,
    ) -> dict[str, Any]:
        payload = _simulate_peer_review_cycle_impl(
            self.thread_id,
            venue_name=venue_name,
            manuscript_text=manuscript_text,
            section_id=section_id,
            max_rounds=max_rounds,
            reviewer2_styles=reviewer2_styles,
            peer_review_ab_variant=peer_review_ab_variant,
        )
        self._record_payload(
            operation="simulate_peer_review_cycle",
            payload=payload,
            metadata={
                "venue_name": venue_name,
                "section_id": section_id,
                "max_rounds": max_rounds,
                "reviewer2_styles": reviewer2_styles or [],
                "peer_review_ab_variant": peer_review_ab_variant,
            },
        )
        return payload

    def get_peer_review_ab_metrics(self) -> dict[str, Any]:
        payload = _get_peer_review_ab_metrics_impl(self.thread_id)
        self._record_payload(operation="get_peer_review_ab_metrics", payload=payload, metadata={})
        return payload

    def run_peer_self_play_training(
        self,
        *,
        episodes: list[dict[str, Any]] | list[SelfPlayEpisodeInput],
        max_rounds: int = 3,
        default_venue_name: str = "NeurIPS",
        default_section_id: str | None = "discussion",
        run_name: str = "peer-self-play",
    ) -> dict[str, Any]:
        payload = _run_peer_self_play_training_impl(
            self.thread_id,
            episodes=episodes,
            max_rounds=max_rounds,
            default_venue_name=default_venue_name,
            default_section_id=default_section_id,
            run_name=run_name,
        )
        self._record_payload(
            operation="run_peer_self_play_training",
            payload=payload,
            metadata={
                "run_name": run_name,
                "episode_count": len(episodes),
                "max_rounds": max_rounds,
            },
        )
        return payload

    def audit_project_section_compliance(
        self,
        *,
        project_id: str,
        section_id: str,
        manuscript_text: str | None = None,
    ) -> dict[str, Any]:
        payload = _audit_project_section_compliance_impl(
            self.thread_id,
            project_id=project_id,
            section_id=section_id,
            manuscript_text=manuscript_text,
        )
        self._record_payload(
            operation="audit_project_section_compliance",
            payload=payload,
            metadata={"project_id": project_id, "section_id": section_id},
        )
        return payload


class EvalService(_BaseRuntimeService):
    service_name = "eval"

    def evaluate_academic_and_persist(
        self,
        *,
        cases: list[AcademicEvalCase],
        name: str = "academic-eval",
        model_label: str = "deerflow-runtime",
        dataset_name: str | None = None,
    ) -> dict[str, Any]:
        payload = _evaluate_academic_and_persist_impl(
            self.thread_id,
            cases=cases,
            name=name,
            model_label=model_label,
            dataset_name=dataset_name,
        )
        self._record_payload(operation="evaluate_academic_and_persist", payload=payload, metadata={"name": name, "case_count": len(cases)})
        return payload

    def get_weekly_academic_leaderboard(self) -> dict[str, Any]:
        payload = _get_weekly_academic_leaderboard_impl(self.thread_id)
        self._record_payload(operation="get_weekly_academic_leaderboard", payload=payload, metadata={})
        return payload

    def import_academic_eval_dataset(
        self,
        *,
        source_dataset_file: Path,
        source_dataset_virtual_path: str,
        dataset_name: str,
        dataset_version: str,
        benchmark_split: str | None = None,
        source_name: str | None = None,
        anonymize: bool = True,
        strict: bool = False,
        autofix: bool = False,
        autofix_level: Literal["safe", "balanced", "aggressive"] = "balanced",
    ) -> dict[str, Any]:
        payload = _import_academic_eval_dataset_impl(
            self.thread_id,
            source_dataset_file=source_dataset_file,
            source_dataset_virtual_path=source_dataset_virtual_path,
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            benchmark_split=benchmark_split,
            source_name=source_name,
            anonymize=anonymize,
            strict=strict,
            autofix=autofix,
            autofix_level=autofix_level,
        )
        self._record_payload(
            operation="import_academic_eval_dataset",
            payload=payload,
            metadata={
                "dataset_name": dataset_name,
                "dataset_version": dataset_version,
                "strict": strict,
                "autofix": autofix,
            },
        )
        return payload


class LatexService(_BaseRuntimeService):
    service_name = "latex"

    def build_latex_manuscript(
        self,
        *,
        project_id: str | None = None,
        section_ids: list[str] | None = None,
        markdown_text: str | None = None,
        title: str | None = None,
        abstract_text: str | None = None,
        authors: list[str] | None = None,
        compile_pdf: bool | None = None,
        engine: LatexEngineOverride | None = None,
        output_name: str | None = None,
    ) -> dict[str, Any]:
        payload = _build_latex_manuscript_impl(
            self.thread_id,
            project_id=project_id,
            section_ids=section_ids,
            markdown_text=markdown_text,
            title=title,
            abstract_text=abstract_text,
            authors=authors,
            compile_pdf=compile_pdf,
            engine=engine,
            output_name=output_name,
        )
        self._record_payload(
            operation="build_latex_manuscript",
            payload=payload,
            metadata={
                "project_id": project_id,
                "compile_pdf": compile_pdf,
                "engine": engine,
            },
        )
        return payload


_ingest_fulltext_evidence_impl = ingest_fulltext_evidence
_compile_project_section_impl = compile_project_section
_plan_project_section_narrative_impl = plan_project_section_narrative
_list_section_versions_impl = list_section_versions
_rollback_section_to_version_impl = rollback_section_to_version
_get_section_traceability_impl = get_section_traceability
_get_engineering_gates_metrics_impl = get_engineering_gates_metrics
_simulate_review_and_plan_impl = simulate_review_and_plan
_simulate_peer_review_cycle_impl = simulate_peer_review_cycle
_get_peer_review_ab_metrics_impl = get_peer_review_ab_metrics
_run_peer_self_play_training_impl = run_peer_self_play_training
_audit_project_section_compliance_impl = audit_project_section_compliance
_evaluate_academic_and_persist_impl = evaluate_academic_and_persist
_get_weekly_academic_leaderboard_impl = get_weekly_academic_leaderboard
_import_academic_eval_dataset_impl = import_academic_eval_dataset
_build_latex_manuscript_impl = build_latex_manuscript
_run_agentic_research_graph_impl = run_agentic_research_graph
_get_capability_catalog_impl = get_capability_catalog
_assess_project_capabilities_impl = assess_project_capabilities


def ingest_fulltext_evidence(thread_id: str, source: LiteratureSource, external_id: str, *, persist: bool = True) -> dict[str, Any]:
    return IngestService(thread_id).ingest_fulltext_evidence(source, external_id, persist=persist)


def run_agentic_research_graph(
    thread_id: str,
    *,
    project_id: str,
    section_id: str | None = None,
    seed_idea: str | None = None,
    max_rounds: int = 3,
) -> dict[str, Any]:
    return OrchestrationService(thread_id).run_agentic_research_graph(
        project_id=project_id,
        section_id=section_id,
        seed_idea=seed_idea,
        max_rounds=max_rounds,
    )


def compile_project_section(
    thread_id: str,
    project_id: str,
    section_id: str,
    *,
    mode: CompileMode = "strict",
    auto_peer_review: bool = False,
    auto_hypothesis: bool = False,
    peer_review_max_rounds: int = 3,
    reviewer2_styles: list[Reviewer2StyleOverride] | None = None,
    peer_review_ab_variant: str | None = None,
    max_hypotheses: int = 5,
    narrative_style: NarrativeStyleOverride = "auto",
    narrative_max_templates: int | None = None,
    narrative_evidence_density: NarrativeDensityOverride | None = None,
    narrative_auto_by_section_type: bool = True,
    narrative_paragraph_tones: list[NarrativeToneOverride] | None = None,
    narrative_paragraph_evidence_densities: list[NarrativeDensityOverride] | None = None,
    journal_style_enabled: bool | None = None,
    journal_style_force_refresh: bool = False,
    journal_style_sample_size: int | None = None,
    journal_style_recent_year_window: int | None = None,
    policy_snapshot_auto_adjust_narrative: bool = True,
    narrative_self_question_rounds: int = 3,
    narrative_include_storyboard: bool = True,
) -> dict[str, Any]:
    return CompileService(thread_id).compile_project_section(
        project_id,
        section_id,
        mode=mode,
        auto_peer_review=auto_peer_review,
        auto_hypothesis=auto_hypothesis,
        peer_review_max_rounds=peer_review_max_rounds,
        reviewer2_styles=reviewer2_styles,
        peer_review_ab_variant=peer_review_ab_variant,
        max_hypotheses=max_hypotheses,
        narrative_style=narrative_style,
        narrative_max_templates=narrative_max_templates,
        narrative_evidence_density=narrative_evidence_density,
        narrative_auto_by_section_type=narrative_auto_by_section_type,
        narrative_paragraph_tones=narrative_paragraph_tones,
        narrative_paragraph_evidence_densities=narrative_paragraph_evidence_densities,
        journal_style_enabled=journal_style_enabled,
        journal_style_force_refresh=journal_style_force_refresh,
        journal_style_sample_size=journal_style_sample_size,
        journal_style_recent_year_window=journal_style_recent_year_window,
        policy_snapshot_auto_adjust_narrative=policy_snapshot_auto_adjust_narrative,
        narrative_self_question_rounds=narrative_self_question_rounds,
        narrative_include_storyboard=narrative_include_storyboard,
    )


def plan_project_section_narrative(
    thread_id: str,
    project_id: str,
    section_id: str,
    *,
    self_question_rounds: int = 3,
    include_storyboard: bool = True,
) -> dict[str, Any]:
    return CompileService(thread_id).plan_project_section_narrative(
        project_id,
        section_id,
        self_question_rounds=self_question_rounds,
        include_storyboard=include_storyboard,
    )


def list_section_versions(
    thread_id: str,
    project_id: str,
    section_id: str,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    return CompileService(thread_id).list_section_versions(project_id, section_id, limit=limit)


def rollback_section_to_version(
    thread_id: str,
    project_id: str,
    section_id: str,
    *,
    version_id: str,
) -> dict[str, Any]:
    return CompileService(thread_id).rollback_section_to_version(project_id, section_id, version_id=version_id)


def get_section_traceability(thread_id: str, project_id: str, section_id: str) -> dict[str, Any]:
    return CompileService(thread_id).get_section_traceability(project_id, section_id)


def get_engineering_gates_metrics(
    thread_id: str,
    *,
    project_id: str | None = None,
    run_limit: int = 60,
    max_constraint_violation_rate: float = 0.2,
    max_safety_valve_trigger_rate: float = 0.4,
    max_hitl_block_rate: float = 0.35,
    min_traceability_coverage_rate: float = 0.8,
    min_delivery_completeness_rate: float = 1.0,
    min_latex_success_rate: float = 0.75,
) -> dict[str, Any]:
    return CompileService(thread_id).get_engineering_gates_metrics(
        project_id=project_id,
        run_limit=run_limit,
        max_constraint_violation_rate=max_constraint_violation_rate,
        max_safety_valve_trigger_rate=max_safety_valve_trigger_rate,
        max_hitl_block_rate=max_hitl_block_rate,
        min_traceability_coverage_rate=min_traceability_coverage_rate,
        min_delivery_completeness_rate=min_delivery_completeness_rate,
        min_latex_success_rate=min_latex_success_rate,
    )


def get_capability_catalog(thread_id: str) -> dict[str, Any]:
    return CompileService(thread_id).get_capability_catalog()


def assess_project_capabilities(
    thread_id: str,
    *,
    project_id: str,
    section_id: str | None = None,
) -> dict[str, Any]:
    return CompileService(thread_id).assess_project_capabilities(project_id=project_id, section_id=section_id)


def simulate_review_and_plan(
    thread_id: str,
    *,
    venue_name: str,
    manuscript_text: str,
    evidence_map: dict[str, list[str]] | None = None,
    section_map: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    return ReviewService(thread_id).simulate_review_and_plan(
        venue_name=venue_name,
        manuscript_text=manuscript_text,
        evidence_map=evidence_map,
        section_map=section_map,
    )


def simulate_peer_review_cycle(
    thread_id: str,
    *,
    venue_name: str,
    manuscript_text: str,
    section_id: str | None = None,
    max_rounds: int = 3,
    reviewer2_styles: list[Reviewer2StyleOverride] | None = None,
    peer_review_ab_variant: str | None = None,
) -> dict[str, Any]:
    return ReviewService(thread_id).simulate_peer_review_cycle(
        venue_name=venue_name,
        manuscript_text=manuscript_text,
        section_id=section_id,
        max_rounds=max_rounds,
        reviewer2_styles=reviewer2_styles,
        peer_review_ab_variant=peer_review_ab_variant,
    )


def get_peer_review_ab_metrics(thread_id: str) -> dict[str, Any]:
    return ReviewService(thread_id).get_peer_review_ab_metrics()


def run_peer_self_play_training(
    thread_id: str,
    *,
    episodes: list[dict[str, Any]] | list[SelfPlayEpisodeInput],
    max_rounds: int = 3,
    default_venue_name: str = "NeurIPS",
    default_section_id: str | None = "discussion",
    run_name: str = "peer-self-play",
) -> dict[str, Any]:
    return ReviewService(thread_id).run_peer_self_play_training(
        episodes=episodes,
        max_rounds=max_rounds,
        default_venue_name=default_venue_name,
        default_section_id=default_section_id,
        run_name=run_name,
    )


def audit_project_section_compliance(
    thread_id: str,
    *,
    project_id: str,
    section_id: str,
    manuscript_text: str | None = None,
) -> dict[str, Any]:
    return ReviewService(thread_id).audit_project_section_compliance(
        project_id=project_id,
        section_id=section_id,
        manuscript_text=manuscript_text,
    )


def evaluate_academic_and_persist(
    thread_id: str,
    *,
    cases: list[AcademicEvalCase],
    name: str = "academic-eval",
    model_label: str = "deerflow-runtime",
    dataset_name: str | None = None,
) -> dict[str, Any]:
    return EvalService(thread_id).evaluate_academic_and_persist(
        cases=cases,
        name=name,
        model_label=model_label,
        dataset_name=dataset_name,
    )


def get_weekly_academic_leaderboard(thread_id: str) -> dict[str, Any]:
    return EvalService(thread_id).get_weekly_academic_leaderboard()


def import_academic_eval_dataset(
    thread_id: str,
    *,
    source_dataset_file: Path,
    source_dataset_virtual_path: str,
    dataset_name: str,
    dataset_version: str,
    benchmark_split: str | None = None,
    source_name: str | None = None,
    anonymize: bool = True,
    strict: bool = False,
    autofix: bool = False,
    autofix_level: Literal["safe", "balanced", "aggressive"] = "balanced",
) -> dict[str, Any]:
    return EvalService(thread_id).import_academic_eval_dataset(
        source_dataset_file=source_dataset_file,
        source_dataset_virtual_path=source_dataset_virtual_path,
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        benchmark_split=benchmark_split,
        source_name=source_name,
        anonymize=anonymize,
        strict=strict,
        autofix=autofix,
        autofix_level=autofix_level,
    )


def build_latex_manuscript(
    thread_id: str,
    *,
    project_id: str | None = None,
    section_ids: list[str] | None = None,
    markdown_text: str | None = None,
    title: str | None = None,
    abstract_text: str | None = None,
    authors: list[str] | None = None,
    compile_pdf: bool | None = None,
    engine: LatexEngineOverride | None = None,
    output_name: str | None = None,
) -> dict[str, Any]:
    return LatexService(thread_id).build_latex_manuscript(
        project_id=project_id,
        section_ids=section_ids,
        markdown_text=markdown_text,
        title=title,
        abstract_text=abstract_text,
        authors=authors,
        compile_pdf=compile_pdf,
        engine=engine,
        output_name=output_name,
    )
