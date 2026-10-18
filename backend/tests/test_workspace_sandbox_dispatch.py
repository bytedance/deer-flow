"""Native sandbox readiness must not preserve stale Run execution authority."""

import asyncio
from contextvars import ContextVar
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401
from test_workspace_mcp import _in_workspace_case

from deerflow.sandbox.local import LocalSandboxProvider

_probe = ContextVar("sandbox_dispatch_fixture")


class ReportModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "offline-native-sandbox-report"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, *args, **kwargs):
        raise AssertionError("native tool main uses the async model")

    async def _agenerate(self, messages, **kwargs):
        if any(isinstance(message, ToolMessage) for message in messages):
            response = AIMessage(content="native report saved")
        else:
            response = AIMessage(
                content="", tool_calls=[{"name": "write_file", "args": {"path": "/mnt/user-data/outputs/readiness-report.txt", "content": "native sandbox research report"}, "id": "actual-write-report", "type": "tool_call"}]
            )
        return ChatResult(generations=[ChatGeneration(message=response)])


class ReadinessProvider(LocalSandboxProvider):
    def acquire(self, thread_id=None, *, user_id=None):
        probe = _probe.get()
        if probe["point"] == "sdk":
            # The composed read-before-write gate may acquire synchronously
            # inside its real thread before the tool's async initialization.
            probe["loop"].call_soon_threadsafe(probe["entered"].set)
            asyncio.run_coroutine_threadsafe(probe["release"].wait(), probe["loop"]).result(20)
        return super().acquire(thread_id, user_id=user_id)

    async def acquire_async(self, thread_id=None, *, user_id=None):
        probe = _probe.get()
        if probe["point"] != "read_gate":
            probe["entered"].set()
            await probe["release"].wait()
        return await super().acquire_async(thread_id, user_id=user_id)


@pytest.mark.parametrize("point", ["ready", "read_gate", "sdk"])
@pytest.mark.parametrize("trigger", ["normal", "member"])
def test_native_sandbox_reauthorizes_after_readiness(native_engine, trigger, point):  # noqa: F811
    from langchain.tools import ToolRuntime
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.config import get_config, get_stream_writer
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.runtime import Runtime

    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from deerflow.authz.workspace import set_current_workspace
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.paths import get_paths
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository
    from deerflow.runtime import MemoryStreamBridge, RunContext, RunManager, run_agent
    from deerflow.runtime.user_context import reset_current_user, set_current_user
    from deerflow.sandbox.lease import ensure_sandbox_lease_owner, get_sandbox_lease_manager
    from deerflow.sandbox.sandbox_provider import reset_sandbox_provider, set_sandbox_provider
    from deerflow.sandbox.tools import ensure_sandbox_initialized_async, write_file_tool

    async def scenario(case):
        config = AppConfig(models=[ModelConfig(name="offline-sandbox", use="test_workspace_sandbox_dispatch:ReportModel", model="offline-sandbox")], sandbox=SandboxConfig(use="test_workspace_sandbox_dispatch:ReadinessProvider"))
        set_app_config(config)
        provider = ReadinessProvider()
        set_sandbox_provider(provider)
        probe = {"entered": asyncio.Event(), "release": asyncio.Event(), "returned": [], "point": point, "gate_returned": False, "loop": asyncio.get_running_loop()}
        probe_token = _probe.set(probe)
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        await threads.create("sandbox-dispatch", user_id="owner")
        manager = RunManager(store=RunRepository(case.sf, workspace_required=True), worker_id="sandbox-dispatch-owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
        async with case.sf() as session:
            principal = await session.get(UserRow, "owner")
        user_token = set_current_user(principal)
        report = get_paths().sandbox_outputs_dir("sandbox-dispatch", user_id="owner") / "readiness-report.txt"
        assert not report.exists()
        task = None
        try:
            record = await manager.create_or_reject("sandbox-dispatch", user_id="owner")

            async def write_report(state, runtime: Runtime):
                ensure_sandbox_lease_owner(runtime.context)
                if point == "sdk":
                    from langchain.agents import create_agent

                    from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
                    from deerflow.models import create_chat_model

                    model = create_chat_model("offline-sandbox", app_config=config)
                    agent = create_agent(model=model, tools=[write_file_tool], middleware=build_lead_runtime_middlewares(app_config=config, user_id="owner"), context_schema=dict)
                    result = await agent.ainvoke(state)
                    assert any(isinstance(message, ToolMessage) and message.content == "OK" for message in result["messages"])
                    probe["returned"].append("OK")
                    return result
                tool_state = dict(state)
                tool_state.update(ThreadDataMiddleware().before_agent(tool_state, runtime))
                tool_runtime = ToolRuntime(state=tool_state, context=runtime.context, config=get_config(), stream_writer=get_stream_writer(), tools=[write_file_tool], tool_call_id="actual-write-report", store=None)
                if point == "read_gate":
                    from langgraph.prebuilt.tool_node import ToolCallRequest

                    from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware

                    await ensure_sandbox_initialized_async(tool_runtime)
                    probe["entered"].set()
                    await probe["release"].wait()
                    request = ToolCallRequest(tool_call={"name": "write_file", "args": {"path": "/mnt/user-data/outputs/readiness-report.txt"}, "id": "actual-write-report"}, tool=write_file_tool, state=tool_state, runtime=tool_runtime)
                    await asyncio.to_thread(ReadBeforeWriteMiddleware()._check_write_gate, request)
                    probe["gate_returned"] = True
                result = await write_file_tool.coroutine(tool_runtime, "/mnt/user-data/outputs/readiness-report.txt", "native sandbox research report")
                probe["returned"].append(result)
                return {"messages": [AIMessage(content=result)]}

            graph = StateGraph(MessagesState, context_schema=dict)
            graph.add_node("write_report", write_report)
            graph.add_edge(START, "write_report")
            graph.add_edge("write_report", END)
            compiled = graph.compile()
            task = asyncio.create_task(
                run_agent(
                    MemoryStreamBridge(),
                    manager,
                    record,
                    ctx=RunContext(checkpointer=None, thread_store=threads, workspace_context=case.original, app_config=config),
                    agent_factory=lambda **kwargs: compiled,
                    graph_input={"messages": [HumanMessage(content="write the research report")]},
                    config={"configurable": {"thread_id": record.thread_id}},
                    thread_incarnation=record.thread_incarnation,
                    stream_modes=["values"],
                )
            )
            record.task = task
            await asyncio.wait_for(probe["entered"].wait(), 15)
            assert not report.exists()
            if trigger == "member":
                async with case.sf() as session:
                    await session.execute(sa.insert(UserRow).values(id="successor", email="successor@example.invalid", email_verified_at=datetime.now(UTC)))
                    await session.commit()
                spaces = WorkspaceRepository(case.sf)
                await spaces.add_member(case.original.workspace_id, "owner", "successor", role="member")
                await spaces.transfer_owner(case.original.workspace_id, "owner", "successor", expected_context=case.original)
            set_current_workspace(case.other)
            probe["release"].set()
            await asyncio.wait_for(task, 15)
            assert report.exists() == (trigger == "normal"), "revoked sandbox tool wrote a report after readiness wait"
            if point == "read_gate":
                assert probe["gate_returned"] == (trigger == "normal"), "read-before-write converted native STOP to fail-open"
            if trigger == "normal":
                assert report.read_text() == "native sandbox research report"
                assert probe["returned"] == ["OK"]
            else:
                assert probe["returned"] == [], "native STOP became a normal tool result"
            assert record.workspace_execution_closed
            assert not get_sandbox_lease_manager(provider)._bindings_by_owner
        finally:
            probe["release"].set()
            if task is not None and not task.done():
                task.cancel()
            if task is not None:
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 15)
            reset_sandbox_provider()
            reset_current_user(user_token)
            _probe.reset(probe_token)
            reset_app_config()

    _in_workspace_case(native_engine, scenario)


@pytest.mark.parametrize("recreate", [False, True])
def test_native_sandbox_thread_recreation_does_not_restore_old_report(native_engine, recreate):  # noqa: F811
    from types import SimpleNamespace

    from langchain.tools import ToolRuntime
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.config import get_config, get_stream_writer
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.runtime import Runtime
    from starlette.requests import Request

    from app.gateway.workspaces.deletion import delete_private_thread
    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.runtime import MemoryStreamBridge, RunContext, RunManager, run_agent
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.user_context import reset_current_user, set_current_user
    from deerflow.sandbox.lease import ensure_sandbox_lease_owner, get_sandbox_lease_manager, run_sync_lifecycle_operation
    from deerflow.sandbox.sandbox_provider import reset_sandbox_provider, set_sandbox_provider
    from deerflow.sandbox.tools import ensure_sandbox_initialized_async, write_file_tool

    async def scenario(case):
        config = AppConfig(models=[], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
        set_app_config(config)
        provider = LocalSandboxProvider()
        set_sandbox_provider(provider)
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        first = await threads.create("sandbox-recreation", user_id="owner")
        store = RunRepository(case.sf, workspace_required=True)
        manager = RunManager(store=store, worker_id="sandbox-recreation-owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
        async with case.sf() as session:
            principal = await session.get(UserRow, "owner")
        user_token = set_current_user(principal)
        observations = []
        cached_state = {}

        async def execute(turn):
            record = await manager.create_or_reject("sandbox-recreation", user_id="owner")

            async def report(state, runtime: Runtime):
                ensure_sandbox_lease_owner(runtime.context)
                tool_state = dict(state)
                tool_state.update(ThreadDataMiddleware().before_agent(tool_state, runtime))
                tool_state.update(cached_state)
                tool_runtime = ToolRuntime(state=tool_state, context=runtime.context, config=get_config(), stream_writer=get_stream_writer(), tools=[write_file_tool], tool_call_id="recreation-report", store=None)
                sandbox = await ensure_sandbox_initialized_async(tool_runtime)
                if turn == 0:
                    result = await write_file_tool.coroutine(tool_runtime, "/mnt/user-data/outputs/report.txt", "private original incarnation report")
                    assert result == "OK"
                else:
                    try:
                        content = await run_sync_lifecycle_operation(sandbox.read_file, "/mnt/user-data/outputs/report.txt")
                    except FileNotFoundError:
                        content = None
                    observations.append(content)
                cached_state["sandbox"] = dict(tool_state["sandbox"])
                return state

            graph = StateGraph(MessagesState, context_schema=dict)
            graph.add_node("report", report)
            graph.add_edge(START, "report")
            graph.add_edge("report", END)
            compiled = graph.compile()
            task = asyncio.create_task(
                run_agent(
                    MemoryStreamBridge(),
                    manager,
                    record,
                    ctx=RunContext(checkpointer=None, thread_store=threads, workspace_context=case.original, app_config=config),
                    agent_factory=lambda **kwargs: compiled,
                    graph_input={"messages": []},
                    config={"configurable": {"thread_id": record.thread_id}},
                    thread_incarnation=record.thread_incarnation,
                    stream_modes=["values"],
                )
            )
            record.task = task
            await task
            assert record.status == "success", "native business node must actually finish"
            assert record.workspace_execution_closed
            assert not get_sandbox_lease_manager(provider)._bindings_by_owner
            return record

        try:
            original = await execute(0)
            assert original.thread_incarnation == first["incarnation"]
            if recreate:
                state = SimpleNamespace(thread_store=threads, run_store=store, run_manager=manager, run_event_store=MemoryRunEventStore(), checkpointer=MemorySaver())
                request = Request({"type": "http", "app": SimpleNamespace(state=state)})
                result = await delete_private_thread(request, "sandbox-recreation")
                assert result["success"]
                replacement = await threads.create("sandbox-recreation", user_id="owner")
                assert replacement["incarnation"] != first["incarnation"]
            next_run = await execute(1)
            assert (next_run.thread_incarnation != original.thread_incarnation) == recreate
            expected = None if recreate else "private original incarnation report"
            assert observations == [expected], "new thread incarnation read a report belonging to its deleted predecessor"
        finally:
            reset_sandbox_provider()
            reset_current_user(user_token)
            reset_app_config()

    _in_workspace_case(native_engine, scenario)
