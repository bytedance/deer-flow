"""A cancelled extension-model caller is not a stopped real provider thread."""

import asyncio
import threading
from contextvars import ContextVar
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401
from test_workspace_mcp import _in_workspace_case

_probe = ContextVar("service_lifetime_fixture")


class ThreadServiceModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "deterministic-host-thread"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        probe = _probe.get()
        probe["calls"] += 1
        probe["loop"].call_soon_threadsafe(probe["entered"].set)
        try:
            assert probe["release"].wait(20), "fixture provider was never released"
            content = "independent service report"
            if any("strict completion evaluator" in str(message.content) for message in messages):
                content = '{"satisfied": true, "blocker": "none", "reason": "report verified", "evidence_summary": "offline fixture"}'
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])
        finally:
            probe["loop"].call_soon_threadsafe(probe["finished"].set)


@pytest.mark.parametrize("trigger", ["normal", "cancel", "member", "provider_cancel"])
def test_native_run_retains_real_model_service_until_provider_stops(native_engine, trigger):  # noqa: F811
    _run_model_lifetime_case(native_engine, trigger, "extension")


@pytest.mark.parametrize(
    ("entrypoint", "trigger"),
    [(entrypoint, trigger) for entrypoint in ("lead", "title", "summary", "goal") for trigger in ("normal", "cancel")] + [("lead", "member"), ("title", "provider_cancel")],
)
def test_native_direct_model_retains_actual_provider(native_engine, trigger, entrypoint):  # noqa: F811
    _run_model_lifetime_case(native_engine, trigger, entrypoint)


async def _call_direct_model(entrypoint, config, state):
    from langchain_core.messages import HumanMessage

    from deerflow.models import create_chat_model

    if entrypoint == "title":
        from deerflow.agents.middlewares.title_middleware import TitleMiddleware
        from deerflow.config.title_config import TitleConfig

        title_config = config.model_copy(update={"title": TitleConfig(model_name="offline-service")})
        result = await TitleMiddleware(app_config=title_config)._agenerate_title_result({"messages": [HumanMessage(content="research question"), AIMessage(content="existing answer")]})
        return {"messages": [AIMessage(content=result["title"])]}
    model = create_chat_model("offline-service", app_config=config, attach_tracing=False)
    if entrypoint == "lead":
        from langchain.agents import create_agent

        from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares

        agent = create_agent(model=model, tools=[], middleware=build_lead_runtime_middlewares(app_config=config, user_id="owner"), context_schema=dict)
        return await agent.ainvoke(state)
    if entrypoint == "summary":
        from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware

        summary = DeerFlowSummarizationMiddleware(model=model, trigger=("tokens", 1024), keep=("messages", 2), app_config=config, run_model_name="offline-service", anchor_model_name="offline-service")
        result = await summary._asummarize_with([HumanMessage(content="research question"), AIMessage(content="existing answer")])
        return {"messages": [AIMessage(content=result)]}
    from deerflow.runtime.goal import build_goal_state, evaluate_goal_completion

    result = await evaluate_goal_completion(build_goal_state("verify offline report"), [HumanMessage(content="research question"), AIMessage(content="existing answer")], model=model, model_name="offline-service", app_config=config)
    assert result["satisfied"]
    return {"messages": [AIMessage(content="goal verified")]}


def _run_model_lifetime_case(engine, trigger, entrypoint):
    from deerflow_extension_api import ModelInvocationRequest, ModelMessage
    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.authz.workspace import set_current_workspace
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.extensions.model_access import ModelInvocationGrant, ModelInvocationScope
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.model import WorkspaceOperationOutboxRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository
    from deerflow.runtime import ConflictError, MemoryStreamBridge, RunContext, RunManager, run_agent
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    async def scenario(case):
        config = AppConfig(models=[ModelConfig(name="offline-service", use="test_workspace_model_service_lifetime:ThreadServiceModel", model="offline-service")], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
        set_app_config(config)
        scope = ModelInvocationScope("native-lifetime-fixture", ModelInvocationGrant(roles={"default": "offline-service"}, max_concurrency=2))
        invoker = scope.bind(config)
        probe = {"calls": 0, "loop": asyncio.get_running_loop(), "entered": asyncio.Event(), "release": threading.Event(), "finished": asyncio.Event()}
        probe_token = _probe.set(probe)
        caller_exited, completion_called = asyncio.Event(), asyncio.Event()
        completed_while_busy = []
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        await threads.create("service-lifetime", user_id="owner")
        repository = RunRepository(case.sf, workspace_required=True)
        ownership = RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120)
        manager = RunManager(store=repository, worker_id="service-owner", run_ownership_config=ownership)
        peer = RunManager(store=repository, worker_id="service-peer", run_ownership_config=ownership)
        async with case.sf() as session:
            principal = await session.get(UserRow, "owner")
        token = set_current_user(principal)
        task = None
        try:
            record = await manager.create_or_reject("service-lifetime", user_id="owner")

            async def call_service(state):
                try:
                    if entrypoint != "extension":
                        from deerflow.runtime.invocation import get_invocation_guard

                        probe["guard"] = get_invocation_guard()
                        return await _call_direct_model(entrypoint, config, state)
                    result = await invoker.invoke(ModelInvocationRequest(messages=[ModelMessage("user", "produce an offline research report")]))
                    return {"messages": [AIMessage(content=result.content)]}
                finally:
                    caller_exited.set()

            async def completion(finished):
                completed_while_busy.append(not probe["finished"].is_set())
                if trigger == "normal":
                    # Legitimate native post-processing remains allowed until
                    # final seal, even though Run metadata is already terminal.
                    followup = await invoker.invoke(ModelInvocationRequest(messages=[ModelMessage("user", "finish the report metadata")]))
                    assert followup.content == "independent service report"
                completion_called.set()

            graph = StateGraph(MessagesState, context_schema=dict)
            graph.add_node("call_service", call_service)
            graph.add_edge(START, "call_service")
            graph.add_edge("call_service", END)
            compiled = graph.compile()
            task = asyncio.create_task(
                run_agent(
                    MemoryStreamBridge(),
                    manager,
                    record,
                    ctx=RunContext(checkpointer=None, thread_store=threads, workspace_context=case.original, app_config=config, on_run_completed=completion),
                    agent_factory=lambda **kwargs: compiled,
                    graph_input={"messages": [HumanMessage(content="research through the host model service")]},
                    config={"configurable": {"thread_id": record.thread_id}},
                    thread_incarnation=record.thread_incarnation,
                    stream_modes=["values"],
                )
            )
            record.task = task
            await manager.start_heartbeat()
            await asyncio.wait_for(probe["entered"].wait(), 15)
            assert probe["calls"] == 1 and len(scope.budget.workers) == int(entrypoint == "extension")
            fresh = case.original
            if trigger == "provider_cancel":
                pending = scope.budget.workers if entrypoint == "extension" else probe["guard"]._providers
                assert len(pending) == 1
                next(iter(pending)).cancel()
            elif trigger == "cancel":
                await manager.cancel(record.run_id, action="interrupt")
            elif trigger == "member":
                async with case.sf() as session:
                    await session.execute(sa.insert(UserRow).values(id="successor", email="successor@example.invalid", email_verified_at=datetime.now(UTC)))
                    await session.commit()
                spaces = WorkspaceRepository(case.sf)
                await spaces.add_member(case.original.workspace_id, "owner", "successor", role="member")
                await spaces.transfer_owner(case.original.workspace_id, "owner", "successor", expected_context=case.original)
                fresh = await case.service.resolve_context("owner", case.original.workspace_id)
                await manager._renew_leases()
            if trigger != "normal":
                if trigger != "provider_cancel":
                    await asyncio.wait_for(caller_exited.wait(), 15)
                assert not probe["finished"].is_set() and len(scope.budget.workers) == int(entrypoint == "extension")
                # A shielded wait observes termination without cancelling the owner.
                done, _ = await asyncio.wait({task}, timeout=1)
                assert not done, "native worker closed while its real service provider thread was still running"
                assert not completion_called.is_set()
                async with case.sf() as session:
                    row = await session.get(RunRow, record.run_id)
                    lease = row.lease_expires_at
                    assert (await session.scalar(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind == "run_execution", WorkspaceOperationOutboxRow.state == "open"))).state == "open"
                set_current_workspace(case.other)
                await manager._renew_leases()
                assert not record.ownership_lost
                async with case.sf() as session:
                    assert (await session.get(RunRow, record.run_id)).lease_expires_at > lease
                set_current_workspace(fresh)
                with pytest.raises(ConflictError):
                    await peer.create_or_reject(record.thread_id, user_id="owner")
                set_current_workspace(case.other)
                # The host service is shared, but pending work belongs to one
                # immutable Run. A different workspace must finish independently.
                independent_probe = {"calls": 0, "loop": asyncio.get_running_loop(), "entered": asyncio.Event(), "release": threading.Event(), "finished": asyncio.Event()}
                independent_probe["release"].set()
                independent_token = _probe.set(independent_probe)
                try:
                    await threads.create("independent-service", user_id="owner")
                    independent = await peer.create_or_reject("independent-service", user_id="owner")
                    other_graph = StateGraph(MessagesState, context_schema=dict)
                    other_graph.add_node("call_service", call_service)
                    other_graph.add_edge(START, "call_service")
                    other_graph.add_edge("call_service", END)
                    await asyncio.wait_for(
                        run_agent(
                            MemoryStreamBridge(),
                            peer,
                            independent,
                            ctx=RunContext(checkpointer=None, thread_store=threads, workspace_context=case.other, app_config=config),
                            agent_factory=lambda **kwargs: other_graph.compile(),
                            graph_input={"messages": [HumanMessage(content="independent report")]},
                            config={"configurable": {"thread_id": independent.thread_id}},
                            thread_incarnation=independent.thread_incarnation,
                            stream_modes=["values"],
                        ),
                        15,
                    )
                    assert independent.workspace_execution_closed and independent_probe["finished"].is_set()
                    assert independent_probe["calls"] == 1
                    assert not task.done() and not probe["finished"].is_set()
                    assert len(scope.budget.workers) == scope.budget.admitted == int(entrypoint == "extension")
                finally:
                    _probe.reset(independent_token)
            probe["release"].set()
            await asyncio.wait_for(task, 15)
            await manager._renew_leases()
            assert probe["finished"].is_set() and completed_while_busy == [False]
            assert not scope.budget.workers and scope.budget.admitted == 0
            assert probe["calls"] == (2 if trigger == "normal" else 1)
            async with case.sf() as session:
                row = await session.get(RunRow, record.run_id)
                # A provider task cancellation is a node/provider failure, not
                # a user interrupt (LangGraph wraps it as NodeCancelledError).
                assert row.status == ("success" if trigger == "normal" else "error" if trigger == "provider_cancel" else "interrupted")
                assert not list((await session.scalars(sa.select(WorkspaceOperationOutboxRow).where(WorkspaceOperationOutboxRow.kind == "run_execution", WorkspaceOperationOutboxRow.state != "completed"))).all())
            set_current_workspace(fresh)
            replacement = await peer.create_or_reject(record.thread_id, user_id="owner")
            assert replacement.run_id != record.run_id
        finally:
            probe["release"].set()
            if task is not None and not task.done():
                task.cancel()
            if task is not None:
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 15)
            if scope.budget.workers:
                await asyncio.wait_for(asyncio.gather(*scope.budget.workers, return_exceptions=True), 15)
            invoker.close()
            await manager.stop_heartbeat()
            reset_current_user(token)
            _probe.reset(probe_token)
            reset_app_config()

    _in_workspace_case(engine, scenario)


@pytest.mark.parametrize("entrypoint", ["extension", "title", "summary", "goal"])
def test_native_system_model_stop_is_not_an_ordinary_fallback(native_engine, entrypoint):  # noqa: F811
    from deerflow_extension_api import ModelInvocationFailed, ModelInvocationRequest, ModelMessage
    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
    from deerflow.agents.middlewares.title_middleware import TitleMiddleware
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.config.title_config import TitleConfig
    from deerflow.extensions.model_access import ModelInvocationGrant, ModelInvocationScope
    from deerflow.models import create_chat_model
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository
    from deerflow.runtime import MemoryStreamBridge, RunContext, RunManager, run_agent
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    async def scenario(case):
        config = AppConfig(
            models=[ModelConfig(name="offline-service", use="test_workspace_model_service_lifetime:ThreadServiceModel", model="offline-service")],
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
            title=TitleConfig(model_name="offline-service"),
        )
        set_app_config(config)
        scope = ModelInvocationScope("native-stop-fixture", ModelInvocationGrant(roles={"default": "offline-service"}))
        invoker = scope.bind(config)
        probe = {"calls": 0, "loop": asyncio.get_running_loop(), "entered": asyncio.Event(), "release": threading.Event(), "finished": asyncio.Event()}
        # If a broken gate reaches the provider, do not hide it behind a timeout.
        probe["release"].set()
        probe_token = _probe.set(probe)
        entered, release = asyncio.Event(), asyncio.Event()
        returned = []
        threads = ThreadMetaRepository(case.sf, workspace_required=True)
        await threads.create("system-model-stop", user_id="owner")
        repository = RunRepository(case.sf, workspace_required=True)
        manager = RunManager(store=repository, worker_id="system-stop-owner", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=120))
        async with case.sf() as session:
            principal = await session.get(UserRow, "owner")
        token = set_current_user(principal)
        task = None
        try:
            record = await manager.create_or_reject("system-model-stop", user_id="owner")

            async def call_system(state):
                if entrypoint == "goal":
                    from langgraph.checkpoint.memory import InMemorySaver
                    from test_goal_worker import _full_accessor, _seed_goal_thread

                    from deerflow.runtime.goal import read_thread_goal
                    from deerflow.runtime.runs.worker import _prepare_goal_continuation_input

                    goal_saver = InMemorySaver()
                    await _seed_goal_thread(goal_saver, thread_id=record.thread_id, goal_text="finish research report")
                entered.set()
                await release.wait()
                if entrypoint == "extension":
                    try:
                        await invoker.invoke(ModelInvocationRequest(messages=[ModelMessage("user", "stop before provider")]))
                    except ModelInvocationFailed:
                        returned.append("normalized failure")
                elif entrypoint == "goal":
                    returned.append(
                        await _prepare_goal_continuation_input(
                            bridge=MemoryStreamBridge(),
                            accessor=_full_accessor(goal_saver),
                            checkpointer=goal_saver,
                            thread_id=record.thread_id,
                            run_id=record.run_id,
                            model_name="offline-service",
                            app_config=config,
                            evaluator_model_factory=lambda: create_chat_model("offline-service", app_config=config, attach_tracing=False),
                        )
                    )
                    # If a broken fallback persists a normal failure, expose its
                    # normalized reason to prove the actual STOP was consumed.
                    returned.append((await read_thread_goal(goal_saver, record.thread_id)).get("last_evaluation"))
                elif entrypoint == "title":
                    title = TitleMiddleware(app_config=config)
                    returned.append(await title._agenerate_title_result({"messages": [HumanMessage(content="research question"), AIMessage(content="existing answer")]}))
                else:
                    model = create_chat_model("offline-service", app_config=config, attach_tracing=False)
                    summary = DeerFlowSummarizationMiddleware(model=model, trigger=("tokens", 1024), keep=("messages", 2), app_config=config, run_model_name="offline-service", anchor_model_name="offline-service")
                    returned.append(await summary._asummarize_with([HumanMessage(content="research question"), AIMessage(content="existing answer")]))
                returned.append("continued after native stop")
                return {"messages": []}

            graph = StateGraph(MessagesState, context_schema=dict)
            graph.add_node("call_system", call_system)
            graph.add_edge(START, "call_system")
            graph.add_edge("call_system", END)
            compiled = graph.compile()
            task = asyncio.create_task(
                run_agent(
                    MemoryStreamBridge(),
                    manager,
                    record,
                    ctx=RunContext(checkpointer=None, thread_store=threads, workspace_context=case.original, app_config=config),
                    agent_factory=lambda **kwargs: compiled,
                    graph_input={"messages": [HumanMessage(content="system model control main")]},
                    config={"configurable": {"thread_id": record.thread_id}},
                    thread_incarnation=record.thread_incarnation,
                    stream_modes=["values"],
                )
            )
            record.task = task
            await asyncio.wait_for(entered.wait(), 15)
            async with case.sf() as session:
                await session.execute(sa.insert(UserRow).values(id="successor", email="successor@example.invalid", email_verified_at=datetime.now(UTC)))
                await session.commit()
            spaces = WorkspaceRepository(case.sf)
            await spaces.add_member(case.original.workspace_id, "owner", "successor", role="member")
            await spaces.transfer_owner(case.original.workspace_id, "owner", "successor", expected_context=case.original)
            release.set()
            await asyncio.wait_for(task, 15)
            assert probe["calls"] == 0
            assert returned == [], "native execution stop was converted to a system model fallback/failure"
            assert record.workspace_execution_closed
        finally:
            release.set()
            probe["release"].set()
            if task is not None and not task.done():
                task.cancel()
            if task is not None:
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 15)
            if scope.budget.workers:
                await asyncio.wait_for(asyncio.gather(*scope.budget.workers, return_exceptions=True), 15)
            invoker.close()
            await manager.stop_heartbeat()
            reset_current_user(token)
            _probe.reset(probe_token)
            reset_app_config()

    _in_workspace_case(native_engine, scenario)
