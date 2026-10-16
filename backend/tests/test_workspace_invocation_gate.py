"""Real native Agent/model/tool admission before an observable file effect."""

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

_probe = ContextVar("invocation_fixture_probe")


class ProbeModel(BaseChatModel):
    purpose: str = "agent"
    max_retries: int = 9

    @property
    def _llm_type(self):
        return "deterministic-native-invocation"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, *args, **kwargs):
        raise AssertionError("native main must invoke the async provider")

    async def _agenerate(self, messages, **kwargs):
        probe = _probe.get()
        probe["model_calls"] += 1
        if self.purpose == "system" or any(isinstance(message, ToolMessage) for message in messages):
            message = AIMessage(content="native research report is ready")
        else:
            message = AIMessage(content="", tool_calls=[{"name": "save_fixture_report", "args": {}, "id": "native-call-1", "type": "tool_call"}])
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.parametrize("point", ["tool", "model", "system", "queue"])
@pytest.mark.parametrize("trigger", ["normal", "member"])
def test_native_invocation_reauthorizes_dispatch(native_engine, tmp_path, trigger, point):  # noqa: F811
    from langchain.agents import create_agent
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.messages import HumanMessage
    from langchain_core.rate_limiters import BaseRateLimiter
    from langchain_core.tools import tool
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.models import create_chat_model
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.model import WorkspaceOperationOutboxRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository
    from deerflow.runtime import MemoryStreamBridge, RunContext, RunManager, run_agent
    from deerflow.runtime.invocation import WorkerInvocationDenied
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    async def scenario(case):
        app_config = AppConfig(models=[ModelConfig(name="offline-native", use="test_workspace_invocation_gate:ProbeModel", model="offline-native")], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
        set_app_config(app_config)
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        await threads.create("invocation-main", user_id="owner")
        repository = RunRepository(case.sf, workspace_required=True)
        manager = RunManager(store=repository, worker_id="invocation-owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
        entered, release = asyncio.Event(), asyncio.Event()
        report = tmp_path / "native-report.txt"
        probe = {"model_calls": 0, "tool_calls": 0}
        probe_token = _probe.set(probe)
        task = None
        models = []
        async with case.sf() as session:
            principal = await session.get(UserRow, "owner")
        token = set_current_user(principal)
        try:
            record = await manager.create_or_reject("invocation-main", user_id="owner")

            @tool
            async def save_fixture_report() -> str:
                """Save the deterministic fixture research report."""
                probe["tool_calls"] += 1
                await asyncio.to_thread(report.write_text, "native research report", encoding="utf-8")
                return "report saved"

            class HoldAtDispatch(AgentMiddleware):
                async def awrap_tool_call(self, request, handler):
                    if point == "tool":
                        entered.set()
                        await release.wait()
                    return await handler(request)

                async def awrap_model_call(self, request, handler):
                    if point == "model" and probe["model_calls"] == 1:
                        entered.set()
                        await release.wait()
                    return await handler(request)

            class HeldQueue(BaseRateLimiter):
                def acquire(self, *, blocking=True):
                    raise AssertionError("native queue main is async")

                async def aacquire(self, *, blocking=True):
                    if probe["model_calls"] == 0:
                        entered.set()
                        await release.wait()
                    return True

            def factory(**kwargs):
                options = {"rate_limiter": HeldQueue()} if point == "queue" else {}
                model = create_chat_model("offline-native", app_config=app_config, attach_tracing=False, purpose=point, max_retries=4, **options)
                assert model.max_retries == 0, "scoped factory left hidden SDK retries enabled"
                models.append(model)
                if point == "system":

                    async def independent_model(state):
                        entered.set()
                        await release.wait()
                        # Native goal/system callers intentionally clear graph callbacks.
                        response = await model.ainvoke(state["messages"], config={"callbacks": []})
                        return {"messages": [response]}

                    graph = StateGraph(MessagesState, context_schema=dict)
                    graph.add_node("independent_model", independent_model)
                    graph.add_edge(START, "independent_model")
                    graph.add_edge("independent_model", END)
                    return graph.compile()
                return create_agent(model=model, tools=[save_fixture_report], middleware=[HoldAtDispatch(), *build_lead_runtime_middlewares(app_config=app_config, user_id="owner")], context_schema=dict)

            task = asyncio.create_task(
                run_agent(
                    MemoryStreamBridge(),
                    manager,
                    record,
                    ctx=RunContext(checkpointer=None, thread_store=threads, workspace_context=case.original, app_config=app_config),
                    agent_factory=factory,
                    graph_input={"messages": [HumanMessage(content="save a deterministic research report")]},
                    config={"configurable": {"thread_id": record.thread_id}},
                    thread_incarnation=record.thread_incarnation,
                    stream_modes=["values"],
                )
            )
            record.task = task
            await asyncio.wait_for(entered.wait(), timeout=20)
            expected_before = {"model_calls": 1 if point in ("tool", "model") else 0, "tool_calls": 1 if point == "model" else 0}
            assert probe == expected_before and report.exists() == (point == "model")
            if trigger == "member":
                async with case.sf() as session:
                    await session.execute(sa.insert(UserRow).values(id="successor", email="successor@example.invalid", email_verified_at=datetime.now(UTC)))
                    await session.commit()
                workspaces = WorkspaceRepository(case.sf)
                await workspaces.add_member(case.original.workspace_id, "owner", "successor", role="member")
                await workspaces.transfer_owner(case.original.workspace_id, "owner", "successor", expected_context=case.original)
            release.set()
            await asyncio.wait_for(task, timeout=20)
            if trigger == "normal":
                assert probe == {"model_calls": 1 if point == "system" else 2, "tool_calls": 0 if point == "system" else 1}
                if point != "system":
                    assert report.read_text(encoding="utf-8") == "native research report"
                else:
                    assert not report.exists()
                    # A cached worker-built model must not silently become an
                    # unbound service capability after its native Run has closed.
                    with pytest.raises(WorkerInvocationDenied):
                        await models[0].ainvoke([HumanMessage(content="do not dispatch")], config={"callbacks": []})
                    assert probe["model_calls"] == 1
            else:
                assert report.exists() == (point == "model"), "withdrawn native tool produced its file effect"
                assert probe == expected_before, "withdrawn native Agent dispatched a waiting handler/provider"
            async with case.sf() as session:
                lifetime = await session.scalar(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind == "run_execution"))
                assert lifetime.state == "completed"
        finally:
            release.set()
            if task is not None and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=20)
                except asyncio.CancelledError:
                    pass
            await manager.stop_heartbeat()
            reset_current_user(token)
            _probe.reset(probe_token)
            reset_app_config()

    _in_workspace_case(native_engine, scenario)
