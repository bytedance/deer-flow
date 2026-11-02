"""Real graph boundaries, native checkpoint receipts and control actions."""

import asyncio
from types import SimpleNamespace
from typing import Annotated

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ConfigDict

from deerflow.agents.middlewares.run_input_middleware import RunInputAdmissionMiddleware, RunInputMiddleware
from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
from deerflow.agents.middlewares.token_usage_middleware import CompletedSubagentUsageMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.config.token_budget_config import TokenBudgetConfig
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY
from deerflow.runtime.runs.input_control import ChildInputGate, RunInputControl
from deerflow.runtime.runs.inputs import INPUT_CONTEXT_KEY, RunInputs
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.subagents.status_contract import SUBAGENT_TOKEN_USAGE_KEY, make_subagent_additional_kwargs


def test_input_control_reaches_the_factory_only_from_the_worker():
    from deerflow.agents.lead_agent.agent import _get_runtime_config
    from deerflow.runtime.runs.worker import _build_runtime_context, _install_runtime_context, _release_run_scoped_references
    from deerflow.runtime.secret_context import redact_config_secrets

    context = _build_runtime_context("thread", "run", {INPUT_CONTEXT_KEY: "forged"})
    assert INPUT_CONTEXT_KEY not in context
    control = RunInputControl(RunInputs(MemoryRunStore(), "run", "owner", "worker"), agent_runs=None, thread_id="thread", checkpointer=None)
    context[INPUT_CONTEXT_KEY] = control
    config = {"context": {"thread_id": "thread"}, "configurable": {}}
    _install_runtime_context(config, context)
    assert _get_runtime_config(config)[INPUT_CONTEXT_KEY] is control
    assert INPUT_CONTEXT_KEY not in redact_config_secrets(config)["context"]
    _release_run_scoped_references([config], context, None)
    assert INPUT_CONTEXT_KEY not in config["context"]


class InputModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    observed: list

    @property
    def _llm_type(self):
        return "offline-input-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.observed.append(messages)
        inputs = [x for x in messages if x.additional_kwargs.get("run_input_id")]
        if inputs:
            message = AIMessage(content="New requirement applied") if any(isinstance(x, ToolMessage) and x.name == "apply_extra" for x in messages) else AIMessage(content="", tool_calls=[{"name": "apply_extra", "args": {}, "id": "extra"}])
        elif any(isinstance(x, ToolMessage) and x.name == "task" for x in messages):
            message = AIMessage(content="Original work completed")
        else:
            message = AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": "long"}])
        return ChatResult(generations=[ChatGeneration(message=message)])


class GatedInputModel(InputModel):
    entered: object
    release: object

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        first = not self.observed
        if first:
            self.entered.set()
            await self.release.wait()
        result = self._generate(messages, stop=stop, run_manager=run_manager)
        message = result.generations[0].message
        message.usage_metadata = {"input_tokens": 1100, "output_tokens": 1, "total_tokens": 1101}
        if first:
            message.additional_kwargs["tool_calls"] = [{"id": "long", "type": "function", "function": {"name": "task", "arguments": "{}"}}]
        return result


@pytest.mark.asyncio
async def test_steer_pauses_a_child_even_before_its_handler_starts():
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    await inputs.submit("immediate", "Handle the new requirement first", "steer")
    control = RunInputControl(inputs, agent_runs=None, thread_id="thread", checkpointer=None)
    release = asyncio.Event()

    async def handler(request):
        await release.wait()
        gate = control.child("child")
        assert not gate.resume.is_set()
        return ToolMessage(content="Finished", name="task", tool_call_id="child")

    try:
        reply = await control.wait_tool(SimpleNamespace(tool_call={"id": "child", "name": "task", "args": {}}), handler)
        assert reply.additional_kwargs["subagent_pending"]
        assert not control.child("child").resume.is_set()
        release.set()
        await asyncio.gather(*control.tasks)
        from deerflow.agents.middlewares.message_utils import requires_input_sanitization

        assert requires_input_sanitization(control.receipts[0])
    finally:
        release.set()
        await control.close()


@pytest.mark.asyncio
async def test_native_task_pending_and_final_results_share_an_id_per_invocation():
    from deerflow.tools.builtins.task_tool import task_tool

    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    await inputs.submit("update", "Handle this first", "steer")
    control = RunInputControl(inputs, agent_runs=None, thread_id="thread", checkpointer=None)
    runtime = SimpleNamespace(context={INPUT_CONTEXT_KEY: control})
    pending_ids, results = [], []
    try:
        for _ in range(2):
            release = asyncio.Event()

            async def handler(request):
                await release.wait()
                result = await task_tool.coroutine(runtime=runtime, prompt="test", subagent_type="unused", tool_call_id="reused", context_mode="invalid")
                results.append(result.update["messages"][0])
                return result

            pending = await control.wait_tool(SimpleNamespace(tool_call={"id": "reused", "name": "task", "args": {}}), handler)
            pending_ids.append(pending.id)
            release.set()
            await asyncio.gather(*control.tasks)
        assert all(pending_ids) and len(set(pending_ids)) == 2
        assert [message.id for message in results] == pending_ids
    finally:
        release.set()
        await control.close()


async def _start_parallel_tasks(inputs, control, handlers):
    """Steer only once every native handler runs, so each waiter sees all gates."""
    started = asyncio.Event()
    running = set()

    def tracked(call_id):
        async def handler(request):
            running.add(call_id)
            if len(running) == len(handlers):
                started.set()
            return await handlers[call_id](request)

        return handler

    waiters = [asyncio.create_task(control.wait_tool(SimpleNamespace(tool_call={"id": call_id, "name": "task", "args": {}}), tracked(call_id))) for call_id in handlers]
    await asyncio.wait_for(started.wait(), 2)
    await inputs.submit("update", "Handle this first", "steer")
    return await asyncio.wait_for(asyncio.gather(*waiters), 5)


@pytest.mark.asyncio
async def test_parallel_pending_results_keep_their_own_ids():
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    control = RunInputControl(inputs, agent_runs=None, thread_id="thread", checkpointer=None)
    release = asyncio.Event()

    async def handler(request):
        await release.wait()
        return ToolMessage(content="Finished", name="task", tool_call_id=request.tool_call["id"])

    try:
        replies = await _start_parallel_tasks(inputs, control, {"first": handler, "second": handler})
        assert [reply.tool_call_id for reply in replies] == ["first", "second"]
        assert [reply.id for reply in replies] == [control.children[reply.tool_call_id][0].result_id for reply in replies]
        assert replies[0].id != replies[1].id
    finally:
        release.set()
        await control.close()


@pytest.mark.asyncio
async def test_finished_task_closes_only_its_own_gate():
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    control = RunInputControl(inputs, agent_runs=None, thread_id="thread", checkpointer=None)
    finished, release = asyncio.Event(), asyncio.Event()

    async def short_task(request):
        await finished.wait()
        return ToolMessage(content="Finished", name="task", tool_call_id="short")

    async def long_task(request):
        await release.wait()
        return ToolMessage(content="Finished", name="task", tool_call_id="long")

    try:
        await _start_parallel_tasks(inputs, control, {"short": short_task, "long": long_task})
        finished.set()
        short_gate, long_gate = control.children["short"][0], control.children["long"][0]
        async with asyncio.timeout(2):
            while not short_gate.closed:
                await asyncio.sleep(0)
        assert not long_gate.closed and not long_gate.resume.is_set()
        control.interrupted_children = {"long"}
        assert control.resume_children("Include 2025") == ["long"]
    finally:
        finished.set()
        release.set()
        await control.close()


class ParallelTaskModel(InputModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.observed.append(messages)
        if len(self.observed) == 1:
            message = AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": "first"}, {"name": "task", "args": {}, "id": "second"}])
        else:
            message = AIMessage(content="New requirement applied")
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.asyncio
async def test_graph_keeps_a_pending_result_for_every_parallel_task():
    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    saver = InMemorySaver()
    control = RunInputControl(inputs, agent_runs=SimpleNamespace(), thread_id="thread", checkpointer=saver)
    entered, release = asyncio.Event(), asyncio.Event()
    started = []

    @tool
    async def task() -> str:
        """Controlled long operation; both parallel calls stay running."""
        started.append(True)
        if len(started) == 2:
            entered.set()
        await release.wait()
        return "Long operation completed"

    model = ParallelTaskModel(observed=[])
    # The real repair layer would otherwise hide a lost result behind a placeholder.
    graph = create_agent(model, tools=[task], middleware=[RunInputAdmissionMiddleware(), DanglingToolCallMiddleware(), RunInputMiddleware()], state_schema=ThreadState, context_schema=dict, checkpointer=saver)
    config = {"configurable": {"thread_id": "thread"}}
    run = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Original task")]}, config, context={INPUT_CONTEXT_KEY: control}))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await inputs.submit("update", "Handle this first", "steer")
        async with asyncio.timeout(5):
            while len(model.observed) < 2:
                await asyncio.sleep(0.01)
        pending = [message for message in model.observed[1] if isinstance(message, ToolMessage)]
        assert [message.tool_call_id for message in pending] == ["first", "second"]
        assert all(message.additional_kwargs.get("subagent_pending") for message in pending)
        checkpoint = await graph.aget_state(config)
        assert [message.tool_call_id for message in checkpoint.values["messages"] if isinstance(message, ToolMessage)] == ["first", "second"]
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(run, return_exceptions=True), 5)
        await control.close()


class SpendingModel(InputModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.observed.append(messages)
        step = len(self.observed)
        calls = [{"name": "task", "args": {}, "id": "long"}] if step == 1 else [{"name": "follow_up", "args": {}, "id": f"follow-{step}"}] if step <= 4 else []
        message = AIMessage(content=f"Step {step}", tool_calls=calls, usage_metadata={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11})
        return ChatResult(generations=[ChatGeneration(message=message)])


def _task_result(tool_call_id, total):
    usage = {"input_tokens": total - 100, "output_tokens": 100, "total_tokens": total}
    return Command(update={"messages": [ToolMessage(content="Child finished", tool_call_id=tool_call_id, name="task", additional_kwargs={SUBAGENT_TOKEN_USAGE_KEY: usage})]})


async def _run_controller():
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    saver = InMemorySaver()
    return inputs, saver, RunInputControl(inputs, agent_runs=SimpleNamespace(), thread_id="thread", checkpointer=saver)


@pytest.mark.asyncio
async def test_budget_stops_on_usage_of_a_task_finished_after_a_steer():
    inputs, saver, control = await _run_controller()
    entered, release = asyncio.Event(), asyncio.Event()
    followed = []

    @tool
    async def task(tool_call_id: Annotated[str, InjectedToolCallId]):
        """A child that spends the whole budget after the lead stopped waiting."""
        entered.set()
        await release.wait()
        return _task_result(tool_call_id, 1_000_000)

    @tool
    async def follow_up() -> str:
        """Lead work that must stop once the child's tokens are charged."""
        followed.append(True)
        release.set()
        async with asyncio.timeout(5):
            while not control.receipts:
                await asyncio.sleep(0.01)
        return "Done"

    budget = TokenBudgetMiddleware.from_config(TokenBudgetConfig(enabled=True, max_tokens=1000))
    context = {INPUT_CONTEXT_KEY: control, "run_id": "run"}
    graph = create_agent(SpendingModel(observed=[]), tools=[task, follow_up], middleware=[RunInputAdmissionMiddleware(), budget, RunInputMiddleware()], state_schema=ThreadState, context_schema=dict, checkpointer=saver)
    run = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Original task")]}, {"configurable": {"thread_id": "thread"}}, context=context))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await inputs.submit("update", "Handle this too", "steer")
        result = await asyncio.wait_for(run, 10)
        assert context.get("stop_reason") == "token_capped"
        assert len(followed) == 1
        assert not result["messages"][-1].tool_calls
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(run, return_exceptions=True), 5)
        await control.close()


@pytest.mark.asyncio
async def test_parallel_deferred_usage_is_charged_once_to_its_dispatch():
    inputs, saver, control = await _run_controller()
    entered, release = asyncio.Event(), asyncio.Event()
    started = []

    @tool
    async def task(tool_call_id: Annotated[str, InjectedToolCallId]):
        """Both parallel calls finish after the Steer released their waiters."""
        started.append(tool_call_id)
        if len(started) == 2:
            entered.set()
        await release.wait()
        return _task_result(tool_call_id, 200 if tool_call_id == "first" else 300)

    model = ParallelTaskModel(observed=[])
    budget = TokenBudgetMiddleware.from_config(TokenBudgetConfig(enabled=True, max_tokens=10_000))
    config = {"configurable": {"thread_id": "thread"}}
    graph = create_agent(model, tools=[task], middleware=[RunInputAdmissionMiddleware(), budget, RunInputMiddleware()], state_schema=ThreadState, context_schema=dict, checkpointer=saver)
    run = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Original task")]}, config, context={INPUT_CONTEXT_KEY: control, "run_id": "run"}))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await inputs.submit("update", "Handle this first", "steer")
        async with asyncio.timeout(5):
            while len(model.observed) < 2:
                await asyncio.sleep(0.01)
        release.set()
        result = await asyncio.wait_for(run, 10)
        dispatch = next(message for message in result["messages"] if isinstance(message, AIMessage) and message.tool_calls)
        assert dispatch.usage_metadata == {"input_tokens": 300, "output_tokens": 200, "total_tokens": 500}
        assert budget._cumulative_usage["run"].total == 500
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(run, return_exceptions=True), 5)
        await control.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(("usage", "charged"), [({"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}, 7), ({"total_tokens": "many"}, None)])
async def test_deferred_usage_survives_a_compacted_dispatch(usage, charged):
    _, _, control = await _run_controller()
    control.calls["compacted"] = {"name": "task", "args": {}, "id": "compacted"}

    async def finished():
        return ToolMessage(content="Child finished", tool_call_id="compacted", name="task", additional_kwargs={SUBAGENT_TOKEN_USAGE_KEY: usage})

    await control._observe(asyncio.create_task(finished()), "compacted")
    latest = AIMessage(id="latest", content="Summarized history", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
    update = await control.deliver({"messages": [AIMessage(id="older", content="Before"), HumanMessage(content="Next"), latest]})

    rewritten = [message for message in update["messages"] if isinstance(message, AIMessage)]
    if charged is None:
        assert not rewritten
    else:
        assert [(message.id, message.usage_metadata["total_tokens"]) for message in rewritten] == [("latest", 2 + charged)]
    assert await control.deliver({"messages": [latest]}) is None


def test_deferred_usage_with_no_ai_message_to_charge_is_reported(caplog):
    from deerflow.agents.middlewares.token_usage_middleware import attribute_deferred_subagent_usage

    usage = {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}
    with caplog.at_level("WARNING", logger="deerflow.agents.middlewares.token_usage_middleware"):
        assert attribute_deferred_subagent_usage([HumanMessage(content="Only input")], [("lost", usage)]) == []
    assert "lost" in caplog.text


class SettledStepModel(InputModel):
    first_calls: list

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.observed.append(messages)
        step = len(self.observed)
        calls = self.first_calls if step == 1 else [{"name": "follow_up", "args": {}, "id": f"follow-{step}"}] if step == 2 else []
        message = AIMessage(content=f"Step {step}", tool_calls=calls, usage_metadata={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11})
        return ChatResult(generations=[ChatGeneration(message=message)])


def _delegated(call_id):
    return {"name": "task", "args": {"description": call_id, "subagent_type": "general-purpose"}, "id": call_id}


def _finished_task(call_id, total):
    usage = {"input_tokens": total - 100, "output_tokens": 100, "total_tokens": total}
    kwargs = make_subagent_additional_kwargs("completed", result=f"{call_id} report", token_usage=usage)
    return Command(update={"messages": [ToolMessage(content=f"{call_id} report", tool_call_id=call_id, name="task", additional_kwargs=kwargs)]})


def _settled_graph(model, tools, saver, *guards):
    from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware

    return create_agent(
        model, tools=tools, middleware=[RunInputAdmissionMiddleware(), DurableContextMiddleware(), *guards, CompletedSubagentUsageMiddleware(), RunInputMiddleware()], state_schema=ThreadState, context_schema=dict, checkpointer=saver
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("opening_marked", [True, False])
async def test_steer_keeps_a_task_finished_in_the_same_step(opening_marked):
    inputs, saver, control = await _run_controller()
    finished, entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    followed = []

    @tool
    async def task(description: str, subagent_type: str, tool_call_id: Annotated[str, InjectedToolCallId]):
        """A child that ends before the steer, so nothing defers its result."""
        finished.set()
        return _finished_task(tool_call_id, 1_000_000)

    @tool
    async def slow() -> str:
        """A sibling that keeps the step open while the steer arrives."""
        entered.set()
        await release.wait()
        return "Done"

    @tool
    async def follow_up() -> str:
        """Lead work that must stop once the child's tokens are charged."""
        followed.append(True)
        return "Done"

    budget = TokenBudgetMiddleware.from_config(TokenBudgetConfig(enabled=True, max_tokens=1000))
    context = {INPUT_CONTEXT_KEY: control, "run_id": "run", CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()}
    model = SettledStepModel(observed=[], first_calls=[_delegated("done"), {"name": "slow", "args": {}, "id": "sibling"}])
    graph = _settled_graph(model, [task, slow, follow_up], saver, budget)
    opening = HumanMessage(content="Original task", id="opening", additional_kwargs={"run_id": "run"} if opening_marked else {})
    run = asyncio.create_task(graph.ainvoke({"messages": [opening]}, {"configurable": {"thread_id": "thread"}}, context=context))
    try:
        await asyncio.wait_for(asyncio.gather(finished.wait(), entered.wait()), 5)
        await inputs.submit("update", "Handle this too", "steer")
        release.set()
        result = await asyncio.wait_for(run, 10)
        [entry] = result["delegations"]
        assert (entry["id"], entry["status"], entry["result_brief"]) == ("done", "completed", "done report")
        assert context.get("stop_reason") == "token_capped"
        assert not followed
        assert next(x for x in result["messages"] if isinstance(x, AIMessage)).usage_metadata["total_tokens"] == 1_000_011
        later = await graph.ainvoke({"messages": [HumanMessage(content="Next turn", id="later", additional_kwargs={"run_id": "later"})]}, {"configurable": {"thread_id": "thread"}}, context={"run_id": "later"})
        assert [entry["status"] for entry in later["delegations"]] == ["completed"]
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(run, return_exceptions=True), 5)
        await control.close()


@pytest.mark.asyncio
async def test_steer_settles_finished_and_pending_siblings_once_each():
    inputs, saver, control = await _run_controller()
    finished, entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    @tool
    async def task(description: str, subagent_type: str, tool_call_id: Annotated[str, InjectedToolCallId]):
        """One child ends before the steer and the other outlives it."""
        if tool_call_id == "short":
            finished.set()
            return _finished_task(tool_call_id, 100)
        entered.set()
        await release.wait()
        return _finished_task(tool_call_id, 1000)

    @tool
    async def follow_up() -> str:
        """Hold the turn until the pending child's receipt is ready."""
        release.set()
        async with asyncio.timeout(5):
            while not control.receipts:
                await asyncio.sleep(0.01)
        return "Done"

    model = SettledStepModel(observed=[], first_calls=[_delegated("short"), _delegated("long")])
    graph = _settled_graph(model, [task, follow_up], saver)
    context = {INPUT_CONTEXT_KEY: control, "run_id": "run"}
    run = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Original task", additional_kwargs={"run_id": "run"})]}, {"configurable": {"thread_id": "thread"}}, context=context))
    try:
        await asyncio.wait_for(asyncio.gather(finished.wait(), entered.wait()), 5)
        await inputs.submit("update", "Handle this too", "steer")
        result = await asyncio.wait_for(run, 10)
        assert {entry["id"]: entry["status"] for entry in result["delegations"]} == {"short": "completed", "long": "completed"}
        assert next(x for x in result["messages"] if isinstance(x, AIMessage)).usage_metadata["total_tokens"] == 1111
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(run, return_exceptions=True), 5)
        await control.close()


def test_steer_does_not_open_a_resumed_runs_delegation_window():
    from deerflow.agents.middlewares.durable_context_middleware import _run_opening_human_index

    opening = HumanMessage(content="Start", id="opening", additional_kwargs={"run_id": "first"})
    steer = HumanMessage(content="Update", id="steer", additional_kwargs={"run_id": "first", "run_input_id": "input"})
    assert _run_opening_human_index([opening, steer], "first", frozenset()) == 0
    assert _run_opening_human_index([opening, steer], "resumed", frozenset({"opening", "steer"})) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("capped", [False, True])
async def test_input_during_inference_defers_old_actions_but_never_overrides_budget(capped):
    from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
    from deerflow.config.token_budget_config import TokenBudgetConfig

    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    control = RunInputControl(inputs, agent_runs=None, thread_id="thread", checkpointer=InMemorySaver())
    entered, release = asyncio.Event(), asyncio.Event()
    executed = []

    @tool
    async def task() -> str:
        """An obsolete action that must never be executed."""
        executed.append("old")
        return "obsolete"

    @tool
    async def apply_extra() -> str:
        """Perform the newly requested action."""
        executed.append("new")
        return "updated"

    model = GatedInputModel(observed=[], entered=entered, release=release)
    middleware = [RunInputAdmissionMiddleware()]
    if capped:
        middleware.append(TokenBudgetMiddleware.from_config(TokenBudgetConfig(enabled=True, max_tokens=1000)))
    middleware.append(RunInputMiddleware())
    context = {INPUT_CONTEXT_KEY: control, "run_id": "run"}
    graph = create_agent(model, tools=[task, apply_extra], middleware=middleware, state_schema=ThreadState, context_schema=dict, checkpointer=control.checkpointer)
    run = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Original task")]}, {"configurable": {"thread_id": "thread"}}, context=context))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        await inputs.submit("update", "Do the new work instead", "steer")
        release.set()
        result = await asyncio.wait_for(run, 5)
        assert "old" not in executed
        if capped:
            assert executed == [] and len(model.observed) == 1
            assert context["stop_reason"] == "token_capped"
        else:
            assert executed == ["new"]
            corrected = next(m for m in result["messages"] if isinstance(m, AIMessage))
            assert not corrected.tool_calls and "tool_calls" not in corrected.additional_kwargs
    finally:
        release.set()
        if not run.done():
            run.cancel()
        await asyncio.gather(run, return_exceptions=True)
        await control.close()


@pytest.mark.asyncio
async def test_graph_applies_input_before_long_tool_finishes_and_confirms_durable_receipt(tmp_path):
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    saver = InMemorySaver()
    control = RunInputControl(inputs, agent_runs=SimpleNamespace(), thread_id="thread", checkpointer=saver)
    entered, release, applied = asyncio.Event(), asyncio.Event(), asyncio.Event()

    @tool
    async def task() -> str:
        """Controlled long operation; its real coroutine stays owned."""
        entered.set()
        await release.wait()
        return "Long operation completed"

    @tool
    async def apply_extra() -> str:
        """Write the updated requirement into the isolated work directory."""
        (tmp_path / "extra.txt").write_text("extra")
        applied.set()
        return "Written"

    observed = []
    model = InputModel(observed=observed)
    observed = model.observed
    graph = create_agent(model, tools=[task, apply_extra], middleware=[RunInputAdmissionMiddleware(), RunInputMiddleware()], state_schema=ThreadState, context_schema=dict, checkpointer=saver)
    config = {"configurable": {"thread_id": "thread"}}
    run = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Original task")]}, config, context={INPUT_CONTEXT_KEY: control}))
    try:
        entered_task = asyncio.create_task(entered.wait())
        done, _ = await asyncio.wait([run, entered_task], timeout=5, return_when=asyncio.FIRST_COMPLETED)
        if run in done:
            run.result()
        if not entered_task.done():
            entered_task.cancel()
        assert entered.is_set()
        await inputs.submit("extra", "Include the extra requirement", "steer")
        await asyncio.wait_for(applied.wait(), 5)
        assert not run.done()
        assert any(any(m.additional_kwargs.get("run_input_id") == "extra" for m in batch) for batch in observed)
        release.set()
        result = await asyncio.wait_for(run, 5)
        assert result["applied_run_inputs"] == {"run_id": "run", "ids": ["extra"]}
        # Summaries can remove message text; the independent graph receipt
        # still proves it was applied before the store acknowledgement.
        ids = [m.id for m in result["messages"] if m.additional_kwargs.get("run_input_id")]
        await graph.aupdate_state(config, {"messages": [RemoveMessage(id=x) for x in ids]})
        await control.confirm_checkpoint()
        assert (await inputs.read())["items"][0]["status"] == "applied"
    finally:
        release.set()
        if not run.done():
            run.cancel()
        await asyncio.gather(run, return_exceptions=True)
        await control.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("steered", [False, True])
async def test_control_tool_cannot_cancel_without_an_authorized_direct_input(steered):
    from unittest.mock import AsyncMock

    from deerflow_extension_api.agent_runs import AgentRunError

    from deerflow.agents.middlewares.run_input_middleware import manage_current_work

    capability = SimpleNamespace(authorize_control=AsyncMock(side_effect=AgentRunError(403, "Cancellation denied")))
    control = RunInputControl(RunInputs(MemoryRunStore(), "run", "owner", "worker"), agent_runs=capability, thread_id="thread", checkpointer=None)
    control.current_input = "direct" if steered else None
    gate = control.child("old-task")
    gate.resume.clear()
    runtime = SimpleNamespace(context={INPUT_CONTEXT_KEY: control}, state={"goal": {"objective": "Keep working", "status": "active"}}, tool_call_id="control")
    with pytest.raises(AgentRunError if steered else ValueError):
        await manage_current_work.coroutine(action="replace", runtime=runtime)
    assert not gate.resume.is_set()
    assert not control.abandoned and runtime.state["goal"]["status"] == "active"


@pytest.mark.asyncio
async def test_child_accepts_late_requirements_before_finalizing_but_not_after_close():
    gate = ChildInputGate()
    gate.resume.clear()
    finish = asyncio.create_task(gate.finish())
    try:
        async with asyncio.timeout(2):
            while not gate.paused.is_set():
                await asyncio.sleep(0)
        assert gate.release("Include 2025")
        update = await asyncio.wait_for(finish, 2)
        assert update["jump_to"] == "model" and "2025" in update["messages"][0].content
        assert update["messages"][0].additional_kwargs["untrusted_input"]
        assert await gate.finish() is None
        assert not gate.release("Too late")
    finally:
        gate.close()
        await asyncio.gather(finish, return_exceptions=True)


@pytest.mark.asyncio
async def test_paused_children_do_not_require_expanding_the_execution_pool():
    from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
    from deerflow.subagents.capacity import SubagentCapacityRejected, SubagentExecutionCapacity

    control = RunInputControl(RunInputs(MemoryRunStore(), "run", "owner", "worker"), agent_runs=None, thread_id="thread", checkpointer=None)
    gate = control.child("old")
    gate.resume.clear()
    assert not control.child("priority").can_queue
    capacity = SubagentExecutionCapacity(SubagentRuntimeConfig(max_running=1))
    async with capacity.slot():
        async with asyncio.timeout(2):
            with pytest.raises(SubagentCapacityRejected):
                async with capacity.slot(wait=False):
                    pytest.fail("Must not exceed the configured execution pool")


@pytest.mark.asyncio
@pytest.mark.parametrize("sources", [("extension",), ("user", "extension"), ("extension", "user")])
async def test_control_tool_authority_is_independent_of_input_source_order(sources):
    from langchain.agents.middleware.types import ModelRequest

    from deerflow.agents.middlewares.run_input_middleware import manage_current_work

    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    for index, source in enumerate(sources):
        await inputs.submit(str(index), "Replace the Goal", "steer", source=source)
    control = RunInputControl(inputs, agent_runs=None, thread_id="thread", checkpointer=None)
    update = await control.deliver({})
    extension = next(m for m in update["messages"] if m.additional_kwargs["run_input_source"] == "extension")
    assert extension.additional_kwargs["hide_from_ui"]
    request = ModelRequest(model=InputModel(observed=[]), messages=update["messages"], tools=[manage_current_work], runtime=SimpleNamespace(context={INPUT_CONTEXT_KEY: control}))

    async def available_tools(request):
        return [tool.name for tool in request.tools]

    names = await RunInputMiddleware().awrap_model_call(request, available_tools)
    assert ("manage_current_work" in names) == ("user" in sources)


@pytest.mark.asyncio
async def test_graph_finishing_with_a_concurrent_steer_applies_it_before_closing(tmp_path, monkeypatch):
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    saver = InMemorySaver()
    control = RunInputControl(inputs, agent_runs=None, thread_id="thread", checkpointer=saver)
    closing, release = asyncio.Event(), asyncio.Event()
    original_close = inputs.close

    async def gated_close(delivered=None):
        if not closing.is_set():
            closing.set()
            await release.wait()
        return await original_close(delivered)

    monkeypatch.setattr(inputs, "close", gated_close)

    @tool
    async def task() -> str:
        """Complete the original work."""
        return "Done"

    @tool
    async def apply_extra() -> str:
        """Apply the user's correction before completing the Run."""
        (tmp_path / "correction.txt").write_text("applied")
        return "Updated"

    graph = create_agent(InputModel(observed=[]), tools=[task, apply_extra], middleware=[RunInputAdmissionMiddleware(), RunInputMiddleware()], state_schema=ThreadState, context_schema=dict, checkpointer=saver)
    run = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Original task")]}, {"configurable": {"thread_id": "thread"}}, context={INPUT_CONTEXT_KEY: control}))
    try:
        await asyncio.wait_for(closing.wait(), 5)
        await inputs.submit("last", "Apply this correction", "steer")
        release.set()
        await asyncio.wait_for(run, 5)
        assert (tmp_path / "correction.txt").read_text() == "applied"
        state = await inputs.read()
        assert state["closed"] and state["items"][0]["status"] == "applied"
    finally:
        release.set()
        if not run.done():
            run.cancel()
        await asyncio.gather(run, return_exceptions=True)
        await control.close()


class ChildAndSiblingModel(InputModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.observed.append(messages)
        if len(self.observed) == 1:
            message = AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": "child"}, {"name": "sibling", "args": {}, "id": "slow"}])
        else:
            message = AIMessage(content="Work completed")
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.asyncio
async def test_steer_withdrawn_before_delivery_releases_the_children_it_paused():
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    saver = InMemorySaver()
    control = RunInputControl(inputs, agent_runs=SimpleNamespace(), thread_id="thread", checkpointer=saver)
    entered, withdrawn, sibling_release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    @tool
    async def task() -> str:
        """Controlled child; a real one parks at this boundary before its next model call."""
        entered.set()
        await withdrawn.wait()
        await control.child("child").boundary()
        return "Child result"

    @tool
    async def sibling() -> str:
        """Keeps the tool step open, so the steer is withdrawn before delivery."""
        await sibling_release.wait()
        return "Sibling result"

    model = ChildAndSiblingModel(observed=[])
    graph = create_agent(model, tools=[task, sibling], middleware=[RunInputAdmissionMiddleware(), RunInputMiddleware()], state_schema=ThreadState, context_schema=dict, checkpointer=saver)
    run = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Original task")]}, {"configurable": {"thread_id": "thread"}}, context={INPUT_CONTEXT_KEY: control}))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await inputs.submit("update", "Handle this first", "steer")
        gate = control.child("child")
        async with asyncio.timeout(5):
            while gate.resume.is_set():
                await asyncio.sleep(0.01)
        await inputs.cancel("update")
        withdrawn.set()
        sibling_release.set()
        result = await asyncio.wait_for(run, 5)
        assert any(message.name == "subagent-result" and "Child result" in message.content for message in result["messages"])
        assert not any(message.additional_kwargs.get("run_input_id") for message in result["messages"])
        assert (await inputs.read())["items"][0]["status"] == "cancelled"
    finally:
        withdrawn.set()
        sibling_release.set()
        if not run.done():
            run.cancel()
        await asyncio.gather(run, return_exceptions=True)
        await control.close()


@pytest.mark.asyncio
async def test_children_stay_paused_while_a_delivered_steer_is_being_handled():
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    await inputs.submit("update", "Handle this first", "steer")
    control = RunInputControl(inputs, agent_runs=None, thread_id="thread", checkpointer=None)
    gate = control.child("child")
    gate.resume.clear()
    assert (await control.deliver({}))["applied_run_inputs"]["ids"] == ["update"]
    # Later model turns of the same steer have nothing to deliver, yet the
    # user's decision on the paused children is still outstanding.
    assert await control.deliver({}) is None
    assert not gate.resume.is_set()
    await control.close()


@pytest.mark.asyncio
async def test_steer_withdrawn_during_a_steering_turn_releases_the_child_it_paused():
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    # Delivered at the first model boundary, before any child exists, so the
    # child paused below is outside this steer's interrupted snapshot.
    await inputs.submit("first", "Delegate the new work", "steer")
    saver = InMemorySaver()
    control = RunInputControl(inputs, agent_runs=SimpleNamespace(), thread_id="thread", checkpointer=saver)
    entered, withdrawn, sibling_release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    @tool
    async def task() -> str:
        """Controlled child; a real one parks at this boundary before its next model call."""
        entered.set()
        await withdrawn.wait()
        await control.child("child").boundary()
        return "Child result"

    @tool
    async def sibling() -> str:
        """Keeps the tool step open, so the second steer is withdrawn before delivery."""
        await sibling_release.wait()
        return "Sibling result"

    model = ChildAndSiblingModel(observed=[])
    graph = create_agent(model, tools=[task, sibling], middleware=[RunInputAdmissionMiddleware(), RunInputMiddleware()], state_schema=ThreadState, context_schema=dict, checkpointer=saver)
    run = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Original task")]}, {"configurable": {"thread_id": "thread"}}, context={INPUT_CONTEXT_KEY: control}))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert control.steering_active and control.interrupted_children == set()
        await inputs.submit("second", "Handle this first", "steer")
        gate = control.child("child")
        async with asyncio.timeout(5):
            while gate.resume.is_set():
                await asyncio.sleep(0.01)
        await inputs.cancel("second")
        withdrawn.set()
        sibling_release.set()
        result = await asyncio.wait_for(run, 5)
        assert any(message.name == "subagent-result" and "Child result" in message.content for message in result["messages"])
        assert {item["id"]: item["status"] for item in (await inputs.read())["items"]}["second"] == "cancelled"
    finally:
        withdrawn.set()
        sibling_release.set()
        if not run.done():
            run.cancel()
        await asyncio.gather(run, return_exceptions=True)
        await control.close()


class ReplacementReusingCallIdModel(InputModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.observed.append(messages)
        calls = {
            1: [{"name": "task", "args": {}, "id": "call_0"}],
            2: [{"name": "manage_current_work", "args": {"action": "replace"}, "id": "replace"}],
            3: [{"name": "task", "args": {}, "id": "call_0"}, {"name": "sibling", "args": {}, "id": "slow"}],
        }.get(len(self.observed), [])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="" if calls else "Work completed", tool_calls=calls))])


@pytest.mark.asyncio
async def test_steer_withdrawn_from_a_replacement_reusing_a_call_id_releases_it():
    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    saver = InMemorySaver()
    old_finished, entered, replacement_entered, withdrawn, sibling_release = (asyncio.Event() for _ in range(5))

    async def authorize_control(**kwargs):
        old_finished.set()
        async with asyncio.timeout(5):
            while not old_gate.closed:
                await asyncio.sleep(0.01)

    control = RunInputControl(inputs, agent_runs=SimpleNamespace(authorize_control=authorize_control), thread_id="thread", checkpointer=saver)
    started = []

    @tool
    async def task() -> str:
        """The first call is replaced; the second reuses its provider call ID."""
        started.append(True)
        if len(started) == 1:
            entered.set()
            await old_finished.wait()
            return "Old result"
        replacement_entered.set()
        await withdrawn.wait()
        await control.child("call_0").boundary()
        return "Replacement result"

    @tool
    async def sibling() -> str:
        """Keeps the tool step open, so the second steer is withdrawn before delivery."""
        await sibling_release.wait()
        return "Sibling result"

    model = ReplacementReusingCallIdModel(observed=[])
    middleware = [RunInputAdmissionMiddleware(), DanglingToolCallMiddleware(), RunInputMiddleware()]
    graph = create_agent(model, tools=[task, sibling], middleware=middleware, state_schema=ThreadState, context_schema=dict, checkpointer=saver)
    run = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Original task")]}, {"configurable": {"thread_id": "thread"}}, context={INPUT_CONTEXT_KEY: control}))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        old_gate = control.child("call_0")
        await inputs.submit("first", "Do this instead", "steer")
        await asyncio.wait_for(replacement_entered.wait(), 5)
        gate = control.child("call_0")
        assert gate is not old_gate and control.abandoned
        await inputs.submit("second", "Handle this first", "steer")
        async with asyncio.timeout(5):
            while gate.resume.is_set():
                await asyncio.sleep(0.01)
        await inputs.cancel("second")
        withdrawn.set()
        sibling_release.set()
        result = await asyncio.wait_for(run, 5)
        assert any(message.name == "subagent-result" and "Replacement result" in message.content for message in result["messages"])
        assert {item["id"]: item["status"] for item in (await inputs.read())["items"]}["second"] == "cancelled"
    finally:
        old_finished.set()
        withdrawn.set()
        sibling_release.set()
        if not run.done():
            run.cancel()
        await asyncio.gather(run, return_exceptions=True)
        await control.close()


@pytest.mark.asyncio
async def test_withdrawn_steer_keeps_children_held_by_the_delivered_steer_paused():
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    await inputs.submit("first", "Handle this first", "steer")
    control = RunInputControl(inputs, agent_runs=None, thread_id="thread", checkpointer=None)
    held = control.child("held")
    held.resume.clear()
    await control.deliver({})
    released = control.child("released")
    released.resume.clear()
    assert await control.deliver({}) is None
    assert released.resume.is_set()
    assert not held.resume.is_set()
    await control.close()


@pytest.mark.asyncio
async def test_terminal_queue_worker_remains_owned_until_it_stops():
    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.schemas import RunStatus

    manager = RunManager(store=MemoryRunStore())
    record = await manager.create("thread")
    await manager.set_status(record.run_id, RunStatus.success)
    release = asyncio.Event()
    producer = asyncio.create_task(release.wait())
    record.task = producer
    cleanup = asyncio.create_task(manager.cleanup(record.run_id, delay=0))
    try:
        await asyncio.sleep(0)
        assert not cleanup.done()
        assert (await manager.get(record.run_id)).task is producer
        release.set()
        await asyncio.wait_for(cleanup, 2)
        assert (await manager.get(record.run_id)).task is None
    finally:
        release.set()
        await asyncio.gather(producer, cleanup, return_exceptions=True)
