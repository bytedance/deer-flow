"""Runtime precedence and caller filtering for managed subagents."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from deerflow.config.agents_config import AgentConfig
from deerflow.config.subagents_config import CustomSubagentConfig, SubagentOverrideConfig, SubagentsAppConfig
from deerflow.config.tool_config import ToolConfig
from deerflow.persistence.agents.file import FileAgentStore
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


def test_user_store_agents_join_runtime_catalog_with_user_scoping(monkeypatch):
    agent = AgentConfig(
        name="writer",
        description="User writer",
        model=None,
        tool_groups=["web"],
        skills=["style-guide"],
    )
    app_config = SimpleNamespace(
        subagents=SubagentsAppConfig(timeout_seconds=1200, max_turns=80),
        tools=[
            ToolConfig(name="web_search", group="web", use="deerflow.community.search:search"),
            ToolConfig(name="bash", group="bash", use="deerflow.sandbox.tools:bash_tool"),
        ],
    )
    captured = {}

    def list_user_agents(*, user_id=None):
        captured["list_user_id"] = user_id
        return [agent]

    def load_user_agent_record(name, *, user_id=None):
        captured["load"] = (name, user_id)
        return agent, "  You are the writer.  "

    monkeypatch.setattr(registry, "_managed_definitions", lambda **_: [])
    monkeypatch.setattr(registry, "_list_user_agents", list_user_agents)
    monkeypatch.setattr(registry, "_load_user_agent_record", load_user_agent_record)

    assert "writer" in registry.get_subagent_names(app_config=app_config, user_id="user-1")

    resolved = registry.get_subagent_config("writer", app_config=app_config, user_id="user-1")

    assert captured == {
        "list_user_id": "user-1",
        "load": ("writer", "user-1"),
    }
    assert resolved is not None
    assert resolved.description == "User writer"
    assert resolved.system_prompt == "You are the writer."
    assert resolved.tools == ["web_search"]
    assert resolved.skills == ["style-guide"]
    assert resolved.model == "inherit"
    assert set(resolved.disallowed_tools or []) == {"task", "ask_clarification", "present_files"}
    assert resolved.timeout_seconds == 1200
    assert resolved.max_turns == 80


def test_file_store_bridge_keeps_user_agents_isolated(monkeypatch, tmp_path):
    from deerflow.config.paths import Paths

    paths = Paths(base_dir=tmp_path)
    store = FileAgentStore()
    monkeypatch.setattr("deerflow.config.agents_config.get_paths", lambda: paths)
    monkeypatch.setattr("deerflow.persistence.agents.get_agent_store", lambda: store)
    monkeypatch.setattr(registry, "_managed_definitions", lambda **_kwargs: [])

    store.create(
        "writer",
        {"name": "writer", "description": "Alice writer"},
        "You are Alice's writer.",
        user_id="alice",
    )
    store.create(
        "writer",
        {"name": "writer", "description": "Bob writer"},
        "You are Bob's writer.",
        user_id="bob",
    )
    store.create(
        "alice-only",
        {"name": "alice-only", "description": "Alice private agent"},
        "Private to Alice.",
        user_id="alice",
    )

    app_config = SimpleNamespace(subagents=SubagentsAppConfig(), tools=[])
    alice_names = registry.get_subagent_names(app_config=app_config, user_id="alice")
    bob_names = registry.get_subagent_names(app_config=app_config, user_id="bob")
    alice_writer = registry.get_subagent_config("writer", app_config=app_config, user_id="alice")
    bob_writer = registry.get_subagent_config("writer", app_config=app_config, user_id="bob")

    assert "alice-only" in alice_names
    assert "alice-only" not in bob_names
    assert registry.get_subagent_config("alice-only", app_config=app_config, user_id="bob") is None
    assert alice_writer is not None
    assert alice_writer.description == "Alice writer"
    assert alice_writer.system_prompt == "You are Alice's writer."
    assert bob_writer is not None
    assert bob_writer.description == "Bob writer"
    assert bob_writer.system_prompt == "You are Bob's writer."


def test_file_store_bridge_rejects_path_traversal(monkeypatch, tmp_path):
    from deerflow.config.paths import Paths

    store = FileAgentStore()
    monkeypatch.setattr("deerflow.config.agents_config.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("deerflow.persistence.agents.get_agent_store", lambda: store)
    monkeypatch.setattr(registry, "_managed_definitions", lambda **_kwargs: [])

    assert registry.get_subagent_config("../other-user", app_config=SubagentsAppConfig(), user_id="alice") is None


def test_user_store_tool_groups_fail_closed_without_full_app_config(monkeypatch, caplog):
    agent = AgentConfig(name="writer", description="User writer", tool_groups=["web"])
    global_loads = []
    monkeypatch.setattr(registry, "_load_user_agent_record", lambda *_args, **_kwargs: (agent, "User soul"))
    monkeypatch.setattr(registry, "_managed_definitions", lambda **_kwargs: [])
    monkeypatch.setattr(
        "deerflow.config.app_config.get_app_config",
        lambda: (
            global_loads.append(True)
            or SimpleNamespace(
                tools=[ToolConfig(name="web_search", group="web", use="deerflow.community.search:search")],
            )
        ),
    )

    resolved = registry.get_subagent_config("writer", app_config=SubagentsAppConfig(), user_id="user-1")

    assert resolved is not None
    assert resolved.tools == []
    assert global_loads == []
    assert "run without tools" in caplog.text


def test_available_descriptions_use_one_user_store_snapshot(monkeypatch):
    calls = []
    monkeypatch.setattr(registry, "_managed_definitions", lambda **_: [])
    monkeypatch.setattr(
        registry,
        "_list_user_agents",
        lambda *, user_id=None: (
            calls.append(user_id)
            or [
                AgentConfig(name="writer", description="User writer"),
                AgentConfig(name="reviewer", description="User reviewer"),
            ]
        ),
    )

    descriptions = registry.get_available_subagent_descriptions(user_id="user-1")

    assert calls == ["user-1"]
    assert descriptions["writer"] == "User writer"
    assert descriptions["reviewer"] == "User reviewer"


def test_user_store_agents_do_not_shadow_operator_definitions(monkeypatch):
    config = SubagentsAppConfig(
        custom_agents={
            "reviewer": CustomSubagentConfig(description="Config reviewer", system_prompt="Config wins."),
        }
    )
    monkeypatch.setattr(registry, "_managed_definitions", lambda **_: [_managed("planner")])
    monkeypatch.setattr(
        registry,
        "_list_user_agents",
        lambda **_: [
            AgentConfig(name="general-purpose", description="User builtin conflict"),
            AgentConfig(name="reviewer", description="User config conflict"),
            AgentConfig(name="planner", description="User managed conflict"),
            AgentConfig(name="writer", description="User writer"),
        ],
    )
    monkeypatch.setattr(
        registry,
        "_load_user_agent_record",
        lambda name, **_: (AgentConfig(name=name, description="User writer"), "User soul"),
    )

    names = registry.get_subagent_names(app_config=config, user_id="user-1")

    assert names == ["general-purpose", "bash", "reviewer", "planner", "writer"]
    assert registry.get_subagent_config("reviewer", app_config=config, user_id="user-1").system_prompt == "Config wins."
    assert registry.get_subagent_config("planner", app_config=config, user_id="user-1").system_prompt == "You are planner."
    assert registry.get_subagent_config("writer", app_config=config, user_id="user-1").system_prompt == "User soul"


def test_user_store_config_failure_degrades_without_crashing(monkeypatch, caplog):
    def fail_config_load(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        "deerflow.config.agents_config.load_agent_config",
        fail_config_load,
    )

    assert registry._load_user_agent_record("writer", user_id="user-1") is None
    assert "Could not load user-scoped custom agent 'writer'" in caplog.text


def test_user_store_soul_failure_does_not_dispatch_without_identity(monkeypatch, caplog):
    def fail_soul_load(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        "deerflow.config.agents_config.load_agent_config",
        lambda *_args, **_kwargs: AgentConfig(name="writer", description="User writer"),
    )
    monkeypatch.setattr(
        "deerflow.config.agents_config.load_agent_soul",
        fail_soul_load,
    )

    assert registry._load_user_agent_record("writer", user_id="user-1") is None
    assert "Could not load SOUL for user-scoped custom agent 'writer'" in caplog.text


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
