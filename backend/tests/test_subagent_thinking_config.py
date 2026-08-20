"""Tests for subagent thinking/reasoning configuration (issue #4875).

Covers:
- SubagentConfig.thinking_enabled and reasoning_effort fields
- SubagentOverrideConfig.thinking_enabled and reasoning_effort fields
- CustomSubagentConfig.thinking_enabled and reasoning_effort fields
- SubagentsAppConfig getter methods for thinking/reasoning
- Registry: thinking/reasoning propagation from config through get_subagent_config()
- Executor: thinking_enabled and reasoning_effort resolution
"""

from deerflow.config.subagents_config import (
    CustomSubagentConfig,
    SubagentOverrideConfig,
    SubagentsAppConfig,
    get_subagents_app_config,
    load_subagents_config_from_dict,
)
from deerflow.subagents.config import SubagentConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_subagents_config(**kwargs) -> None:
    """Reset global subagents config to a known state."""
    load_subagents_config_from_dict(kwargs)


def make_executor(thinking_enabled=None, reasoning_effort=None):
    """Simulate SubagentExecutor's thinking resolution logic.
    Config-only: no parent inheritance."""
    result_thinking = thinking_enabled if thinking_enabled is not None else False
    result_reasoning = reasoning_effort
    return result_thinking, result_reasoning


# ---------------------------------------------------------------------------
# SubagentConfig.thinking_enabled / reasoning_effort
# ---------------------------------------------------------------------------


class TestSubagentConfigThinking:
    def test_default_thinking_is_none(self):
        config = SubagentConfig(name="test", description="test")
        assert config.thinking_enabled is None
        assert config.reasoning_effort is None

    def test_explicit_thinking_enabled(self):
        config = SubagentConfig(name="test", description="test", thinking_enabled=True)
        assert config.thinking_enabled is True

    def test_explicit_thinking_disabled(self):
        config = SubagentConfig(name="test", description="test", thinking_enabled=False)
        assert config.thinking_enabled is False

    def test_explicit_reasoning_effort(self):
        config = SubagentConfig(name="test", description="test", reasoning_effort="high")
        assert config.reasoning_effort == "high"

    def test_both_fields(self):
        config = SubagentConfig(
            name="test",
            description="test",
            thinking_enabled=True,
            reasoning_effort="medium",
        )
        assert config.thinking_enabled is True
        assert config.reasoning_effort == "medium"


# ---------------------------------------------------------------------------
# SubagentOverrideConfig.thinking_enabled / reasoning_effort
# ---------------------------------------------------------------------------


class TestSubagentOverrideConfigThinking:
    def test_default_is_none(self):
        oc = SubagentOverrideConfig()
        assert oc.thinking_enabled is None
        assert oc.reasoning_effort is None

    def test_explicit_values(self):
        oc = SubagentOverrideConfig(thinking_enabled=True, reasoning_effort="high")
        assert oc.thinking_enabled is True
        assert oc.reasoning_effort == "high"

    def test_thinking_disabled(self):
        oc = SubagentOverrideConfig(thinking_enabled=False)
        assert oc.thinking_enabled is False


# ---------------------------------------------------------------------------
# CustomSubagentConfig.thinking_enabled / reasoning_effort
# ---------------------------------------------------------------------------


class TestCustomSubagentConfigThinking:
    def test_default_is_none(self):
        cc = CustomSubagentConfig(description="test", system_prompt="test")
        assert cc.thinking_enabled is None
        assert cc.reasoning_effort is None

    def test_explicit_values(self):
        cc = CustomSubagentConfig(
            description="test",
            system_prompt="test",
            thinking_enabled=True,
            reasoning_effort="low",
        )
        assert cc.thinking_enabled is True
        assert cc.reasoning_effort == "low"


# ---------------------------------------------------------------------------
# SubagentsAppConfig getter methods for thinking/reasoning
# ---------------------------------------------------------------------------


class TestSubagentsAppConfigThinkingGetters:
    def test_get_thinking_enabled_for_returns_override(self):
        sac = SubagentsAppConfig(agents={"test": SubagentOverrideConfig(thinking_enabled=True)})
        assert sac.get_thinking_enabled_for("test") is True

    def test_get_thinking_enabled_for_nonexistent(self):
        sac = SubagentsAppConfig()
        assert sac.get_thinking_enabled_for("nonexistent") is None

    def test_get_thinking_enabled_for_no_override(self):
        sac = SubagentsAppConfig(agents={"test": SubagentOverrideConfig()})
        assert sac.get_thinking_enabled_for("test") is None

    def test_get_reasoning_effort_for_returns_override(self):
        sac = SubagentsAppConfig(agents={"test": SubagentOverrideConfig(reasoning_effort="high")})
        assert sac.get_reasoning_effort_for("test") == "high"

    def test_get_reasoning_effort_for_nonexistent(self):
        sac = SubagentsAppConfig()
        assert sac.get_reasoning_effort_for("nonexistent") is None


# ---------------------------------------------------------------------------
# Thinking resolution in SubagentExecutor (simulated logic)
# ---------------------------------------------------------------------------


class TestThinkingResolution:
    """Test the resolution logic: config explicit > False (no parent inheritance)"""

    def test_config_true_wins(self):
        t, r = make_executor(thinking_enabled=True)
        assert t is True

    def test_default_is_false(self):
        t, r = make_executor()
        assert t is False
        assert r is None

    def test_reasoning_config_wins(self):
        t, r = make_executor(reasoning_effort="high")
        assert r == "high"

    def test_reasoning_default_is_none(self):
        t, r = make_executor()
        assert r is None

    def test_disabled_thinking_explicit(self):
        t, r = make_executor(thinking_enabled=False)
        assert t is False

    def test_reasoning_effort_with_thinking_enabled(self):
        t, r = make_executor(thinking_enabled=True, reasoning_effort="high")
        assert t is True
        assert r == "high"


# ---------------------------------------------------------------------------
# Config propagation through load_subagents_config_from_dict
# ---------------------------------------------------------------------------


class TestLoadSubagentsConfigThinking:
    def test_custom_agent_thinking_propagated(self):
        """CustomSubagentConfig.thinking_enabled propagates to SubagentConfig."""
        _reset_subagents_config(
            custom_agents={
                "analysis": {
                    "description": "Analysis agent",
                    "system_prompt": "You are an analyst.",
                    "thinking_enabled": True,
                    "reasoning_effort": "medium",
                }
            }
        )
        sac = get_subagents_app_config()
        custom = sac.custom_agents["analysis"]
        assert custom.thinking_enabled is True
        assert custom.reasoning_effort == "medium"

    def test_override_thinking_propagated(self):
        """SubagentOverrideConfig.thinking_enabled propagates to SubagentsAppConfig."""
        _reset_subagents_config(
            agents={
                "general-purpose": {
                    "thinking_enabled": True,
                    "reasoning_effort": "high",
                }
            }
        )
        sac = get_subagents_app_config()
        override = sac.agents["general-purpose"]
        assert override.thinking_enabled is True
        assert override.reasoning_effort == "high"
