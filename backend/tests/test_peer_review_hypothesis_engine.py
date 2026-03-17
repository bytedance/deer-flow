"""Tests for peer-review loop and hypothesis reasoning engine."""

from __future__ import annotations

import re

from src.research_writing.citation_registry import CitationRecord, CitationRegistry
from src.research_writing.evidence_store import EvidenceStore, EvidenceUnit
from src.research_writing.hypothesis_engine import generate_hypotheses
from src.research_writing.peer_review_loop import run_peer_review_loop
from src.research_writing.source_of_truth import NumericFact, SourceOfTruthStore


def test_peer_review_loop_resolves_major_scientific_gaps():
    draft = "We prove our method always works and outperforms prior methods."
    result = run_peer_review_loop(
        manuscript_text=draft,
        venue_name="NeurIPS",
        section_id="discussion",
        max_rounds=3,
    )

    assert result.rounds
    assert result.unresolved_issue_count == 0
    assert result.final_decision == "accept"
    lowered = result.final_text.lower()
    assert "ablation" in lowered
    assert "limitation" in lowered
    assert "hypothesis" in lowered
    assert re.search(r"\bprove\b", lowered) is None
    assert "always" not in lowered


def test_peer_review_loop_emits_explainable_rubric_and_evidence_chain():
    draft = "This draft is short and claims definitive causal effects."
    result = run_peer_review_loop(
        manuscript_text=draft,
        venue_name="Nature",
        section_id="discussion",
        max_rounds=2,
    )
    assert result.rounds
    first_round = result.rounds[0]
    assert first_round.detector_name.startswith("IssueDetector")
    assert first_round.planner_name.startswith("RevisionPlanner")
    assert first_round.policy_name.startswith("AreaChairPolicy")
    assert first_round.rubric_scores
    dimensions = {item.dimension for item in first_round.rubric_scores}
    assert {"novelty", "method", "statistics", "ethics", "reproducibility"}.issubset(dimensions)
    assert any(event.stage == "policy" for event in first_round.evidence_chain)


def test_peer_review_loop_reviewer2_personas_drive_multi_round_resolution():
    draft = "We prove this approach always works and generalizes."
    result = run_peer_review_loop(
        manuscript_text=draft,
        venue_name="Nature",
        section_id="discussion",
        max_rounds=3,
        reviewer2_styles=["statistical_tyrant", "methodology_fundamentalist", "domain_traditionalist"],
    )

    assert result.reviewer2_styles == [
        "statistical_tyrant",
        "methodology_fundamentalist",
        "domain_traditionalist",
    ]
    assert len(result.rounds) >= 1
    assert result.unresolved_issue_count == 0
    assert result.final_decision == "accept"
    assert any(round_item.reviewer2_attack_notes for round_item in result.rounds)
    reviewer2_issues = [issue for round_item in result.rounds for issue in round_item.reviewer_issues if issue.reviewer2_style]
    assert reviewer2_issues
    assert any(issue.reviewer2_style == "statistical_tyrant" for issue in reviewer2_issues)
    assert any(issue.reviewer2_style == "methodology_fundamentalist" for issue in reviewer2_issues)
    final_text_lower = result.final_text.lower()
    assert "alternative hypothesis" in final_text_lower
    assert "bias" in final_text_lower
    assert "random seed" in final_text_lower


def test_hypothesis_engine_generates_ranked_candidates(tmp_path):
    evidence_store = EvidenceStore(tmp_path / "evidence.json")
    citation_registry = CitationRegistry(tmp_path / "citations.json")
    source_of_truth = SourceOfTruthStore(tmp_path / "source_of_truth.json")

    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="ev1",
            evidence_type="raw_data",
            summary="Pathway activation signal rises in treated cohorts with robust response separation.",
            source_ref="raw:exp-1",
            citation_ids=["c1"],
        )
    )
    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="ev2",
            evidence_type="paper_passage",
            summary="Independent studies report cohort-specific adaptation under pathway perturbation.",
            source_ref="doi:10.1000/example",
            citation_ids=["c1", "c2"],
        )
    )
    evidence_store.upsert(
        EvidenceUnit(
            evidence_id="ev3",
            evidence_type="paper_passage",
            summary="However, one benchmark reports inconsistent effects under batch shifts.",
            source_ref="doi:10.1000/example-2",
            citation_ids=["c2"],
        )
    )

    citation_registry.upsert(
        CitationRecord(
            citation_id="c1",
            title="Pathway perturbation and downstream response",
            authors=["A. Author"],
            year=2023,
            source="crossref",
            verified=True,
        )
    )
    citation_registry.upsert(
        CitationRecord(
            citation_id="c2",
            title="Batch shift artifacts in cohort studies",
            authors=["B. Author"],
            year=2024,
            source="crossref",
            verified=False,
        )
    )

    source_of_truth.upsert_fact(
        NumericFact(
            fact_id="f1",
            metric="AUROC",
            value=0.87,
            source_artifact="/tmp/auroc.csv",
        )
    )
    source_of_truth.upsert_fact(
        NumericFact(
            fact_id="f2",
            metric="F1",
            value=0.81,
            source_artifact="/tmp/f1.csv",
        )
    )

    bundle = generate_hypotheses(
        evidence_store=evidence_store,
        citation_registry=citation_registry,
        source_of_truth_store=source_of_truth,
        max_hypotheses=5,
    )

    assert len(bundle.hypotheses) == 5
    assert bundle.feature_summary
    assert bundle.synthesis_paragraph
    overall_scores = [candidate.score.overall for candidate in bundle.hypotheses]
    assert overall_scores == sorted(overall_scores, reverse=True)
    assert bundle.hypotheses[0].supporting_evidence_ids
