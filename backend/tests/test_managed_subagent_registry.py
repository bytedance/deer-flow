"""Runtime precedence and caller filtering for managed subagents."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

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


def test_default_lead_catalog_preserves_builtin_defaults(monkeypatch):
    monkeypatch.setattr(registry, "_managed_definitions", lambda **_: [_managed("planner")])
    config = SubagentsAppConfig()

    assert registry.get_subagent_names(app_config=config) == ["general-purpose", "bash", "planner"]

    general = registry.get_subagent_config("general-purpose", app_config=config)
    assert general is not None
    assert general.tools is None
    assert set(general.disallowed_tools or []) == {"task", "ask_clarification", "present_files"}
    assert general.model == "inherit"
    assert general.max_turns == 150
    assert general.timeout_seconds == 1800

    bash = registry.get_subagent_config("bash", app_config=config)
    assert bash is not None
    assert bash.tools == ["bash", "ls", "read_file", "write_file", "str_replace"]
    assert set(bash.disallowed_tools or []) == {"task", "ask_clarification", "present_files"}
    assert bash.model == "inherit"
    assert bash.max_turns == 60
    assert bash.timeout_seconds == 1800


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
            self.signature_calls = 0
            self.list_calls = 0

        def signature(self):
            self.signature_calls += 1
            return self.revision

        def cache_identity(self):
            return "fake-managed-subagent-store"

        def list(self):
            self.list_calls += 1
            return self.definitions

    store = FakeStore()
    config = SubagentsAppConfig()
    now = [100.0]
    registry._clear_managed_definitions_cache()
    monkeypatch.setattr(registry, "get_managed_subagent_store", lambda *_: store)
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    assert "planner" in registry.get_subagent_names(app_config=config)
    assert registry.get_subagent_config("planner", app_config=config).description == "Managed planner"
    assert store.signature_calls == 1
    assert store.list_calls == 1

    store.revision = 2
    store.definitions = [_managed("writer")]
    now[0] += registry._MANAGED_SIGNATURE_TTL_SECONDS

    assert "writer" in registry.get_subagent_names(app_config=config)
    assert "planner" not in registry.get_subagent_names(app_config=config)
    assert store.signature_calls == 2
    assert store.list_calls == 2


def test_list_subagents_checks_managed_signature_once_per_ttl_window(monkeypatch):
    class FakeStore:
        def __init__(self):
            self.signature_calls = 0
            self.list_calls = 0
            self.definitions = [_managed(f"worker-{index}") for index in range(25)]

        def signature(self):
            self.signature_calls += 1
            return 1

        def cache_identity(self):
            return "signature-ttl-managed-subagent-store"

        def list(self):
            self.list_calls += 1
            return self.definitions

    store = FakeStore()
    config = SubagentsAppConfig()
    registry._clear_managed_definitions_cache()
    monkeypatch.setattr(registry, "get_managed_subagent_store", lambda *_: store)
    monkeypatch.setattr(time, "monotonic", lambda: 100.0)

    configs = registry.list_subagents(app_config=config)

    assert len(configs) == 27
    assert store.signature_calls == 1
    assert store.list_calls == 1


def test_managed_definitions_cache_serializes_concurrent_first_load(monkeypatch):
    class FakeStore:
        def __init__(self):
            self.signature_calls = 0
            self.list_calls = 0

        def signature(self):
            self.signature_calls += 1
            return 1

        def cache_identity(self):
            return "concurrent-managed-subagent-store"

        def list(self):
            self.list_calls += 1
            return [_managed("planner")]

    store = FakeStore()
    config = SubagentsAppConfig()
    registry._clear_managed_definitions_cache()
    monkeypatch.setattr(registry, "get_managed_subagent_store", lambda *_: store)
    monkeypatch.setattr(time, "monotonic", lambda: 100.0)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: registry.get_subagent_names(app_config=config), range(16)))

    assert all("planner" in names for names in results)
    assert store.signature_calls == 1
    assert store.list_calls == 1
