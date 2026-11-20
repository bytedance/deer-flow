"""Native registry coverage for per-worker reasoning defaults and overrides."""

import pytest

from deerflow.config.subagents_config import CustomSubagentConfig, SubagentOverrideConfig, SubagentsAppConfig
from deerflow.persistence.managed_subagents import ManagedSubagentDefinition
from deerflow.subagents import registry


@pytest.mark.parametrize("source", ["builtin", "config", "managed"])
def test_reasoning_settings_flow_through_registry_without_mutating_definitions(monkeypatch, source):
    name = "general-purpose" if source == "builtin" else "researcher"
    settings = {"thinking_enabled": True, "reasoning_effort": "deep"}
    app_config = SubagentsAppConfig()
    monkeypatch.setattr(registry, "_managed_definitions", lambda **_: [])
    if source == "builtin":
        app_config.agents[name] = SubagentOverrideConfig(**settings)
        original = registry.BUILTIN_SUBAGENTS[name]
    elif source == "config":
        original = CustomSubagentConfig(description="Research", system_prompt="Research the task.", **settings)
        app_config.custom_agents[name] = original
    else:
        original = ManagedSubagentDefinition(name=name, description="Research", system_prompt="Research the task.", **settings)
        monkeypatch.setattr(registry, "_managed_definitions", lambda **_: [original])

    configured = registry.get_subagent_config(name, app_config=app_config)
    assert (configured.thinking_enabled, configured.reasoning_effort) == (True, "deep")

    app_config.agents[name] = SubagentOverrideConfig(thinking_enabled=False, reasoning_effort="lite")
    overridden = registry.get_subagent_config(name, app_config=app_config)
    assert (overridden.thinking_enabled, overridden.reasoning_effort) == (False, "lite")
    assert (configured.thinking_enabled, configured.reasoning_effort) == (True, "deep")
    assert original.thinking_enabled is (None if source == "builtin" else True)
    assert original.reasoning_effort == (None if source == "builtin" else "deep")


def test_unconfigured_workers_keep_reasoning_defaults(monkeypatch):
    monkeypatch.setattr(registry, "_managed_definitions", lambda **_: [])
    configured = registry.get_subagent_config("general-purpose", app_config=SubagentsAppConfig())
    assert configured.thinking_enabled is None
    assert configured.reasoning_effort is None
