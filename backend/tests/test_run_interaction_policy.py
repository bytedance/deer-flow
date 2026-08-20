from deerflow.agents.run_interaction_policy import RunInteractionPolicy


def test_policy_modes_share_tool_and_prompt_contract():
    interactive = RunInteractionPolicy.resolve({})
    webhook = RunInteractionPolicy.resolve({"run_interaction_mode": "webhook"})
    scheduled = RunInteractionPolicy.resolve({"run_interaction_mode": "scheduled"})

    assert interactive.allows_clarification is True
    assert "ask_clarification" in interactive.prompt_guidance
    assert webhook.allows_clarification is False
    assert scheduled.allows_clarification is False
    for policy in (webhook, scheduled):
        assert "ask_clarification" not in policy.prompt_guidance
        assert "Do not wait for a human response" in policy.prompt_guidance


def test_legacy_non_interactive_fields_resolve_without_breaking_callers():
    assert RunInteractionPolicy.resolve({"non_interactive": True}).mode == "scheduled"
    assert RunInteractionPolicy.resolve({"disable_clarification": True}).mode == "webhook"


def test_explicit_mode_takes_precedence_over_legacy_fields():
    policy = RunInteractionPolicy.resolve({"run_interaction_mode": "interactive", "non_interactive": True})

    assert policy.allows_clarification is True
