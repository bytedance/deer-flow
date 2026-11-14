"""Explicit worker catalogs share native discovery and extension rollback."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from deerflow.config.acp_config import ACPAgentConfig
from deerflow.config.subagents_config import SubagentsAppConfig
from deerflow.extensions.registry import ExtensionRegistry
from deerflow.subagents.registry import get_delegation_targets, get_subagent_config, resolve_worker_plan, validate_worker_catalog
from deerflow.subagents.worker_backends import WorkerCapabilities, WorkerOutcome


class Backend:
    capabilities = WorkerCapabilities()

    def bind(self, name, config, app_config):
        agent = app_config.acp_agents[config["agent"]]
        return {"agent": config["agent"], "launch": agent.model_dump(), "timeout_seconds": agent.timeout_seconds}

    async def execute(self, plan, execution):
        return WorkerOutcome(result=execution.prompt)


@pytest.mark.anyio
async def test_generic_worker_does_not_require_an_acp_agent(monkeypatch, tmp_path):
    import importlib

    from langchain_core.messages import AIMessage

    from deerflow.config.app_config import AppConfig
    from deerflow.subagents.runtime import SubagentRuntime

    class Echo(Backend):
        def bind(self, name, config, app_config):
            return {"timeout_seconds": 30}

    registry = ExtensionRegistry()
    with registry.attributed_to("echo"):
        registry.worker_backend("echo", Echo())
    app = AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, subagents={"workers": {"echo": {"backend": "echo", "description": "Echo"}}})
    runtime = SubagentRuntime.from_app_config(app, extensions=registry.build(), workspace_resolver=lambda *args: tmp_path / args[-1])
    from deerflow.subagents import registry as catalog

    monkeypatch.setattr(catalog, "_managed_definitions", lambda **kwargs: ())
    module = importlib.import_module("deerflow.tools.builtins.task_tool")
    monkeypatch.setattr(module, "get_stream_writer", lambda: lambda event: None)

    async def emit(*args, **kwargs):
        pass

    monkeypatch.setattr(module, "aemit_custom_event", emit)
    bound = module.bind_task_tool(runtime.execution_capacity, app_config=app, extensions=runtime.extensions, workspace_resolver=runtime.workspace_resolver)
    parent = SimpleNamespace(context={"thread_id": "thread"}, config={"metadata": {}}, state={"messages": [AIMessage(id="dispatch", content="", tool_calls=[{"name": "task", "id": "call", "args": {}}])]})
    result = await bound.coroutine(runtime=parent, subagent_type="echo", prompt="echo me", tool_call_id="call")
    message = result.update["messages"][0]
    assert message.additional_kwargs["subagent_status"] == "completed"
    assert message.additional_kwargs["subagent_executor"] == "echo"
    assert message.additional_kwargs["subagent_result_brief"] == "echo me"


def configured(alias="external"):
    return SimpleNamespace(
        subagents=SubagentsAppConfig(workers={alias: {"backend": "acp", "description": "External coder", "config": {"agent": "coder"}}}), acp_agents={"coder": ACPAgentConfig(command="test-acp", description="Test", timeout_seconds=73)}
    )


def test_worker_registration_rolls_back_and_snapshot_is_immutable():
    registry = ExtensionRegistry()
    mark = registry.mark()
    with registry.attributed_to("test"):
        assert registry.worker_backend("acp", Backend()) is True
    snapshot = registry.build()
    registry.rollback_to(mark)
    assert not registry.build().worker_backends
    assert len(snapshot.worker_backends) == 1
    with registry.attributed_to("test"):
        registry.worker_backend("acp", Backend())
    registry.discard("test")
    assert not registry.build().worker_backends


def test_explicit_catalog_allowlist_and_captured_launch(monkeypatch):
    from deerflow.subagents import registry as catalog

    monkeypatch.setattr(catalog, "_managed_definitions", lambda **kwargs: ())
    app = configured()
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        registry.worker_backend("acp", Backend())
    extensions = registry.build()
    validate_worker_catalog(app_config=app, extensions=extensions)
    plan = resolve_worker_plan("external", app_config=app, extensions=extensions)
    assert plan.timeout_seconds == 73
    app.acp_agents["coder"].command = "changed"
    assert plan.config["launch"]["command"] == "test-acp"
    with pytest.raises(TypeError):
        plan.config["launch"]["command"] = "changed"
    assert get_subagent_config("external", app_config=app) is None
    assert [target.name for target in get_delegation_targets(app_config=app, allowed_subagents=["external"])] == ["external"]
    assert not get_delegation_targets(app_config=app, allowed_subagents=[])


def test_conflicts_and_native_overrides_are_rejected(monkeypatch):
    from deerflow.subagents import registry as catalog

    monkeypatch.setattr(catalog, "_managed_definitions", lambda **kwargs: (SimpleNamespace(name="external"),))
    with pytest.raises(ValueError, match="conflicts"):
        validate_worker_catalog(app_config=configured(), extensions=None)
    with pytest.raises(ValueError, match="conflicts"):
        validate_worker_catalog(app_config=configured("general-purpose"), extensions=None)
    with pytest.raises(ValidationError):
        SubagentsAppConfig(workers={"external": {"backend": "acp", "description": "Test", "max_turns": 3}})
    with pytest.raises(ValidationError):
        SubagentsAppConfig(workers={"external": {"backend": "acp", "description": "Test"}}, agents={"external": {"model": "native"}})
