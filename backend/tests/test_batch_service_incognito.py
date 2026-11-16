"""The batch worker rebuilds the incognito verdict from the durable spec.

A batch item can execute on another process after a restart, where the only
record of the parent run is the stored ``execution_spec``. Reconstructing the
executor's ``incognito`` flag from that spec is what keeps a delegated
incognito run's shared blob writes off across the process boundary, matching
the in-process task-tool propagation.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_extension_task_store_runtime import _subagent_env as _subagent_env

from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.runtime.context_keys import INCOGNITO_CONTEXT_KEY
from deerflow.subagents import batch_service as service_module
from deerflow.tools import tools as assembly


@pytest.mark.asyncio
@pytest.mark.parametrize("incognito", [True, False])
async def test_batch_worker_rebuilds_incognito_marker_from_spec(monkeypatch, _subagent_env, incognito):
    captured = {}
    repo = SimpleNamespace(
        renew_item_lease=AsyncMock(return_value={"valid": True}),
        finalize_item=AsyncMock(return_value=True),
    )
    config = SimpleNamespace(
        tools=[],
        models=[],
        acp_agents={},
        get_model_config=lambda name: None,
        authorization=SimpleNamespace(enabled=False),
        tool_search=SimpleNamespace(enabled=False),
    )
    service = service_module.SubagentBatchService(
        repository=repo,
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(),
        app_config=config,
    )
    spec = {
        "subagent_config": {"name": "researcher", "description": "d", "system_prompt": "p"},
        "parent_model": "model-a",
        "mcp_plugins": [],
        "tool_groups": [],
    }
    if incognito:
        spec[INCOGNITO_CONTEXT_KEY] = True
    item = {
        "id": "item-1",
        "item_key": "key-1",
        "prompt": "research one source",
        "batch": {"id": "batch-1", "thread_id": "thread-1", "user_id": "user-1", "run_id": None, "execution_spec": spec},
    }

    monkeypatch.setattr(assembly, "BUILTIN_TOOLS", [])
    monkeypatch.setattr(assembly, "is_host_bash_allowed", lambda config: False)
    monkeypatch.setattr(assembly, "is_mcp_task_runtime_available", lambda: False)
    monkeypatch.setattr("deerflow.mcp.cache.get_cached_mcp_tools", lambda: [])
    monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *args, **kwargs: "model-a")

    class CaptureExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            return "exec-1"

    monkeypatch.setattr(service_module, "SubagentExecutor", CaptureExecutor)
    monkeypatch.setattr(service_module, "SubagentStatus", _subagent_env.SubagentStatus)
    monkeypatch.setattr(
        service_module,
        "get_background_task_result",
        lambda _: SimpleNamespace(status=service_module.SubagentStatus.COMPLETED, result="done", error=None, stop_reason=None, token_usage_records=None),
    )
    monkeypatch.setattr(service_module, "cleanup_background_task", lambda _: None)

    await service._execute_item(item, lease_owner="claim-1")

    assert repo.finalize_item.await_args.kwargs["succeeded"]
    forwarded = captured["executor_kwargs"].get("incognito")
    if incognito:
        assert forwarded is True
    else:
        assert forwarded is None
