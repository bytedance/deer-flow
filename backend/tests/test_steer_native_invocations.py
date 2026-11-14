"""Steer isolation through native task polling, executor registry, and child graphs."""

import asyncio
import importlib
import sys
import threading
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain.tools import ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ConfigDict

from deerflow.agents.middlewares.run_input_middleware import RunInputAdmissionMiddleware, RunInputMiddleware, manage_current_work
from deerflow.agents.thread_state import ThreadState
from deerflow.config.app_config import AppConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.extensions import EXTENSION_SNAPSHOT_CONTEXT_KEY
from deerflow.extensions.registry import ExtensionRegistry
from deerflow.runtime.runs.input_control import RunInputControl
from deerflow.runtime.runs.inputs import INPUT_CONTEXT_KEY, RunInputs
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.subagents.capacity import SubagentExecutionCapacity
from deerflow.subagents.config import SubagentConfig


class NativeChildModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    label: str
    entered: object
    release: object

    @property
    def _llm_type(self):
        return "offline-native-child"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise AssertionError("The native executor must use the asynchronous graph")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.entered.set()
        assert await asyncio.to_thread(self.release.wait, 30), "Child model was never released"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=f"Native report {self.label}"))])


class NativeLeadModel(BaseChatModel):
    calls: int = 0

    @property
    def _llm_type(self):
        return "offline-native-parent"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls <= 2:
            label = "A" if self.calls == 1 else "B"
            message = AIMessage(content="", id=f"dispatch-{label}", tool_calls=[{"id": "call_0", "name": "task", "args": {"prompt": f"Report {label}", "subagent_type": label}}])
        else:
            message = AIMessage(content="Reports collected")
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.fixture
def native_env(monkeypatch, tmp_path):
    """Restore the real executor after conftest's import-cycle stub, then isolate it."""
    import deerflow.subagents as subagents
    from deerflow.config import app_config as config_module
    from deerflow.config import paths as paths_module

    task_module = importlib.import_module("deerflow.tools.builtins.task_tool")
    old_executor = sys.modules.pop("deerflow.subagents.executor")
    missing = object()
    old_executor_attr = getattr(subagents, "executor", missing)
    try:
        executor = importlib.import_module("deerflow.subagents.executor")
    finally:
        sys.modules["deerflow.subagents.executor"] = old_executor
        if old_executor_attr is missing:
            delattr(subagents, "executor")
        else:
            subagents.executor = old_executor_attr
    monkeypatch.setitem(sys.modules, "deerflow.subagents.executor", executor)
    monkeypatch.setattr(subagents, "executor", executor, raising=False)
    # Reconnect imports captured while conftest's cycle-breaking stub was active.
    for name in ("SubagentExecutor", "SubagentStatus", "cleanup_background_task", "force_cleanup_background_task", "get_background_task_result", "request_cancel_background_task", "run_on_isolated_subagent_loop"):
        monkeypatch.setattr(task_module, name, getattr(executor, name))
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths_module, "_paths", paths_module.Paths(tmp_path / "home"))
    config = AppConfig.model_validate({"models": [{"name": name, "use": "langchain_openai:ChatOpenAI", "model": "offline"} for name in ("A", "B")], "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}})
    monkeypatch.setattr(config_module, "_app_config", config)
    monkeypatch.setattr(config_module, "_app_config_is_custom", True)
    definitions = {name: SubagentConfig(name=name, description="Offline test child", model=name, tools=[], skills=[]) for name in ("A", "B")}
    monkeypatch.setattr(task_module, "get_available_subagent_names", lambda **kwargs: list(definitions))
    monkeypatch.setattr(task_module, "get_subagent_config", lambda name, **kwargs: definitions.get(name))
    entered = {name: threading.Event() for name in definitions}
    release = {name: threading.Event() for name in definitions}
    monkeypatch.setattr(executor, "create_chat_model", lambda name, **kwargs: NativeChildModel(label=name, entered=entered[name], release=release[name]))
    capacity = SubagentExecutionCapacity(SubagentRuntimeConfig(max_running=2))
    env = SimpleNamespace(executor=executor, task=task_module.bind_task_tool(capacity, app_config=config), config=config, entered=entered, release=release)
    try:
        yield env
    finally:
        for event in release.values():
            event.set()
        executor._shutdown_isolated_subagent_loop()


async def _wait(event):
    assert await asyncio.to_thread(event.wait, 20), "The native child did not reach the expected execution boundary"


@pytest.mark.asyncio
@pytest.mark.parametrize("action,first", [("continue", "A"), ("continue", "B"), ("replace", "B"), ("cancel", None)])
async def test_native_reused_call_keeps_its_own_execution(native_env, action, first):
    env = native_env
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    authorized = []

    async def authorize_control(**kwargs):
        authorized.append(kwargs)

    control = RunInputControl(inputs, agent_runs=SimpleNamespace(authorize_control=authorize_control), thread_id="thread", checkpointer=InMemorySaver())
    context = {INPUT_CONTEXT_KEY: control, "app_config": env.config, "run_id": "run", "thread_id": "thread", EXTENSION_SNAPSHOT_CONTEXT_KEY: ExtensionRegistry().build()}
    graph = create_agent(NativeLeadModel(), tools=[env.task], middleware=[RunInputAdmissionMiddleware(), RunInputMiddleware()], state_schema=ThreadState, context_schema=dict, checkpointer=control.checkpointer)
    config = {"configurable": {"thread_id": "thread"}}
    run = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Start A")]}, config, context=context))
    records = []
    try:
        await _wait(env.entered["A"])
        [old] = env.executor.list_background_tasks()
        records.append(old)
        await inputs.submit("steer", "Run B first; retain A for later", "steer")
        await _wait(env.entered["B"])
        [new] = [record for record in env.executor.list_background_tasks() if record.task_id != old.task_id]
        records.append(new)
        assert old.external_task_id == new.external_task_id == "call_0"
        assert old.task_id != new.task_id
        assert not old.execution_done_event.is_set()
        runtime = ToolRuntime(state={}, context=context, config=config, stream_writer=lambda _: None, tool_call_id="control", store=None)

        if action == "cancel":
            run.cancel()
            await asyncio.gather(run, return_exceptions=True)
            await control.close()
            assert old.cancel_event.is_set() and new.cancel_event.is_set()
        elif action == "replace":
            await manage_current_work.coroutine(action="replace", runtime=runtime)
            assert old.cancel_event.is_set()
            assert not new.cancel_event.is_set(), "Replacing held work must not cancel the priority execution"
            assert old.execution_done_event.is_set()
            env.release["B"].set()
        else:
            await manage_current_work.coroutine(action="continue", runtime=runtime)
            env.release[first].set()
            await _wait(old.execution_done_event if first == "A" else new.execution_done_event)
            other = new if first == "A" else old
            assert not other.execution_done_event.is_set()
            assert not other.cancel_event.is_set()
            env.release["B" if first == "A" else "A"].set()

        if action != "cancel":
            result = await asyncio.wait_for(run, 20)
            receipts = [message for message in result["messages"] if message.additional_kwargs.get("origin_task_id") == "call_0"]
            assert len(receipts) == 1
            assert "Native report B" in str(result["messages"])
            assert ("Native report A" in receipts[0].content) == (action == "continue")
            if action == "replace":
                assert len(authorized) == 2
            snapshot = await graph.aget_state(config)
            assert snapshot.values["applied_run_inputs"] == {"run_id": "run", "ids": ["steer"]}
    finally:
        for event in env.release.values():
            event.set()
        if not run.done():
            run.cancel()
        await asyncio.gather(run, return_exceptions=True)
        await control.close()
        for record in records:
            await _wait(record.execution_done_event)
            env.executor.cleanup_background_task(record.task_id)
        assert not env.executor.list_background_tasks()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["close", "replace"])
async def test_direct_preflight_does_not_launch_after_its_invocation_is_stopped(native_env, monkeypatch, action):
    env = native_env
    task_module = importlib.import_module("deerflow.tools.builtins.task_tool")
    catalog_entered, catalog_release = threading.Event(), threading.Event()
    original_lookup = task_module.get_subagent_config

    def gated_catalog(name, **kwargs):
        catalog_entered.set()
        assert catalog_release.wait(20), "Catalog lookup was never released"
        return original_lookup(name, **kwargs)

    monkeypatch.setattr(task_module, "get_subagent_config", gated_catalog)
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    authorized = []

    async def authorize_control(**kwargs):
        authorized.append(kwargs)

    control = RunInputControl(inputs, agent_runs=SimpleNamespace(authorize_control=authorize_control), thread_id="thread", checkpointer=None)
    context = {INPUT_CONTEXT_KEY: control, "app_config": env.config, "run_id": "run", EXTENSION_SNAPSHOT_CONTEXT_KEY: ExtensionRegistry().build()}
    runtime = ToolRuntime(state={}, context=context, config={}, stream_writer=lambda _: None, tool_call_id="call_0", store=None)
    call = asyncio.create_task(env.task.coroutine(runtime=runtime, prompt="Do not launch after cancellation", subagent_type="A", tool_call_id="call_0"))
    try:
        await _wait(catalog_entered)
        assert not env.executor.list_background_tasks()
        if action == "close":
            await control.close()
        else:
            await inputs.submit("steer", "Replace the pending work", "steer")
            await control.deliver({"messages": []})
            await manage_current_work.coroutine(action="replace", runtime=runtime)
            assert len(authorized) == 2
        catalog_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(call, 20)
        assert not env.entered["A"].is_set()
        assert not env.executor.list_background_tasks(), "Stopped preflight must not register a native execution"
    finally:
        catalog_release.set()
        for event in env.release.values():
            event.set()
        if not call.done():
            call.cancel()
        await asyncio.gather(call, return_exceptions=True)
        await control.close()
        for record in env.executor.list_background_tasks():
            env.executor.request_cancel_background_task(record.task_id)
            await _wait(record.execution_done_event)
            env.executor.cleanup_background_task(record.task_id)
