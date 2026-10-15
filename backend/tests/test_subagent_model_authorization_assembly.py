"""Model fallback must precede tool selection in both native dispatch paths."""

import atexit
import importlib
import importlib.util
import sys
import threading
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.subagents.config import SubagentConfig


@pytest.fixture
def assembly(monkeypatch):
    # conftest pre-mocks the executor to break package import cycles. Load its
    # implementation under an isolated name after the packages are initialized.
    task_module = importlib.import_module("deerflow.tools.builtins.task_tool")
    batch_module = importlib.import_module("deerflow.subagents.batch_service")
    lead_module = importlib.import_module("deerflow.agents.lead_agent.agent")
    tool_module = importlib.import_module("deerflow.tools")
    executor_path = Path(__file__).resolve().parents[1] / "packages/harness/deerflow/subagents/executor.py"
    spec = importlib.util.spec_from_file_location("subagent_model_assembly_executor", executor_path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    captured = {}
    executors = []
    events = []
    real_tools = tool_module.get_available_tools

    def get_tools(**kwargs):
        captured["tool_model"] = kwargs["model_name"]
        return real_tools(**kwargs, include_mcp=False)

    def executor_factory(**kwargs):
        executor = module.SubagentExecutor(**kwargs)
        executors.append(executor)
        monkeypatch.setattr(executor, "execute_async", lambda *args, **kwargs: "child-1")
        monkeypatch.setattr(executor, "_load_skills", AsyncMock(return_value=[]))
        monkeypatch.setattr(executor, "_resolve_skill_authorization", lambda: None)
        return executor

    def create_model(**kwargs):
        captured["model_factory_name"] = kwargs["name"]
        return object()

    def create_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(get_graph=lambda: SimpleNamespace(nodes={}))

    result = module.SubagentResult(task_id="child-1", trace_id="trace-1", status=module.SubagentStatus.COMPLETED, result="done")
    for dispatcher in (task_module, batch_module):
        monkeypatch.setattr(dispatcher, "SubagentExecutor", executor_factory)
        monkeypatch.setattr(dispatcher, "SubagentStatus", module.SubagentStatus)
        monkeypatch.setattr(dispatcher, "get_background_task_result", lambda _: result)
        monkeypatch.setattr(dispatcher, "cleanup_background_task", lambda _: None)
    monkeypatch.setattr(task_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(tool_module, "get_available_tools", get_tools)
    monkeypatch.setattr(module, "create_chat_model", create_model)
    monkeypatch.setattr(module, "create_agent", create_agent)
    # Isolate model authorization from the independent tool/skill policy layers.
    monkeypatch.setattr("deerflow.authz.tool_filter.apply_tool_authorization", lambda tools, **kwargs: (tools, None))
    monkeypatch.setattr("deerflow.authz.runtime.resolve_authorization_provider", lambda _: None)
    yield SimpleNamespace(task=task_module, batch=batch_module, lead=lead_module, captured=captured, executors=executors, events=events)
    atexit.unregister(module._shutdown_isolated_subagent_loop)


def _app_config(vision):
    config = AppConfig(
        models=[
            ModelConfig(name="denied", use="langchain_openai:ChatOpenAI", model="denied", supports_vision=not vision),
            ModelConfig(name="allowed", use="langchain_openai:ChatOpenAI", model="allowed", supports_vision=vision),
        ],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )
    config.authorization.enabled = True
    return config


_IDENTITY = {
    "user_id": "user-1",
    "user_role": "member",
    "oauth_provider": "github",
    "oauth_id": "oauth-1",
    "channel_user_id": "sender-1",
    "is_internal": False,
    "authz_attributes": {"department": "engineering"},
}


async def _dispatch(assembly, monkeypatch, path, app_config):
    agent = SubagentConfig(name="custom", description="Custom agent", model="denied", tools=None, skills=[])
    if path == "task":
        monkeypatch.setattr(assembly.task, "get_subagent_config", lambda *args, **kwargs: agent)
        monkeypatch.setattr(assembly.task, "get_available_subagent_names", lambda **kwargs: ["custom"])
        runtime = SimpleNamespace(
            context={**_IDENTITY, "thread_id": "thread-1", "app_config": app_config},
            state={},
            config={"metadata": {"model_name": "allowed"}},
        )
        return await assembly.task.task_tool.coroutine(runtime=runtime, description="Inspect image", prompt="Inspect image", subagent_type="custom", tool_call_id="call-1")
    repository = SimpleNamespace(
        renew_item_lease=AsyncMock(return_value={"valid": True}),
        finalize_item=AsyncMock(return_value=True),
    )
    service = assembly.batch.SubagentBatchService(
        repository=repository,
        config=SubagentBatchesConfig(),
        runtime_config=SubagentRuntimeConfig(),
        app_config=app_config,
    )
    await service._execute_item(
        {
            "id": "item-1",
            "item_key": "image",
            "prompt": "Inspect image",
            "batch": {
                "id": "batch-1",
                "thread_id": "thread-1",
                "user_id": "user-1",
                "execution_spec": {**_IDENTITY, "parent_model": "allowed", "subagent_config": asdict(agent)},
            },
        }
    )
    return repository


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["task", "batch"])
@pytest.mark.parametrize("vision", [True, False], ids=["text-to-vision", "vision-to-text"])
async def test_fallback_keeps_tools_state_and_middleware_on_one_model(assembly, monkeypatch, path, vision):
    from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware

    app_config = _app_config(vision)
    caller_thread = threading.current_thread()
    decisions = []

    def authorize(name, *, context, app_config):
        assert threading.current_thread() is not caller_thread
        assert context == _IDENTITY
        decisions.append(name)
        return "allowed"

    monkeypatch.setattr(assembly.lead, "_authorize_model_name", authorize)
    await _dispatch(assembly, monkeypatch, path, app_config)
    assert len(assembly.executors) == 1
    executor = assembly.executors[0]
    state, tools, deferred = await executor._build_initial_state("Inspect image")
    await executor._create_agent(tools, deferred_setup=deferred)

    assert assembly.captured["tool_model"] == "allowed"
    assert executor.model_name == "allowed"
    assert assembly.captured["model_factory_name"] == "allowed"
    assert executor.config.model == "denied", "retain the requested profile for attribution"
    assert decisions == ["denied"], "execution must reuse the dispatch decision"
    assert ("view_image" in {tool.name for tool in tools}) is vision
    assert ("view_image" in {tool.name for tool in assembly.captured["tools"]}) is vision
    assert any(isinstance(m, ViewImageMiddleware) for m in assembly.captured["middleware"]) is vision
    assert state["messages"]
    if path == "task":
        assert any(event.get("model_name") == "allowed" for event in assembly.events)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["task", "batch"])
async def test_denied_model_stops_before_tool_assembly_or_launch(assembly, monkeypatch, path):
    app_config = _app_config(True)
    tools = MagicMock(side_effect=AssertionError("tools must not be assembled"))
    monkeypatch.setattr("deerflow.tools.get_available_tools", tools)

    def deny(*args, **kwargs):
        raise ValueError("No authorized model")

    monkeypatch.setattr(assembly.lead, "_authorize_model_name", deny)
    if path == "task":
        with pytest.raises(ValueError, match="No authorized model"):
            await _dispatch(assembly, monkeypatch, path, app_config)
    else:
        repository = await _dispatch(assembly, monkeypatch, path, app_config)
        assert repository.finalize_item.await_args.kwargs["error"] == "No authorized model"
    tools.assert_not_called()
    assert not assembly.executors
