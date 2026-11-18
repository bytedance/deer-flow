"""Native subagent checkpoint history across the real isolated-loop boundary.

The model is deterministic and local. The executor, graph builder, middleware,
SQLite saver, context propagation and background execution are production code.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
import threading
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import var_child_runnable_config
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph

from deerflow.config.app_config import AppConfig
from deerflow.config.paths import Paths
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.runtime.checkpointer.async_provider import make_checkpointer


class _OfflineModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "offline-subagent-checkpoints"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(isinstance(message, ToolMessage) for message in messages):
            answer = AIMessage(content="CHILD_FINAL")
        else:
            answer = AIMessage(content="", tool_calls=[{"name": "echo", "args": {"text": "child evidence"}, "id": "child-call", "type": "tool_call"}])
        return ChatResult(generations=[ChatGeneration(message=answer)])


@tool
async def echo(text: str) -> str:
    """Return deterministic evidence without external side effects."""
    return text


@tool
async def forbidden() -> str:
    """A declaration that the test policy must remove before model binding."""
    pytest.fail("A denied middleware tool executed")


class _CopyingToolMiddleware(AgentMiddleware):
    """Exercise state-preserving and constructor-rebuilding extension copies."""

    def __init__(self, *, rebuild_on_copy: bool = False):
        self.rebuild_on_copy = rebuild_on_copy
        self.tools = [echo, forbidden]

    def __copy__(self):
        clone = type(self)(rebuild_on_copy=self.rebuild_on_copy)
        if not self.rebuild_on_copy:
            clone.__dict__.update(self.__dict__)
        return clone


@pytest.fixture
def native_executor(monkeypatch, tmp_path):
    # conftest supplies an executor stub for collection-time cycles. Import
    # its real dependencies before loading the actual executor for this test.
    import deerflow.agents.thread_state  # noqa: F401
    import deerflow.subagents as package

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("deerflow.config.paths._paths", Paths(str(tmp_path / "home")))
    monkeypatch.delitem(sys.modules, "deerflow.subagents.executor", raising=False)
    monkeypatch.delattr(package, "executor", raising=False)
    module = importlib.import_module("deerflow.subagents.executor")
    monkeypatch.setattr(module, "create_chat_model", lambda **kwargs: _OfflineModel())
    monkeypatch.setattr(module, "build_tracing_callbacks", lambda: [])
    yield module
    module._shutdown_isolated_subagent_loop()
    # importlib installed this attribute outside monkeypatch's tracked writes.
    if getattr(package, "executor", None) is module:
        delattr(package, "executor")


@pytest.fixture
def native_task_tool(native_executor, monkeypatch):
    import deerflow.subagents as package

    # The package export also comes from conftest's executor stub. Restore the
    # real class before loading task_tool with its real polling/cleanup helpers.
    # A separate module avoids changing cached tool references in other suites.
    monkeypatch.setattr(package, "SubagentExecutor", native_executor.SubagentExecutor)
    path = Path(native_executor.__file__).parents[1] / "tools/builtins/task_tool.py"
    spec = importlib.util.spec_from_file_location("_checkpoint_task_tool", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module.task_tool


def _config(tmp_path, *, enabled=True, mode="full"):
    config = AppConfig.model_validate(
        {
            "models": [{"name": "offline", "use": "langchain_openai:ChatOpenAI", "model": "offline", "api_key": "unused"}],
            "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path / "db"), "checkpoint_channel_mode": mode},
            "subagent_runtime": {"checkpoint_enabled": enabled},
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "memory": {"enabled": False},
            "summarization": {"enabled": False},
            "title": {"enabled": False},
        }
    )
    return config


def test_checkpoint_persistence_is_opt_in():
    assert SubagentRuntimeConfig().checkpoint_enabled is False
    assert SubagentRuntimeConfig(checkpoint_enabled=True).checkpoint_enabled is True


@pytest.mark.asyncio
async def test_peer_factory_recovers_after_import_under_temporary_gateway_patch(tmp_path, monkeypatch):
    from deerflow.runtime.checkpointer import async_provider

    @asynccontextmanager
    async def temporary_factory(_config):
        yield object()

    # Load an isolated copy of the production module while the Gateway's
    # resource factory is patched, without replacing its live registry.
    path = Path(__file__).parents[1] / "packages/harness/deerflow/subagents/checkpoints.py"
    spec = importlib.util.spec_from_file_location("_checkpoint_factory_import_probe", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    with monkeypatch.context() as importing:
        importing.setattr(async_provider, "make_checkpointer", temporary_factory)
        spec.loader.exec_module(module)

    config = _config(tmp_path)
    invocation = {"configurable": {"thread_id": "restored-factory-thread"}}
    async with make_checkpointer(config) as parent_saver:
        runtime = module.SubagentCheckpointRuntime(config, parent_saver)
        try:
            await runtime.start()
            builder = StateGraph(MessagesState)
            builder.add_node("reply", lambda _state: {"messages": [AIMessage(content="RESTORED_FACTORY")]})
            builder.add_edge(START, "reply")
            builder.add_edge("reply", END)
            graph = builder.compile(checkpointer=runtime.saver)
            state = await graph.ainvoke({"messages": [HumanMessage(content="Record evidence")]}, invocation)
            assert state["messages"][-1].content == "RESTORED_FACTORY"
        finally:
            await runtime.stop()

    # A fresh reader must find real SQLite history after both writers close.
    async with make_checkpointer(config) as reader:
        saved = await reader.aget_tuple(invocation)
        assert saved is not None
        assert saved.checkpoint["channel_values"]["messages"][-1].content == "RESTORED_FACTORY"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True], ids=["disabled", "enabled"])
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_task_tool_checkpoint_history_reopens_with_delegation_identity(native_task_tool, tmp_path, monkeypatch, enabled, mode):
    from langchain.agents import create_agent

    from deerflow.agents.thread_state import get_thread_state_schema
    from deerflow.runtime.checkpoint_mode import freeze_checkpoint_channel_mode
    from deerflow.subagents.checkpoints import subagent_checkpoint_runtime

    app_config = _config(tmp_path, enabled=enabled, mode=mode)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(app_config.model_dump_json(), encoding="utf-8")
    extensions_path = tmp_path / "extensions_config.json"
    extensions_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [echo])
    freeze_checkpoint_channel_mode(mode)

    class ParentModel(_OfflineModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if any(isinstance(message, ToolMessage) for message in messages):
                answer = AIMessage(content="PARENT_FINAL")
            else:
                answer = AIMessage(
                    content="",
                    tool_calls=[{"id": "outer-call", "name": "task", "args": {"subagent_type": "general-purpose", "prompt": "Use echo once, then report the result", "description": "Offline checkpoint integration"}}],
                )
            return ChatResult(generations=[ChatGeneration(message=answer)])

    async with make_checkpointer(app_config) as saver:
        async with subagent_checkpoint_runtime(app_config, saver):
            parent = create_agent(model=ParentModel(), tools=[native_task_tool], checkpointer=saver, context_schema=dict, state_schema=get_thread_state_schema(mode))
            state = await asyncio.wait_for(
                parent.ainvoke(
                    {"messages": [HumanMessage(content="Delegate the offline work")]},
                    config={"configurable": {"thread_id": "task-history-thread"}, "metadata": {"model_name": "offline", "run_id": "task-parent-run"}},
                    context={"app_config": app_config, "thread_id": "task-history-thread", "run_id": "task-parent-run", "user_id": "task-user", "user_role": "admin"},
                ),
                timeout=25,
            )
            outer_result = next(message for message in state["messages"] if isinstance(message, ToolMessage) and message.tool_call_id == "outer-call")
            assert outer_result.additional_kwargs["subagent_status"] == "completed"
            assert "CHILD_FINAL" in outer_result.content
            assert state["messages"][-1].content == "PARENT_FINAL"
            assert not any(isinstance(message, ToolMessage) and message.tool_call_id == "child-call" for message in state["messages"])

    # Both writer lifetimes have ended: read from a new connection, just as
    # a history consumer does after a Gateway restart.
    async with make_checkpointer(app_config) as reader:
        history = [entry async for entry in reader.alist({"configurable": {"thread_id": "task-history-thread"}})]
        roots = [entry for entry in history if not entry.config["configurable"].get("checkpoint_ns")]
        children = [entry for entry in history if entry.config["configurable"].get("checkpoint_ns")]
        assert roots
        if not enabled:
            assert not children
            return
        assert children
        namespaces = {entry.config["configurable"]["checkpoint_ns"] for entry in children}
        execution_ids = {entry.metadata["deerflow_subagent_execution_id"] for entry in children}
        assert len(namespaces) == len(execution_ids) == 1
        execution_id = next(iter(execution_ids))
        namespace = next(iter(namespaces))
        assert execution_id != "outer-call"
        assert namespace.endswith(f"|deerflow_subagent:{execution_id}")
        assert all(entry.metadata["deerflow_subagent_name"] == "general-purpose" for entry in children)
        assert all(entry.metadata["deerflow_parent_run_id"] == "task-parent-run" for entry in children)
        assert all(entry.metadata["deerflow_subagent_tool_call_id"] == "outer-call" for entry in children)
        root_ids = {entry.checkpoint["id"] for entry in roots}
        assert all(entry.metadata["parents"][""] in root_ids for entry in children)

        child = create_agent(model=_OfflineModel(), tools=[echo], state_schema=get_thread_state_schema(mode), checkpointer=reader)
        restored = await child.aget_state({"configurable": {"thread_id": "task-history-thread", "checkpoint_ns": namespace, "__pregel_checkpointer": reader}})
        messages = restored.values["messages"]
        calls = [call for message in messages if isinstance(message, AIMessage) for call in message.tool_calls]
        assert any(call["id"] == "child-call" and call["name"] == "echo" and call["args"] == {"text": "child evidence"} for call in calls)
        assert any(isinstance(message, ToolMessage) and message.tool_call_id == "child-call" and message.content == "child evidence" for message in messages)
        assert messages[-1].content == "CHILD_FINAL"
        assert all(message.content not in {"Delegate the offline work", "PARENT_FINAL"} for message in messages if isinstance(message.content, str))


@pytest.mark.asyncio
@pytest.mark.parametrize("restriction", ["global", "subagent"])
@pytest.mark.parametrize("rebuild_on_copy", [False, True], ids=["preserving-copy", "rebuilding-copy"])
async def test_delta_middleware_copies_preserve_tool_restrictions(native_executor, tmp_path, monkeypatch, restriction, rebuild_on_copy):
    from deerflow.config.authorization_config import AuthorizationConfig
    from deerflow.config.extensions_config import ConfiguredMiddlewareSpec
    from deerflow.runtime.checkpoint_mode import freeze_checkpoint_channel_mode
    from deerflow.subagents.checkpoints import subagent_checkpoint_runtime
    from deerflow.subagents.config import SubagentConfig

    app_config = _config(tmp_path, mode="delta")
    app_config.extensions.middlewares = [ConfiguredMiddlewareSpec(class_path=f"{__name__}:_CopyingToolMiddleware", kwargs={"rebuild_on_copy": rebuild_on_copy}, apply_to="subagent")]
    if restriction == "global":
        app_config.authorization = AuthorizationConfig.model_validate({"enabled": True, "provider": {"use": "deerflow.authz.rbac:RbacAuthorizationProvider", "config": {"roles": {"user": {"tools": {"allow": "*", "deny": ["forbidden"]}}}}}})
    freeze_checkpoint_channel_mode("delta")
    bound_names = []

    class RecordingModel(_OfflineModel):
        def bind_tools(self, tools, **kwargs):
            bound_names.append([tool.name for tool in tools])
            return self

    monkeypatch.setattr(native_executor, "create_chat_model", lambda **kwargs: RecordingModel())

    async def delegate(_state):
        executor = native_executor.SubagentExecutor(
            config=SubagentConfig(name="copy-policy", description="Check extension copies", skills=[], disallowed_tools=["forbidden"] if restriction == "subagent" else []),
            tools=[echo],
            parent_model="offline",
            thread_id="copy-thread",
            user_id="copy-user",
            user_role="user",
            app_config=app_config,
        )
        execution_id = executor.execute_async("Use echo to return child evidence")
        result = native_executor.get_background_task_result(execution_id)
        try:
            assert await asyncio.to_thread(result.execution_done_event.wait, 15)
            if rebuild_on_copy:
                assert result.status is native_executor.SubagentStatus.FAILED
                assert "forbidden" in result.error
                assert ("not authorized" if restriction == "global" else "final tool set") in result.error
                assert not bound_names
            else:
                assert result.status is native_executor.SubagentStatus.COMPLETED, result.error
                assert bound_names
                assert all("echo" in names and "forbidden" not in names for names in bound_names)
        finally:
            native_executor.cleanup_background_task(result.task_id)
        return {}

    builder = StateGraph(MessagesState)
    builder.add_node("delegate", delegate)
    builder.add_edge(START, "delegate")
    builder.add_edge("delegate", END)
    async with make_checkpointer(app_config) as saver:
        async with subagent_checkpoint_runtime(app_config, saver):
            parent = builder.compile(checkpointer=saver)
            await parent.ainvoke({"messages": [HumanMessage(content="Check tool restrictions")]}, {"configurable": {"thread_id": "copy-thread"}})


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("clone_parent", [False, True])
async def test_parallel_children_reopen_with_execution_identity(native_executor, tmp_path, enabled, mode, clone_parent):
    from deerflow.runtime.checkpoint_mode import freeze_checkpoint_channel_mode
    from deerflow.subagents.checkpoints import subagent_checkpoint_runtime
    from deerflow.subagents.config import SubagentConfig

    app_config = _config(tmp_path, enabled=enabled, mode=mode)
    freeze_checkpoint_channel_mode(mode)
    completed = []
    parent_loop = asyncio.get_running_loop()

    async with make_checkpointer(app_config) as parent_saver:
        async with subagent_checkpoint_runtime(app_config, parent_saver) as runtime:

            async def delegate(_state, config: RunnableConfig):
                # Bind the real SQLite lock to the parent loop through actual
                # contention, and keep it held until both children complete.
                # This stabilizes the original cross-loop failure without
                # injecting an exception or holding a database transaction.
                raw = getattr(parent_saver, "source_saver", parent_saver)
                await raw.lock.acquire()
                waiter = asyncio.create_task(raw.setup())
                await asyncio.sleep(0)
                assert raw.lock._loop is parent_loop
                parent_context = var_child_runnable_config.get()
                parent_namespace = parent_context["configurable"]["checkpoint_ns"]
                inherited_saver = parent_context["configurable"]["__pregel_checkpointer"]
                try:
                    results = []
                    for _ in range(2):
                        executor = native_executor.SubagentExecutor(
                            config=SubagentConfig(name="checkpoint-test", description="Offline checkpoint regression", system_prompt="Use echo once, then answer.", timeout_seconds=30),
                            tools=[echo],
                            parent_model="offline",
                            thread_id="history-thread",
                            run_id=config["metadata"]["run_id"],
                            app_config=app_config,
                        )
                        # Intentionally reused across children and parent runs.
                        execution_id = executor.execute_async("Return evidence", task_id="reused-provider-call")
                        results.append(native_executor.get_background_task_result(execution_id))
                    await asyncio.wait_for(asyncio.gather(*(asyncio.to_thread(result.execution_done_event.wait) for result in results)), timeout=20)
                    for result in results:
                        assert result.status.value == "completed", result.error
                        completed.append((config["metadata"]["run_id"], result.task_id))
                finally:
                    raw.lock.release()
                    await waiter
                    for result in results:
                        native_executor.cleanup_background_task(result.task_id)
                assert var_child_runnable_config.get() is parent_context
                assert parent_context["configurable"]["checkpoint_ns"] == parent_namespace
                assert parent_context["configurable"]["__pregel_checkpointer"] is inherited_saver
                assert "deerflow_subagent_execution_id" not in parent_context["metadata"]
                return {"messages": [AIMessage(content="PARENT_FINAL")]}

            builder = StateGraph(MessagesState)
            builder.add_node("delegate", delegate)
            builder.add_edge(START, "delegate")
            builder.add_edge("delegate", END)
            # Same connection, different saver identity: mirrors the strict
            # serializer allowlist clones used by newer LangGraph releases.
            graph_saver = parent_saver.with_allowlist({("builtins", "dict")}) if clone_parent else parent_saver
            parent = builder.compile(checkpointer=graph_saver)
            for run_id in ("parent-run-1", "parent-run-2"):
                streamed = [
                    message
                    async for message, _ in parent.astream(
                        {"messages": [HumanMessage(content="Delegate")]},
                        config={"configurable": {"thread_id": "history-thread"}, "metadata": {"run_id": run_id}},
                        stream_mode="messages",
                    )
                ]
                assert any(message.content == "PARENT_FINAL" for message in streamed)
                assert all(message.content != "CHILD_FINAL" and not isinstance(message, ToolMessage) for message in streamed)
            if enabled:
                assert runtime.saver is not parent_saver
                assert runtime.loop is not parent_loop
        if enabled:
            assert runtime.closed

    # Fresh resources materialize evidence after both writer lifetimes end.
    async with make_checkpointer(app_config) as reader:
        history = [entry async for entry in reader.alist({"configurable": {"thread_id": "history-thread"}})]
        root = [entry for entry in history if not entry.config["configurable"].get("checkpoint_ns")]
        assert root
        root_ids = {entry.checkpoint["id"] for entry in root}
        assert all(message.content != "CHILD_FINAL" for entry in root for message in entry.checkpoint["channel_values"].get("messages", []))
        children = [entry for entry in history if entry.config["configurable"].get("checkpoint_ns")]
        if not enabled:
            assert not children
            return
        groups = defaultdict(list)
        for entry in children:
            groups[entry.metadata["deerflow_subagent_execution_id"]].append(entry)
        assert set(groups) == {execution_id for _, execution_id in completed}
        namespaces = set()
        for parent_run_id, execution_id in completed:
            entries = groups[execution_id]
            own_namespaces = {entry.config["configurable"]["checkpoint_ns"] for entry in entries}
            assert len(own_namespaces) == 1
            assert not own_namespaces & namespaces
            namespaces.update(own_namespaces)
            assert all(entry.metadata["deerflow_parent_run_id"] == parent_run_id for entry in entries)
            assert all(entry.metadata["deerflow_subagent_tool_call_id"] == "reused-provider-call" for entry in entries)
            assert all(entry.metadata["parents"][""] in root_ids for entry in entries)
            # Use the actual child graph schema to reconstruct full and delta
            # states, rather than expecting raw delta channel blobs to be text.
            from deerflow.agents.thread_state import get_thread_state_schema

            accessor_builder = StateGraph(get_thread_state_schema(mode))
            accessor_builder.add_node("unused", lambda state: {})
            accessor_builder.add_edge(START, "unused")
            accessor_builder.add_edge("unused", END)
            accessor = accessor_builder.compile(checkpointer=reader)
            snapshot = await accessor.aget_state({"configurable": {"thread_id": "history-thread", "checkpoint_ns": next(iter(own_namespaces)), "__pregel_checkpointer": reader}})
            messages = snapshot.values["messages"]
            assert any(isinstance(message, ToolMessage) and "child evidence" in message.content for message in messages)
            assert any(message.content == "CHILD_FINAL" for message in messages)
            assert all(message.content not in {"Delegate", "PARENT_FINAL"} for message in messages if isinstance(message.content, str))


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
async def test_checkpoint_history_only_accepts_sqlite(native_executor, tmp_path, legacy, enabled):
    from deerflow.config.checkpointer_config import CheckpointerConfig
    from deerflow.subagents.checkpoints import subagent_checkpoint_runtime

    config = _config(tmp_path, enabled=enabled)
    async with make_checkpointer(config) as saver:
        # Only exercise admission here: no PostgreSQL driver or server is used.
        # A legacy section must take precedence over the unified SQLite config.
        if legacy:
            config.checkpointer = CheckpointerConfig(type="postgres")
        else:
            config.database.backend = "postgres"
        if enabled:
            with pytest.raises(ValueError, match="only supports file-backed SQLite"):
                async with subagent_checkpoint_runtime(config, saver):
                    pytest.fail("Unsupported checkpoint backend was accepted")
        else:
            async with subagent_checkpoint_runtime(config, saver) as runtime:
                assert runtime is None


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_memory_checkpoint_history_is_rejected(native_executor, tmp_path, legacy):
    from deerflow.subagents.checkpoints import subagent_checkpoint_runtime

    config = _config(tmp_path)
    if legacy:
        from deerflow.config.checkpointer_config import CheckpointerConfig

        config.checkpointer = CheckpointerConfig(type="sqlite", connection_string=":memory:")
    else:
        config.database.backend = "memory"
    async with make_checkpointer(config) as saver:
        with pytest.raises(ValueError, match="persistent|file-backed"):
            async with subagent_checkpoint_runtime(config, saver):
                pytest.fail("Non-persistent checkpoint storage was accepted")


@pytest.mark.asyncio
async def test_partial_host_startup_closes_peer_before_parent(native_executor, tmp_path):
    from deerflow.subagents.checkpoints import _runtimes, subagent_checkpoint_runtime

    config = _config(tmp_path)
    async with make_checkpointer(config) as saver:
        with pytest.raises(RuntimeError, match="later startup failure"):
            async with subagent_checkpoint_runtime(config, saver) as runtime:
                raise RuntimeError("later startup failure")
        assert runtime.closed
        assert id(saver) not in _runtimes
        # Parent resource remains usable after the peer's teardown.
        await saver.setup()


@pytest.mark.asyncio
async def test_gateway_runtime_installs_and_closes_peer(native_executor, tmp_path):
    from fastapi import FastAPI

    from app.gateway.deps import langgraph_runtime
    from deerflow.subagents.checkpoints import _runtimes

    config = _config(tmp_path)
    app = FastAPI()
    async with langgraph_runtime(app, config):
        saver = app.state.checkpointer
        runtime = _runtimes[id(saver)]
        assert runtime.saver is not saver
        assert runtime.loop is not asyncio.get_running_loop()
        assert config.run_events.backend == "memory"
        await saver.setup()
    assert runtime.closed
    assert id(saver) not in _runtimes


@pytest.mark.asyncio
async def test_startup_cancellation_closes_created_peer(native_executor, tmp_path, monkeypatch):
    from deerflow.subagents.checkpoints import SubagentCheckpointRuntime, _runtimes, subagent_checkpoint_runtime

    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()
    opened = []
    original_start = SubagentCheckpointRuntime.start

    async def paused_start(runtime):
        await original_start(runtime)
        opened.append(runtime)
        started.set()
        await asyncio.to_thread(release.wait)

    monkeypatch.setattr(SubagentCheckpointRuntime, "start", paused_start)
    async with make_checkpointer(config) as saver:
        manager = subagent_checkpoint_runtime(config, saver)
        startup = asyncio.create_task(manager.__aenter__())
        try:
            assert await asyncio.to_thread(started.wait, 10)
            startup.cancel()
            await asyncio.sleep(0)
            startup.cancel()
            await asyncio.sleep(0)
            assert not startup.done()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(startup, 10)
        assert opened[0].closed
        assert id(saver) not in _runtimes
        await saver.setup()


@pytest.mark.asyncio
async def test_loop_shutdown_closes_peer_on_owner_loop(native_executor, tmp_path):
    from deerflow.subagents.checkpoints import subagent_checkpoint_runtime

    config = _config(tmp_path)
    async with make_checkpointer(config) as saver:
        async with subagent_checkpoint_runtime(config, saver) as runtime:
            owner = runtime.loop
            await asyncio.to_thread(native_executor._shutdown_isolated_subagent_loop)
            assert runtime.closed
            assert owner.is_closed()
            await saver.setup()


def test_default_sync_parent_keeps_async_child_isolated(native_executor, tmp_path):
    from langgraph.checkpoint.sqlite import SqliteSaver

    from deerflow.subagents.config import SubagentConfig

    config = _config(tmp_path, enabled=False)

    def delegate(_state):
        executor = native_executor.SubagentExecutor(
            config=SubagentConfig(name="checkpoint-test", description="Sync parent regression", system_prompt="Use echo.", timeout_seconds=30),
            tools=[echo],
            parent_model="offline",
            thread_id="sync-thread",
            app_config=config,
        )
        result = executor.execute("Return evidence")
        assert result.status.value == "completed", result.error
        return {"messages": [AIMessage(content="PARENT_DONE")]}

    with SqliteSaver.from_conn_string(str(tmp_path / "sync.sqlite")) as saver:
        builder = StateGraph(MessagesState)
        builder.add_node("delegate", delegate)
        builder.add_edge(START, "delegate")
        builder.add_edge("delegate", END)
        parent = builder.compile(checkpointer=saver)
        state = parent.invoke({"messages": [HumanMessage(content="Delegate")]}, {"configurable": {"thread_id": "sync-thread"}})
        assert state["messages"][-1].content == "PARENT_DONE"


@pytest.mark.asyncio
async def test_shutdown_drains_cancelled_child_and_fences_late_dispatch(native_executor, tmp_path):
    from deerflow.subagents.checkpoints import _runtimes, subagent_checkpoint_runtime
    from deerflow.subagents.config import SubagentConfig

    config = _config(tmp_path)
    entered = threading.Event()
    cleanup_entered = threading.Event()
    release_cleanup = threading.Event()
    results = []
    captured_contexts = []

    @tool("echo")
    async def blocking_echo(text: str) -> str:
        """Pause a deterministic child until shutdown cancels it."""
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_entered.set()
            await asyncio.to_thread(release_cleanup.wait)
        return text

    def executor():
        return native_executor.SubagentExecutor(
            config=SubagentConfig(name="checkpoint-test", description="Shutdown regression", system_prompt="Use echo.", timeout_seconds=30),
            tools=[blocking_echo],
            parent_model="offline",
            thread_id="shutdown-thread",
            run_id="shutdown-parent-run",
            app_config=config,
        )

    async def delegate(_state):
        captured_contexts.append(native_executor._copy_isolated_subagent_context())
        execution_id = executor().execute_async("Pause")
        result = native_executor.get_background_task_result(execution_id)
        results.append(result)
        await asyncio.to_thread(result.execution_done_event.wait)
        return {"messages": [AIMessage(content="PARENT_DONE")]}

    async with make_checkpointer(config) as saver:
        manager = subagent_checkpoint_runtime(config, saver)
        runtime = await manager.__aenter__()
        builder = StateGraph(MessagesState)
        builder.add_node("delegate", delegate)
        builder.add_edge(START, "delegate")
        builder.add_edge("delegate", END)
        parent = builder.compile(checkpointer=saver)
        parent_task = asyncio.create_task(parent.ainvoke({"messages": [HumanMessage(content="Pause")]}, {"configurable": {"thread_id": "shutdown-thread"}}))
        stop = None
        late_result = None
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            stop = asyncio.create_task(manager.__aexit__(None, None, None))
            assert await asyncio.to_thread(cleanup_entered.wait, 10)
            stop.cancel()
            await asyncio.sleep(0)
            stop.cancel()
            await asyncio.sleep(0)
            assert not stop.done()
            assert not runtime.closed
            assert runtime.closing
            await saver.setup()

            late_id = captured_contexts[0].run(executor().execute_async, "Late task")
            late_result = native_executor.get_background_task_result(late_id)
            assert await asyncio.to_thread(late_result.execution_done_event.wait, 10)
            assert late_result.status.value == "failed"
            assert "shutting down" in late_result.error
        finally:
            release_cleanup.set()
            if stop is not None:
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(stop, 10)
            else:
                await manager.__aexit__(None, None, None)
            await asyncio.wait_for(parent_task, 10)
            for result in [*results, *([late_result] if late_result is not None else [])]:
                native_executor.cleanup_background_task(result.task_id)
        assert runtime.closed
        assert id(saver) not in _runtimes
        assert results[0].status.value == "cancelled"
        assert results[0].execution_done_event.is_set()
        await saver.setup()
        # A dispatch context captured before shutdown must remain fenced even
        # after the runtime has been removed from the process registry.
        after_close_id = captured_contexts[0].run(executor().execute_async, "After close")
        after_close = native_executor.get_background_task_result(after_close_id)
        try:
            assert await asyncio.to_thread(after_close.execution_done_event.wait, 10)
            assert after_close.status.value == "failed"
            assert "shutting down" in after_close.error
        finally:
            native_executor.cleanup_background_task(after_close_id)
