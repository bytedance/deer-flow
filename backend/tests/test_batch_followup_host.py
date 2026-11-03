"""Real AgentRuns admission and SQL fencing for native batch follow-ups."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage
from langgraph.graph import MessagesState, StateGraph
from test_extension_agent_runs import host as _host_fixture
from test_extension_agent_runs import runtime as _runtime_fixture

host = _host_fixture
runtime = _runtime_fixture


@pytest_asyncio.fixture
async def batch_host(runtime, monkeypatch, tmp_path):
    from app.gateway import services
    from app.subagent_batches.continuation import BatchContinuations
    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.subagent_batches import SubagentBatchRepository
    from deerflow.runtime import RunManager
    from deerflow.subagents.batch_runtime import BatchSubmitRequest

    runs, state, request, _, _ = runtime
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path / "db")))
    sf = get_session_factory()
    state.run_store = RunRepository(sf)
    state.run_manager = RunManager(store=state.run_store)
    state.subagent_batch_repo = repo = SubagentBatchRepository(sf)
    entered, release = asyncio.Event(), asyncio.Event()
    factory = services.resolve_agent_factory("lead_agent")

    async def answer(state):
        text = state["messages"][-1].content
        if text == "source":
            entered.set()
            await release.wait()
        return {"messages": [AIMessage(content="finished:" + text)]}

    def gated(*, config):
        graph = StateGraph(MessagesState)
        graph.add_node("answer", answer)
        graph.set_entry_point("answer")
        graph.set_finish_point("answer")
        return replace(factory(config=config), graph=graph.compile())

    monkeypatch.setattr(services, "resolve_agent_factory", lambda _: gated)
    thread = await runs.create_thread(thread_id="native-batch-followup")
    source = await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "source"}]})
    await asyncio.wait_for(entered.wait(), 5)
    controller = BatchContinuations(request.app)
    owner = str(request.state.user.id)
    thread_row = await state.thread_store.get(thread, user_id=owner)
    submission = BatchSubmitRequest(
        owner,
        thread,
        source.run_id,
        "call",
        "submission",
        "Process records",
        "general-purpose",
        [{"key": "a", "prompt": "Read A"}],
        1,
        1,
        {"thread_incarnation": thread_row["incarnation"]},
        continuation="Write the requested summary",
        continuation_authority=runs,
        continuation_context={"goal": None, "context": {"mode": "flash", "locale": "en-US"}, "config": {"recursion_limit": 99}},
    )
    continuation = await controller.prepare(submission)
    await repo.create_batch(
        batch_id="batch",
        user_id=owner,
        thread_id=thread,
        run_id=source.run_id,
        tool_call_id="call",
        submission_key="submission",
        title="Process records",
        subagent_type="general-purpose",
        items=submission.items,
        max_live_items=1,
        max_running_items=1,
        max_attempts=1,
        execution_spec=submission.execution_spec,
        continuation=continuation,
    )
    release.set()
    assert (await runs.wait(thread_id=thread, run_id=source.run_id, timeout=5)).status == "success"
    now = datetime.now(UTC)
    item = (await repo.claim_items(now=now, lease_owner="item-worker", lease_seconds=120, limit=1))[0]
    await repo.finalize_item(
        item["id"], lease_owner="item-worker", succeeded=True, result="Source read", result_preview="Source read", result_truncated=False, error=None, stop_reason=None, token_usage=None, model_name="fixture", completed_at=now
    )
    claimed = (await repo.claim_continuations(now=datetime.now(UTC), lease_owner="continuation-worker", lease_seconds=120))[0]
    try:
        yield controller, claimed, repo, runs, state, request
    finally:
        release.set()
        await state.run_manager.shutdown()
        await close_engine()


@pytest.mark.asyncio
async def test_followup_runs_once_and_reconciles_an_unknown_admission(batch_host):
    controller, batch, repo, runs, state, _ = batch_host
    first = await controller.dispatch(batch)
    assert first["status"] == "dispatched"
    assert (await runs.wait(thread_id=batch["thread_id"], run_id=first["run_id"], timeout=5)).status == "success"
    # Simulate the batch worker losing the admission response before receipt persistence.
    second = await controller.dispatch(batch)
    assert second == first
    record = await state.run_manager.get(first["run_id"])
    assert record.kwargs["config"]["recursion_limit"] == 99
    assert record.metadata["deerflow_origin"]["kind"] == "subagent_batch"
    assert await repo.finish_continuation(batch["id"], lease_owner="continuation-worker", status="dispatched", run_id=first["run_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "supersede"])
async def test_cancellation_or_goal_change_fences_a_launch_already_in_flight(batch_host, monkeypatch, action):
    from app.gateway import services

    controller, batch, repo, _, state, _ = batch_host
    reached, release = asyncio.Event(), asyncio.Event()
    start = services.start_run

    async def delayed(*args, **kwargs):
        reached.set()
        await release.wait()
        return await start(*args, **kwargs)

    monkeypatch.setattr(services, "start_run", delayed)
    launch = asyncio.create_task(controller.dispatch(batch))
    try:
        await asyncio.wait_for(reached.wait(), 5)
        if action == "cancel":
            await repo.cancel_batch(batch["id"], user_id=batch["user_id"])
        else:
            from app.gateway.routers.threads import ThreadGoalRequest, set_thread_goal
            from deerflow.runtime.user_context import reset_current_user, set_current_user

            request = batch_host[-1]
            token = set_current_user(request.state.user)
            try:
                await set_thread_goal(batch["thread_id"], ThreadGoalRequest(objective="The user's replacement goal"), request)
            finally:
                reset_current_user(token)
        release.set()
        assert await launch is None
        assert await repo.continuation_run_id(batch["id"], user_id=batch["user_id"]) is None
    finally:
        release.set()
        await asyncio.gather(launch, return_exceptions=True)


@pytest.mark.asyncio
async def test_revoked_original_account_cannot_launch_followup(batch_host):
    controller, batch, repo, _, state, request = batch_host
    state.agent_runs_host.load_user.return_value = request.state.user.model_copy(update={"token_version": request.state.user.token_version + 1})
    assert await controller.dispatch(batch) == {"status": "suppressed"}
    assert await repo.continuation_run_id(batch["id"], user_id=batch["user_id"]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "reason", "cancelled"), [("error", None, True), ("success", "token_capped", True), ("success", "loop_capped", True), ("success", "subagent_limit_capped", False)])
async def test_source_completion_preserves_existing_hard_stop_policy(batch_host, status, reason, cancelled):
    from types import SimpleNamespace

    from deerflow.config.subagent_batches_config import SubagentBatchesConfig
    from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
    from deerflow.subagents.batch_service import SubagentBatchService

    controller, batch, repo, _, state, _ = batch_host
    state.subagent_batch_service = SubagentBatchService(repository=repo, config=SubagentBatchesConfig(), runtime_config=SubagentRuntimeConfig(), cancel_continuation=controller.cancel)
    await controller.source_finished(SimpleNamespace(run_id=batch["run_id"], thread_id=batch["thread_id"], status=status, stop_reason=reason))
    current = await repo.get_batch(batch["id"], user_id=batch["user_id"])
    assert (current["continuation_status"] == "cancelled") is cancelled


@pytest.mark.asyncio
async def test_worker_wakes_the_same_waiting_goal_and_accounts_once(batch_host, monkeypatch):
    from app.gateway import services
    from deerflow.agents.thread_state import ThreadState
    from deerflow.runtime.goal import build_goal_state, write_thread_goal

    controller, batch, _, runs, state, _ = batch_host
    goal = build_goal_state("Finish the requested work", max_continuations=2)
    goal["last_evaluation"] = {"blocker": "external_wait", "stand_down_reason": "blocked:external_wait"}
    await write_thread_goal(state.checkpointer, batch["thread_id"], goal)
    batch["continuation"]["goal"] = {key: goal[key] for key in ("created_at", "status", "objective")}
    observed = []
    factory = services.resolve_agent_factory("lead_agent")

    async def answer(values):
        observed.append(values["goal"]["continuation_count"])
        return {"messages": [AIMessage(content="The requested work is finished.")]}

    def with_goal(*, config):
        graph = StateGraph(ThreadState)
        graph.add_node("answer", answer)
        graph.set_entry_point("answer")
        graph.set_finish_point("answer")
        return replace(factory(config=config), graph=graph.compile())

    async def evaluated(*args, **kwargs):
        return {"satisfied": True, "blocker": "none", "reason": "The controlled work finished"}

    monkeypatch.setattr(services, "resolve_agent_factory", lambda _: with_goal)
    monkeypatch.setattr("deerflow.runtime.runs.worker.create_goal_evaluator_model", lambda **_: None)
    monkeypatch.setattr("deerflow.runtime.runs.worker.evaluate_goal_completion", evaluated)
    launched = await controller.dispatch(batch)
    assert launched["status"] == "dispatched"
    assert (await runs.wait(thread_id=batch["thread_id"], run_id=launched["run_id"], timeout=5)).status == "success"
    result = await runs.get_state(thread_id=batch["thread_id"])
    assert result["values"]["goal_outcome"]["status"] == "achieved"
    assert result["values"]["goal_outcome"]["continuation_count"] == 1
    assert observed == [1]
    assert await controller.dispatch(batch) == launched
    assert observed == [1]
