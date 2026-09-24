"""Pin durable worker plugin tools and execution to one app generation."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from deerflow_extension_api.plugins import ModelTool, PluginContribution
from test_extension_task_store_runtime import _CapturingSubagent
from test_extension_task_store_runtime import _subagent_env as _subagent_env

from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.extensions import get_loaded_extensions, set_loaded_extensions
from deerflow.extensions.plugin_tools import plugin_tool_name
from deerflow.extensions.registry import ExtensionRegistry
from deerflow.subagents import batch_service as service_module
from deerflow.tools import tools as assembly


def _generation(name):
    async def identify(payload, context):
        return name

    registry = ExtensionRegistry()
    with registry.attributed_to("probe"):
        registry.plugin(PluginContribution(namespace=f"probe.{name}", title=name, enabled=True, tools=(ModelTool("identify", "Identify generation", {"type": "object", "properties": {}, "additionalProperties": False}, identify),)))
    return registry.build()


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement,explicit_snapshot,late_replace,empty", [(False, False, False, False), (True, False, False, False), (True, True, False, False), (False, False, True, False), (True, True, True, True)])
async def test_batch_keeps_its_construction_snapshot(monkeypatch, _subagent_env, replacement, explicit_snapshot, late_replace, empty):
    original = get_loaded_extensions()
    a, b = _generation("alpha"), _generation("beta")
    if empty:
        a = ExtensionRegistry().build()
    monkeypatch.setattr("deerflow.extensions._loaded", a)
    if explicit_snapshot:
        set_loaded_extensions(b)
    config = SimpleNamespace(tools=[], models=[], acp_agents={}, get_model_config=lambda name: None, authorization=SimpleNamespace(enabled=False), tool_search=SimpleNamespace(enabled=False))
    seen = {}
    captured = {}
    repo = SimpleNamespace(renew_item_lease=AsyncMock(return_value={"valid": True}), finalize_item=AsyncMock(return_value=True))
    service = service_module.SubagentBatchService(repository=repo, config=SubagentBatchesConfig(), runtime_config=SubagentRuntimeConfig(), app_config=config, **({"extensions": a} if explicit_snapshot else {}))
    item = {
        "id": "item-1",
        "item_key": "key-1",
        "prompt": "identify",
        "batch": {
            "id": "batch-1",
            "thread_id": "thread-1",
            "user_id": "user-1",
            "run_id": None,
            "execution_spec": {"subagent_config": {"name": "researcher", "description": "d", "system_prompt": "p"}, "parent_model": "model-a", "mcp_plugins": [], "tool_groups": ["extensions"]},
        },
    }
    real_assembly = assembly.get_available_tools
    monkeypatch.setattr(assembly, "BUILTIN_TOOLS", [])
    monkeypatch.setattr(assembly, "is_host_bash_allowed", lambda config: False)
    monkeypatch.setattr(assembly, "is_mcp_task_runtime_available", lambda: False)
    monkeypatch.setattr("deerflow.mcp.cache.get_cached_mcp_tools", lambda: [])
    monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *args, **kwargs: "model-a")

    def assemble(**kwargs):
        kwargs["include_mcp"] = False
        tools = real_assembly(**kwargs)
        captured["tool_names"] = [t.name for t in tools]
        return tools

    monkeypatch.setattr("deerflow.tools.get_available_tools", assemble)

    class CaptureExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            return "exec-1"

    monkeypatch.setattr(service_module, "SubagentExecutor", CaptureExecutor)
    monkeypatch.setattr(service_module, "SubagentStatus", _subagent_env.SubagentStatus)
    monkeypatch.setattr(service_module, "get_background_task_result", lambda _: SimpleNamespace(status=service_module.SubagentStatus.COMPLETED, result="done", error=None, stop_reason=None, token_usage_records=None))
    monkeypatch.setattr(service_module, "cleanup_background_task", lambda _: None)

    async def initial(self, task):
        return ({}, self.tools, None)

    def create(self, tools, *, deferred_setup=None, extensions=None):
        seen["extensions"] = extensions
        return _CapturingSubagent(seen)

    monkeypatch.setattr(_subagent_env.SubagentExecutor, "_build_initial_state", initial)
    monkeypatch.setattr(_subagent_env.SubagentExecutor, "_create_agent", create)
    try:
        set_loaded_extensions(b if replacement else a)
        await service._execute_item(item)
        assert repo.finalize_item.await_args.kwargs["succeeded"]
        if late_replace:
            set_loaded_extensions(b)
        executor = _subagent_env.SubagentExecutor(**captured["executor_kwargs"])
        result = await executor._aexecute("identify")
        assert result.status == _subagent_env.SubagentStatus.COMPLETED, result.error
        assert captured["tool_names"] == ([] if empty else [plugin_tool_name("probe.alpha", "identify")])
        assert seen["extensions"] is a
        # Replay the same durable record under a new worker after a restart.
        # The record carries no Python snapshot; the new worker owns generation B.
        original_spec = deepcopy(item["batch"]["execution_spec"])
        restarted = service_module.SubagentBatchService(repository=repo, config=SubagentBatchesConfig(), runtime_config=SubagentRuntimeConfig(), app_config=config, extensions=b)
        set_loaded_extensions(a)
        await restarted._execute_item(item)
        executor = _subagent_env.SubagentExecutor(**captured["executor_kwargs"])
        result = await executor._aexecute("identify")
        assert result.status == _subagent_env.SubagentStatus.COMPLETED, result.error
        assert seen["extensions"] is b
        assert captured["tool_names"] == [plugin_tool_name("probe.beta", "identify")]
        assert item["batch"]["execution_spec"] == original_spec
    finally:
        set_loaded_extensions(original)
