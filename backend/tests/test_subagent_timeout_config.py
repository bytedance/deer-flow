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
    default_subagent_token_budget,
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
        assert override.model is None

    def test_explicit_value(self):
        override = SubagentOverrideConfig(timeout_seconds=300, max_turns=42, model="gpt-5.4")
        assert override.timeout_seconds == 300
        assert override.max_turns == 42
        assert override.model == "gpt-5.4"

    def test_model_accepts_any_non_empty_string(self):
        """Model name is a free-form non-empty string; cross-reference validation
        against the `models:` section happens at registry lookup time."""
        override = SubagentOverrideConfig(model="any-arbitrary-model-name")
        assert override.model == "any-arbitrary-model-name"

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

    def test_rejects_empty_model(self):
        """Empty-string model would silently bypass the `is not None` check and
        reach `create_chat_model(name="")` as a runtime error. Reject at load time
        instead, symmetric with the `ge=1` guard on timeout_seconds / max_turns."""
        with pytest.raises(ValueError):
            SubagentOverrideConfig(model="")

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
        assert config.timeout_seconds == 1800

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

    def test_default_token_budget_coupled_to_summarization_switch(self):
        """The token-budget backstop engages by default (#3857 point 4). Its
        ``max_tokens`` ceiling is coupled to whether subagent summarization is
        on (#3875 Phase 3 review): 1M when compaction runs, 2M otherwise —
        because Phase 2 acknowledged legitimate deep-research runs can exceed
        1M without compaction, so tightening to 1M unconditionally would
        prematurely cap summarization-off deployments."""
        # Default (no summarization): 2M — preserves Phase 2 headroom.
        budget_off = default_subagent_token_budget(summarization_enabled=False)
        assert budget_off.enabled is True
        assert budget_off.max_tokens == 2_000_000
        assert budget_off.warn_threshold == 0.7
        # Summarization on: 1M — compaction justifies the tighter ceiling.
        budget_on = default_subagent_token_budget(summarization_enabled=True)
        assert budget_on.max_tokens == 1_000_000
        # The AppConfig model-level default cannot read summarization.enabled,
        # so it falls back to the no-compaction 2M; the builder recomputes via
        # get_token_budget_for(summarization_enabled=...).
        config = SubagentsAppConfig()
        assert config.token_budget.max_tokens == 2_000_000
        assert config.token_budget.enabled is True

    def test_get_token_budget_for_couples_default_to_summarization(self):
        """``get_token_budget_for`` must re-couple the DEFAULT ceiling to the
        summarization switch, but a user-set budget (global or per-agent) must
        always win regardless of the switch (#3875 Phase 3 review)."""
        # Default global budget → re-coupled.
        config = SubagentsAppConfig()
        assert config.get_token_budget_for("general-purpose", summarization_enabled=True).max_tokens == 1_000_000
        assert config.get_token_budget_for("general-purpose", summarization_enabled=False).max_tokens == 2_000_000

    def test_get_token_budget_for_respects_explicit_global(self):
        """A user-set global ``token_budget`` is respected as-is — the
        summarization coupling only affects the default."""
        from deerflow.config.token_budget_config import TokenBudgetConfig

        config = SubagentsAppConfig(token_budget=TokenBudgetConfig(enabled=True, max_tokens=500_000))
        # Explicit global wins for an agent with no per-agent override.
        assert config.get_token_budget_for("general-purpose", summarization_enabled=True).max_tokens == 500_000
        assert config.get_token_budget_for("general-purpose", summarization_enabled=False).max_tokens == 500_000

    def test_get_token_budget_for_respects_per_agent_override(self):
        """A per-agent ``token_budget`` override wins over both the default and
        the summarization coupling."""
        from deerflow.config.token_budget_config import TokenBudgetConfig

        config = SubagentsAppConfig(
            agents={"bash": SubagentOverrideConfig(token_budget=TokenBudgetConfig(enabled=True, max_tokens=300_000))},
        )
        assert config.get_token_budget_for("bash", summarization_enabled=True).max_tokens == 300_000


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

    def test_get_model_for_returns_none_when_no_override(self):
        """No per-agent model override -> returns None so callers fall back to builtin/parent."""
        config = SubagentsAppConfig(timeout_seconds=900)
        assert config.get_model_for("general-purpose") is None
        assert config.get_model_for("bash") is None
        assert config.get_model_for("unknown-agent") is None

    def test_get_model_for_returns_override_when_set(self):
        config = SubagentsAppConfig(
            timeout_seconds=900,
            agents={
                "general-purpose": SubagentOverrideConfig(model="qwen3.5-35b-a3b"),
                "bash": SubagentOverrideConfig(model="gpt-5.4"),
            },
        )
        assert config.get_model_for("general-purpose") == "qwen3.5-35b-a3b"
        assert config.get_model_for("bash") == "gpt-5.4"

    def test_get_model_for_returns_none_for_omitted_agent(self):
        """An agent not listed in overrides returns None even when other agents have model overrides."""
        config = SubagentsAppConfig(
            timeout_seconds=900,
            agents={"bash": SubagentOverrideConfig(model="gpt-5.4")},
        )
        assert config.get_model_for("general-purpose") is None

    def test_get_model_for_handles_explicit_none(self):
        """Explicit model=None in the override is equivalent to no override."""
        config = SubagentsAppConfig(
            timeout_seconds=900,
            agents={"bash": SubagentOverrideConfig(timeout_seconds=300, model=None)},
        )
        assert config.get_model_for("bash") is None
        # Timeout override is still applied even when model is None.
        assert config.get_timeout_for("bash") == 300


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

    def test_load_with_model_overrides(self):
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "agents": {
                    "general-purpose": {"model": "qwen3.5-35b-a3b"},
                    "bash": {"model": "gpt-5.4", "timeout_seconds": 300},
                },
            }
        )
        cfg = get_subagents_app_config()
        assert cfg.get_model_for("general-purpose") == "qwen3.5-35b-a3b"
        assert cfg.get_model_for("bash") == "gpt-5.4"
        # Other override fields on the same agent must still load correctly.
        assert cfg.get_timeout_for("bash") == 300

    def test_load_empty_dict_uses_defaults(self):
        load_subagents_config_from_dict({})
        cfg = get_subagents_app_config()
        assert cfg.timeout_seconds == 1800
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

    def test_explicit_global_timeout_propagates_to_general_purpose(self):
        """An explicit global timeout (here the non-default 900) propagates to a
        built-in agent, while max_turns still comes from the builtin def (150).
        """
        from deerflow.subagents.registry import get_subagent_config

        _reset_subagents_config(timeout_seconds=900)
        config = get_subagent_config("general-purpose")
        assert config.timeout_seconds == 900
        assert config.max_turns == 150

    def test_builtin_defaults_have_research_headroom(self):
        """Out-of-box defaults (no config.yaml subagents section) must give
        general-purpose enough turns/time for deep research, which previously
        failed with GraphRecursionError at the old max_turns=100 limit.
        """
        from deerflow.subagents.registry import get_subagent_config

        load_subagents_config_from_dict({})  # no subagents config -> model defaults
        config = get_subagent_config("general-purpose")
        assert config.max_turns == 150
        assert config.timeout_seconds == 1800
        # Pin bash too so the config.example.yaml "bash=60" doc cannot drift.
        assert get_subagent_config("bash").max_turns == 60

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

    def test_per_agent_model_override_applied(self):
        from deerflow.subagents.registry import get_subagent_config

        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "agents": {"bash": {"model": "gpt-5.4-mini"}},
            }
        )
        bash_config = get_subagent_config("bash")
        assert bash_config.model == "gpt-5.4-mini"

    def test_omitted_model_keeps_builtin_value(self):
        """When config.yaml has no `model` field for an agent, the builtin default must be preserved."""
        from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
        from deerflow.subagents.registry import get_subagent_config

        builtin_bash_model = BUILTIN_SUBAGENTS["bash"].model
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "agents": {"bash": {"timeout_seconds": 300}},
            }
        )
        bash_config = get_subagent_config("bash")
        assert bash_config.model == builtin_bash_model

    def test_explicit_null_model_keeps_builtin_value(self):
        """An explicit `model: null` in config.yaml is equivalent to omission — builtin wins."""
        from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
        from deerflow.subagents.registry import get_subagent_config

        builtin_bash_model = BUILTIN_SUBAGENTS["bash"].model
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "agents": {"bash": {"model": None}},
            }
        )
        bash_config = get_subagent_config("bash")
        assert bash_config.model == builtin_bash_model

    def test_model_override_does_not_affect_other_agents(self):
        from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
        from deerflow.subagents.registry import get_subagent_config

        builtin_gp_model = BUILTIN_SUBAGENTS["general-purpose"].model
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "agents": {"bash": {"model": "gpt-5.4"}},
            }
        )
        gp_config = get_subagent_config("general-purpose")
        assert gp_config.model == builtin_gp_model

    def test_model_override_preserves_other_fields(self):
        """Applying a model override must leave timeout_seconds / max_turns / name intact."""
        from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
        from deerflow.subagents.registry import get_subagent_config

        original = BUILTIN_SUBAGENTS["bash"]
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "agents": {"bash": {"model": "gpt-5.4-mini"}},
            }
        )
        overridden = get_subagent_config("bash")
        assert overridden.model == "gpt-5.4-mini"
        assert overridden.name == original.name
        assert overridden.description == original.description
        # No timeout / max_turns override was set, so they use global default / builtin.
        assert overridden.timeout_seconds == 900
        assert overridden.max_turns == original.max_turns

    def test_model_override_does_not_mutate_builtin(self):
        """Registry must return a new object, leaving the builtin default intact."""
        from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
        from deerflow.subagents.registry import get_subagent_config

        original_bash_model = BUILTIN_SUBAGENTS["bash"].model
        load_subagents_config_from_dict(
            {
                "timeout_seconds": 900,
                "agents": {"bash": {"model": "gpt-5.4-mini"}},
            }
        )
        _ = get_subagent_config("bash")
        assert BUILTIN_SUBAGENTS["bash"].model == original_bash_model

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
