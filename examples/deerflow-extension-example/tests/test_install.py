"""What install() registers, and what it refuses to."""

from __future__ import annotations

import pytest
from conftest import FakeRegistry
from deerflow_extension_api import (
    AgentBuildContext,
    AgentScope,
    ExtensionData,
    ExtensionRegistry,
    Placement,
)

from deerflow_extension_example import install
from deerflow_extension_example.lifecycle import SystemCallRecorder, TaskRecorder
from deerflow_extension_example.probes import ProbeContributor
from deerflow_extension_example.service import ROUTE_PREFIX, ExampleService
from deerflow_extension_example.stats import MAX_RECENT_TASKS, RunStats


def test_fake_registry_satisfies_the_published_contract() -> None:
    # The contract Protocol is runtime-checkable, which is what lets a third
    # party verify conformance without the host.
    assert isinstance(FakeRegistry(), ExtensionRegistry)


def test_registers_all_five_contribution_points() -> None:
    registry = FakeRegistry()

    install(registry, {})

    assert len(registry.registered_middlewares) == 1
    assert isinstance(registry.registered_middlewares[0], ProbeContributor)
    assert len(registry.registered_lifecycle) == 1
    assert isinstance(registry.registered_lifecycle[0], TaskRecorder)
    assert len(registry.registered_observers) == 1
    assert isinstance(registry.registered_observers[0], SystemCallRecorder)
    assert len(registry.registered_services) == 1
    assert isinstance(registry.registered_services[0], ExampleService)
    assert len(registry.registered_routers) == 1


def test_router_is_built_eagerly_at_the_declared_prefix() -> None:
    registry = FakeRegistry()

    install(registry, {})

    paths = [route.path for route in registry.registered_routers[0].routes]
    assert paths == [f"{ROUTE_PREFIX}/stats"]


def test_install_declares_the_api_version_it_was_written_against() -> None:
    assert install.__deerflow_api__ == "0.1"
    assert install.__deerflow_name__ == "example"


def test_disabled_registers_nothing_and_does_not_fail() -> None:
    registry = FakeRegistry()

    install(registry, {"enabled": False})

    assert registry.registered_middlewares == []
    assert registry.registered_lifecycle == []
    assert registry.registered_observers == []
    assert registry.registered_services == []
    assert registry.registered_routers == []


def test_malformed_config_fails_loudly_during_install() -> None:
    # The host turns this into a diagnostic naming this extension, and skips it
    # unless the operator marked it `required: true`.
    with pytest.raises(ValueError, match="recent_task_limit"):
        install(FakeRegistry(), {"recent_task_limit": "twenty"})


def test_recent_task_limit_is_clamped() -> None:
    registry = FakeRegistry()
    install(registry, {"recent_task_limit": 10_000})

    app_store = ExtensionData("app")
    registry.registered_middlewares[0].contribute_middlewares(app_store, _lead_ctx())

    assert app_store.get(RunStats).recent_limit == MAX_RECENT_TASKS


def test_contributions_declare_paired_placements_and_scopes() -> None:
    registry = FakeRegistry()
    install(registry, {})

    contributions = registry.registered_middlewares[0].contribute_middlewares(ExtensionData("app"), _lead_ctx())

    declared = [(item.placement, item.scope) for item in contributions]
    assert declared == [
        (Placement.MODEL_LOGICAL, AgentScope.BOTH),
        (Placement.MODEL_PHYSICAL, AgentScope.BOTH),
        (Placement.TOOL_VISIBLE, AgentScope.LEAD),
        (Placement.TOOL_RAW, AgentScope.LEAD),
    ]


def test_the_builder_records_what_the_host_told_it() -> None:
    registry = FakeRegistry()
    install(registry, {})
    app_store = ExtensionData("app")

    registry.registered_middlewares[0].contribute_middlewares(app_store, _lead_ctx())
    registry.registered_middlewares[0].contribute_middlewares(app_store, AgentBuildContext(scope=AgentScope.SUBAGENT, model_name="fast-model"))

    snapshot = app_store.get(RunStats).snapshot()
    assert snapshot["agent_builds"]["by_scope"] == {"lead": 1, "subagent": 1}
    assert snapshot["agent_builds"]["models_seen"] == {"main-model": 1, "fast-model": 1}
    assert snapshot["agent_builds"]["policy_max_subagents_per_run"] == 6


def _lead_ctx() -> AgentBuildContext:
    from deerflow_extension_api import HostPolicySnapshot

    return AgentBuildContext(
        scope=AgentScope.LEAD,
        agent_name="lead-agent",
        model_name="main-model",
        policy=HostPolicySnapshot(max_subagents_per_run=6),
    )
