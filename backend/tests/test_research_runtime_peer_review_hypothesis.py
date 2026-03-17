"""Integration-style tests for runtime peer-review + hypothesis flow."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from src.config.paths import Paths
from src.config.reviewer2_strategy_config import (
    Reviewer2StrategyConfig,
    get_reviewer2_strategy_config,
    set_reviewer2_strategy_config,
)
from src.evals.academic.schemas import AcademicEvalCase
from src.research_writing.claim_graph import Claim
from src.research_writing.evidence_store import EvidenceUnit
from src.research_writing.project_state import HitlDecision, ResearchProject, SectionDraft
from src.research_writing.runtime_service import (
    compile_project_section,
    evaluate_academic_and_persist,
    generate_project_hypotheses,
    get_writer_l3_few_shot_addendum,
    get_peer_review_ab_metrics,
    get_project_hitl_decisions,
    get_project_policy_snapshot,
    get_section_traceability,
    get_weekly_academic_leaderboard,
    plan_project_section_narrative,
    run_agentic_research_graph,
    run_peer_self_play_training,
    simulate_peer_review_cycle,
    upsert_claim,
    upsert_evidence,
    upsert_project,
    upsert_section,
    upsert_project_hitl_decisions,
)


def test_compile_section_auto_runs_hypothesis_and_peer_review(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths),
        patch(
            "src.research_writing.runtime_service.get_prompt_pack_metadata",
            return_value={
                "prompt_pack_id": "rw.superagent.test",
                "prompt_pack_hash": "abc123def4567890",
                "prompt_layer_schema_version": "deerflow.prompt_layers.v1",
                "prompt_layer_versions": {"L0": "v1", "L1": "v1", "L2": "v1", "L3": "v1", "L4": "v1", "L5": "v1"},
                "prompt_layer_rollbacks": {"L0": "v0", "L1": "v0", "L2": "v0", "L3": "v0", "L4": "v0", "L5": "v0"},
                "runtime_stage_recipe_schema_version": "deerflow.runtime_stage_recipe.v1",
                "runtime_stage_recipe_stages": ["ingest", "plan", "draft", "verify", "revise", "submit"],
            },
        ),
    ):
        upsert_project(
            "thread-1",
            ResearchProject(
                project_id="p1",
                title="Auto reasoning pipeline",
                discipline="ai_cs",
                target_venue="NeurIPS",
                sections=[
                    SectionDraft(
                        section_id="discussion",
                        section_name="Discussion",
                        content="We prove our method always works.",
                        claim_ids=["c1"],
                    )
                ],
            ),
        )
        upsert_claim(
            "thread-1",
            Claim(
                claim_id="c1",
                text="Our method demonstrates definitive superiority.",
                claim_type="strong",
                evidence_ids=[],
                citation_ids=[],
            ),
        )

        payload = compile_project_section(
            thread_id="thread-1",
            project_id="p1",
            section_id="discussion",
            auto_peer_review=True,
            auto_hypothesis=True,
        )

    assert payload["peer_review"] is not None
    assert payload["hypothesis_bundle"] is not None
    assert "hypothesis-driven interpretation" in payload["compiled_text"].lower()
    assert payload["artifact_path"].startswith("/mnt/user-data/outputs/research-writing/compiled/")
    assert payload["claim_map"]["schema_version"] == "deerflow.claim_map.v1"
    assert payload["claim_map"]["table_columns"] == [
        "Claim ID",
        "核心主张",
        "支撑 Data ID",
        "支撑 Citation ID",
        "局限性/Caveat",
    ]
    assert payload["claim_map"]["summary"]["total_claim_ids"] == 1
    assert "rewrite_required_claims" in payload["claim_map"]["summary"]
    assert payload["claim_map_artifact_path"].startswith("/mnt/user-data/outputs/research-writing/claim-maps/")
    assert payload["prompt_pack_id"] == "rw.superagent.test"
    assert payload["prompt_pack_hash"] == "abc123def4567890"
    assert payload["prompt_layer_schema_version"] == "deerflow.prompt_layers.v1"
    assert payload["prompt_layer_versions"]["L0"] == "v1"
    assert payload["prompt_layer_versions"]["L5"] == "v1"
    assert payload["runtime_stage_context"]["operation"] == "compile_section"
    assert isinstance(payload["prompt_layer_versions"], dict)
    assert isinstance(payload["prompt_layer_rollbacks"], dict)
    assert payload["runtime_stage_context"]["operation"] == "compile_section"
    assert "draft" in payload["runtime_stage_context"]["active_stage_ids"]
    assert "verify" in payload["runtime_stage_context"]["active_stage_ids"]
    assert payload["venue_style_adapter"]["schema_version"] == "deerflow.venue_style_adapter.v1"
    assert isinstance(payload["runtime_strategy"], dict)
    assert isinstance(payload["runtime_strategy_hash"], str)
    assert len(payload["runtime_strategy_hash"]) == 16
    assert isinstance(payload["eval_impact"], dict)
    assert isinstance(payload["eval_attribution_key"], str)
    assert len(payload["eval_attribution_key"]) == 20
    assert payload["runtime_strategy"]["narrative"]["enabled"] is True
    assert payload["runtime_strategy"]["peer_review"]["enabled"] is True
    detail_path = paths.resolve_virtual_path("thread-1", payload["details_artifact_path"])
    detail_payload = json.loads(detail_path.read_text(encoding="utf-8"))
    metadata = detail_payload.get("metadata")
    assert isinstance(metadata, dict)
    assert metadata["prompt_pack_id"] == "rw.superagent.test"
    assert metadata["prompt_pack_hash"] == "abc123def4567890"
    assert isinstance(metadata["runtime_strategy"], dict)
    assert isinstance(metadata["eval_impact"], dict)
    assert isinstance(metadata["eval_attribution_key"], str)


def test_plan_narrative_includes_claim_map_payload(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths):
        upsert_project(
            "thread-plan",
            ResearchProject(
                project_id="p-plan",
                title="Narrative planning with claim map",
                discipline="ai_cs",
                target_venue="NeurIPS",
                sections=[
                    SectionDraft(
                        section_id="intro",
                        section_name="Introduction",
                        content="Draft intro.",
                        claim_ids=["c-plan"],
                    )
                ],
            ),
        )
        upsert_claim(
            "thread-plan",
            Claim(
                claim_id="c-plan",
                text="The method improves AUROC by 3.2%.",
                claim_type="result",
                evidence_ids=[],
                citation_ids=[],
            ),
        )

        payload = plan_project_section_narrative(
            thread_id="thread-plan",
            project_id="p-plan",
            section_id="intro",
            self_question_rounds=3,
            include_storyboard=True,
        )

    assert payload["claim_map"]["schema_version"] == "deerflow.claim_map.v1"
    assert payload["claim_map"]["table_columns"][0] == "Claim ID"
    assert payload["claim_map"]["summary"]["total_claim_ids"] == 1
    assert payload["claim_map_artifact_path"].startswith("/mnt/user-data/outputs/research-writing/claim-maps/")


def test_runtime_exposes_standalone_peer_review_and_hypothesis_endpoints(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths):
        upsert_project(
            "thread-2",
            ResearchProject(
                project_id="p2",
                title="Standalone runtime APIs",
                discipline="biomed",
                target_venue="Nature",
                sections=[SectionDraft(section_id="discussion", section_name="Discussion", content="Short draft.")],
            ),
        )
        peer_payload = simulate_peer_review_cycle(
            thread_id="thread-2",
            venue_name="Nature",
            manuscript_text="Short draft without controls or limitations.",
            section_id="discussion",
            max_rounds=3,
            reviewer2_styles=["statistical_tyrant", "methodology_fundamentalist"],
        )
        hypothesis_payload = generate_project_hypotheses(
            thread_id="thread-2",
            project_id="p2",
            section_id="discussion",
            max_hypotheses=5,
        )

    assert peer_payload["final_text_path"].startswith("/mnt/user-data/outputs/research-writing/review/")
    assert "final_decision" in peer_payload
    assert peer_payload["reviewer2_styles"] == ["statistical_tyrant", "methodology_fundamentalist"]
    assert len(hypothesis_payload["hypotheses"]) == 5
    assert "historical_hypothesis_context" in hypothesis_payload
    assert "historical_failed_attempts" in hypothesis_payload
    assert hypothesis_payload["artifact_path"].startswith("/mnt/user-data/outputs/research-writing/hypotheses/")


def test_runtime_agentic_graph_blackboard_reroutes_on_gaps(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths):
        upsert_project(
            "thread-graph",
            ResearchProject(
                project_id="p-graph",
                title="Agentic graph flow",
                discipline="ai_cs",
                sections=[
                    SectionDraft(
                        section_id="discussion",
                        section_name="Discussion",
                        content="Initial short draft.",
                        evidence_ids=[],
                    )
                ],
            ),
        )
        payload = run_agentic_research_graph(
            thread_id="thread-graph",
            project_id="p-graph",
            section_id="discussion",
            seed_idea="Revisit earlier weak trend and test if it is real.",
            max_rounds=2,
        )

    assert payload["orchestrator_version"] == "deerflow.agentic_graph.v1"
    assert payload["reroute_count"] >= 1
    assert payload["rounds_executed"] >= 1
    assert payload["artifact_path"].startswith("/mnt/user-data/outputs/research-writing/agentic-graph/")
    assert any(item.get("agent") == "data-scientist" for item in payload["blackboard"])
    assert any(item.get("agent") == "experiment-designer" for item in payload["blackboard"])
    assert any(item.get("agent") == "writer-agent" for item in payload["blackboard"])


def test_peer_review_strategy_auto_selects_reviewer2_styles_by_venue(tmp_path):
    paths = Paths(base_dir=tmp_path)
    captured: dict[str, object] = {}

    def _fake_run_peer_review_loop(*, manuscript_text: str, venue_name: str, section_id: str | None, max_rounds: int, reviewer2_styles: list[str]):
        captured["venue_name"] = venue_name
        captured["section_id"] = section_id
        captured["max_rounds"] = max_rounds
        captured["reviewer2_styles"] = reviewer2_styles
        fake = SimpleNamespace(final_text=f"{manuscript_text}\n\nRevised.")
        fake.model_dump = lambda: {
            "venue": venue_name,
            "section_id": section_id,
            "reviewer2_styles": reviewer2_styles,
            "red_team_agents": ["reviewer_agent", "reviewer2_agent", "area_chair_agent"],
            "blue_team_agents": ["author_agent"],
            "rounds": [],
            "final_text": fake.final_text,
            "final_decision": "accept",
            "unresolved_issue_count": 0,
        }
        return fake

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths),
        patch("src.research_writing.runtime_service.run_peer_review_loop", side_effect=_fake_run_peer_review_loop),
    ):
        payload = simulate_peer_review_cycle(
            thread_id="thread-auto-style",
            venue_name="Nature",
            manuscript_text="Draft without explicit reviewer2 styles.",
            section_id="discussion",
            max_rounds=3,
        )

    assert captured["reviewer2_styles"] == ["methodology_fundamentalist", "domain_traditionalist"]
    assert captured["max_rounds"] == 3
    assert payload["peer_review_ab_variant"] == "off"
    assert payload["peer_review_strategy"]["style_source"] == "venue_default"
    assert payload["peer_review_strategy"]["round_source"] == "request"


def test_peer_review_strategy_ab_variant_overrides_rounds_and_style_combo(tmp_path):
    paths = Paths(base_dir=tmp_path)
    captured: dict[str, object] = {}

    def _fake_run_peer_review_loop(*, manuscript_text: str, venue_name: str, section_id: str | None, max_rounds: int, reviewer2_styles: list[str]):
        captured["max_rounds"] = max_rounds
        captured["reviewer2_styles"] = reviewer2_styles
        fake = SimpleNamespace(final_text=manuscript_text)
        fake.model_dump = lambda: {
            "venue": venue_name,
            "section_id": section_id,
            "reviewer2_styles": reviewer2_styles,
            "red_team_agents": ["reviewer_agent", "reviewer2_agent", "area_chair_agent"],
            "blue_team_agents": ["author_agent"],
            "rounds": [],
            "final_text": fake.final_text,
            "final_decision": "accept",
            "unresolved_issue_count": 0,
        }
        return fake

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths),
        patch("src.research_writing.runtime_service.run_peer_review_loop", side_effect=_fake_run_peer_review_loop),
    ):
        payload = simulate_peer_review_cycle(
            thread_id="thread-ab-switch",
            venue_name="NeurIPS",
            manuscript_text="Draft.",
            section_id="discussion",
            max_rounds=2,
            reviewer2_styles=["domain_traditionalist"],
            peer_review_ab_variant="B",
        )

    assert captured["max_rounds"] == 4
    assert captured["reviewer2_styles"] == [
        "statistical_tyrant",
        "methodology_fundamentalist",
        "domain_traditionalist",
    ]
    assert payload["peer_review_ab_variant"] == "B"
    assert payload["peer_review_strategy"]["style_source"] == "ab:B"
    assert payload["peer_review_strategy"]["round_source"] == "ab:B"


def test_peer_review_strategy_explicit_off_disables_ab_default_variant(tmp_path):
    paths = Paths(base_dir=tmp_path)
    captured: dict[str, object] = {}

    def _fake_run_peer_review_loop(*, manuscript_text: str, venue_name: str, section_id: str | None, max_rounds: int, reviewer2_styles: list[str]):
        captured["max_rounds"] = max_rounds
        captured["reviewer2_styles"] = reviewer2_styles
        fake = SimpleNamespace(final_text=manuscript_text)
        fake.model_dump = lambda: {
            "venue": venue_name,
            "section_id": section_id,
            "reviewer2_styles": reviewer2_styles,
            "red_team_agents": ["reviewer_agent", "reviewer2_agent", "area_chair_agent"],
            "blue_team_agents": ["author_agent"],
            "rounds": [],
            "final_text": fake.final_text,
            "final_decision": "accept",
            "unresolved_issue_count": 0,
        }
        return fake

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths),
        patch("src.research_writing.runtime_service.run_peer_review_loop", side_effect=_fake_run_peer_review_loop),
        patch(
            "src.research_writing.runtime_service.get_reviewer2_strategy_config",
            return_value=SimpleNamespace(
                default_styles=["statistical_tyrant", "methodology_fundamentalist"],
                venue_style_overrides={"neurips": ["statistical_tyrant", "methodology_fundamentalist"]},
                ab_enabled=True,
                ab_default_variant="A",
                ab_variant_a_max_rounds=2,
                ab_variant_a_styles=["statistical_tyrant", "methodology_fundamentalist"],
                ab_variant_b_max_rounds=4,
                ab_variant_b_styles=["statistical_tyrant", "methodology_fundamentalist", "domain_traditionalist"],
            ),
        ),
    ):
        payload = simulate_peer_review_cycle(
            thread_id="thread-ab-off",
            venue_name="NeurIPS",
            manuscript_text="Draft.",
            section_id="discussion",
            max_rounds=3,
            peer_review_ab_variant="off",
        )

    assert payload["peer_review_ab_variant"] == "off"
    assert payload["peer_review_strategy"]["round_source"] == "request"
    assert captured["max_rounds"] == 3


def test_peer_review_strategy_auto_variant_hashes_thread_into_ab_arm(tmp_path):
    paths = Paths(base_dir=tmp_path)
    captured: dict[str, object] = {}

    def _fake_run_peer_review_loop(*, manuscript_text: str, venue_name: str, section_id: str | None, max_rounds: int, reviewer2_styles: list[str]):
        captured["max_rounds"] = max_rounds
        captured["reviewer2_styles"] = reviewer2_styles
        fake = SimpleNamespace(final_text=manuscript_text)
        fake.model_dump = lambda: {
            "venue": venue_name,
            "section_id": section_id,
            "reviewer2_styles": reviewer2_styles,
            "red_team_agents": ["reviewer_agent", "reviewer2_agent", "area_chair_agent"],
            "blue_team_agents": ["author_agent"],
            "rounds": [],
            "final_text": fake.final_text,
            "final_decision": "accept",
            "unresolved_issue_count": 0,
        }
        return fake

    previous = get_reviewer2_strategy_config().model_copy(deep=True)
    try:
        set_reviewer2_strategy_config(
            Reviewer2StrategyConfig(
                ab_enabled=True,
                ab_default_variant="off",
                ab_auto_split_enabled=True,
                ab_auto_split_ratio_a=0.5,
                ab_auto_split_salt="unit-test-hash",
                ab_variant_a_max_rounds=2,
                ab_variant_a_styles=["statistical_tyrant", "methodology_fundamentalist"],
                ab_variant_b_max_rounds=4,
                ab_variant_b_styles=["statistical_tyrant", "methodology_fundamentalist", "domain_traditionalist"],
            )
        )
        with (
            patch("src.research_writing.runtime_service.get_paths", return_value=paths),
            patch("src.research_writing.runtime_service.run_peer_review_loop", side_effect=_fake_run_peer_review_loop),
        ):
            payload = simulate_peer_review_cycle(
                thread_id="thread-auto-hash",
                venue_name="NeurIPS",
                manuscript_text="Draft.",
                section_id="discussion",
                peer_review_ab_variant="auto",
            )
    finally:
        set_reviewer2_strategy_config(previous)

    assert payload["peer_review_ab_variant"] in {"A", "B"}
    assert payload["peer_review_strategy"]["auto_split_applied"] is True
    assert payload["peer_review_strategy"]["ab_variant_source"] == "request:auto"
    assert isinstance(payload["peer_review_strategy"]["thread_hash_ratio"], float)
    if payload["peer_review_ab_variant"] == "A":
        assert captured["max_rounds"] == 2
    else:
        assert captured["max_rounds"] == 4


def test_peer_review_ab_metrics_aggregate_across_variants(tmp_path):
    paths = Paths(base_dir=tmp_path)

    def _fake_run_peer_review_loop(*, manuscript_text: str, venue_name: str, section_id: str | None, max_rounds: int, reviewer2_styles: list[str]):
        needs_more = "needs_more" in manuscript_text
        fake = SimpleNamespace(final_text=manuscript_text)
        fake.model_dump = lambda: {
            "venue": venue_name,
            "section_id": section_id,
            "reviewer2_styles": reviewer2_styles,
            "red_team_agents": ["reviewer_agent", "reviewer2_agent", "area_chair_agent"],
            "blue_team_agents": ["author_agent"],
            "rounds": [{"round_id": 1}] if not needs_more else [{"round_id": 1}, {"round_id": 2}],
            "final_text": fake.final_text,
            "final_decision": "needs_human_intervention" if needs_more else "accept",
            "unresolved_issue_count": 2 if needs_more else 0,
        }
        return fake

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths),
        patch("src.research_writing.runtime_service.run_peer_review_loop", side_effect=_fake_run_peer_review_loop),
    ):
        simulate_peer_review_cycle(
            thread_id="thread-metrics",
            venue_name="NeurIPS",
            manuscript_text="clean draft",
            section_id="discussion",
            peer_review_ab_variant="A",
        )
        simulate_peer_review_cycle(
            thread_id="thread-metrics",
            venue_name="NeurIPS",
            manuscript_text="needs_more evidence",
            section_id="discussion",
            peer_review_ab_variant="B",
        )
        metrics = get_peer_review_ab_metrics("thread-metrics")

    assert metrics["total_runs"] == 2
    assert metrics["by_variant_total"]["A"]["runs"] == 1.0
    assert metrics["by_variant_total"]["B"]["runs"] == 1.0
    assert metrics["by_variant_total"]["A"]["accept_rate"] == 1.0
    assert metrics["by_variant_total"]["B"]["accept_rate"] == 0.0
    assert len(metrics["recent_runs"]) == 2
    assert metrics["artifact_path"] is not None


def test_compile_section_strict_blocks_when_key_hitl_is_rejected(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths):
        upsert_project(
            "thread-3",
            ResearchProject(
                project_id="p3",
                title="HITL gating",
                discipline="ai_cs",
                target_venue="NeurIPS",
                sections=[SectionDraft(section_id="discussion", section_name="Discussion", content="Draft content.")],
            ),
        )
        upsert_project_hitl_decisions(
            thread_id="thread-3",
            project_id="p3",
            section_id="discussion",
            decisions=[
                HitlDecision(
                    action_id="hitl.confirm_outline",
                    source="PI",
                    label="确认大纲",
                    decision="rejected",
                )
            ],
        )

        try:
            compile_project_section(
                thread_id="thread-3",
                project_id="p3",
                section_id="discussion",
                mode="strict",
            )
            assert False, "Expected strict compile to raise when key HITL is rejected"
        except ValueError as exc:
            assert "HITL" in str(exc)
        metrics_path = (
            paths.sandbox_outputs_dir("thread-3")
            / "research-writing"
            / "metrics"
            / "compile-gates.json"
        )
        metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        assert metrics_payload["strict_hitl_blocked_count"] >= 1
        assert metrics_payload["strict_compile_attempts"] >= 1


def test_hitl_decisions_include_compile_impact_preview(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths):
        upsert_project(
            "thread-4",
            ResearchProject(
                project_id="p4",
                title="HITL preview",
                discipline="ai_cs",
                sections=[SectionDraft(section_id="discussion", section_name="Discussion", content="Draft.")],
            ),
        )
        upsert_project_hitl_decisions(
            thread_id="thread-4",
            project_id="p4",
            section_id="discussion",
            decisions=[
                HitlDecision(
                    action_id="hitl.lock_figure_set",
                    source="PI",
                    label="拍板图表组合",
                    decision="rejected",
                )
            ],
        )
        payload = get_project_hitl_decisions(
            thread_id="thread-4",
            project_id="p4",
            section_id="discussion",
        )

    assert payload["impact_preview"]["strict_compile_blocked"] is True
    assert "compile_section(mode=strict)" in payload["impact_preview"]["blocked_actions"]
    assert payload["policy_snapshot"]["signal_count"] == 1
    assert payload["policy_snapshot_artifact_path"].endswith(".json")


def test_compile_section_fail_close_when_missing_key_evidence(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths):
        upsert_project(
            "thread-risk",
            ResearchProject(
                project_id="p-risk",
                title="Fail-close test",
                discipline="ai_cs",
                target_venue="NeurIPS",
                sections=[
                    SectionDraft(
                        section_id="discussion",
                        section_name="Discussion",
                        content="We prove this always works.",
                        claim_ids=["c-risk"],
                    )
                ],
            ),
        )
        upsert_claim(
            "thread-risk",
            Claim(
                claim_id="c-risk",
                text="This result demonstrates definitive superiority.",
                claim_type="strong",
                evidence_ids=[],
                citation_ids=[],
            ),
        )
        payload = compile_project_section(
            thread_id="thread-risk",
            project_id="p-risk",
            section_id="discussion",
            mode="strict",
            auto_peer_review=False,
            auto_hypothesis=False,
        )

    assert payload["safety_valve_triggered"] is True
    assert payload["risk_conclusion_template"] is not None
    assert "风险结论模板" in payload["compiled_text"]
    assert isinstance(payload["hard_grounding_sentence_check"], dict)
    assert isinstance(payload["literature_alignment_check"], dict)
    assert payload["hard_grounding_sentence_check"]["missing_data_binding_count"] >= 1
    assert payload["hard_grounding_sentence_check"]["missing_citation_binding_count"] >= 1
    assert isinstance(payload["compliance_audit"], dict)
    assert payload["compliance_audit_artifact_path"].endswith(".json")


def test_compile_section_policy_snapshot_narrative_toggle_for_ab(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths):
        upsert_project(
            "thread-ab",
            ResearchProject(
                project_id="p-ab",
                title="Policy snapshot A/B",
                discipline="ai_cs",
                target_venue="NeurIPS",
                sections=[
                    SectionDraft(
                        section_id="discussion",
                        section_name="Discussion",
                        content="Draft discussion text.",
                    )
                ],
            ),
        )
        upsert_project_hitl_decisions(
            thread_id="thread-ab",
            project_id="p-ab",
            section_id="discussion",
            decisions=[
                HitlDecision(
                    action_id="peer-r1-ablation-causal",
                    source="Peer Loop Round 1",
                    label="add ablation baseline and soften causal claim",
                    decision="rejected",
                )
            ],
        )

        with_adjustment = compile_project_section(
            thread_id="thread-ab",
            project_id="p-ab",
            section_id="discussion",
            mode="lenient",
            auto_peer_review=False,
            auto_hypothesis=False,
            narrative_style="auto",
            narrative_evidence_density="low",
            policy_snapshot_auto_adjust_narrative=True,
        )
        without_adjustment = compile_project_section(
            thread_id="thread-ab",
            project_id="p-ab",
            section_id="discussion",
            mode="lenient",
            auto_peer_review=False,
            auto_hypothesis=False,
            narrative_style="auto",
            narrative_evidence_density="low",
            policy_snapshot_auto_adjust_narrative=False,
        )

    assert with_adjustment["policy_snapshot_auto_adjust_narrative"] is True
    assert with_adjustment["policy_snapshot_adjustment_applied"] is True
    assert with_adjustment["narrative_strategy"]["evidence_density"] == "high"
    assert without_adjustment["policy_snapshot_auto_adjust_narrative"] is False
    assert without_adjustment["policy_snapshot_adjustment_applied"] is False
    assert without_adjustment["narrative_strategy"]["evidence_density"] == "low"


def test_compile_section_ab_variant_controls_peer_review_rounds_and_styles(tmp_path):
    paths = Paths(base_dir=tmp_path)
    captured: dict[str, object] = {}

    def _fake_run_peer_review_loop(*, manuscript_text: str, venue_name: str, section_id: str | None, max_rounds: int, reviewer2_styles: list[str]):
        captured["max_rounds"] = max_rounds
        captured["reviewer2_styles"] = reviewer2_styles
        fake = SimpleNamespace(final_text=f"{manuscript_text}\n\nPeer-reviewed.")
        fake.model_dump = lambda: {
            "venue": venue_name,
            "section_id": section_id,
            "reviewer2_styles": reviewer2_styles,
            "red_team_agents": ["reviewer_agent", "reviewer2_agent", "area_chair_agent"],
            "blue_team_agents": ["author_agent"],
            "rounds": [],
            "final_text": fake.final_text,
            "final_decision": "accept",
            "unresolved_issue_count": 0,
        }
        return fake

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths),
        patch("src.research_writing.runtime_service.run_peer_review_loop", side_effect=_fake_run_peer_review_loop),
    ):
        upsert_project(
            "thread-compile-ab",
            ResearchProject(
                project_id="p-compile-ab",
                title="Compile peer-review A/B",
                discipline="ai_cs",
                target_venue="NeurIPS",
                sections=[SectionDraft(section_id="discussion", section_name="Discussion", content="Draft content.")],
            ),
        )
        payload = compile_project_section(
            thread_id="thread-compile-ab",
            project_id="p-compile-ab",
            section_id="discussion",
            mode="lenient",
            auto_peer_review=True,
            auto_hypothesis=False,
            peer_review_ab_variant="A",
            reviewer2_styles=["domain_traditionalist"],
        )

    assert captured["max_rounds"] == 2
    assert captured["reviewer2_styles"] == ["statistical_tyrant", "methodology_fundamentalist"]
    assert payload["peer_review_ab_variant"] == "A"
    assert payload["peer_review_max_rounds"] == 2
    assert payload["peer_review_strategy"]["style_source"] == "ab:A"


def test_claim_grounding_marks_stale_after_artifact_update(tmp_path):
    paths = Paths(base_dir=tmp_path)
    thread_id = "thread-grounding"
    project_id = "p-grounding"
    section_id = "results"
    data_virtual_path = "/mnt/user-data/outputs/research-writing/raw/results.csv"

    with patch("src.research_writing.runtime_service.get_paths", return_value=paths):
        data_file = paths.resolve_virtual_path(thread_id, data_virtual_path)
        data_file.parent.mkdir(parents=True, exist_ok=True)
        data_file.write_text("metric,value\nauroc,0.82\n", encoding="utf-8")

        upsert_project(
            thread_id,
            ResearchProject(
                project_id=project_id,
                title="Claim grounding stale check",
                discipline="ai_cs",
                target_venue="NeurIPS",
                sections=[
                    SectionDraft(
                        section_id=section_id,
                        section_name="Results",
                        content="Initial grounded result.",
                        claim_ids=["c-ground"],
                        evidence_ids=["ev-ground"],
                    )
                ],
            ),
        )
        upsert_claim(
            thread_id,
            Claim(
                claim_id="c-ground",
                text="Our method improves AUROC by 0.05 over baseline.",
                claim_type="strong",
                evidence_ids=["ev-ground"],
                citation_ids=[],
            ),
        )
        upsert_evidence(
            thread_id,
            EvidenceUnit(
                evidence_id="ev-ground",
                evidence_type="raw_data",
                summary="Statistical test reports p < 0.05, effect size 0.4, and confidence interval [0.2, 0.6].",
                source_ref=data_virtual_path,
            ),
        )

        compile_payload = compile_project_section(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
            mode="lenient",
            auto_peer_review=False,
            auto_hypothesis=False,
        )
        assert compile_payload["claim_grounding"]["summary"]["valid_claims"] >= 1
        assert compile_payload["claim_grounding"]["summary"]["stale_claims"] == 0

        data_file.write_text("metric,value\nauroc,0.74\n", encoding="utf-8")
        trace_payload = get_section_traceability(
            thread_id=thread_id,
            project_id=project_id,
            section_id=section_id,
        )

    claim_rows = [row for row in trace_payload["claims"] if row.get("claim_id") == "c-ground"]
    assert claim_rows
    assert claim_rows[0]["grounding_status"] == "stale"
    assert trace_payload["claim_grounding"]["summary"]["stale_claims"] >= 1


def test_runtime_service_records_artifact_ledger(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths),
        patch(
            "src.research_writing.runtime_service.get_prompt_pack_metadata",
            return_value={
                "prompt_pack_id": "rw.superagent.test",
                "prompt_pack_hash": "abc123def4567890",
                "prompt_layer_schema_version": "deerflow.prompt_layers.v1",
                "prompt_layer_versions": {"L0": "v1", "L1": "v1", "L2": "v1", "L3": "v1", "L4": "v1", "L5": "v1"},
            },
        ),
    ):
        simulate_peer_review_cycle(
            thread_id="thread-ledger",
            venue_name="NeurIPS",
            manuscript_text="Short draft without ablation or limitations.",
            section_id="discussion",
            max_rounds=2,
        )
    ledger_path = paths.sandbox_outputs_dir("thread-ledger") / "research-writing" / "artifact-ledger.json"
    rows = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert rows
    assert any(row.get("service") == "review" for row in rows)
    for row in rows:
        metadata = row.get("metadata") or {}
        assert metadata.get("prompt_pack_id") == "rw.superagent.test"
        assert metadata.get("prompt_pack_hash") == "abc123def4567890"
        assert metadata.get("prompt_layer_schema_version") == "deerflow.prompt_layers.v1"
        runtime_strategy = metadata.get("runtime_strategy")
        assert isinstance(runtime_strategy, dict)
        assert isinstance(runtime_strategy.get("peer_review"), dict)
        assert runtime_strategy["peer_review"]["enabled"] is True
        assert isinstance(metadata.get("eval_impact"), dict)
        assert isinstance(metadata.get("eval_attribution_key"), str)
        prompt_registry = metadata.get("prompt_registry")
        assert isinstance(prompt_registry, dict)
        assert prompt_registry.get("prompt_pack_id") == "rw.superagent.test"
        assert prompt_registry.get("prompt_pack_hash") == "abc123def4567890"


def test_policy_snapshot_and_weekly_leaderboard_pipeline(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths),
        patch(
            "src.research_writing.runtime_service.get_prompt_pack_metadata",
            return_value={
                "prompt_pack_id": "rw.superagent.test",
                "prompt_pack_hash": "abc123def4567890",
                "prompt_layer_schema_version": "deerflow.prompt_layers.v1",
                "prompt_layer_versions": {"L0": "v1", "L1": "v1", "L2": "v1", "L3": "v1", "L4": "v1", "L5": "v1"},
            },
        ),
    ):
        upsert_project(
            "thread-policy",
            ResearchProject(
                project_id="p-policy",
                title="Policy and leaderboard",
                discipline="ai_cs",
                target_venue="NeurIPS",
                sections=[SectionDraft(section_id="discussion", section_name="Discussion", content="Draft text.")],
            ),
        )
        upsert_project_hitl_decisions(
            thread_id="thread-policy",
            project_id="p-policy",
            section_id="discussion",
            decisions=[
                HitlDecision(
                    action_id="peer-r1-ablation",
                    source="Peer Loop Round 1",
                    label="add ablation baseline",
                    decision="rejected",
                )
            ],
        )
        policy = get_project_policy_snapshot(
            thread_id="thread-policy",
            project_id="p-policy",
            section_id="discussion",
        )
        summary = evaluate_academic_and_persist(
            "thread-policy",
            cases=[
                AcademicEvalCase(
                    case_id="c-acc",
                    domain="ai_cs",
                    venue="NeurIPS",
                    decision="accepted",
                ),
                AcademicEvalCase(
                    case_id="c-rej",
                    domain="ai_cs",
                    venue="NeurIPS",
                    decision="rejected",
                ),
            ],
            name="weekly-eval",
            model_label="unit-model",
            dataset_name="unit-set",
        )
        leaderboard = get_weekly_academic_leaderboard("thread-policy")

    assert policy["policy_snapshot"]["signal_count"] == 1
    assert summary["leaderboard_entries_updated"] >= 1
    assert summary["leaderboard_artifact_path"].endswith("weekly.json")
    assert leaderboard["buckets"]
    assert summary["prompt_pack_id"] == "rw.superagent.test"
    assert summary["prompt_pack_hash"] == "abc123def4567890"
    assert summary["prompt_layer_schema_version"] == "deerflow.prompt_layers.v1"


def test_policy_snapshot_writing_directives_flow_into_l4_adapter(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths):
        upsert_project(
            "thread-directive",
            ResearchProject(
                project_id="p-directive",
                title="Policy writing directives",
                discipline="ai_cs",
                target_venue="NeurIPS",
                sections=[SectionDraft(section_id="discussion", section_name="Discussion", content="Draft text.")],
            ),
        )
        upsert_project_hitl_decisions(
            thread_id="thread-directive",
            project_id="p-directive",
            section_id="discussion",
            decisions=[
                HitlDecision(
                    action_id="peer-r1-soften-causal-claim",
                    source="Researcher edit",
                    label="soften causal claim and add ablation baseline",
                    decision="rejected",
                    metadata={"writing_directives": ["Prefer cautious wording for mechanism claims."]},
                )
            ],
        )
        snapshot = get_project_policy_snapshot(
            thread_id="thread-directive",
            project_id="p-directive",
            section_id="discussion",
        )
        payload = compile_project_section(
            thread_id="thread-directive",
            project_id="p-directive",
            section_id="discussion",
            mode="lenient",
            auto_peer_review=False,
            auto_hypothesis=False,
            policy_snapshot_auto_adjust_narrative=True,
        )

    assert snapshot["writing_directives"]
    assert payload["policy_writing_directives"]
    assert payload["venue_style_adapter"]["writing_directives"]
    assert set(payload["policy_writing_directives"]).issubset(set(payload["venue_style_adapter"]["writing_directives"]))


def test_policy_snapshot_auto_captures_section_edit_feedback(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths):
        upsert_project(
            "thread-auto-edit",
            ResearchProject(
                project_id="p-auto-edit",
                title="Auto capture human section edits",
                discipline="ai_cs",
                target_venue="NeurIPS",
                sections=[
                    SectionDraft(
                        section_id="discussion",
                        section_name="Discussion",
                        content="We prove a definitive causal effect without caveats.",
                    )
                ],
            ),
        )
        upsert_section(
            "thread-auto-edit",
            "p-auto-edit",
            SectionDraft(
                section_id="discussion",
                section_name="Discussion",
                content=(
                    "Results suggest an association rather than proof. "
                    "We add baseline/control validation and include one mechanism hypothesis plus an alternative explanation. "
                    "Reproducibility constraints are explicitly documented."
                ),
            ),
        )
        decisions_payload = get_project_hitl_decisions(
            thread_id="thread-auto-edit",
            project_id="p-auto-edit",
            section_id="discussion",
        )
        snapshot = get_project_policy_snapshot(
            thread_id="thread-auto-edit",
            project_id="p-auto-edit",
            section_id="discussion",
        )

    assert any(item["action_id"] == "hitl.auto_section_edit_feedback" for item in decisions_payload["decisions"])
    assert snapshot["writing_directives"]
    assert any("conservative language" in item for item in snapshot["writing_directives"])


def test_self_play_mines_fewshot_library_and_writer_l3_addendum(tmp_path):
    paths = Paths(base_dir=tmp_path)

    def _fake_peer_loop(*, manuscript_text: str, venue_name: str, section_id: str | None, max_rounds: int):
        issue_major_1 = SimpleNamespace(issue_type="method_gap", severity="major")
        issue_major_2 = SimpleNamespace(issue_type="overclaim", severity="major")
        round1 = SimpleNamespace(
            reviewer_issues=[issue_major_1, issue_major_2],
            author_revision_notes=["soften causal claim", "add ablation baseline"],
        )
        round2 = SimpleNamespace(
            reviewer_issues=[],
            author_revision_notes=["clarify limitations and evidence chain"],
        )
        return SimpleNamespace(
            rounds=[round1, round2],
            final_decision="accept",
            unresolved_issue_count=0,
            final_text=f"{manuscript_text}\n\nRevised with calibrated claims and stronger evidence chain.",
        )

    fake_compliance = SimpleNamespace(
        blocked_by_critical=False,
        risk_level="low",
        findings=[],
        compliance_score=0.92,
    )

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths),
        patch("src.research_writing.self_play_trainer.run_peer_review_loop", side_effect=_fake_peer_loop),
        patch("src.research_writing.self_play_trainer.audit_scientific_compliance", return_value=fake_compliance),
    ):
        payload = run_peer_self_play_training(
            thread_id="thread-self-play",
            episodes=[{"manuscript_text": "Initial draft with strong causal wording."}],
            run_name="unit-self-play",
            max_rounds=3,
        )
        addendum = get_writer_l3_few_shot_addendum("thread-self-play", top_k=1)

    assert payload["few_shot_examples_added"] >= 1
    assert payload["few_shot_library"]["accepted_recovery_examples"] >= 1
    assert payload["few_shot_library_artifact_path"].endswith("writer-l3-fewshot-library.json")
    assert isinstance(addendum, str)
    assert "[L3 Dynamic Few-shot Contract Addendum]" in addendum
    assert "Before:" in addendum
    assert "After:" in addendum


def test_compile_section_flags_citation_listing_without_alignment(tmp_path):
    paths = Paths(base_dir=tmp_path)
    with patch("src.research_writing.runtime_service.get_paths", return_value=paths):
        upsert_project(
            "thread-listing",
            ResearchProject(
                project_id="p-listing",
                title="Listing style detection",
                discipline="ai_cs",
                target_venue="NeurIPS",
                sections=[
                    SectionDraft(
                        section_id="discussion",
                        section_name="Discussion",
                        content=(
                            "Paper A reports observation X [citation:A] [data:ev1]. "
                            "Paper B reports observation Y [citation:B] [data:ev1]."
                        ),
                    )
                ],
            ),
        )
        payload = compile_project_section(
            thread_id="thread-listing",
            project_id="p-listing",
            section_id="discussion",
            mode="lenient",
            auto_peer_review=False,
            auto_hypothesis=False,
        )

    assert isinstance(payload["literature_alignment_check"], dict)
    assert payload["literature_alignment_check"]["likely_listing_without_alignment"] is True
    assert payload["safety_valve_triggered"] is True
    assert any("citation listing without [支持]/[反驳]/[调和]" in reason for reason in payload["safety_valve_reasons"])
