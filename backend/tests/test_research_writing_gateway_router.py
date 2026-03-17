"""Tests for research-writing gateway router."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_paths(base_dir: Path):
    from src.config.paths import Paths

    return Paths(base_dir=base_dir)


def _make_app() -> FastAPI:
    from src.gateway.routers.research_writing import router

    app = FastAPI()
    app.include_router(router)
    return app


def test_research_project_crud_and_eval(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            upsert_resp = client.post(
                "/api/threads/thread-1/research/projects/upsert",
                json={
                    "project_id": "p1",
                    "title": "Runtime research project",
                    "discipline": "ai_cs",
                    "sections": [
                        {
                            "section_id": "intro",
                            "section_name": "Introduction",
                            "status": "outlined",
                            "content": "Initial intro section.",
                        }
                    ],
                },
            )
            assert upsert_resp.status_code == 200
            assert upsert_resp.json()["project"]["project_id"] == "p1"

            list_resp = client.get("/api/threads/thread-1/research/projects")
            assert list_resp.status_code == 200
            assert len(list_resp.json()["projects"]) == 1

            get_resp = client.get("/api/threads/thread-1/research/projects/p1")
            assert get_resp.status_code == 200
            assert get_resp.json()["project"]["title"] == "Runtime research project"

            eval_resp = client.post(
                "/api/threads/thread-1/research/evals/academic",
                json={
                    "artifact_name": "unit-eval",
                    "cases": [
                        {
                            "case_id": "c1",
                            "domain": "ai_cs",
                            "venue": "NeurIPS",
                            "generated_citations": ["10.1/a"],
                            "verified_citations": ["10.1/a"],
                            "claims": [{"type": "strong", "has_evidence": True, "has_citation": True}],
                            "abstract_numbers": [0.9],
                            "body_numbers": [0.9],
                            "reviewer_comment_ids": ["R1"],
                            "rebuttal_addressed_ids": ["R1"],
                            "venue_checklist_items": ["ablation"],
                            "venue_satisfied_items": ["ablation"],
                            "cross_modal_items_expected": 1,
                            "cross_modal_items_used": 1,
                            "revision_terms": [["ablation"], ["ablation"]],
                            "revision_numbers": [[0.9], [0.9]],
                        }
                    ],
                },
            )
            assert eval_resp.status_code == 200
            payload = eval_resp.json()
            assert payload["case_count"] == 1
            assert payload["artifact_path"].startswith("/mnt/user-data/outputs/research-writing/evals/")

            builtin_eval_resp = client.post(
                "/api/threads/thread-1/research/evals/academic",
                json={
                    "artifact_name": "builtin-eval",
                    "dataset_name": "top_tier_accept_reject_v1",
                },
            )
            assert builtin_eval_resp.status_code == 200
            builtin_payload = builtin_eval_resp.json()
            assert builtin_payload["case_count"] == 8
            assert builtin_payload["accepted_case_count"] > 0
            assert builtin_payload["rejected_case_count"] > 0

            source_virtual_path = "/mnt/user-data/outputs/research-writing/raw/accept-reject.json"
            source_file = paths_instance.resolve_virtual_path("thread-1", source_virtual_path)
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "manuscript_id": "MS-A",
                                "decision": "accepted",
                                "venue": "Nature",
                                "claims": [
                                    {
                                        "type": "strong",
                                        "has_evidence": True,
                                        "has_citation": True,
                                    }
                                ],
                            },
                            {
                                "manuscript_id": "MS-B",
                                "decision": "rejected",
                                "venue": "Cell",
                                "claims": [
                                    {
                                        "type": "strong",
                                        "has_evidence": False,
                                        "has_citation": False,
                                    }
                                ],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            import_resp = client.post(
                "/api/threads/thread-1/research/evals/academic/import",
                json={
                    "source_dataset_path": source_virtual_path,
                    "dataset_name": "top_tier_accept_reject_real",
                    "dataset_version": "v2026.03",
                    "anonymize": True,
                },
            )
            assert import_resp.status_code == 200
            import_payload = import_resp.json()
            assert import_payload["imported_case_count"] == 2
            assert import_payload["accepted_case_count"] == 1
            assert import_payload["rejected_case_count"] == 1
            assert import_payload["dataset_path"].startswith("/mnt/user-data/outputs/research-writing/evals/datasets/")
            assert import_payload["validation_status"] in {
                "pass",
                "has_warnings",
                "has_errors",
            }
            assert import_payload["validation_report_path"].startswith(
                "/mnt/user-data/outputs/research-writing/evals/datasets/"
            )
            assert import_payload["validation_markdown_path"].startswith(
                "/mnt/user-data/outputs/research-writing/evals/datasets/"
            )
            assert import_payload["autofix_applied"] is False
            assert import_payload["autofix_modified_record_count"] == 0
            assert import_payload["autofix_report_path"] is None
            assert import_payload["autofix_markdown_path"] is None

            autofix_virtual_path = "/mnt/user-data/outputs/research-writing/raw/accept-reject-autofix.json"
            autofix_file = paths_instance.resolve_virtual_path("thread-1", autofix_virtual_path)
            autofix_file.parent.mkdir(parents=True, exist_ok=True)
            autofix_file.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "manuscript_id": "MS-C",
                                "outcome": "accepted",
                                "journal": "Nature",
                                "claim_annotations": {
                                    "type": "strong",
                                    "has_evidence": True,
                                    "has_citation": True,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            autofix_resp = client.post(
                "/api/threads/thread-1/research/evals/academic/import",
                json={
                    "source_dataset_path": autofix_virtual_path,
                    "dataset_name": "top_tier_accept_reject_real",
                    "dataset_version": "v2026.03",
                    "anonymize": True,
                    "strict": True,
                    "autofix": True,
                    "autofix_level": "aggressive",
                },
            )
            assert autofix_resp.status_code == 200
            autofix_payload = autofix_resp.json()
            assert autofix_payload["autofix_applied"] is True
            assert autofix_payload["autofix_level"] == "aggressive"
            assert autofix_payload["autofix_modified_record_count"] >= 1
            assert autofix_payload["autofix_report_path"].startswith(
                "/mnt/user-data/outputs/research-writing/evals/datasets/"
            )
            assert autofix_payload["autofix_markdown_path"].startswith(
                "/mnt/user-data/outputs/research-writing/evals/datasets/"
            )


def test_research_peer_loop_and_hypothesis_endpoints(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            upsert_resp = client.post(
                "/api/threads/thread-2/research/projects/upsert",
                json={
                    "project_id": "p2",
                    "title": "Advanced reasoning project",
                    "discipline": "ai_cs",
                    "target_venue": "NeurIPS",
                    "sections": [{"section_id": "discussion", "section_name": "Discussion", "content": "Initial draft."}],
                },
            )
            assert upsert_resp.status_code == 200

            peer_resp = client.post(
                "/api/threads/thread-2/research/review/peer-loop",
                json={
                    "venue_name": "NeurIPS",
                    "manuscript_text": "Short draft without ablation or limitations.",
                    "section_id": "discussion",
                    "max_rounds": 3,
                    "reviewer2_styles": ["statistical_tyrant", "methodology_fundamentalist"],
                    "peer_review_ab_variant": "B",
                },
            )
            assert peer_resp.status_code == 200
            peer_payload = peer_resp.json()
            assert "final_decision" in peer_payload
            assert peer_payload["artifact_path"].startswith("/mnt/user-data/outputs/research-writing/review/")
            assert peer_payload["reviewer2_styles"] == ["statistical_tyrant", "methodology_fundamentalist", "domain_traditionalist"]
            assert peer_payload["peer_review_ab_variant"] == "B"

            hyp_resp = client.post(
                "/api/threads/thread-2/research/hypotheses/generate",
                json={
                    "project_id": "p2",
                    "section_id": "discussion",
                    "max_hypotheses": 5,
                },
            )
            assert hyp_resp.status_code == 200
            hyp_payload = hyp_resp.json()
            assert hyp_payload["project_id"] == "p2"
            assert len(hyp_payload["hypotheses"]) == 5

            put_hitl_resp = client.put(
                "/api/threads/thread-2/research/projects/p2/hitl-decisions",
                json={
                    "section_id": "discussion",
                    "decisions": [
                        {
                            "action_id": "peer-r1-abc",
                            "source": "Peer Loop Round 1",
                            "label": "Add additional ablation study",
                            "decision": "approved",
                            "metadata": {"by": "human-reviewer"},
                        }
                    ],
                },
            )
            assert put_hitl_resp.status_code == 200
            put_hitl_payload = put_hitl_resp.json()
            assert put_hitl_payload["project_id"] == "p2"
            assert put_hitl_payload["total_count"] == 1
            assert put_hitl_payload["decisions"][0]["decision"] == "approved"
            assert put_hitl_payload["artifact_path"].startswith("/mnt/user-data/outputs/research-writing/hitl/")

            get_hitl_resp = client.get(
                "/api/threads/thread-2/research/projects/p2/hitl-decisions?section_id=discussion"
            )
            assert get_hitl_resp.status_code == 200
            get_hitl_payload = get_hitl_resp.json()
            assert get_hitl_payload["project_id"] == "p2"
            assert get_hitl_payload["section_id"] == "discussion"
            assert get_hitl_payload["total_count"] == 1
            assert get_hitl_payload["decisions"][0]["action_id"] == "peer-r1-abc"


def test_peer_review_ab_metrics_endpoint_and_auto_variant_passthrough(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            with patch(
                "src.gateway.routers.research_writing.simulate_peer_review_cycle",
                return_value={
                    "venue": "NeurIPS",
                    "section_id": "discussion",
                    "red_team_agents": ["reviewer_agent"],
                    "blue_team_agents": ["author_agent"],
                    "rounds": [],
                    "final_text": "final",
                    "final_decision": "accept",
                    "unresolved_issue_count": 0,
                    "artifact_path": "/mnt/user-data/outputs/research-writing/review/peer-loop-neurips.json",
                    "final_text_path": "/mnt/user-data/outputs/research-writing/review/peer-loop-neurips.md",
                    "reviewer2_styles": ["statistical_tyrant"],
                    "peer_review_ab_variant": "A",
                    "peer_review_max_rounds": 2,
                    "peer_review_strategy": {"ab_variant_source": "request:auto"},
                    "peer_review_ab_metrics": {
                        "metrics_schema_version": "deerflow.peer_review_ab_metrics.v1",
                        "thread_id": "thread-ab",
                        "total_runs": 1,
                        "window_size": 1,
                        "by_variant_total": {"A": {"runs": 1.0, "accepts": 1.0, "accept_rate": 1.0, "avg_unresolved_issue_count": 0.0, "avg_round_count": 1.0}},
                        "by_variant_window": {"A": {"runs": 1.0, "accepts": 1.0, "accept_rate": 1.0, "avg_unresolved_issue_count": 0.0, "avg_round_count": 1.0}},
                        "recent_runs": [],
                        "strategy_config": {
                            "default_styles": ["statistical_tyrant"],
                            "venue_style_overrides": {"neurips": ["statistical_tyrant"]},
                            "ab_enabled": True,
                            "ab_default_variant": "off",
                            "ab_variant_a_max_rounds": 2,
                            "ab_variant_a_styles": ["statistical_tyrant"],
                            "ab_variant_b_max_rounds": 4,
                            "ab_variant_b_styles": ["statistical_tyrant", "methodology_fundamentalist"],
                            "ab_auto_split_enabled": True,
                            "ab_auto_split_ratio_a": 0.5,
                            "ab_auto_split_salt": "v1",
                            "ab_metrics_enabled": True,
                            "ab_metrics_max_recent_runs": 120,
                            "thread_assignment_preview": {"ab_variant": "A", "thread_hash_ratio": 0.22},
                        },
                        "artifact_path": "/mnt/user-data/outputs/research-writing/review/peer-review-ab-metrics.json",
                    },
                },
            ) as peer_loop_mock:
                resp = client.post(
                    "/api/threads/thread-ab/research/review/peer-loop",
                    json={
                        "venue_name": "NeurIPS",
                        "manuscript_text": "draft",
                        "section_id": "discussion",
                        "peer_review_ab_variant": "auto",
                    },
                )
                assert resp.status_code == 200
                _, call_kwargs = peer_loop_mock.call_args
                assert call_kwargs["peer_review_ab_variant"] == "auto"

            with patch(
                "src.gateway.routers.research_writing.get_peer_review_ab_metrics",
                return_value={
                    "metrics_schema_version": "deerflow.peer_review_ab_metrics.v1",
                    "thread_id": "thread-ab",
                    "updated_at": "2026-03-17T00:00:00+00:00",
                    "total_runs": 3,
                    "window_size": 3,
                    "by_variant_total": {},
                    "by_variant_window": {},
                    "recent_runs": [],
                    "strategy_config": {
                        "default_styles": ["statistical_tyrant"],
                        "venue_style_overrides": {"neurips": ["statistical_tyrant"]},
                        "ab_enabled": True,
                        "ab_default_variant": "off",
                        "ab_variant_a_max_rounds": 2,
                        "ab_variant_a_styles": ["statistical_tyrant"],
                        "ab_variant_b_max_rounds": 4,
                        "ab_variant_b_styles": ["statistical_tyrant", "methodology_fundamentalist"],
                        "ab_auto_split_enabled": True,
                        "ab_auto_split_ratio_a": 0.5,
                        "ab_auto_split_salt": "v1",
                        "ab_metrics_enabled": True,
                        "ab_metrics_max_recent_runs": 120,
                        "thread_assignment_preview": {"ab_variant": "B", "thread_hash_ratio": 0.81},
                    },
                    "artifact_path": "/mnt/user-data/outputs/research-writing/review/peer-review-ab-metrics.json",
                },
            ):
                metrics_resp = client.get("/api/threads/thread-ab/research/review/ab-metrics")
                assert metrics_resp.status_code == 200
                metrics_payload = metrics_resp.json()
                assert metrics_payload["thread_id"] == "thread-ab"
                assert metrics_payload["total_runs"] == 3
                assert metrics_payload["strategy_config"]["ab_auto_split_enabled"] is True


def test_engineering_gates_metrics_endpoint(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            with patch(
                "src.gateway.routers.research_writing.get_engineering_gates_metrics",
                return_value={
                    "metrics_schema_version": "deerflow.engineering_gates_runtime_metrics.v1",
                    "thread_id": "thread-eg",
                    "project_id": "p-eg",
                    "run_limit": 120,
                    "updated_at": "2026-03-17T00:00:00+00:00",
                    "compile_runs": [],
                    "latex_runs": [],
                    "compile_summary": {"run_count": 0},
                    "latex_summary": {"run_count": 0},
                    "thresholds": {
                        "max_constraint_violation_rate": 0.2,
                        "max_safety_valve_trigger_rate": 0.4,
                        "max_hitl_block_rate": 0.35,
                        "min_traceability_coverage_rate": 0.8,
                        "min_delivery_completeness_rate": 1.0,
                        "min_latex_success_rate": 0.75,
                    },
                    "alerts": [],
                    "status": "pass",
                    "counters": {},
                    "artifacts": {},
                },
            ) as metrics_mock:
                resp = client.get(
                    "/api/threads/thread-eg/research/metrics/engineering-gates"
                    "?project_id=p-eg&run_limit=120"
                    "&max_constraint_violation_rate=0.1"
                    "&max_safety_valve_trigger_rate=0.2"
                    "&max_hitl_block_rate=0.15"
                    "&min_traceability_coverage_rate=0.9"
                    "&min_delivery_completeness_rate=1.0"
                    "&min_latex_success_rate=0.95"
                )

            assert resp.status_code == 200
            payload = resp.json()
            assert payload["thread_id"] == "thread-eg"
            assert payload["project_id"] == "p-eg"
            assert payload["run_limit"] == 120
            _, kwargs = metrics_mock.call_args
            assert kwargs["thread_id"] == "thread-eg"
            assert kwargs["project_id"] == "p-eg"
            assert kwargs["run_limit"] == 120
            assert kwargs["max_constraint_violation_rate"] == 0.1
            assert kwargs["max_safety_valve_trigger_rate"] == 0.2
            assert kwargs["max_hitl_block_rate"] == 0.15
            assert kwargs["min_traceability_coverage_rate"] == 0.9
            assert kwargs["min_delivery_completeness_rate"] == 1.0
            assert kwargs["min_latex_success_rate"] == 0.95


def test_research_fulltext_ingest_returns_citation_graph_fields(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            with patch(
                "src.gateway.routers.research_writing.ingest_fulltext_evidence",
                return_value={
                    "record": {"source": "arxiv", "external_id": "2501.00001", "title": "Graph Paper"},
                    "evidence_count": 2,
                    "persisted_evidence_ids": ["arxiv:2501.00001:p1"],
                    "persisted_citation_ids": ["10.1234/demo", "s2:S1"],
                    "citation_graph": {
                        "nodes": [{"node_id": "s1"}, {"node_id": "s2"}],
                        "edges": [{"source_id": "s1", "target_id": "s2", "relation": "co_citation", "weight": 3}],
                        "narrative_threads": ["Timeline ..."],
                        "sources_used": ["semantic_scholar"],
                    },
                    "literature_graph": {
                        "anchor_claim_id": "claim:arxiv:2501.00001:anchor",
                        "claims": [{"claim_id": "claim:arxiv:2501.00001:anchor"}],
                        "edges": [{"paper_id": "s1", "relation": "supports"}],
                        "synthesis_threads": ["Debate map ..."],
                    },
                    "citation_graph_node_count": 2,
                    "co_citation_edge_count": 1,
                    "literature_graph_claim_count": 1,
                    "literature_graph_edge_count": 1,
                    "narrative_threads": ["Timeline ..."],
                    "literature_synthesis_threads": ["Debate map ..."],
                    "artifact_path": "/mnt/user-data/outputs/research-writing/artifacts/ingest-arxiv-2501.00001.json",
                },
            ):
                resp = client.post(
                    "/api/threads/thread-graph/research/ingest/fulltext",
                    json={"source": "arxiv", "external_id": "2501.00001", "persist": True},
                )

            assert resp.status_code == 200
            payload = resp.json()
            assert payload["citation_graph_node_count"] == 2
            assert payload["co_citation_edge_count"] == 1
            assert payload["literature_graph_claim_count"] == 1
            assert payload["literature_graph_edge_count"] == 1
            assert payload["persisted_citation_ids"] == ["10.1234/demo", "s2:S1"]


def test_compile_section_accepts_narrative_strategy_controls(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            with patch(
                "src.gateway.routers.research_writing.compile_project_section",
                return_value={
                    "section_id": "discussion",
                    "compiled_text": "compiled text",
                    "issues": [],
                    "artifact_path": "/mnt/user-data/outputs/research-writing/compiled/p-discussion.md",
                    "details_artifact_path": "/mnt/user-data/outputs/research-writing/compiled/p-discussion.json",
                    "claim_map": {
                        "schema_version": "deerflow.claim_map.v1",
                        "summary": {"total_claim_ids": 1},
                        "claims": [],
                    },
                    "claim_map_artifact_path": "/mnt/user-data/outputs/research-writing/claim-maps/p-discussion.json",
                    "resolved_venue": "Nature",
                    "narrative_strategy": {
                        "tone": "conservative",
                        "max_templates": 1,
                        "evidence_density": "high",
                        "auto_by_section_type": True,
                        "section_type": "discussion",
                        "paragraph_tones": ["conservative", "aggressive"],
                        "paragraph_evidence_densities": ["medium", "high"],
                    },
                    "narrative_sentence_count": 1,
                    "journal_style": {
                        "venue_name": "Nature",
                        "sample_size": 5,
                    },
                    "journal_style_alignment_applied": True,
                    "narrative_plan": {
                        "planner_version": "deerflow.narrative_plan.v1",
                        "takeaway_message": "Takeaway",
                        "logical_flow": ["L1", "L2"],
                    },
                    "narrative_plan_artifact_path": "/mnt/user-data/outputs/research-writing/narrative-plans/p-discussion.json",
                    "narrative_self_question_rounds": 4,
                    "narrative_include_storyboard": True,
                    "reviewer2_styles": ["statistical_tyrant", "domain_traditionalist"],
                    "peer_review": None,
                    "hypothesis_bundle": None,
                    "claim_grounding": {
                        "schema_version": "deerflow.claim_grounding_ast.v1",
                        "summary": {"total_claims": 1, "valid_claims": 1, "stale_claims": 0, "invalid_claims": 0},
                        "claims": [],
                    },
                    "claim_grounding_alerts": [],
                    "claim_grounding_artifact_path": "/mnt/user-data/outputs/research-writing/compiled/p-discussion.claim-grounding.json",
                    "hard_grounding_sentence_check": {
                        "checked_sentence_count": 5,
                        "flagged_sentence_count": 0,
                        "missing_data_binding_count": 0,
                        "missing_citation_binding_count": 0,
                    },
                    "literature_alignment_check": {
                        "citation_sentence_count": 2,
                        "triad_marker_present": True,
                        "mechanism_conflict_sentence_count": 1,
                        "listing_like_sentence_count": 0,
                        "likely_listing_without_alignment": False,
                    },
                    "peer_review_ab_variant": "A",
                    "peer_review_max_rounds": 2,
                    "peer_review_strategy": {
                        "ab_variant": "A",
                        "resolved_max_rounds": 2,
                        "resolved_reviewer2_styles": ["statistical_tyrant", "methodology_fundamentalist"],
                        "style_source": "ab:A",
                        "round_source": "ab:A",
                        "venue_name": "Nature",
                    },
                },
            ) as compile_mock:
                resp = client.post(
                    "/api/threads/thread-compile/research/compile/section",
                    json={
                        "project_id": "p",
                        "section_id": "discussion",
                        "mode": "strict",
                        "narrative_style": "conservative",
                        "narrative_max_templates": 1,
                        "narrative_evidence_density": "high",
                        "narrative_auto_by_section_type": True,
                        "narrative_paragraph_tones": [
                            "conservative",
                            "aggressive",
                        ],
                        "narrative_paragraph_evidence_densities": [
                            "medium",
                            "high",
                        ],
                        "narrative_self_question_rounds": 4,
                        "narrative_include_storyboard": True,
                        "reviewer2_styles": [
                            "statistical_tyrant",
                            "domain_traditionalist",
                        ],
                        "peer_review_ab_variant": "A",
                    },
                )

            assert resp.status_code == 200
            payload = resp.json()
            assert payload["resolved_venue"] == "Nature"
            assert payload["claim_map"]["schema_version"] == "deerflow.claim_map.v1"
            assert payload["claim_map_artifact_path"].startswith("/mnt/user-data/outputs/research-writing/claim-maps/")
            assert payload["narrative_strategy"]["tone"] == "conservative"
            assert payload["narrative_sentence_count"] == 1
            assert payload["journal_style"]["sample_size"] == 5
            assert payload["journal_style_alignment_applied"] is True
            assert payload["narrative_plan"]["planner_version"] == "deerflow.narrative_plan.v1"
            assert payload["narrative_self_question_rounds"] == 4
            assert payload["narrative_strategy"]["paragraph_tones"] == [
                "conservative",
                "aggressive",
            ]
            assert payload["reviewer2_styles"] == ["statistical_tyrant", "domain_traditionalist"]
            assert payload["claim_grounding"]["schema_version"] == "deerflow.claim_grounding_ast.v1"
            assert payload["hard_grounding_sentence_check"]["missing_data_binding_count"] == 0
            assert payload["literature_alignment_check"]["likely_listing_without_alignment"] is False
            assert payload["peer_review_ab_variant"] == "A"
            assert payload["peer_review_max_rounds"] == 2
            _, call_kwargs = compile_mock.call_args
            assert call_kwargs["narrative_auto_by_section_type"] is True
            assert call_kwargs["narrative_paragraph_tones"] == [
                "conservative",
                "aggressive",
            ]
            assert call_kwargs["narrative_paragraph_evidence_densities"] == [
                "medium",
                "high",
            ]
            assert call_kwargs["narrative_self_question_rounds"] == 4
            assert call_kwargs["narrative_include_storyboard"] is True
            assert call_kwargs["reviewer2_styles"] == ["statistical_tyrant", "domain_traditionalist"]
            assert call_kwargs["peer_review_ab_variant"] == "A"


def test_plan_narrative_endpoint(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            with patch(
                "src.gateway.routers.research_writing.plan_project_section_narrative",
                return_value={
                    "project_id": "p",
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
                    "claim_map": {
                        "schema_version": "deerflow.claim_map.v1",
                        "summary": {"total_claim_ids": 1},
                        "claims": [],
                    },
                    "claim_map_artifact_path": "/mnt/user-data/outputs/research-writing/claim-maps/p-intro.json",
                    "artifact_path": "/mnt/user-data/outputs/research-writing/narrative-plans/p-intro.json",
                },
            ) as plan_mock:
                resp = client.post(
                    "/api/threads/thread-compile/research/plan/narrative",
                    json={
                        "project_id": "p",
                        "section_id": "intro",
                        "self_question_rounds": 3,
                        "include_storyboard": True,
                    },
                )

            assert resp.status_code == 200
            payload = resp.json()
            assert payload["planner_version"] == "deerflow.narrative_plan.v1"
            assert payload["claim_map"]["schema_version"] == "deerflow.claim_map.v1"
            assert payload["self_question_rounds"] == 3
            _, call_kwargs = plan_mock.call_args
            assert call_kwargs["project_id"] == "p"
            assert call_kwargs["section_id"] == "intro"
            assert call_kwargs["self_question_rounds"] == 3
            assert call_kwargs["include_storyboard"] is True


def test_agentic_graph_endpoint(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            with patch(
                "src.gateway.routers.research_writing.run_agentic_research_graph",
                return_value={
                    "orchestrator_version": "deerflow.agentic_graph.v1",
                    "project_id": "p",
                    "section_id": "discussion",
                    "seed_idea": "idea",
                    "max_rounds": 3,
                    "rounds_executed": 2,
                    "reroute_count": 1,
                    "converged": False,
                    "open_gaps": ["need evidence"],
                    "proposed_actions": ["collect new batch"],
                    "final_writer_draft": "conservative draft",
                    "route_trace": ["data-scientist", "experiment-designer", "writer-agent"],
                    "blackboard": [{"agent": "data-scientist"}],
                    "historical_failed_attempts": [],
                    "agents": ["data-scientist", "experiment-designer", "writer-agent"],
                    "artifact_path": "/mnt/user-data/outputs/research-writing/agentic-graph/agentic-graph-p-discussion.json",
                },
            ) as graph_mock:
                resp = client.post(
                    "/api/threads/thread-graph/research/orchestration/agentic-graph/run",
                    json={
                        "project_id": "p",
                        "section_id": "discussion",
                        "seed_idea": "idea",
                        "max_rounds": 3,
                    },
                )

            assert resp.status_code == 200
            payload = resp.json()
            assert payload["orchestrator_version"] == "deerflow.agentic_graph.v1"
            assert payload["project_id"] == "p"
            assert payload["reroute_count"] == 1
            _, call_kwargs = graph_mock.call_args
            assert call_kwargs["project_id"] == "p"
            assert call_kwargs["section_id"] == "discussion"
            assert call_kwargs["seed_idea"] == "idea"
            assert call_kwargs["max_rounds"] == 3


def test_latex_compile_endpoint(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            with patch(
                "src.gateway.routers.research_writing.build_latex_manuscript",
                return_value={
                    "project_id": "p-latex",
                    "section_ids": ["discussion"],
                    "title": "Demo paper",
                    "source_markdown_path": "/mnt/user-data/outputs/research-writing/latex/p-latex.source.md",
                    "tex_path": "/mnt/user-data/outputs/research-writing/latex/p-latex.tex",
                    "pdf_path": "/mnt/user-data/outputs/research-writing/latex/p-latex.pdf",
                    "compile_log_path": "/mnt/user-data/outputs/research-writing/latex/p-latex.compile.log",
                    "compile_status": "success",
                    "compiler": "latexmk",
                    "engine_requested": "auto",
                    "compile_pdf_requested": True,
                    "citation_keys": ["10.1000/demo"],
                    "citation_count": 1,
                    "warning": None,
                    "artifact_path": "/mnt/user-data/outputs/research-writing/latex/p-latex.tex",
                    "summary_artifact_path": "/mnt/user-data/outputs/research-writing/latex/p-latex.json",
                },
            ):
                resp = client.post(
                    "/api/threads/thread-latex/research/latex/compile",
                    json={
                        "project_id": "p-latex",
                        "section_ids": ["discussion"],
                        "compile_pdf": True,
                    },
                )

            assert resp.status_code == 200
            payload = resp.json()
            assert payload["compile_status"] == "success"
            assert payload["tex_path"].endswith(".tex")
            assert payload["pdf_path"].endswith(".pdf")


def test_section_versions_endpoint(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            with patch(
                "src.gateway.routers.research_writing.list_section_versions",
                return_value={
                    "version_schema_version": "deerflow.section_versions.v1",
                    "project_id": "p1",
                    "section_id": "discussion",
                    "total_count": 3,
                    "versions": [
                        {
                            "version_id": "discussion-v1",
                            "version_number": 1,
                            "source": "upsert_section",
                        },
                        {
                            "version_id": "discussion-v2",
                            "version_number": 2,
                            "source": "compile_section",
                        },
                    ],
                    "updated_at": "2026-03-16T00:00:00Z",
                    "artifact_path": "/mnt/user-data/outputs/research-writing/section-versions/p1-discussion.json",
                },
            ) as versions_mock:
                resp = client.get(
                    "/api/threads/thread-version/research/projects/p1/sections/discussion/versions?limit=5"
                )

            assert resp.status_code == 200
            payload = resp.json()
            assert payload["project_id"] == "p1"
            assert payload["section_id"] == "discussion"
            assert payload["total_count"] == 3
            assert payload["version_schema_version"] == "deerflow.section_versions.v1"
            _, kwargs = versions_mock.call_args
            assert kwargs["limit"] == 5


def test_section_rollback_endpoint(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            with patch(
                "src.gateway.routers.research_writing.rollback_section_to_version",
                return_value={
                    "project_id": "p1",
                    "section_id": "discussion",
                    "rolled_back_to_version_id": "discussion-v1",
                    "rolled_back_to_version_number": 1,
                    "new_section_version": 4,
                    "new_history_version_id": "discussion-v4",
                    "diff": {
                        "schema_version": "deerflow.section_change_diff.v1",
                        "triplets": [
                            {
                                "change_type": "modified",
                                "before": "old text",
                                "after": "new text",
                                "evidence_ids": ["ev1"],
                                "citation_ids": ["cit1"],
                                "reason": "rollback",
                            }
                        ],
                    },
                    "section": {
                        "section_id": "discussion",
                        "section_name": "Discussion",
                        "content": "rolled-back content",
                        "version": 4,
                    },
                    "artifact_path": "/mnt/user-data/outputs/research-writing/section-versions/p1-discussion-rollback.json",
                },
            ):
                resp = client.post(
                    "/api/threads/thread-version/research/projects/p1/sections/discussion/rollback",
                    json={"version_id": "discussion-v1"},
                )

            assert resp.status_code == 200
            payload = resp.json()
            assert payload["project_id"] == "p1"
            assert payload["rolled_back_to_version_number"] == 1
            assert payload["section"]["content"] == "rolled-back content"


def test_section_traceability_endpoint(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            with patch(
                "src.gateway.routers.research_writing.get_section_traceability",
                return_value={
                    "trace_schema_version": "deerflow.section_trace.v1",
                    "project_id": "p1",
                    "section_id": "discussion",
                    "generated_at": "2026-03-16T00:00:00Z",
                    "compiled_artifact_path": "/mnt/user-data/outputs/research-writing/compiled/p1-discussion.md",
                    "sentence_links": [
                        {
                            "sentence_id": "s1",
                            "sentence": "Sentence 1",
                            "claim_ids": ["c1"],
                            "evidence_ids": ["ev1"],
                            "citation_ids": ["cit1"],
                            "figure_paths": ["/mnt/user-data/outputs/research-writing/figures/f1.png"],
                            "evidence": [],
                        }
                    ],
                    "claims": [
                        {
                            "claim_id": "c1",
                            "claim_text": "Claim 1",
                            "linked_sentence_ids": ["s1"],
                            "evidence_ids": ["ev1"],
                            "citation_ids": ["cit1"],
                        }
                    ],
                    "evidence": [
                        {
                            "evidence_id": "ev1",
                            "summary": "Evidence 1",
                            "evidence_type": "manual_note",
                            "source_ref": "/mnt/user-data/outputs/research-writing/artifacts/ev1.json",
                            "figure_paths": ["/mnt/user-data/outputs/research-writing/figures/f1.png"],
                            "linked_sentence_ids": ["s1"],
                            "linked_claim_ids": ["c1"],
                        }
                    ],
                    "artifact_path": "/mnt/user-data/outputs/research-writing/compiled/p1-discussion.trace.json",
                },
            ):
                resp = client.get(
                    "/api/threads/thread-version/research/projects/p1/sections/discussion/trace"
                )

            assert resp.status_code == 200
            payload = resp.json()
            assert payload["project_id"] == "p1"
            assert payload["trace_schema_version"] == "deerflow.section_trace.v1"
            assert payload["sentence_links"][0]["sentence_id"] == "s1"


def test_capability_catalog_and_assessment_endpoints(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            with patch(
                "src.gateway.routers.research_writing.get_capability_catalog",
                return_value={
                    "catalog_schema_version": "deerflow.capability_catalog.v1",
                    "generated_at": "2026-03-17T00:00:00Z",
                    "capabilities": [{"capability_id": "claim_engineering", "name": "主张工程"}],
                },
            ):
                catalog_resp = client.get("/api/threads/thread-cap/research/capabilities/catalog")
            assert catalog_resp.status_code == 200
            catalog_payload = catalog_resp.json()
            assert catalog_payload["catalog_schema_version"] == "deerflow.capability_catalog.v1"
            assert catalog_payload["capabilities"][0]["capability_id"] == "claim_engineering"

            with patch(
                "src.gateway.routers.research_writing.assess_project_capabilities",
                return_value={
                    "generated_at": "2026-03-17T00:00:00Z",
                    "project_id": "p1",
                    "section_id": "discussion",
                    "catalog": {"schema_version": "deerflow.capability_catalog.v1", "capabilities": []},
                    "assessment": {"overall_score": 0.81, "status": "pass", "scorecards": []},
                    "artifact_path": "/mnt/user-data/outputs/research-writing/capabilities/assessment-p1-discussion.json",
                },
            ) as assess_mock:
                assess_resp = client.post(
                    "/api/threads/thread-cap/research/capabilities/assess",
                    json={"project_id": "p1", "section_id": "discussion"},
                )
            assert assess_resp.status_code == 200
            assess_payload = assess_resp.json()
            assert assess_payload["project_id"] == "p1"
            assert assess_payload["assessment"]["overall_score"] == 0.81
            _, kwargs = assess_mock.call_args
            assert kwargs["project_id"] == "p1"
            assert kwargs["section_id"] == "discussion"


def test_research_self_play_compliance_policy_and_leaderboard_endpoints(tmp_path):
    paths_instance = _make_paths(tmp_path)

    with (
        patch("src.research_writing.runtime_service.get_paths", return_value=paths_instance),
        patch("src.gateway.path_utils.get_paths", return_value=paths_instance),
    ):
        app = _make_app()
        with TestClient(app) as client:
            with patch(
                "src.gateway.routers.research_writing.run_peer_self_play_training",
                return_value={
                    "schema_version": "deerflow.self_play_training.v1",
                    "generated_at": "2026-03-16T00:00:00Z",
                    "run_name": "peer-self-play",
                    "total_episodes": 2,
                    "accepted_episodes": 1,
                    "hard_negative_count": 1,
                    "hard_negative_rate": 0.5,
                    "episodes": [{"episode_id": "ep-1"}],
                    "hard_negatives": [{"hard_negative_id": "hn-1"}],
                    "artifact_path": "/mnt/user-data/outputs/research-writing/self-play/run.json",
                    "hard_negatives_artifact_path": "/mnt/user-data/outputs/research-writing/self-play/run.hard-negatives.json",
                },
            ):
                self_play_resp = client.post(
                    "/api/threads/thread-p2/research/review/self-play",
                    json={
                        "episodes": [
                            {
                                "episode_id": "ep-1",
                                "manuscript_text": "We prove this always works.",
                                "venue_name": "NeurIPS",
                                "section_id": "discussion",
                            }
                        ],
                        "max_rounds": 2,
                    },
                )
            assert self_play_resp.status_code == 200
            assert self_play_resp.json()["hard_negative_count"] == 1

            with patch(
                "src.gateway.routers.research_writing.audit_project_section_compliance",
                return_value={
                    "project_id": "p1",
                    "section_id": "discussion",
                    "compliance_audit": {
                        "findings": [{"issue_type": "missing_ethics_statement"}],
                        "risk_level": "high",
                    },
                    "artifact_path": "/mnt/user-data/outputs/research-writing/compliance/audit-p1-discussion.json",
                },
            ):
                compliance_resp = client.post(
                    "/api/threads/thread-p2/research/compliance/audit",
                    json={"project_id": "p1", "section_id": "discussion"},
                )
            assert compliance_resp.status_code == 200
            assert compliance_resp.json()["compliance_audit"]["risk_level"] == "high"

            with patch(
                "src.gateway.routers.research_writing.get_project_policy_snapshot",
                return_value={
                    "project_id": "p1",
                    "section_id": "discussion",
                    "policy_snapshot": {
                        "signal_count": 3,
                        "recommended_tone": "conservative",
                    },
                    "artifact_path": "/mnt/user-data/outputs/research-writing/policy/policy-p1-discussion.json",
                },
            ):
                policy_resp = client.get(
                    "/api/threads/thread-p2/research/projects/p1/policy-snapshot?section_id=discussion"
                )
            assert policy_resp.status_code == 200
            assert policy_resp.json()["policy_snapshot"]["signal_count"] == 3

            with patch(
                "src.gateway.routers.research_writing.get_weekly_academic_leaderboard",
                return_value={
                    "schema_version": "deerflow.academic_leaderboard.v1",
                    "cadence": "weekly",
                    "updated_at": "2026-03-16T00:00:00Z",
                    "buckets": [{"discipline": "ai_cs", "venue": "NeurIPS", "entries": []}],
                    "artifact_path": "/mnt/user-data/outputs/research-writing/evals/leaderboard/weekly.json",
                },
            ):
                leaderboard_resp = client.get(
                    "/api/threads/thread-p2/research/evals/academic/leaderboard"
                )
            assert leaderboard_resp.status_code == 200
            assert leaderboard_resp.json()["schema_version"] == "deerflow.research.v1"
