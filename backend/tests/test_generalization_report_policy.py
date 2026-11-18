"""Evidence and proportional interaction regressions."""

from deerflow.agents.interaction_policy import RunInteractionPolicy
from deerflow.agents.middlewares.receipt_verification import render_citation_verdict, verify_receipt_citations


def test_negated_action_text_is_not_semantically_classified():
    verdict = verify_receipt_citations("I did not modify report.py or run tests.", [])
    assert verdict["no_citation_claims"] is False
    assert verdict["citation_resolved"] is False
    assert "no receipt citations" in render_citation_verdict(verdict)


def test_uncited_tool_execution_is_unresolved_regardless_of_language_or_length():
    receipt = {"id": "r1", "status": "success", "tool_name": "bash"}
    for text in ("42", "No changes were needed.", "??", "x" * 500):
        verdict = verify_receipt_citations(text, [receipt])
        assert verdict["citation_resolved"] is False
        assert "action claims" not in render_citation_verdict(verdict)


def test_interactive_policy_allows_inspection_and_reversible_assumptions():
    policy = RunInteractionPolicy.interactive()
    assert "reversible" in policy.clarification_system
    assert "independent" in policy.clarification_system
    assert "Clarification ALWAYS comes BEFORE action" not in policy.clarification_system
    assert "If anything is unclear" not in policy.thinking_guidance
