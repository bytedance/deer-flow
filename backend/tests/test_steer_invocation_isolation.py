"""A provider's reused tool-call ID must not alias overlapping child executions."""

import asyncio
import inspect
import json
from types import SimpleNamespace
from typing import Annotated

import pytest
from langchain.agents import create_agent
from langchain.tools import ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ConfigDict

from deerflow.agents.middlewares.run_input_middleware import RunInputAdmissionMiddleware, RunInputMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.runtime.runs.input_control import RunInputControl
from deerflow.runtime.runs.inputs import INPUT_CONTEXT_KEY, RunInputs
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.subagents.status_contract import SUBAGENT_TOKEN_USAGE_KEY, make_subagent_additional_kwargs


async def _controller():
    store = MemoryRunStore()
    await store.put("run", thread_id="thread", user_id="owner", status="running", owner_worker_id="worker")
    inputs = RunInputs(store, "run", "owner", "worker")
    control = RunInputControl(inputs, agent_runs=None, thread_id="thread", checkpointer=InMemorySaver())
    return inputs, control


def _dispatch(label, call_id="call_0"):
    return AIMessage(content="", id=f"dispatch-{label}", tool_calls=[{"id": call_id, "name": "task", "args": {"label": label}}])


def _result(label, call_id, result_id=None, total=10):
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=f"Report {label}",
                    id=result_id,
                    name="task",
                    tool_call_id=call_id,
                    additional_kwargs={
                        **make_subagent_additional_kwargs("completed", result=f"Report {label}"),
                        SUBAGENT_TOKEN_USAGE_KEY: {"input_tokens": total - 1, "output_tokens": 1, "total_tokens": total},
                    },
                )
            ]
        }
    )


class SteeredModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    second_call_id: str
    observed: list = []

    @property
    def _llm_type(self):
        return "offline-steered-reuse"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.observed.append(messages)
        if len(self.observed) == 1:
            message = _dispatch("A")
        elif not any(isinstance(message, ToolMessage) and message.content == "Report B" for message in messages):
            message = _dispatch("B", self.second_call_id)
        else:
            message = AIMessage(content="Both reports incorporated")
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.asyncio
@pytest.mark.parametrize("second_call_id", ["call_0", "different"])
async def test_graph_runs_priority_child_while_steered_child_waits(second_call_id):
    inputs, control = await _controller()
    started_a, started_b, crossed_b, finish_b = (asyncio.Event() for _ in range(4))
    reach_a_boundary = asyncio.Event()
    gates = {}

    @tool("task")
    async def task(label: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
        """Produce a controlled report at a real child input boundary."""
        gate = control.child(tool_call_id)
        gates[label] = gate
        if label == "A":
            started_a.set()
            await reach_a_boundary.wait()
        else:
            started_b.set()
        await gate.boundary()
        if label == "B":
            crossed_b.set()
            await finish_b.wait()
        return _result(label, tool_call_id, gate.result_id)

    model = SteeredModel(second_call_id=second_call_id)
    graph = create_agent(
        model,
        tools=[task],
        middleware=[RunInputAdmissionMiddleware(), RunInputMiddleware()],
        state_schema=ThreadState,
        context_schema=dict,
        checkpointer=control.checkpointer,
    )
    config = {"configurable": {"thread_id": "thread"}}
    run = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Start A")]}, config, context={INPUT_CONTEXT_KEY: control}))
    try:
        await asyncio.wait_for(started_a.wait(), 5)
        await inputs.submit("steer", "Complete B first, then resume A", "steer")
        await asyncio.wait_for(started_b.wait(), 5)
        reach_a_boundary.set()
        await asyncio.wait_for(crossed_b.wait(), 5)
        assert not gates["A"].resume.is_set(), "B must execute without resuming the interrupted A"
        assert gates["A"] is not gates["B"]
        finish_b.set()
        result = await asyncio.wait_for(run, 5)
        receipts = [message for message in result["messages"] if message.additional_kwargs.get("origin_task_id")]
        assert len(receipts) == 1 and "Report A" in receipts[0].content
        assert any(isinstance(message, ToolMessage) and message.content == "Report B" for message in result["messages"])
        snapshot = await graph.aget_state(config)
        assert snapshot.values["applied_run_inputs"] == {"run_id": "run", "ids": ["steer"]}
        assert (await inputs.read())["items"][0]["status"] == "applied"
    finally:
        reach_a_boundary.set()
        finish_b.set()
        if not run.done():
            run.cancel()
        await asyncio.gather(run, return_exceptions=True)
        await control.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("order", [("A", "B"), ("B", "A")])
async def test_overlapping_reports_keep_distinct_receipts_and_dispatch_usage(order):
    inputs, control = await _controller()
    releases = {label: asyncio.Event() for label in order}
    started = {label: asyncio.Event() for label in order}
    native, gates = {}, {}
    await inputs.submit("steer", "Reconsider both tasks", "steer")
    try:
        pending = {}
        for label in ("A", "B"):
            dispatch = _dispatch(label)

            async def handler(request, label=label):
                gate = control.child(request.tool_call["id"])
                gates[label] = gate
                native[label] = asyncio.current_task()
                started[label].set()
                await releases[label].wait()
                return _result(label, request.tool_call["id"], gate.result_id, 10 if label == "A" else 20)

            pending[label] = await control.wait_tool(SimpleNamespace(tool_call=dispatch.tool_calls[0], state={"messages": [dispatch]}), handler)
            await asyncio.wait_for(started[label].wait(), 5)

        for index, label in enumerate(order):
            releases[label].set()
            await asyncio.wait_for(asyncio.shield(native[label]), 5)
            if index == 0:
                assert not gates[order[1]].closed, "Completing one child must not close its sibling's input gate"
        await asyncio.gather(*control.tasks)
        update = await control.deliver({"messages": [_dispatch("A"), pending["A"], _dispatch("B"), pending["B"]]})
        receipts = [message for message in update["messages"] if isinstance(message, HumanMessage) and message.additional_kwargs.get("origin_task_id")]
        assert len({message.id for message in receipts}) == 2, "Both delayed reports must survive the messages reducer"
        assert {json.loads(message.content)["result"] for message in receipts} == {"Report A", "Report B"}
        assert all(json.loads(message.content)["task_call_id"] == "call_0" for message in receipts)
        assert all(message.additional_kwargs["hide_from_ui"] and message.additional_kwargs["untrusted_input"] for message in receipts)
        usage = {message.id: message.usage_metadata["total_tokens"] for message in update["messages"] if isinstance(message, AIMessage)}
        assert usage == {"dispatch-A": 10, "dispatch-B": 20}
        assert pending["A"].id != pending["B"].id
        assert await control.deliver({"messages": update["messages"]}) is None
    finally:
        for release in releases.values():
            release.set()
        await control.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch_state", ["retained", "compacted", "missing-id"])
async def test_late_usage_uses_original_dispatch_or_compaction_fallback_once(dispatch_state):
    inputs, control = await _controller()
    release = asyncio.Event()
    await inputs.submit("steer", "Prioritize another task", "steer")
    original = _dispatch("A")
    if dispatch_state == "missing-id":
        original.id = None

    async def handler(request):
        await release.wait()
        return _result("A", "call_0", total=17)

    try:
        pending = await control.wait_tool(SimpleNamespace(tool_call=original.tool_calls[0], state={"messages": [original]}), handler)
        release.set()
        await asyncio.gather(*control.tasks)
        # A later response can legitimately reuse call_0. It must not receive
        # A's usage merely because it is the latest matching provider ID.
        history = [_dispatch("B"), AIMessage(id="latest", content="Summary", usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})]
        if dispatch_state != "compacted":
            history = [original, pending, *history]
        update = await control.deliver({"messages": history})
        usage = {message.id: message.usage_metadata["total_tokens"] for message in update["messages"] if isinstance(message, AIMessage)}
        assert usage == ({"dispatch-A": 17} if dispatch_state == "retained" else {"latest": 20})
        assert await control.deliver({"messages": [*history, *update["messages"]]}) is None
    finally:
        release.set()
        await control.close()


def _tool_runtime(control=None):
    return ToolRuntime(state={}, context={INPUT_CONTEXT_KEY: control} if control else {}, config={}, stream_writer=lambda _: None, tools=[], tool_call_id="call_0", store=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("order", [("A", "B"), ("B", "A")])
async def test_native_preflight_failure_preserves_each_pending_message_id(order):
    from deerflow.tools.builtins.task_tool import task_tool

    inputs, control = await _controller()
    releases = {label: asyncio.Event() for label in order}
    completed = {label: asyncio.Event() for label in order}
    results, pending = {}, {}
    await inputs.submit("steer", "Hold the existing tasks", "steer")
    try:
        for label in ("A", "B"):
            dispatch = _dispatch(label)

            async def handler(request, label=label):
                await releases[label].wait()
                result = await task_tool.coroutine(_tool_runtime(control), label, "unused", "call_0", context_mode="invalid")
                results[label] = result.update["messages"][0]
                completed[label].set()
                return result

            pending[label] = await control.wait_tool(SimpleNamespace(tool_call=dispatch.tool_calls[0], state={"messages": [dispatch]}), handler)
        for label in order:
            releases[label].set()
            await asyncio.wait_for(completed[label].wait(), 5)
        await asyncio.gather(*control.tasks)
        assert pending["A"].id != pending["B"].id
        assert {label: message.id for label, message in results.items()} == {label: message.id for label, message in pending.items()}
        assert all(message.additional_kwargs["subagent_status"] == "failed" for message in results.values())
    finally:
        for release in releases.values():
            release.set()
        await control.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_controller", [False, True])
async def test_direct_native_coroutine_keeps_signature_and_owns_its_fallback(with_controller):
    from deerflow.tools.builtins.task_tool import task_tool

    _, control = await _controller()
    runtime = _tool_runtime(control if with_controller else None)
    try:
        positional = await task_tool.coroutine(runtime, "A", "unused", "call_0", context_mode="invalid")
        keyword = await task_tool.coroutine(runtime=runtime, prompt="B", subagent_type="unused", tool_call_id="call_0", context_mode="invalid")
        messages = [result.update["messages"][0] for result in (positional, keyword)]
        assert all(message.additional_kwargs["subagent_status"] == "failed" for message in messages)
        if with_controller:
            assert messages[0].id and messages[1].id and messages[0].id != messages[1].id
        else:
            assert [message.id for message in messages] == [None, None]
        parameters = inspect.signature(task_tool.coroutine).parameters
        assert list(parameters) == ["runtime", "prompt", "subagent_type", "tool_call_id", "acceptance_criteria", "description", "context_mode", "model_name"]
        assert parameters["acceptance_criteria"].kind is inspect.Parameter.KEYWORD_ONLY
        assert task_tool.coroutine.__doc__.startswith("Delegate a bounded task")
        schema = task_tool.tool_call_schema.model_json_schema()
        assert set(schema["properties"]) == {"prompt", "subagent_type", "acceptance_criteria", "description", "context_mode", "model_name"}
        assert schema["required"] == ["prompt", "subagent_type"]
    finally:
        await control.close()


@pytest.mark.asyncio
async def test_nested_native_calls_restore_context_without_borrowing_other_calls():
    from deerflow.tools.builtins.task_tool import task_tool

    _, outer = await _controller()
    _, other = await _controller()
    dispatch = _dispatch("outer")
    seen = {}

    async def handler(request):
        gate = outer.child("call_0")
        # Same provider ID in a different Run, then a different ID in this Run.
        # Both direct calls need their own fallback lifetime, and must restore
        # the original handler's context even when preflight rejects the task.
        cross_run = await task_tool.coroutine(_tool_runtime(other), "nested", "unused", "call_0", context_mode="invalid")
        cross_call = await task_tool.coroutine(_tool_runtime(outer), "nested", "unused", "other-id", context_mode="invalid")
        seen.update(outer=gate.result_id, other=cross_run.update["messages"][0].id, nested=cross_call.update["messages"][0].id)
        assert outer.child("call_0") is gate
        assert not gate.closed
        return _result("outer", "call_0", gate.result_id)

    try:
        result = await outer.wait_tool(SimpleNamespace(tool_call=dispatch.tool_calls[0], state={"messages": [dispatch]}), handler)
        assert len(set(seen.values())) == 3
        assert result.update["messages"][0].id == seen["outer"]
        # The native handler's ContextVar must never leak back to its caller.
        with pytest.raises(RuntimeError, match="invocation"):
            outer.child("call_0")
        with pytest.raises(RuntimeError, match="invocation"):
            other.child("call_0")
    finally:
        await outer.close()
        await other.close()


@pytest.mark.asyncio
async def test_old_child_failure_does_not_hide_cancellation_of_reused_call():
    inputs, control = await _controller()
    reported = []
    failure_reported = asyncio.Event()

    def on_result(message):
        reported.append(message)
        if message.additional_kwargs["subagent_status"] == "failed":
            failure_reported.set()

    control.on_result = on_result
    release_old, started_new, release_new = (asyncio.Event() for _ in range(3))
    injected = asyncio.Event()
    await inputs.submit("steer", "Hold both reports", "steer")

    async def old_handler(request):
        await release_old.wait()
        injected.set()
        raise OSError("offline transport failed")

    async def new_handler(request):
        started_new.set()
        await release_new.wait()
        return _result("B", "call_0")

    try:
        old = _dispatch("A")
        old_pending = await control.wait_tool(SimpleNamespace(tool_call=old.tool_calls[0], state={"messages": [old]}), old_handler)
        new = _dispatch("B")
        new_pending = await control.wait_tool(SimpleNamespace(tool_call=new.tool_calls[0], state={"messages": [new]}), new_handler)
        await asyncio.wait_for(started_new.wait(), 5)
        release_old.set()
        # Observe A's failure through the real result callback before parent
        # cancellation, while B is still genuinely suspended.
        await asyncio.wait_for(failure_reported.wait(), 5)
        await control.close()
        assert injected.is_set()
        assert {(message.id, message.additional_kwargs["subagent_status"]) for message in reported} == {
            (old_pending.id, "failed"),
            (new_pending.id, "cancelled"),
        }
        assert old_pending.id != new_pending.id
    finally:
        release_old.set()
        release_new.set()
        await control.close()


@pytest.mark.asyncio
async def test_cancelled_old_native_reports_its_own_result_while_new_child_continues():
    inputs, control = await _controller()
    old_started, new_started, cancelled_reported, finish_new = (asyncio.Event() for _ in range(4))
    native = {}
    reported = []

    def on_result(message):
        reported.append(message)
        if message.additional_kwargs["subagent_status"] == "cancelled":
            cancelled_reported.set()

    control.on_result = on_result
    await inputs.submit("steer", "Let B run first", "steer")
    old, new = _dispatch("A"), _dispatch("B")

    async def old_handler(request):
        native["A"] = asyncio.current_task()
        old_started.set()
        await asyncio.Event().wait()

    async def new_handler(request):
        gate = control.child("call_0")
        native["gate-B"] = gate
        await gate.boundary()
        new_started.set()
        await finish_new.wait()
        return _result("B", "call_0", gate.result_id)

    waiter = None
    try:
        pending = await control.wait_tool(SimpleNamespace(tool_call=old.tool_calls[0], state={"messages": [old]}), old_handler)
        await asyncio.wait_for(old_started.wait(), 5)
        await control.deliver({"messages": [old, pending]})
        waiter = asyncio.create_task(control.wait_tool(SimpleNamespace(tool_call=new.tool_calls[0], state={"messages": [old, pending, new]}), new_handler))
        await asyncio.wait_for(new_started.wait(), 5)
        native["A"].cancel()
        await asyncio.wait_for(cancelled_reported.wait(), 5)
        assert [(message.id, message.additional_kwargs["subagent_status"]) for message in reported] == [(pending.id, "cancelled")]
        assert not native["gate-B"].closed
        finish_new.set()
        result = await asyncio.wait_for(waiter, 5)
        assert result.update["messages"][0].id != pending.id
        assert result.update["messages"][0].content == "Report B"
        update = await control.deliver({"messages": [old, pending, new]})
        receipts = [message for message in update["messages"] if message.additional_kwargs.get("origin_task_id")]
        assert len(receipts) == 1
        assert await control.deliver({"messages": update["messages"]}) is None
    finally:
        finish_new.set()
        if waiter is not None and not waiter.done():
            waiter.cancel()
        if waiter is not None:
            await asyncio.gather(waiter, return_exceptions=True)
        await control.close()


@pytest.mark.asyncio
async def test_duplicate_observation_and_delivery_do_not_repeat_reports_or_usage(monkeypatch):
    inputs, control = await _controller()
    release = asyncio.Event()
    observations = []
    observe = control._observe

    async def capture_observation(*args):
        observations.append(args)
        return await observe(*args)

    # Record the real observer's call, preserving its behavior. Replaying that
    # completion checks idempotence without constructing controller internals.
    monkeypatch.setattr(control, "_observe", capture_observation)
    await inputs.submit("steer", "Hold the report", "steer")
    dispatch = _dispatch("A")

    async def handler(request):
        await release.wait()
        return _result("A", "call_0", total=23)

    try:
        await control.wait_tool(SimpleNamespace(tool_call=dispatch.tool_calls[0], state={"messages": [dispatch]}), handler)
        release.set()
        await asyncio.gather(*control.tasks)
        assert len(observations) == 1
        await asyncio.gather(*(observe(*observations[0]) for _ in range(2)))
        update = await control.deliver({"messages": [dispatch]})
        receipts = [message for message in update["messages"] if message.additional_kwargs.get("origin_task_id")]
        assert len(receipts) == 1
        charged = [message for message in update["messages"] if isinstance(message, AIMessage)]
        assert [(message.id, message.usage_metadata["total_tokens"]) for message in charged] == [("dispatch-A", 23)]
        assert await control.deliver({"messages": update["messages"]}) is None
    finally:
        release.set()
        await control.close()
