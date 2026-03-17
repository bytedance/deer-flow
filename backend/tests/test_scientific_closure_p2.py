"""Tests for P2 professor-grade closure modules."""

from __future__ import annotations

from src.research_writing.ethics_compliance import audit_scientific_compliance
from src.research_writing.policy_learning import learn_policy_from_hitl_decisions
from src.research_writing.project_state import HitlDecision
from src.research_writing.self_play_trainer import SelfPlayEpisodeInput, run_self_play_training


def test_compliance_audit_flags_critical_ethics_and_repro_gaps():
    text = "We prove this causes the outcome in a single-center small sample cohort."
    report = audit_scientific_compliance(text)
    issue_types = {item.issue_type for item in report.findings}
    assert "over_causal_claim" in issue_types
    assert "sample_bias_risk" in issue_types
    assert "missing_ethics_statement" in issue_types
    assert "missing_reproducibility_statement" in issue_types
    assert report.blocked_by_critical is True
    assert report.risk_level == "high"


def test_hitl_policy_learning_converts_feedback_to_strategy_signal():
    decisions = [
        HitlDecision(
            action_id="peer-r1-causal",
            source="Peer Loop Round 1",
            label="reduce causal wording",
            decision="rejected",
            section_id="discussion",
        ),
        HitlDecision(
            action_id="peer-r1-ablation",
            source="Peer Loop Round 1",
            label="add ablation baseline experiment",
            decision="rejected",
            section_id="discussion",
        ),
        HitlDecision(
            action_id="peer-r2-limitation",
            source="Peer Loop Round 2",
            label="add explicit limitations",
            decision="approved",
            section_id="discussion",
        ),
    ]
    snapshot = learn_policy_from_hitl_decisions(decisions, section_id="discussion")
    assert snapshot.signal_count == 3
    assert snapshot.rejection_count == 2
    assert snapshot.require_stronger_validation is True
    assert snapshot.prefer_conservative_claims is True
    assert snapshot.action_stats


def test_self_play_training_mines_hard_negative_examples():
    episodes = [
        SelfPlayEpisodeInput(
            episode_id="ep-1",
            manuscript_text="We prove this always works.",
            venue_name="NeurIPS",
            section_id="discussion",
        )
    ]
    result = run_self_play_training(episodes=episodes, max_rounds=1, run_name="p2-unit")
    assert result.total_episodes == 1
    assert result.hard_negative_count >= 1
    assert result.hard_negatives
    assert result.hard_negatives[0].reasons
