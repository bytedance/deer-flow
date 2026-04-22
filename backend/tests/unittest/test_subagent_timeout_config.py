"""Tests for subagent runtime configuration.

Covers:
- SubagentsAppConfig / SubagentOverrideConfig model validation and defaults
- get_timeout_for() / get_max_turns_for() resolution logic
- load_subagents_config_from_dict() and get_subagents_app_config() singleton
- registry.get_subagent_config() applies config overrides
- registry.list_subagents() applies overrides for all agents
- Polling timeout calculation in task_tool is consistent with config
"""

import pytest

from deerflow.config.subagents_config import (
    SubagentOverrideConfig,
    SubagentsAppConfig,
    get_subagents_app_config,
    load_subagents_config_from_dict,
)
from deerflow.subagents.config import SubagentConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_subagents_config(
    timeout_seconds: int = 900,
    *,
    max_turns: int | None = None,
    agents: dict | None = None,
) -> None:
    """Reset global subagents config to a known state."""
    load_subagents_config_from_dict(
        {
            "timeout_seconds": timeout_seconds,
            "max_turns": max_turns,
            "agents": agents or {},
        }
    )


# ---------------------------------------------------------------------------
# SubagentOverrideConfig
# ---------------------------------------------------------------------------


class TestSubagentOverrideConfig:
    def test_default_is_none(self):
        override = SubagentOverrideConfig()
        assert override.timeout_seconds is None
        assert override.max_turns is None

    def test_explicit_value(self):
        override = SubagentOverrideConfig(timeout_seconds=300, max_turns=42)
        assert override.timeout_seconds == 300
        assert override.max_turns == 42

    def test_rejects_zero(self):
        with pytest.raises(ValueError):
            SubagentOverrideConfig(timeout_seconds=0)
        with pytest.raises(ValueError):
            SubagentOverrideConfig(max_turns=0)

    def test_rejects_negative(self):
        with pytest.raises(ValueError):
            SubagentOverrideConfig(timeout_seconds=-1)
        with pytest.raises(ValueError):
            SubagentOverrideConfig(max_turns=-1)

    def test_minimum_valid_value(self):
        override = SubagentOverrideConfig(timeout_seconds=1, max_turns=1)
        assert override.timeout_seconds == 1
        assert override.max_turns == 1


# ---------------------------------------------------------------------------
# SubagentsAppConfig – defaults and validation
# ---------------------------------------------------------------------------


class TestSubagentsAppConfigDefaults:
    def test_default_timeout(self):
        config = SubagentsAppConfig()
        assert config.timeout_seconds == 900

    def test_default_max_turns_override_is_none(self):
        config = SubagentsAppConfig()
        assert config.max_turns is None

    def test_default_agents_empty(self):
        config = SubagentsAppConfig()
        assert config.agents == {}

    def test_custom_global_runtime_overrides(self):
        config = SubagentsAppConfig(timeout_seconds=1800, max_turns=120)
        assert config.timeout_seconds == 1800
        assert config.max_turns == 120

    def test_rejects_zero_timeout(self):
        with pytest.raises(ValueError):
            SubagentsAppConfig(timeout_seconds=0)
        with pytest.raises(ValueError):
            SubagentsAppConfig(max_turns=0)

    def test_rejects_negative_timeout(self):
        with pytest.raises(ValueError):
            SubagentsAppConfig(timeout_seconds=-60)
        with pytest.raises(ValueError):
            SubagentsAppConfig(max_turns=-60)


# ---------------------------------------------------------------------------
# SubagentsAppConfig resolution helpers
# ---------------------------------------------------------------------------


class TestRuntimeResolution:
    def test_returns_global_default_when_no_override(self):
        config = SubagentsAppConfig(timeout_seconds=600)
        assert config.get_timeout_for("general-purpose") == 600
        assert config.get_timeout_for("bash") == 600
        assert config.get_timeout_for("unknown-agent") == 600
        assert config.get_max_turns_for("general-purpose", 100) == 100
        assert config.get_max_turns_for("bash", 60) == 60

    def test_returns_per_agent_override_when_set(self):
        config = SubagentsAppConfig(
            timeout_seconds=900,
            max_turns=120,
            agents={"bash": SubagentOverrideConfig(timeout_seconds=300, max_turns=80)},
        )
        assert config.get_timeout_for("bash") == 300
        assert config.get_max_turns_for("bash", 60) == 80

    def test_other_agents_still_use_global_default(self):
        config = SubagentsAppConfig(
            timeout_seconds=900,
            max_turns=140,
            agents={"bash": SubagentOverrideConfig(timeout_seconds=300, max_turns=80)},
        )
        assert config.get_timeout_for("general-purpose") == 900
        assert config.get_max_turns_for("general-purpose", 100) == 140

    def test_agent_with_none_override_falls_back_to_global(self):
        config = SubagentsAppConfig(
            timeout_seconds=900,
            max_turns=150,
            agents={"general-purpose": SubagentOverrideConfig(timeout_seconds=None, max_turns=None)},
        )
        assert config.get_timeout_for("general-purpose") == 900
        assert config.get_max_turns_for("general-purpose", 100) == 150

    def test_multiple_per_agent_overrides(self):
        config = SubagentsAppConfig(
            timeout_seconds=900,
            max_turns=120,
            agents={
                "general-purpose": SubagentOverrideConfig(timeout_seconds=1800, max_turns=200),
                "bash": SubagentOverrideConfig(timeout_seconds=120, max_turns=80),
            },
        )
        assert config.get_timeout_for("general-purpose") == 1800
        assert config.get_timeout_for("bash") == 120
        assert config.get_max_turns_for("general-purpose", 100) == 200
        assert config.get_max_turns_for("bash", 60) == 80


# ---------------------------------------------------------------------------
# load_subagents_config_from_dict / get_subagents_app_config singleton
# ---------------------------------------------------------------------------


class TestLoadSubagentsConfig:
    def teardown_method(self):
        """Restore defaults after each test."""
        _reset_subagents_config()

    def test_load_global_timeout(self):
        load_subagents_config_from_dict({"timeout_seconds": 300, "max_turns": 120})
        assert get_subagents_app_config().timeout_seconds == 300
        assert get_subagents_app_config().max_turns == 120

    def test_load_with_per_agent_overrides(self):
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "max_turns": 120,
                "agents": {
                    "general-purpose": {"timeout_seconds": 1800, "max_turns": 200},
                    "bash": {"timeout_seconds": 60, "max_turns": 80},
                },
            }
        )
        cfg = get_subagents_app_config()
        assert cfg.get_timeout_for("general-purpose") == 1800
        assert cfg.get_timeout_for("bash") == 60
        assert cfg.get_max_turns_for("general-purpose", 100) == 200
        assert cfg.get_max_turns_for("bash", 60) == 80

    def test_load_partial_override(self):
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 600,
                "agents": {"bash": {"timeout_seconds": 120, "max_turns": 70}},
            }
        )
        cfg = get_subagents_app_config()
        assert cfg.get_timeout_for("general-purpose") == 600
        assert cfg.get_timeout_for("bash") == 120
        assert cfg.get_max_turns_for("general-purpose", 100) == 100
        assert cfg.get_max_turns_for("bash", 60) == 70

    def test_load_empty_dict_uses_defaults(self):
        load_subagents_config_from_dict({})
        cfg = get_subagents_app_config()
        assert cfg.timeout_seconds == 900
        assert cfg.max_turns is None
        assert cfg.agents == {}

    def test_load_replaces_previous_config(self):
        load_subagents_config_from_dict({"timeout_seconds": 100, "max_turns": 90})
        assert get_subagents_app_config().timeout_seconds == 100
        assert get_subagents_app_config().max_turns == 90

        load_subagents_config_from_dict({"timeout_seconds": 200, "max_turns": 110})
        assert get_subagents_app_config().timeout_seconds == 200
        assert get_subagents_app_config().max_turns == 110

    def test_singleton_returns_same_instance_between_calls(self):
        load_subagents_config_from_dict({"timeout_seconds": 777, "max_turns": 123})
        assert get_subagents_app_config() is get_subagents_app_config()


# ---------------------------------------------------------------------------
# registry.get_subagent_config – runtime overrides applied
# ---------------------------------------------------------------------------


class TestRegistryGetSubagentConfig:
    def teardown_method(self):
        _reset_subagents_config()

    def test_returns_none_for_unknown_agent(self):
        from deerflow.subagents.registry import get_subagent_config

        assert get_subagent_config("nonexistent") is None

    def test_returns_config_for_builtin_agents(self):
        from deerflow.subagents.registry import get_subagent_config

        assert get_subagent_config("general-purpose") is not None
        assert get_subagent_config("bash") is not None

    def test_default_timeout_preserved_when_no_config(self):
        from deerflow.subagents.registry import get_subagent_config

        _reset_subagents_config(timeout_seconds=900)
        config = get_subagent_config("general-purpose")
        assert config.timeout_seconds == 900
        assert config.max_turns == 100

    def test_global_timeout_override_applied(self):
        from deerflow.subagents.registry import get_subagent_config

        _reset_subagents_config(timeout_seconds=1800, max_turns=140)
        config = get_subagent_config("general-purpose")
        assert config.timeout_seconds == 1800
        assert config.max_turns == 140

    def test_per_agent_runtime_override_applied(self):
        from deerflow.subagents.registry import get_subagent_config

        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "max_turns": 120,
                "agents": {"bash": {"timeout_seconds": 120, "max_turns": 80}},
            }
        )
        bash_config = get_subagent_config("bash")
        assert bash_config.timeout_seconds == 120
        assert bash_config.max_turns == 80

    def test_per_agent_override_does_not_affect_other_agents(self):
        from deerflow.subagents.registry import get_subagent_config

        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "max_turns": 120,
                "agents": {"bash": {"timeout_seconds": 120, "max_turns": 80}},
            }
        )
        gp_config = get_subagent_config("general-purpose")
        assert gp_config.timeout_seconds == 900
        assert gp_config.max_turns == 120

    def test_builtin_config_object_is_not_mutated(self):
        """Registry must return a new object, leaving the builtin default intact."""
        from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
        from deerflow.subagents.registry import get_subagent_config

        original_timeout = BUILTIN_SUBAGENTS["bash"].timeout_seconds
        original_max_turns = BUILTIN_SUBAGENTS["bash"].max_turns
        load_subagents_config_from_dict({"timeout_seconds": 42, "max_turns": 88})

        returned = get_subagent_config("bash")
        assert returned.timeout_seconds == 42
        assert returned.max_turns == 88
        assert BUILTIN_SUBAGENTS["bash"].timeout_seconds == original_timeout
        assert BUILTIN_SUBAGENTS["bash"].max_turns == original_max_turns

    def test_config_preserves_other_fields(self):
        """Applying runtime overrides must not change other SubagentConfig fields."""
        from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
        from deerflow.subagents.registry import get_subagent_config

        _reset_subagents_config(timeout_seconds=300, max_turns=140)
        original = BUILTIN_SUBAGENTS["general-purpose"]
        overridden = get_subagent_config("general-purpose")

        assert overridden.name == original.name
        assert overridden.description == original.description
        assert overridden.max_turns == 140
        assert overridden.model == original.model
        assert overridden.tools == original.tools
        assert overridden.disallowed_tools == original.disallowed_tools


# ---------------------------------------------------------------------------
# registry.list_subagents – all agents get overrides
# ---------------------------------------------------------------------------


class TestRegistryListSubagents:
    def teardown_method(self):
        _reset_subagents_config()

    def test_lists_both_builtin_agents(self):
        from deerflow.subagents.registry import list_subagents

        names = {cfg.name for cfg in list_subagents()}
        assert "general-purpose" in names
        assert "bash" in names

    def test_all_returned_configs_get_global_override(self):
        from deerflow.subagents.registry import list_subagents

        _reset_subagents_config(timeout_seconds=123, max_turns=77)
        for cfg in list_subagents():
            assert cfg.timeout_seconds == 123, f"{cfg.name} has wrong timeout"
            assert cfg.max_turns == 77, f"{cfg.name} has wrong max_turns"

    def test_per_agent_overrides_reflected_in_list(self):
        from deerflow.subagents.registry import list_subagents

        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "max_turns": 120,
                "agents": {
                    "general-purpose": {"timeout_seconds": 1800, "max_turns": 200},
                    "bash": {"timeout_seconds": 60, "max_turns": 80},
                },
            }
        )
        by_name = {cfg.name: cfg for cfg in list_subagents()}
        assert by_name["general-purpose"].timeout_seconds == 1800
        assert by_name["bash"].timeout_seconds == 60
        assert by_name["general-purpose"].max_turns == 200
        assert by_name["bash"].max_turns == 80


# ---------------------------------------------------------------------------
# Polling timeout calculation (logic extracted from task_tool)
# ---------------------------------------------------------------------------


class TestPollingTimeoutCalculation:
    """Verify the formula (timeout_seconds + 60) // 5 is correct for various inputs."""

    @pytest.mark.parametrize(
        "timeout_seconds, expected_max_polls",
        [
            (900, 192),  # default 15 min → (900+60)//5 = 192
            (300, 72),  # 5 min → (300+60)//5 = 72
            (1800, 372),  # 30 min → (1800+60)//5 = 372
            (60, 24),  # 1 min → (60+60)//5 = 24
            (1, 12),  # minimum → (1+60)//5 = 12
        ],
    )
    def test_polling_timeout_formula(self, timeout_seconds: int, expected_max_polls: int):
        dummy_config = SubagentConfig(
            name="test",
            description="test",
            system_prompt="test",
            timeout_seconds=timeout_seconds,
        )
        max_poll_count = (dummy_config.timeout_seconds + 60) // 5
        assert max_poll_count == expected_max_polls

    def test_polling_timeout_exceeds_execution_timeout(self):
        """Safety-net polling window must always be longer than the execution timeout."""
        for timeout_seconds in [60, 300, 900, 1800]:
            dummy_config = SubagentConfig(
                name="test",
                description="test",
                system_prompt="test",
                timeout_seconds=timeout_seconds,
            )
            max_poll_count = (dummy_config.timeout_seconds + 60) // 5
            polling_window_seconds = max_poll_count * 5
            assert polling_window_seconds > timeout_seconds
