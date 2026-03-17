"""Tests for venue-calibrated reviewer simulation and rebuttal planning."""

from __future__ import annotations

from src.research_writing import build_rebuttal_plan, get_venue_profile, render_rebuttal_letter, simulate_reviewer_comments


def test_get_venue_profile():
    profile = get_venue_profile("NeurIPS")
    assert profile.domain == "ai_cs"
    assert "ablation study" in " ".join(profile.experimental_expectations).lower()


def test_simulate_reviewer_comments_for_neurips():
    manuscript = """
    We propose a new model and compare to prior methods.
    Results are strong.
    """
    result = simulate_reviewer_comments(manuscript, "NeurIPS")
    assert result.venue == "NeurIPS"
    assert result.comments
    assert any("Ablation study is missing" in c.content for c in result.comments)


def test_build_rebuttal_plan_and_letter():
    result = simulate_reviewer_comments("Short draft without controls.", "Nature")
    actions = build_rebuttal_plan(result.comments, evidence_map={"R2": ["ev-control-1"]})
    assert len(actions) == len(result.comments)
    assert any(a.action in {"new_experiment", "new_analysis", "clarification", "manuscript_revision"} for a in actions)

    letter = render_rebuttal_letter(result.comments, actions)
    assert "Response to Reviewers" in letter
    assert "Response plan" in letter
    assert "Response category" in letter
