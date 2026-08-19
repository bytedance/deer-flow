"""Runtime precedence and caller filtering for managed subagents."""

from __future__ import annotations

from deerflow.config.subagents_config import CustomSubagentConfig, SubagentOverrideConfig, SubagentsAppConfig
from deerflow.persistence.managed_subagents import ManagedSubagentDefinition
from deerflow.subagents import registry


def _managed(name: str, *, enabled: bool = True) -> ManagedSubagentDefinition:
    return ManagedSubagentDefinition(
        name=name,
        description=f"Managed {name}",
        system_prompt=f"You are {name}.",
        enabled=enabled,
    )


def test_enabled_managed_definitions_join_runtime_catalog(monkeypatch):
    monkeypatch.setattr(registry, "_managed_definitions", lambda **_: [_managed("planner"), _managed("disabled", enabled=False)])
    config = SubagentsAppConfig()

    assert "planner" in registry.get_subagent_names(app_config=config)
    assert "disabled" not in registry.get_subagent_names(app_config=config)
    assert registry.get_subagent_config("planner", app_config=config).system_prompt == "You are planner."


def test_builtin_and_config_definitions_win_name_conflicts(monkeypatch):
    monkeypatch.setattr(registry, "_managed_definitions", lambda **_: [_managed("general-purpose"), _managed("reviewer")])
    config = SubagentsAppConfig(
        custom_agents={
            "reviewer": CustomSubagentConfig(description="Config reviewer", system_prompt="Config wins."),
        }
    )

    names = registry.get_subagent_names(app_config=config)
    assert names.count("general-purpose") == 1
    assert names.count("reviewer") == 1
    assert registry.get_subagent_config("reviewer", app_config=config).system_prompt == "Config wins."


def test_allowed_subagents_is_a_hard_runtime_filter(monkeypatch):
    monkeypatch.setattr(registry, "_managed_definitions", lambda **_: [_managed("planner"), _managed("writer")])
    config = SubagentsAppConfig()

    assert registry.get_subagent_names(app_config=config, allowed_subagents=[]) == []
    assert registry.get_subagent_names(app_config=config, allowed_subagents=["planner"]) == ["planner"]


def test_config_yaml_overrides_remain_explicitly_higher_priority(monkeypatch):
    monkeypatch.setattr(registry, "_managed_definitions", lambda **_: [_managed("planner")])
    config = SubagentsAppConfig(
        agents={"planner": SubagentOverrideConfig(model="configured-model", max_turns=12)},
    )

    resolved = registry.get_subagent_config("planner", app_config=config)
    assert resolved.model == "configured-model"
    assert resolved.max_turns == 12


def test_managed_definitions_cache_reuses_and_invalidates_store_snapshot(monkeypatch):
    class FakeStore:
        def __init__(self):
            self.revision = 1
            self.definitions = [_managed("planner")]
            self.list_calls = 0

        def signature(self):
            return self.revision

        def cache_identity(self):
            return "fake-managed-subagent-store"

        def list(self):
            self.list_calls += 1
            return self.definitions

    store = FakeStore()
    config = SubagentsAppConfig()
    registry._clear_managed_definitions_cache()
    monkeypatch.setattr(registry, "get_managed_subagent_store", lambda *_: store)

    assert "planner" in registry.get_subagent_names(app_config=config)
    assert registry.get_subagent_config("planner", app_config=config).description == "Managed planner"
    assert store.list_calls == 1

    store.revision = 2
    store.definitions = [_managed("writer")]

    assert "writer" in registry.get_subagent_names(app_config=config)
    assert "planner" not in registry.get_subagent_names(app_config=config)
    assert store.list_calls == 2
