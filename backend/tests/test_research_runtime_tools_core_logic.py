"""Core behavior tests for research runtime built-in tools."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

research_project_tool_module = importlib.import_module("src.tools.builtins.research_project_tool")
research_fulltext_tool_module = importlib.import_module("src.tools.builtins.research_fulltext_ingest_tool")
academic_eval_tool_module = importlib.import_module("src.tools.builtins.academic_eval_tool")


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(
        state={"thread_data": {"outputs_path": "/tmp/outputs"}},
        context={"thread_id": "thread-1"},
    )


def test_research_project_tool_list_projects(monkeypatch):
    monkeypatch.setattr(
        research_project_tool_module,
        "list_projects",
        lambda _thread_id: [SimpleNamespace(model_dump=lambda: {"project_id": "p1"})],
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/list-projects.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="list_projects",
        payload={},
        tool_call_id="tc-1",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/list-projects.json"]
    assert "action=list_projects" in result.update["messages"][0].content


def test_research_project_tool_simulate_peer_review_loop(monkeypatch):
    captured: dict[str, object] = {}

    def _mock_simulate_peer_review_cycle(**kwargs):
        captured.update(kwargs)
        return {
            "venue": "NeurIPS",
            "section_id": "discussion",
            "red_team_agents": ["reviewer_agent", "area_chair_agent"],
            "blue_team_agents": ["author_agent"],
            "rounds": [],
            "final_text": "revised discussion",
            "final_decision": "accept",
            "unresolved_issue_count": 0,
            "artifact_path": "/mnt/user-data/outputs/research-writing/review/peer-loop-neurips.json",
            "final_text_path": "/mnt/user-data/outputs/research-writing/review/peer-loop-neurips.md",
        }

    monkeypatch.setattr(
        research_project_tool_module,
        "simulate_peer_review_cycle",
        _mock_simulate_peer_review_cycle,
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/sim-peer-loop.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="simulate_peer_review_loop",
        payload={
            "venue_name": "NeurIPS",
            "manuscript_text": "draft",
            "reviewer2_styles": ["statistical_tyrant", "domain_traditionalist"],
            "peer_review_ab_variant": "auto",
        },
        tool_call_id="tc-10",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/sim-peer-loop.json"]
    assert "action=simulate_peer_review_loop" in result.update["messages"][0].content
    assert captured["reviewer2_styles"] == ["statistical_tyrant", "domain_traditionalist"]
    assert captured["peer_review_ab_variant"] == "auto"


def test_research_project_tool_generate_hypotheses(monkeypatch):
    monkeypatch.setattr(
        research_project_tool_module,
        "generate_project_hypotheses",
        lambda **_kwargs: {
            "project_id": "p1",
            "section_id": "discussion",
            "feature_summary": ["Evidence coverage: 3 units."],
            "hypotheses": [{"hypothesis_id": "H1"}],
            "synthesis_paragraph": "Top-ranked hypothesis ...",
            "artifact_path": "/mnt/user-data/outputs/research-writing/hypotheses/hypothesis-p1-discussion.json",
        },
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/hypothesis.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="generate_hypotheses",
        payload={"project_id": "p1", "section_id": "discussion"},
        tool_call_id="tc-11",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/hypothesis.json"]
    assert "action=generate_hypotheses" in result.update["messages"][0].content


def test_research_project_tool_compile_section_passes_narrative_strategy(monkeypatch):
    captured: dict[str, object] = {}

    def _mock_compile_project_section(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "section_id": "discussion",
            "compiled_text": "compiled text",
            "issues": [],
            "artifact_path": "/mnt/user-data/outputs/research-writing/compiled/p-discussion.md",
            "details_artifact_path": "/mnt/user-data/outputs/research-writing/compiled/p-discussion.json",
            "resolved_venue": "Nature",
            "narrative_strategy": {
                "tone": "conservative",
                "max_templates": 1,
                "evidence_density": "high",
                "auto_by_section_type": True,
                "section_type": "discussion",
            },
            "narrative_sentence_count": 1,
            "peer_review": None,
            "hypothesis_bundle": None,
        }

    monkeypatch.setattr(research_project_tool_module, "compile_project_section", _mock_compile_project_section)
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/compile.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="compile_section",
        payload={
            "project_id": "p1",
            "section_id": "discussion",
            "mode": "strict",
            "narrative_style": "conservative",
            "narrative_max_templates": 1,
            "narrative_evidence_density": "high",
            "narrative_auto_by_section_type": True,
            "narrative_paragraph_tones": ["conservative", "aggressive"],
            "narrative_paragraph_evidence_densities": ["medium", "high"],
            "journal_style_enabled": True,
            "journal_style_force_refresh": True,
            "journal_style_sample_size": 4,
            "journal_style_recent_year_window": 6,
            "narrative_self_question_rounds": 5,
            "narrative_include_storyboard": False,
            "reviewer2_styles": ["statistical_tyrant", "methodology_fundamentalist"],
            "peer_review_ab_variant": "A",
        },
        tool_call_id="tc-compile",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/compile.json"]
    assert captured["narrative_style"] == "conservative"
    assert captured["narrative_max_templates"] == 1
    assert captured["narrative_evidence_density"] == "high"
    assert captured["narrative_auto_by_section_type"] is True
    assert captured["narrative_paragraph_tones"] == ["conservative", "aggressive"]
    assert captured["narrative_paragraph_evidence_densities"] == ["medium", "high"]
    assert captured["journal_style_enabled"] is True
    assert captured["journal_style_force_refresh"] is True
    assert captured["journal_style_sample_size"] == 4
    assert captured["journal_style_recent_year_window"] == 6
    assert captured["narrative_self_question_rounds"] == 5
    assert captured["narrative_include_storyboard"] is False
    assert captured["reviewer2_styles"] == ["statistical_tyrant", "methodology_fundamentalist"]
    assert captured["peer_review_ab_variant"] == "A"


def test_research_project_tool_plan_narrative(monkeypatch):
    monkeypatch.setattr(
        research_project_tool_module,
        "plan_project_section_narrative",
        lambda **_kwargs: {
            "project_id": "p1",
            "section_id": "intro",
            "section_name": "Introduction",
            "planner_version": "deerflow.narrative_plan.v1",
            "takeaway_message": "Takeaway",
            "gap_statement": "Gap",
            "disruption_statement": "Disruption",
            "logical_flow": ["f1", "f2"],
            "figure_storyboard": [{"figure_id": "F1"}],
            "self_questioning": [{"round_index": 1}],
            "introduction_hook": "hook",
            "discussion_pivot": "pivot",
            "self_question_rounds": 3,
            "include_storyboard": True,
            "artifact_path": "/mnt/user-data/outputs/research-writing/narrative-plans/p1-intro.json",
        },
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/plan-narrative.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="plan_narrative",
        payload={"project_id": "p1", "section_id": "intro", "self_question_rounds": 3},
        tool_call_id="tc-plan",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/plan-narrative.json"]
    assert "action=plan_narrative" in result.update["messages"][0].content


def test_research_project_tool_run_agentic_graph(monkeypatch):
    captured: dict[str, object] = {}

    def _mock_run_agentic_research_graph(**kwargs):
        captured.update(kwargs)
        return {
            "orchestrator_version": "deerflow.agentic_graph.v1",
            "project_id": "p1",
            "section_id": "discussion",
            "seed_idea": "idea",
            "max_rounds": 3,
            "rounds_executed": 2,
            "reroute_count": 1,
            "converged": False,
            "open_gaps": ["need more evidence"],
            "proposed_actions": ["collect new cohort"],
            "final_writer_draft": "conservative draft",
            "route_trace": ["data-scientist", "experiment-designer", "writer-agent"],
            "blackboard": [{"agent": "data-scientist"}],
            "historical_failed_attempts": [],
            "agents": ["data-scientist", "experiment-designer", "writer-agent"],
            "artifact_path": "/mnt/user-data/outputs/research-writing/agentic-graph/agentic-graph-p1-discussion.json",
        }

    monkeypatch.setattr(
        research_project_tool_module,
        "run_agentic_research_graph",
        _mock_run_agentic_research_graph,
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/agentic-graph.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="run_agentic_graph",
        payload={
            "project_id": "p1",
            "section_id": "discussion",
            "seed_idea": "idea",
            "max_rounds": 3,
        },
        tool_call_id="tc-agentic",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/agentic-graph.json"]
    assert "action=run_agentic_graph" in result.update["messages"][0].content
    assert captured["project_id"] == "p1"
    assert captured["section_id"] == "discussion"
    assert captured["seed_idea"] == "idea"
    assert captured["max_rounds"] == 3


def test_research_project_tool_list_section_versions(monkeypatch):
    captured: dict[str, object] = {}

    def _mock_list_section_versions(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "version_schema_version": "deerflow.section_versions.v1",
            "project_id": "p1",
            "section_id": "discussion",
            "total_count": 2,
            "versions": [{"version_id": "discussion-v1"}, {"version_id": "discussion-v2"}],
            "artifact_path": "/mnt/user-data/outputs/research-writing/section-versions/p1-discussion.json",
        }

    monkeypatch.setattr(research_project_tool_module, "list_section_versions", _mock_list_section_versions)
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/versions.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="list_section_versions",
        payload={
            "project_id": "p1",
            "section_id": "discussion",
            "limit": 15,
        },
        tool_call_id="tc-versions",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/versions.json"]
    assert captured["limit"] == 15


def test_research_project_tool_rollback_section(monkeypatch):
    captured: dict[str, object] = {}

    def _mock_rollback_section(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "project_id": "p1",
            "section_id": "discussion",
            "rolled_back_to_version_id": "discussion-v1",
            "new_section_version": 4,
            "new_history_version_id": "discussion-v4",
            "diff": {"triplets": []},
            "section": {"section_id": "discussion", "content": "rolled back"},
            "artifact_path": "/mnt/user-data/outputs/research-writing/section-versions/rollback.json",
        }

    monkeypatch.setattr(research_project_tool_module, "rollback_section_to_version", _mock_rollback_section)
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/rollback.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="rollback_section",
        payload={
            "project_id": "p1",
            "section_id": "discussion",
            "version_id": "discussion-v1",
        },
        tool_call_id="tc-rollback",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/rollback.json"]
    assert captured["version_id"] == "discussion-v1"


def test_research_project_tool_get_section_traceability(monkeypatch):
    monkeypatch.setattr(
        research_project_tool_module,
        "get_section_traceability",
        lambda **_kwargs: {
            "trace_schema_version": "deerflow.section_trace.v1",
            "project_id": "p1",
            "section_id": "discussion",
            "sentence_links": [{"sentence_id": "s1"}],
            "claims": [],
            "evidence": [],
            "artifact_path": "/mnt/user-data/outputs/research-writing/compiled/p1-discussion.trace.json",
        },
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/trace.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="get_section_traceability",
        payload={
            "project_id": "p1",
            "section_id": "discussion",
        },
        tool_call_id="tc-trace",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/trace.json"]
    assert "action=get_section_traceability" in result.update["messages"][0].content


def test_research_project_tool_get_hitl_decisions(monkeypatch):
    monkeypatch.setattr(
        research_project_tool_module,
        "get_project_hitl_decisions",
        lambda **_kwargs: {
            "project_id": "p1",
            "section_id": "discussion",
            "decisions": [{"action_id": "peer-r1-abc", "decision": "approved"}],
            "total_count": 1,
            "updated_at": "2026-03-16T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/get-hitl.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="get_hitl_decisions",
        payload={"project_id": "p1", "section_id": "discussion"},
        tool_call_id="tc-12",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/get-hitl.json"]
    assert "action=get_hitl_decisions" in result.update["messages"][0].content


def test_research_project_tool_upsert_hitl_decisions(monkeypatch):
    monkeypatch.setattr(
        research_project_tool_module,
        "upsert_project_hitl_decisions",
        lambda **_kwargs: {
            "project_id": "p1",
            "section_id": "discussion",
            "decisions": [{"action_id": "peer-r1-abc", "decision": "approved"}],
            "total_count": 1,
            "updated_at": "2026-03-16T00:00:00Z",
            "artifact_path": "/mnt/user-data/outputs/research-writing/hitl/hitl-decisions-p1.json",
        },
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/upsert-hitl.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="upsert_hitl_decisions",
        payload={
            "project_id": "p1",
            "section_id": "discussion",
            "decisions": [
                {
                    "action_id": "peer-r1-abc",
                    "source": "Peer Loop Round 1",
                    "label": "Add ablation",
                    "decision": "approved",
                }
            ],
        },
        tool_call_id="tc-13",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/upsert-hitl.json"]
    assert "action=upsert_hitl_decisions" in result.update["messages"][0].content


def test_research_project_tool_compile_latex(monkeypatch):
    monkeypatch.setattr(
        research_project_tool_module,
        "build_latex_manuscript",
        lambda **_kwargs: {
            "project_id": "p1",
            "section_ids": ["discussion"],
            "title": "Paper",
            "source_markdown_path": "/mnt/user-data/outputs/research-writing/latex/p1.source.md",
            "tex_path": "/mnt/user-data/outputs/research-writing/latex/p1.tex",
            "pdf_path": "/mnt/user-data/outputs/research-writing/latex/p1.pdf",
            "compile_log_path": "/mnt/user-data/outputs/research-writing/latex/p1.compile.log",
            "compile_status": "success",
            "compiler": "latexmk",
            "engine_requested": "auto",
            "compile_pdf_requested": True,
            "citation_keys": ["10.1000/demo"],
            "citation_count": 1,
            "warning": None,
            "artifact_path": "/mnt/user-data/outputs/research-writing/latex/p1.tex",
            "summary_artifact_path": "/mnt/user-data/outputs/research-writing/latex/p1.json",
        },
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/latex.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="compile_latex",
        payload={
            "project_id": "p1",
            "section_ids": ["discussion"],
            "compile_pdf": True,
            "engine": "auto",
        },
        tool_call_id="tc-latex",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/latex.json"]
    assert "action=compile_latex" in result.update["messages"][0].content


def test_research_fulltext_ingest_tool_success(monkeypatch):
    monkeypatch.setattr(
        research_fulltext_tool_module,
        "ingest_fulltext_evidence",
        lambda **_kwargs: {
            "record": {"source": "arxiv", "external_id": "2501.00001"},
            "evidence_count": 3,
            "persisted_evidence_ids": ["arxiv:2501.00001:p1"],
            "artifact_path": "/mnt/user-data/outputs/research-writing/artifacts/ingest-arxiv-2501.00001.json",
        },
    )

    result = research_fulltext_tool_module.research_fulltext_ingest_tool.func(
        runtime=_runtime(),
        source="arxiv",
        external_id="2501.00001",
        persist=True,
        tool_call_id="tc-2",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/artifacts/ingest-arxiv-2501.00001.json"]
    assert "evidence_count=3" in result.update["messages"][0].content


def test_academic_eval_tool_inline_cases(monkeypatch):
    monkeypatch.setattr(
        academic_eval_tool_module,
        "evaluate_academic_and_persist",
        lambda _thread_id, cases, name: {
            "case_count": len(cases),
            "average_overall_score": 0.75,
            "average_citation_fidelity": 0.8,
            "average_claim_grounding": 0.7,
            "average_abstract_body_consistency": 0.9,
            "average_reviewer_rebuttal_completeness": 0.6,
            "average_venue_fit": 0.7,
            "average_cross_modality_synthesis": 0.8,
            "average_long_horizon_consistency": 0.75,
            "results": [],
            "artifact_path": "/mnt/user-data/outputs/research-writing/evals/eval.json",
        },
    )

    result = academic_eval_tool_module.academic_eval_tool.func(
        runtime=_runtime(),
        tool_call_id="tc-3",
        cases=[
            {
                "case_id": "c1",
                "domain": "ai_cs",
                "venue": "NeurIPS",
                "generated_citations": [],
                "verified_citations": [],
                "claims": [],
                "abstract_numbers": [],
                "body_numbers": [],
                "reviewer_comment_ids": [],
                "rebuttal_addressed_ids": [],
                "venue_checklist_items": [],
                "venue_satisfied_items": [],
                "cross_modal_items_expected": 0,
                "cross_modal_items_used": 0,
                "revision_terms": [],
                "revision_numbers": [],
            }
        ],
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/evals/eval.json"]
    assert "case_count=1" in result.update["messages"][0].content


def test_academic_eval_tool_builtin_dataset(monkeypatch):
    class _Case:
        def __init__(self, case_id: str):
            self.case_id = case_id

    monkeypatch.setattr(
        academic_eval_tool_module,
        "load_builtin_eval_cases",
        lambda _name: [_Case("c1"), _Case("c2")],
    )
    monkeypatch.setattr(
        academic_eval_tool_module,
        "evaluate_academic_and_persist",
        lambda _thread_id, cases, name: {
            "case_count": len(cases),
            "average_overall_score": 0.66,
            "average_citation_fidelity": 0.7,
            "average_claim_grounding": 0.6,
            "average_abstract_body_consistency": 0.8,
            "average_reviewer_rebuttal_completeness": 0.5,
            "average_venue_fit": 0.6,
            "average_cross_modality_synthesis": 0.7,
            "average_long_horizon_consistency": 0.68,
            "results": [],
            "artifact_path": "/mnt/user-data/outputs/research-writing/evals/eval-builtin.json",
        },
    )

    result = academic_eval_tool_module.academic_eval_tool.func(
        runtime=_runtime(),
        tool_call_id="tc-4",
        dataset_name="top_tier_accept_reject_v1",
    )

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/evals/eval-builtin.json"]
    assert "case_count=2" in result.update["messages"][0].content


def test_research_project_tool_run_self_play_training(monkeypatch):
    monkeypatch.setattr(
        research_project_tool_module,
        "run_peer_self_play_training",
        lambda **_kwargs: {
            "schema_version": "deerflow.self_play_training.v1",
            "generated_at": "2026-03-16T00:00:00Z",
            "run_name": "peer-self-play",
            "total_episodes": 1,
            "accepted_episodes": 0,
            "hard_negative_count": 1,
            "hard_negative_rate": 1.0,
            "episodes": [{"episode_id": "ep-1"}],
            "hard_negatives": [{"hard_negative_id": "hn-1"}],
            "artifact_path": "/mnt/user-data/outputs/research-writing/self-play/run.json",
            "hard_negatives_artifact_path": "/mnt/user-data/outputs/research-writing/self-play/run.hard-negatives.json",
        },
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/self-play.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="run_self_play_training",
        payload={"episodes": [{"manuscript_text": "draft"}]},
        tool_call_id="tc-self-play",
    )
    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/self-play.json"]
    assert "action=run_self_play_training" in result.update["messages"][0].content


def test_research_project_tool_audit_compliance(monkeypatch):
    monkeypatch.setattr(
        research_project_tool_module,
        "audit_project_section_compliance",
        lambda **_kwargs: {
            "project_id": "p1",
            "section_id": "discussion",
            "compliance_audit": {"risk_level": "high"},
            "artifact_path": "/mnt/user-data/outputs/research-writing/compliance/audit-p1-discussion.json",
        },
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/compliance.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="audit_compliance",
        payload={"project_id": "p1", "section_id": "discussion"},
        tool_call_id="tc-compliance",
    )
    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/compliance.json"]
    assert "action=audit_compliance" in result.update["messages"][0].content


def test_research_project_tool_get_policy_snapshot(monkeypatch):
    monkeypatch.setattr(
        research_project_tool_module,
        "get_project_policy_snapshot",
        lambda **_kwargs: {
            "project_id": "p1",
            "section_id": "discussion",
            "policy_snapshot": {"signal_count": 2},
            "artifact_path": "/mnt/user-data/outputs/research-writing/policy/policy-p1-discussion.json",
        },
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/policy.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="get_policy_snapshot",
        payload={"project_id": "p1", "section_id": "discussion"},
        tool_call_id="tc-policy",
    )
    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/policy.json"]
    assert "action=get_policy_snapshot" in result.update["messages"][0].content


def test_research_project_tool_get_academic_leaderboard(monkeypatch):
    monkeypatch.setattr(
        research_project_tool_module,
        "get_weekly_academic_leaderboard",
        lambda _thread_id: {
            "schema_version": "deerflow.academic_leaderboard.v1",
            "cadence": "weekly",
            "updated_at": "2026-03-16T00:00:00Z",
            "buckets": [{"discipline": "ai_cs", "venue": "NeurIPS", "entries": []}],
            "artifact_path": "/mnt/user-data/outputs/research-writing/evals/leaderboard/weekly.json",
        },
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/leaderboard.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="get_academic_leaderboard",
        payload={},
        tool_call_id="tc-leaderboard",
    )
    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/leaderboard.json"]
    assert "action=get_academic_leaderboard" in result.update["messages"][0].content


def test_research_project_tool_get_capability_catalog(monkeypatch):
    monkeypatch.setattr(
        research_project_tool_module,
        "get_capability_catalog",
        lambda _thread_id: {
            "catalog_schema_version": "deerflow.capability_catalog.v1",
            "generated_at": "2026-03-17T00:00:00Z",
            "capabilities": [{"capability_id": "claim_engineering"}],
        },
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/capability-catalog.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="get_capability_catalog",
        payload={},
        tool_call_id="tc-capability-catalog",
    )
    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/capability-catalog.json"]
    assert "action=get_capability_catalog" in result.update["messages"][0].content


def test_research_project_tool_assess_capabilities(monkeypatch):
    captured: dict[str, object] = {}

    def _mock_assess_project_capabilities(**kwargs):
        captured.update(kwargs)
        return {
            "schema_version": "deerflow.capability_assessment.v1",
            "generated_at": "2026-03-17T00:00:00Z",
            "project_id": "p1",
            "section_id": "discussion",
            "catalog": {"schema_version": "deerflow.capability_catalog.v1", "capabilities": []},
            "assessment": {"overall_score": 0.78, "status": "pass", "scorecards": []},
            "artifact_path": "/mnt/user-data/outputs/research-writing/capabilities/assessment-p1-discussion.json",
        }

    monkeypatch.setattr(
        research_project_tool_module,
        "assess_project_capabilities",
        _mock_assess_project_capabilities,
    )
    monkeypatch.setattr(
        research_project_tool_module,
        "_write_tool_artifact",
        lambda _thread_id, _action, _payload: "/mnt/user-data/outputs/research-writing/tool-runs/capability-assessment.json",
    )

    result = research_project_tool_module.research_project_tool.func(
        runtime=_runtime(),
        action="assess_capabilities",
        payload={"project_id": "p1", "section_id": "discussion"},
        tool_call_id="tc-capability-assessment",
    )
    assert result.update["artifacts"] == ["/mnt/user-data/outputs/research-writing/tool-runs/capability-assessment.json"]
    assert "action=assess_capabilities" in result.update["messages"][0].content
    assert captured["project_id"] == "p1"
    assert captured["section_id"] == "discussion"
