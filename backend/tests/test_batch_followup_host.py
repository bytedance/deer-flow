"""Real AgentRuns admission and SQL fencing for native batch follow-ups."""

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage
from langgraph.graph import MessagesState, StateGraph
from test_batch_dependencies import create
from test_batch_dependencies import repo as _repo_fixture
from test_extension_agent_runs import host as _host_fixture
from test_extension_agent_runs import runtime as _runtime_fixture

host = _host_fixture
runtime = _runtime_fixture
repo = _repo_fixture


def graph_factory(factory, answer, schema=MessagesState):
    def build(*, config):
        graph = StateGraph(schema)
        graph.add_node("answer", answer)
        graph.set_entry_point("answer")
        graph.set_finish_point("answer")
        return replace(factory(config=config), graph=graph.compile())

    return build


@pytest_asyncio.fixture
async def batch_host(runtime, repo, monkeypatch, request):
    from app.gateway import services
    from app.subagent_batches.continuation import BatchContinuations
    from deerflow.config.subagent_batches_config import SubagentBatchesConfig
    from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.runtime import RunManager
    from deerflow.subagents.batch_runtime import BatchSubmitRequest
    from deerflow.subagents.batch_service import SubagentBatchService

    settings = getattr(request, "param", {})
    runs, state, request, _, _ = runtime
    sf = get_session_factory()
    state.run_store = RunRepository(sf)
    state.run_manager = RunManager(store=state.run_store)
    state.subagent_batch_repo = repo
    entered, release = asyncio.Event(), asyncio.Event()
    factory = services.resolve_agent_factory("lead_agent")

    async def answer(state):
        text = state["messages"][-1].content
        if text == "source":
            entered.set()
            await release.wait()
        return {"messages": [AIMessage(content="finished:" + text)]}

    monkeypatch.setattr(services, "resolve_agent_factory", lambda _: graph_factory(factory, answer))
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
        continuation_context={"goal": None, "context": {"mode": "flash", "locale": "en-US", **settings}, "config": {"recursion_limit": 99}},
    )
    service = SubagentBatchService(
        repository=repo,
        config=SubagentBatchesConfig(enabled=True, max_attempts=1),
        runtime_config=SubagentRuntimeConfig(),
        prepare_continuation=controller.prepare,
        dispatch_continuation=controller.dispatch,
        cancel_continuation=controller.cancel,
    )
    state.subagent_batch_service = service
    await service.submit(submission)
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
@pytest.mark.parametrize("batch_host", [{"model_name": "parent", "model_selection_requested": "parent", "subagent_model_name": "child"}], indirect=True)
async def test_followup_preserves_explicit_model_controls(batch_host):
    context = batch_host[1]["continuation"]["context"]
    assert context["model_selection_requested"] == context["model_name"] == "parent"
    assert context["subagent_model_name"] == "child"


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
@pytest.mark.parametrize(
    "scope",
    [
        {"version": 1, "mode": "disabled"},
        {"version": 1, "mode": "selected", "dataset_ids": ["approved"], "document_filters": [{"dataset_id": "approved", "document_ids": ["one"]}]},
    ],
)
async def test_resumed_native_batch_preserves_admitted_scope_in_followup(batch_host, monkeypatch, scope):
    from types import SimpleNamespace

    from langgraph.runtime import Runtime
    from langgraph.types import interrupt
    from test_batch_task_tool import tool_module

    from app.gateway import services
    from deerflow.config.app_config import AppConfig, set_app_config
    from deerflow.config.subagent_batches_config import SubagentBatchesConfig
    from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
    from deerflow.knowledge_scope import KNOWLEDGE_SCOPE_KEY, KNOWLEDGE_SCOPE_RUNTIME_KEY
    from deerflow.subagents.batch_service import SubagentBatchService

    controller, _, repo, runs, state, request = batch_host
    set_app_config(
        AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "knowledge_base": {"enabled": True},
                "tools": [{"name": "knowledge_search", "group": "knowledge", "use": "deerflow.community.ragflow.tools:knowledge_search_tool"}],
            }
        )
    )
    service = SubagentBatchService(repository=repo, config=SubagentBatchesConfig(enabled=True), runtime_config=SubagentRuntimeConfig(), prepare_continuation=controller.prepare, dispatch_continuation=controller.dispatch)
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: service)
    observed = []
    factory = services.resolve_agent_factory("lead_agent")

    async def answer(values, runtime: Runtime, config):
        if values["messages"][-1].content == "scoped work":
            interrupt("Continue?")
            record = await state.run_manager.get(runtime.context["run_id"])
            assert record.kwargs["input"] is None
            command = await tool_module.batch_task.coroutine(
                title="Scoped batch",
                items=[tool_module.BatchTaskItem(key="a", prompt="Read authorized records")],
                subagent_type="general-purpose",
                runtime=SimpleNamespace(context=runtime.context, state=values, config=config),
                tool_call_id="scoped-call",
                continuation="Present the result",
            )
            assert command.update["messages"][0].status != "error", command.update["messages"][0].content
        observed.append(runtime.context.get(KNOWLEDGE_SCOPE_RUNTIME_KEY))
        return {"messages": [AIMessage(content="Finished")]}

    monkeypatch.setattr(services, "resolve_agent_factory", lambda _: graph_factory(factory, answer))
    thread = await runs.create_thread(thread_id="scoped-resume")
    first = await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "scoped work", "additional_kwargs": {KNOWLEDGE_SCOPE_KEY: scope}}]})
    assert (await runs.wait(thread_id=thread, run_id=first.run_id, timeout=5)).status == "success"
    resumed = await runs.resume(thread_id=thread, resume="yes")
    assert (await runs.wait(thread_id=thread, run_id=resumed.run_id, timeout=5)).status == "success"
    assert observed == [scope]
    now = datetime.now(UTC)
    item = (await repo.claim_items(now=now, lease_owner="scoped-worker", lease_seconds=120, limit=1))[0]
    await repo.finalize_item(item["id"], lease_owner="scoped-worker", succeeded=True, result="Done", result_preview="Done", result_truncated=False, error=None, stop_reason=None, token_usage=None, model_name="fixture", completed_at=now)
    batch = (await repo.claim_continuations(now=datetime.now(UTC), lease_owner="scoped-followup", lease_seconds=120))[0]
    assert batch["continuation"]["knowledge_scope"] == scope
    launched = await controller.dispatch(batch)
    assert (await runs.wait(thread_id=thread, run_id=launched["run_id"], timeout=5)).status == "success"
    assert observed == [scope, scope]


@pytest.mark.asyncio
async def test_followup_waits_for_an_actual_answer_without_a_goal(batch_host, monkeypatch):
    from langchain_core.messages import ToolMessage

    from app.gateway import services
    from deerflow.agents.human_input import extract_unanswered_human_input_request

    controller, batch, repo, runs, state, _ = batch_host
    factory = services.resolve_agent_factory("lead_agent")
    question = {"kind": "human_input_request", "request_id": "recipient", "question": "Which recipient?", "source": "ask_clarification"}

    async def answer(values):
        if values["messages"][-1].content == "ask":
            return {
                "messages": [
                    AIMessage(content="", tool_calls=[{"name": "ask_clarification", "args": {}, "id": "ask"}]),
                    ToolMessage(content="Which recipient?", tool_call_id="ask", name="ask_clarification", artifact={"human_input": question}),
                ]
            }
        return {"messages": [AIMessage(content="Understood")]}

    monkeypatch.setattr(services, "resolve_agent_factory", lambda _: graph_factory(factory, answer))

    async def ask():
        asked = await runs.start(thread_id=batch["thread_id"], input={"messages": [{"role": "user", "content": "ask"}]})
        assert (await runs.wait(thread_id=batch["thread_id"], run_id=asked.run_id, timeout=5)).status == "success"
        assert (await state.run_manager.get(asked.run_id)).human_input_request == question

    await ask()
    assert await controller.dispatch(batch) == {"status": "waiting"}
    # Waiting keeps the claim until its lease expires instead of every poll.
    await state.subagent_batch_service._continue_batch(batch, "continuation-worker")
    assert await repo.claim_continuations(now=datetime.now(UTC), lease_owner="poller", lease_seconds=120) == []
    assert await repo.continuation_run_id(batch["id"], user_id=batch["user_id"]) is None
    pending = await runs.get_state(thread_id=batch["thread_id"])
    assert extract_unanswered_human_input_request(pending["values"]["messages"]) == question
    answered = await runs.start(thread_id=batch["thread_id"], input={"messages": [{"role": "user", "content": "Use the team inbox"}]})
    assert (await runs.wait(thread_id=batch["thread_id"], run_id=answered.run_id, timeout=5)).status == "success"
    launched = await controller.dispatch(batch)
    assert (await runs.wait(thread_id=batch["thread_id"], run_id=launched["run_id"], timeout=5)).status == "success"
    assert await controller.dispatch(batch) == launched


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

    async def evaluated(*args, **kwargs):
        return {"satisfied": True, "blocker": "none", "reason": "The controlled work finished"}

    monkeypatch.setattr(services, "resolve_agent_factory", lambda _: graph_factory(factory, answer, ThreadState))
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


@pytest.mark.asyncio
async def test_cancel_batch_tool_requires_runs_cancel_for_followups(batch_host, monkeypatch):
    from types import SimpleNamespace

    from deerflow_extension_api.agent_runs import AGENT_RUNS_CONTEXT_KEY, AgentRunError
    from test_batch_task_tool import tool_module

    from app.gateway import services
    from deerflow.subagents.batch_runtime import BatchSubmitRequest

    controller, batch, repo, runs, state, request = batch_host
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: state.subagent_batch_service)
    request.state.auth.permissions = ["threads:write", "threads:read", "runs:create", "runs:read"]
    no_cancel_runs = state.agent_runs_host.bind(request)
    request.state.auth.permissions.append("runs:cancel")

    def tool_runtime(authority):
        context = {"user_id": batch["user_id"], "thread_id": batch["thread_id"]}
        if authority is not None:
            context[AGENT_RUNS_CONTEXT_KEY] = authority
        return SimpleNamespace(context=context)

    ordinary = await state.subagent_batch_service.submit(
        BatchSubmitRequest(
            batch["user_id"],
            batch["thread_id"],
            batch["run_id"],
            "ordinary-call",
            "ordinary-submission",
            "Ordinary batch",
            "general-purpose",
            [{"key": "a", "prompt": "Read A"}],
            1,
            1,
            {},
        )
    )
    assert await tool_module.cancel_batch.coroutine(runtime=tool_runtime(no_cancel_runs), batch_id=ordinary["id"]) == (f"Batch {ordinary['id']} cancellation requested.")

    for authority in (no_cancel_runs, None):
        with pytest.raises(AgentRunError) as exc_info:
            await tool_module.cancel_batch.coroutine(runtime=tool_runtime(authority), batch_id=batch["id"])
        assert exc_info.value.status_code == 403
    assert (await repo.get_batch(batch["id"], user_id=batch["user_id"]))["continuation_status"] == "dispatching"

    entered, release = asyncio.Event(), asyncio.Event()
    factory = services.resolve_agent_factory("lead_agent")

    async def hold(_values):
        entered.set()
        await release.wait()
        return {"messages": [AIMessage(content="finished followup")]}

    monkeypatch.setattr(services, "resolve_agent_factory", lambda _: graph_factory(factory, hold))
    try:
        launched = await controller.dispatch(batch)
        assert launched["status"] == "dispatched"
        assert await repo.finish_continuation(batch["id"], lease_owner="continuation-worker", status="dispatched", run_id=launched["run_id"])
        await asyncio.wait_for(entered.wait(), 5)
        with pytest.raises(AgentRunError) as exc_info:
            await tool_module.cancel_batch.coroutine(runtime=tool_runtime(no_cancel_runs), batch_id=batch["id"])
        assert exc_info.value.status_code == 403
        record = await state.run_manager.get(launched["run_id"])
        assert not record.abort_event.is_set()
        assert (await repo.get_batch(batch["id"], user_id=batch["user_id"]))["continuation_status"] == "dispatched"

        result = await tool_module.cancel_batch.coroutine(runtime=tool_runtime(runs), batch_id=batch["id"])
        assert result == f"Batch {batch['id']} cancellation requested."
        assert (await runs.wait(thread_id=batch["thread_id"], run_id=launched["run_id"], timeout=5)).status == "interrupted"
        assert (await repo.get_batch(batch["id"], user_id=batch["user_id"]))["continuation_status"] == "cancelled"
    finally:
        release.set()


@pytest.mark.asyncio
async def test_scheduler_failure_does_not_skip_batch_cancellation(batch_host, caplog):
    """A scheduled-task store failure must not skip batch_continuations cleanup.

    `_run_completion_hook` awaits the scheduler first; an exception there used to
    leave the claimed follow-up of a loop_capped source run in `dispatching`
    instead of being cancelled (issue #7969). The worker logs hook errors as
    non-fatal, so cancellation must still run.
    """
    from types import SimpleNamespace

    from app.gateway.deps import _run_completion_hook

    controller, batch, repo, _, _, _ = batch_host

    class FailingScheduler:
        async def handle_run_completion(self, record):
            raise OSError("schedule store unavailable")

    # The production hook, with a scheduler whose store is unavailable.
    hook = _run_completion_hook(
        scheduled_task_service=FailingScheduler(),
        batch_continuations=controller,
    )

    with caplog.at_level(logging.WARNING, logger="app.gateway.deps"):
        await hook(SimpleNamespace(run_id=batch["run_id"], thread_id=batch["thread_id"], status="success", stop_reason="loop_capped"))

    current = await repo.get_batch(batch["id"], user_id=batch["user_id"])
    assert current["continuation_status"] == "cancelled"
    warnings = [record for record in caplog.records if record.name == "app.gateway.deps" and record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == f"Scheduled task completion hook failed for run {batch['run_id']} (non-fatal)"
    assert warnings[0].exc_info and isinstance(warnings[0].exc_info[1], OSError)


@pytest.mark.asyncio
async def test_batch_cancellation_failure_does_not_skip_remaining_batches(batch_host, monkeypatch, caplog):
    from types import SimpleNamespace

    controller, batch, repo, _, _, _ = batch_host
    other = await create(
        repo,
        [{"key": "b", "prompt": "Read B"}],
        user_id=batch["user_id"],
        thread_id=batch["thread_id"],
        run_id=batch["run_id"],
        continuation=batch["continuation"],
    )
    cancel_batch = repo.cancel_batch
    failed_id = None

    async def fail_first_cancel(batch_id, *, user_id):
        nonlocal failed_id
        if failed_id is None:
            failed_id = batch_id
            raise OSError("batch store unavailable")
        return await cancel_batch(batch_id, user_id=user_id)

    monkeypatch.setattr(repo, "cancel_batch", fail_first_cancel)
    with caplog.at_level(logging.WARNING, logger="app.subagent_batches.continuation"):
        await controller.source_finished(SimpleNamespace(run_id=batch["run_id"], thread_id=batch["thread_id"], status="success", stop_reason="loop_capped"))

    statuses = {batch_id: (await repo.get_batch(batch_id, user_id=batch["user_id"]))["continuation_status"] for batch_id in (batch["id"], other["id"])}
    assert statuses[failed_id] in ("pending", "dispatching")
    assert list(statuses.values()).count("cancelled") == 1
    assert [entry for entry in caplog.record_tuples if entry[0] == "app.subagent_batches.continuation"] == [
        ("app.subagent_batches.continuation", logging.WARNING, f"Batch {failed_id} cancellation failed for run {batch['run_id']} (non-fatal)")
    ]
