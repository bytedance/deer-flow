from deerflow.agents.interaction_policy import (
    ASK_CLARIFICATION_TOOL_NAME,
    RunInteractionMode,
    RunInteractionPolicy,
    resolve_run_interaction_policy,
)


def test_interactive_policy_keeps_clarification_available():
    policy = resolve_run_interaction_policy({})

    assert policy.mode is RunInteractionMode.INTERACTIVE
    assert policy.allows_clarification
    assert policy.disabled_tool_names == frozenset()
    assert "MUST call ask_clarification" in policy.clarification_system


def test_scheduled_policy_disables_tool_and_uses_autonomous_guidance():
    policy = resolve_run_interaction_policy({"context": {"non_interactive": True}})

    assert policy.mode is RunInteractionMode.SCHEDULED
    assert not policy.allows_clarification
    assert policy.disabled_tool_names == frozenset({ASK_CLARIFICATION_TOOL_NAME})
    assert "MUST call ask_clarification" not in policy.clarification_system
    assert "minimal reversible assumptions" in policy.clarification_reminder


def test_github_policy_resolves_as_webhook_without_legacy_flag():
    policy = resolve_run_interaction_policy({"context": {"channel_name": "github", "disable_clarification": True}})

    assert policy.mode is RunInteractionMode.WEBHOOK
    assert not policy.allows_clarification
    assert "issue, pull request, repository, and event context" in policy.clarification_system


def test_explicit_mode_takes_precedence_over_legacy_flags():
    policy = resolve_run_interaction_policy(
        {
            "configurable": {"interaction_mode": "autonomous"},
            "context": {"non_interactive": True, "channel_name": "github"},
        }
    )

    assert policy == RunInteractionPolicy(RunInteractionMode.AUTONOMOUS)
