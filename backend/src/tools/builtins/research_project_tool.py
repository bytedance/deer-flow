import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.config import get_config
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from src.research_writing.citation_registry import CitationRecord
from src.research_writing.claim_graph import Claim
from src.research_writing.evidence_store import EvidenceUnit
from src.research_writing.project_state import HitlDecision, ResearchProject, SectionDraft
from src.research_writing.runtime_service import (
    assess_project_capabilities,
    audit_project_section_compliance,
    build_latex_manuscript,
    compile_project_section,
    generate_project_hypotheses,
    get_capability_catalog,
    get_project,
    get_project_hitl_decisions,
    get_project_policy_snapshot,
    get_section_traceability,
    get_weekly_academic_leaderboard,
    run_prompt_layer_optimizer,
    list_projects,
    list_section_versions,
    plan_project_section_narrative,
    rollback_section_to_version,
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

ResearchProjectAction = Literal[
    "upsert_project",
    "get_project",
    "list_projects",
    "upsert_section",
    "upsert_claim",
    "upsert_evidence",
    "upsert_citation",
    "upsert_fact",
    "plan_narrative",
    "run_agentic_graph",
    "compile_section",
    "verify_claim_map_only",
    "list_section_versions",
    "rollback_section",
    "get_section_traceability",
    "simulate_review",
    "simulate_peer_review_loop",
    "generate_hypotheses",
    "run_self_play_training",
    "audit_compliance",
    "get_hitl_decisions",
    "upsert_hitl_decisions",
    "get_policy_snapshot",
    "get_academic_leaderboard",
    "optimize_prompt_layers",
    "get_capability_catalog",
    "assess_capabilities",
    "compile_latex",
]


def _resolve_thread_id(runtime: ToolRuntime[ContextT, ThreadState]) -> str | None:
    ctx = runtime.context
    thread_id = ctx.get("thread_id") if (ctx is not None and hasattr(ctx, "get")) else None
    if thread_id:
        return thread_id
    try:
        return get_config().get("configurable", {}).get("thread_id")
    except RuntimeError:
        return None


def _write_tool_artifact(thread_id: str, action: str, payload: dict[str, Any]) -> str:
    outputs_dir = get_paths().sandbox_outputs_dir(thread_id)
    artifact_dir = outputs_dir / "research-writing" / "tool-runs"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifact_path = artifact_dir / f"{action}-{ts}.json"
    artifact_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    rel = artifact_path.resolve().relative_to(outputs_dir.resolve())
    return f"{VIRTUAL_PATH_PREFIX}/outputs/{rel.as_posix()}"


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_choice(value: Any, *, allowed: set[str], default: str | None = None) -> str | None:
    if value is None:
        return default
    candidate = str(value).strip().lower()
    if candidate in allowed:
        return candidate
    return default


def _as_choice_list(value: Any, *, allowed: set[str]) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        raw_items = [item.strip().lower() for item in value.split(",")]
    elif isinstance(value, list):
        raw_items = [str(item).strip().lower() for item in value]
    else:
        return None
    parsed = [item for item in raw_items if item in allowed]
    return parsed or None


def _as_peer_review_ab_variant(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    upper = raw.upper()
    if upper in {"A", "B"}:
        return upper
    lowered = raw.lower()
    if lowered in {"off", "none", "default"}:
        return "off"
    if lowered in {"auto", "hash", "hash_auto"}:
        return "auto"
    return None


@tool("research_project", parse_docstring=True)
def research_project_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    action: ResearchProjectAction,
    tool_call_id: Annotated[str, InjectedToolCallId],
    payload: dict[str, Any] | None = None,
) -> Command:
    """Operate structured research-writing project state.

    This tool bridges runtime conversation with `research_writing` structured models:
    project/section/claim/evidence/citation/fact upserts, section compilation, and reviewer simulation.

    Args:
        action: Operation name. One of:
            - upsert_project
            - get_project
            - list_projects
            - upsert_section
            - upsert_claim
            - upsert_evidence
            - upsert_citation
            - upsert_fact
            - plan_narrative
            - run_agentic_graph
            - compile_section
            - verify_claim_map_only
            - list_section_versions
            - rollback_section
            - get_section_traceability
            - simulate_review
            - simulate_peer_review_loop
            - generate_hypotheses
            - run_self_play_training
            - audit_compliance
            - get_hitl_decisions
            - upsert_hitl_decisions
            - get_policy_snapshot
            - get_academic_leaderboard
            - optimize_prompt_layers
            - get_capability_catalog
            - assess_capabilities
            - compile_latex
        payload: Operation payload object. Required fields vary by action.
    """
    thread_id = _resolve_thread_id(runtime)
    if not thread_id:
        return Command(update={"messages": [ToolMessage("Error: thread_id is not available in runtime context", tool_call_id=tool_call_id)]})

    payload = payload or {}
    try:
        if action == "upsert_project":
            project = ResearchProject.model_validate(payload.get("project", payload))
            result = {"project": upsert_project(thread_id, project).model_dump()}
        elif action == "get_project":
            project_id = str(payload.get("project_id") or "")
            if not project_id:
                raise ValueError("payload.project_id is required")
            project = get_project(thread_id, project_id)
            result = {"project": project.model_dump() if project else None}
        elif action == "list_projects":
            result = {"projects": [p.model_dump() for p in list_projects(thread_id)]}
        elif action == "upsert_section":
            project_id = str(payload.get("project_id") or "")
            if not project_id:
                raise ValueError("payload.project_id is required")
            section = SectionDraft.model_validate(payload.get("section", payload))
            result = {"section": upsert_section(thread_id, project_id, section).model_dump()}
        elif action == "upsert_claim":
            claim = Claim.model_validate(payload.get("claim", payload))
            result = {"claim": upsert_claim(thread_id, claim).model_dump()}
        elif action == "upsert_evidence":
            evidence = EvidenceUnit.model_validate(payload.get("evidence", payload))
            result = {"evidence": upsert_evidence(thread_id, evidence).model_dump()}
        elif action == "upsert_citation":
            citation = CitationRecord.model_validate(payload.get("citation", payload))
            result = {"citation": upsert_citation(thread_id, citation).model_dump()}
        elif action == "upsert_fact":
            fact = NumericFact.model_validate(payload.get("fact", payload))
            result = {"fact": upsert_fact(thread_id, fact).model_dump()}
        elif action == "plan_narrative":
            project_id = str(payload.get("project_id") or "")
            section_id = str(payload.get("section_id") or "")
            if not project_id or not section_id:
                raise ValueError("payload.project_id and payload.section_id are required")
            result = plan_project_section_narrative(
                thread_id=thread_id,
                project_id=project_id,
                section_id=section_id,
                self_question_rounds=_as_int(payload.get("self_question_rounds"), 3),
                include_storyboard=_as_bool(payload.get("include_storyboard"), True),
            )
        elif action == "run_agentic_graph":
            project_id = str(payload.get("project_id") or "")
            if not project_id:
                raise ValueError("payload.project_id is required")
            section_id = payload.get("section_id")
            seed_idea = payload.get("seed_idea")
            result = run_agentic_research_graph(
                thread_id=thread_id,
                project_id=project_id,
                section_id=str(section_id).strip() if section_id is not None and str(section_id).strip() else None,
                seed_idea=str(seed_idea).strip() if seed_idea is not None and str(seed_idea).strip() else None,
                max_rounds=max(1, _as_int(payload.get("max_rounds"), 3)),
            )
        elif action == "compile_section":
            project_id = str(payload.get("project_id") or "")
            section_id = str(payload.get("section_id") or "")
            mode = payload.get("mode", "strict")
            if not project_id or not section_id:
                raise ValueError("payload.project_id and payload.section_id are required")
            claim_map_json = payload.get("claim_map_json")
            claim_map_artifact_path = payload.get("claim_map_artifact_path")
            require_claim_map_submission = _as_bool(payload.get("require_claim_map_submission"), True)
            has_inline_claim_map = claim_map_json is not None and (not isinstance(claim_map_json, str) or bool(claim_map_json.strip()))
            has_claim_map_artifact = isinstance(claim_map_artifact_path, str) and bool(claim_map_artifact_path.strip())
            if require_claim_map_submission and not (has_inline_claim_map or has_claim_map_artifact):
                raise ValueError(
                    "payload.claim_map_json or payload.claim_map_artifact_path is required for compile_section. "
                    "Call plan_narrative first and submit its Claim Map JSON."
                )
            reviewer2_styles = _as_choice_list(
                payload.get("reviewer2_styles"),
                allowed={"statistical_tyrant", "methodology_fundamentalist", "domain_traditionalist"},
            )
            peer_review_ab_variant = _as_peer_review_ab_variant(payload.get("peer_review_ab_variant"))
            result = compile_project_section(
                thread_id,
                project_id,
                section_id,
                mode=mode,
                auto_peer_review=_as_bool(payload.get("auto_peer_review"), True),
                auto_hypothesis=_as_bool(payload.get("auto_hypothesis"), True),
                peer_review_max_rounds=_as_int(payload.get("peer_review_max_rounds"), 3),
                max_hypotheses=_as_int(payload.get("max_hypotheses"), 5),
                narrative_style=_as_choice(
                    payload.get("narrative_style"),
                    allowed={"auto", "conservative", "balanced", "aggressive"},
                    default="auto",
                )
                or "auto",
                narrative_max_templates=_as_int(payload.get("narrative_max_templates"), 2) if payload.get("narrative_max_templates") is not None else None,
                narrative_evidence_density=_as_choice(
                    payload.get("narrative_evidence_density"),
                    allowed={"low", "medium", "high"},
                    default=None,
                ),
                narrative_auto_by_section_type=_as_bool(payload.get("narrative_auto_by_section_type"), True),
                narrative_paragraph_tones=_as_choice_list(
                    payload.get("narrative_paragraph_tones"),
                    allowed={"conservative", "balanced", "aggressive"},
                ),
                narrative_paragraph_evidence_densities=_as_choice_list(
                    payload.get("narrative_paragraph_evidence_densities"),
                    allowed={"low", "medium", "high"},
                ),
                journal_style_enabled=payload.get("journal_style_enabled") if isinstance(payload.get("journal_style_enabled"), bool) else None,
                journal_style_force_refresh=_as_bool(payload.get("journal_style_force_refresh"), False),
                journal_style_sample_size=_as_int(payload.get("journal_style_sample_size"), 5) if payload.get("journal_style_sample_size") is not None else None,
                journal_style_recent_year_window=_as_int(payload.get("journal_style_recent_year_window"), 5)
                if payload.get("journal_style_recent_year_window") is not None
                else None,
                dynamic_retrieval_top_k=_as_int(payload.get("dynamic_retrieval_top_k"), 3)
                if payload.get("dynamic_retrieval_top_k") is not None
                else None,
                dynamic_retrieval_min_score=_as_float(payload.get("dynamic_retrieval_min_score"), 0.08)
                if payload.get("dynamic_retrieval_min_score") is not None
                else None,
                task_complexity_score=_as_float(payload.get("task_complexity_score"), 0.5)
                if payload.get("task_complexity_score") is not None
                else None,
                analysis_confidence=_as_float(payload.get("analysis_confidence"), 0.7)
                if payload.get("analysis_confidence") is not None
                else None,
                role_contract_auto_tighten=_as_bool(payload.get("role_contract_auto_tighten"), True),
                policy_snapshot_auto_adjust_narrative=_as_bool(payload.get("policy_snapshot_auto_adjust_narrative"), True),
                narrative_self_question_rounds=_as_int(payload.get("narrative_self_question_rounds"), 3),
                narrative_include_storyboard=_as_bool(payload.get("narrative_include_storyboard"), True),
                hypothesis_reasoning_mode=_as_choice(
                    payload.get("hypothesis_reasoning_mode"),
                    allowed={"tot", "got", "auto"},
                    default=None,
                ),
                min_competing_hypotheses=_as_int(payload.get("min_competing_hypotheses"), 3)
                if payload.get("min_competing_hypotheses") is not None
                else None,
                min_survivors_required=_as_int(payload.get("min_survivors_required"), 1)
                if payload.get("min_survivors_required") is not None
                else None,
                falsification_fail_close=_as_choice(
                    payload.get("falsification_fail_close"),
                    allowed={"strict", "lenient"},
                    default=None,
                ),
                reviewer2_styles=reviewer2_styles,
                peer_review_ab_variant=peer_review_ab_variant,
                claim_map_json=claim_map_json,
                claim_map_artifact_path=claim_map_artifact_path if isinstance(claim_map_artifact_path, str) else None,
                require_claim_map_submission=require_claim_map_submission,
            )
        elif action == "verify_claim_map_only":
            project_id = str(payload.get("project_id") or "")
            section_id = str(payload.get("section_id") or "")
            if not project_id or not section_id:
                raise ValueError("payload.project_id and payload.section_id are required")
            claim_map_json = payload.get("claim_map_json")
            claim_map_artifact_path = payload.get("claim_map_artifact_path")
            require_claim_map_submission = _as_bool(payload.get("require_claim_map_submission"), True)
            has_inline_claim_map = claim_map_json is not None and (not isinstance(claim_map_json, str) or bool(claim_map_json.strip()))
            has_claim_map_artifact = isinstance(claim_map_artifact_path, str) and bool(claim_map_artifact_path.strip())
            if require_claim_map_submission and not (has_inline_claim_map or has_claim_map_artifact):
                raise ValueError(
                    "payload.claim_map_json or payload.claim_map_artifact_path is required for verify_claim_map_only."
                )
            result = verify_project_section_claim_map(
                thread_id=thread_id,
                project_id=project_id,
                section_id=section_id,
                claim_map_json=claim_map_json,
                claim_map_artifact_path=claim_map_artifact_path if isinstance(claim_map_artifact_path, str) else None,
                require_claim_map_submission=require_claim_map_submission,
            )
        elif action == "list_section_versions":
            project_id = str(payload.get("project_id") or "")
            section_id = str(payload.get("section_id") or "")
            if not project_id or not section_id:
                raise ValueError("payload.project_id and payload.section_id are required")
            result = list_section_versions(
                thread_id=thread_id,
                project_id=project_id,
                section_id=section_id,
                limit=_as_int(payload.get("limit"), 20),
            )
        elif action == "rollback_section":
            project_id = str(payload.get("project_id") or "")
            section_id = str(payload.get("section_id") or "")
            version_id = str(payload.get("version_id") or "")
            if not project_id or not section_id or not version_id:
                raise ValueError("payload.project_id, payload.section_id, and payload.version_id are required")
            result = rollback_section_to_version(
                thread_id=thread_id,
                project_id=project_id,
                section_id=section_id,
                version_id=version_id,
            )
        elif action == "get_section_traceability":
            project_id = str(payload.get("project_id") or "")
            section_id = str(payload.get("section_id") or "")
            if not project_id or not section_id:
                raise ValueError("payload.project_id and payload.section_id are required")
            result = get_section_traceability(
                thread_id=thread_id,
                project_id=project_id,
                section_id=section_id,
            )
        elif action == "simulate_review":
            venue_name = str(payload.get("venue_name") or "")
            manuscript_text = str(payload.get("manuscript_text") or "")
            if not venue_name or not manuscript_text:
                raise ValueError("payload.venue_name and payload.manuscript_text are required")
            result = simulate_review_and_plan(
                thread_id=thread_id,
                venue_name=venue_name,
                manuscript_text=manuscript_text,
                evidence_map=payload.get("evidence_map"),
                section_map=payload.get("section_map"),
            )
        elif action == "simulate_peer_review_loop":
            venue_name = str(payload.get("venue_name") or "")
            manuscript_text = str(payload.get("manuscript_text") or "")
            if not venue_name or not manuscript_text:
                raise ValueError("payload.venue_name and payload.manuscript_text are required")
            reviewer2_styles = _as_choice_list(
                payload.get("reviewer2_styles"),
                allowed={"statistical_tyrant", "methodology_fundamentalist", "domain_traditionalist"},
            )
            peer_review_ab_variant = _as_peer_review_ab_variant(payload.get("peer_review_ab_variant"))
            result = simulate_peer_review_cycle(
                thread_id=thread_id,
                venue_name=venue_name,
                manuscript_text=manuscript_text,
                section_id=payload.get("section_id"),
                max_rounds=_as_int(payload.get("max_rounds"), 3),
                reviewer2_styles=reviewer2_styles,
                peer_review_ab_variant=peer_review_ab_variant,
            )
        elif action == "generate_hypotheses":
            project_id = str(payload.get("project_id") or "")
            if not project_id:
                raise ValueError("payload.project_id is required")
            section_id = payload.get("section_id")
            result = generate_project_hypotheses(
                thread_id=thread_id,
                project_id=project_id,
                section_id=str(section_id) if section_id is not None else None,
                max_hypotheses=_as_int(payload.get("max_hypotheses"), 5),
                reasoning_mode=_as_choice(
                    payload.get("reasoning_mode"),
                    allowed={"tot", "got", "auto"},
                    default=None,
                ),
                min_competing_hypotheses=_as_int(payload.get("min_competing_hypotheses"), 3)
                if payload.get("min_competing_hypotheses") is not None
                else None,
                min_survivors_required=_as_int(payload.get("min_survivors_required"), 1)
                if payload.get("min_survivors_required") is not None
                else None,
                falsification_fail_close=_as_choice(
                    payload.get("falsification_fail_close"),
                    allowed={"strict", "lenient"},
                    default=None,
                ),
            )
        elif action == "run_self_play_training":
            raw_episodes = payload.get("episodes")
            if not isinstance(raw_episodes, list) or len(raw_episodes) == 0:
                raise ValueError("payload.episodes must be a non-empty list")
            result = run_peer_self_play_training(
                thread_id=thread_id,
                episodes=raw_episodes,
                max_rounds=_as_int(payload.get("max_rounds"), 3),
                default_venue_name=str(payload.get("default_venue_name") or "NeurIPS"),
                default_section_id=str(payload.get("default_section_id")) if payload.get("default_section_id") is not None else "discussion",
                run_name=str(payload.get("run_name") or "peer-self-play"),
            )
        elif action == "audit_compliance":
            project_id = str(payload.get("project_id") or "")
            section_id = str(payload.get("section_id") or "")
            if not project_id or not section_id:
                raise ValueError("payload.project_id and payload.section_id are required")
            result = audit_project_section_compliance(
                thread_id=thread_id,
                project_id=project_id,
                section_id=section_id,
                manuscript_text=str(payload.get("manuscript_text")) if payload.get("manuscript_text") is not None else None,
            )
        elif action == "get_hitl_decisions":
            project_id = str(payload.get("project_id") or "")
            if not project_id:
                raise ValueError("payload.project_id is required")
            section_id = payload.get("section_id")
            result = get_project_hitl_decisions(
                thread_id=thread_id,
                project_id=project_id,
                section_id=str(section_id) if section_id is not None else None,
            )
        elif action == "upsert_hitl_decisions":
            project_id = str(payload.get("project_id") or "")
            if not project_id:
                raise ValueError("payload.project_id is required")
            raw_decisions = payload.get("decisions")
            if not isinstance(raw_decisions, list) or len(raw_decisions) == 0:
                raise ValueError("payload.decisions must be a non-empty list")
            decisions = [HitlDecision.model_validate(item) for item in raw_decisions]
            section_id = payload.get("section_id")
            result = upsert_project_hitl_decisions(
                thread_id=thread_id,
                project_id=project_id,
                decisions=decisions,
                section_id=str(section_id) if section_id is not None else None,
            )
        elif action == "get_policy_snapshot":
            project_id = str(payload.get("project_id") or "")
            if not project_id:
                raise ValueError("payload.project_id is required")
            section_id = payload.get("section_id")
            result = get_project_policy_snapshot(
                thread_id=thread_id,
                project_id=project_id,
                section_id=str(section_id) if section_id is not None else None,
            )
        elif action == "get_academic_leaderboard":
            result = get_weekly_academic_leaderboard(thread_id)
        elif action == "optimize_prompt_layers":
            optimizer_config = payload.get("optimizer_config")
            resolved_optimizer_config = optimizer_config if isinstance(optimizer_config, dict) else None
            if resolved_optimizer_config is None and any(
                payload.get(key) is not None for key in ("optimizer_mode", "llm_model_name", "llm_thinking_enabled", "llm_temperature")
            ):
                resolved_optimizer_config = {
                    "optimizer_mode": _as_choice(
                        payload.get("optimizer_mode"),
                        allowed={"rules", "llm_structured_patch"},
                        default="rules",
                    )
                    or "rules",
                    "model_name": str(payload.get("llm_model_name")).strip() if payload.get("llm_model_name") is not None else None,
                    "thinking_enabled": _as_bool(payload.get("llm_thinking_enabled"), False),
                    "temperature": _as_float(payload.get("llm_temperature"), 0.0),
                }
            result = run_prompt_layer_optimizer(
                thread_id=thread_id,
                compile_metrics_path=str(payload.get("compile_metrics_path")).strip()
                if payload.get("compile_metrics_path") is not None
                else None,
                offline_regression_report_path=str(payload.get("offline_regression_report_path")).strip()
                if payload.get("offline_regression_report_path") is not None
                else None,
                prompt_layers_path=str(payload.get("prompt_layers_path")).strip()
                if payload.get("prompt_layers_path") is not None
                else None,
                apply_prompt_patch=_as_bool(payload.get("apply_prompt_patch"), False),
                run_offline_validation=_as_bool(payload.get("run_offline_validation"), True),
                dataset_version=str(payload.get("dataset_version") or "optimizer-candidate"),
                optimizer_config=resolved_optimizer_config,
                optimizer_mode=_as_choice(
                    payload.get("optimizer_mode"),
                    allowed={"rules", "llm_structured_patch"},
                    default="rules",
                )
                or "rules",
                llm_model_name=str(payload.get("llm_model_name")).strip() if payload.get("llm_model_name") is not None else None,
                llm_thinking_enabled=_as_bool(payload.get("llm_thinking_enabled"), False),
                llm_temperature=_as_float(payload.get("llm_temperature"), 0.0),
            )
        elif action == "get_capability_catalog":
            result = get_capability_catalog(thread_id)
        elif action == "assess_capabilities":
            project_id = str(payload.get("project_id") or "")
            if not project_id:
                raise ValueError("payload.project_id is required")
            section_id = payload.get("section_id")
            result = assess_project_capabilities(
                thread_id=thread_id,
                project_id=project_id,
                section_id=str(section_id).strip() if section_id is not None and str(section_id).strip() else None,
            )
        elif action == "compile_latex":
            section_ids_raw = payload.get("section_ids")
            section_ids: list[str] | None = None
            if isinstance(section_ids_raw, list):
                section_ids = [str(item).strip() for item in section_ids_raw if str(item).strip()]
            authors_raw = payload.get("authors")
            authors: list[str] | None = None
            if isinstance(authors_raw, list):
                authors = [str(item).strip() for item in authors_raw if str(item).strip()]
            result = build_latex_manuscript(
                thread_id=thread_id,
                project_id=str(payload.get("project_id")).strip() if payload.get("project_id") is not None else None,
                section_ids=section_ids,
                markdown_text=str(payload.get("markdown_text")).strip() if payload.get("markdown_text") is not None else None,
                title=str(payload.get("title")).strip() if payload.get("title") is not None else None,
                abstract_text=str(payload.get("abstract_text")).strip() if payload.get("abstract_text") is not None else None,
                authors=authors,
                compile_pdf=payload.get("compile_pdf") if isinstance(payload.get("compile_pdf"), bool) else None,
                engine=_as_choice(
                    payload.get("engine"),
                    allowed={"auto", "none", "latexmk", "pdflatex", "xelatex"},
                    default=None,
                ),
                output_name=str(payload.get("output_name")).strip() if payload.get("output_name") is not None else None,
            )
        else:
            raise ValueError(f"Unsupported action: {action}")
    except Exception as exc:
        return Command(update={"messages": [ToolMessage(f"Error: research_project failed: {exc}", tool_call_id=tool_call_id)]})

    artifact_path = _write_tool_artifact(thread_id, action, result)
    message = f"research_project action={action} completed. artifact={artifact_path}"
    return Command(update={"artifacts": [artifact_path], "messages": [ToolMessage(message, tool_call_id=tool_call_id)]})
