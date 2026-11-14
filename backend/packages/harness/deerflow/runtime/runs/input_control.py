"""Run-owned input delivery and native task supervision; no model polling."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.utils.messages import SUBAGENT_RESULT_MESSAGE_NAME

from .inputs import RunInputs
from .schemas import GOAL_RUN_HARD_STOP_REASONS

if TYPE_CHECKING:
    from deerflow.agents.middlewares.token_usage_middleware import DeferredSubagentUsage


class ChildInputGate:
    def __init__(self, *, can_queue=True):
        self.result_id = str(uuid4())
        self.can_queue = can_queue
        self.closed = False
        self.resume = threading.Event()
        self.resume.set()
        self.paused = threading.Event()
        self._lock = threading.Lock()
        self._instructions: list[str] = []

    async def boundary(self):
        if not self.resume.is_set():
            self.paused.set()
            while not self.resume.is_set():
                await asyncio.sleep(0.05)
            self.paused.clear()
        with self._lock:
            text = "\n".join(self._instructions)
            self._instructions.clear()
        if text:
            return {"messages": [HumanMessage(content=text, additional_kwargs={"hide_from_ui": True, "untrusted_input": True})]}
        return None

    def release(self, instructions=""):
        with self._lock:
            accepted = not self.closed
            if instructions and accepted:
                self._instructions.append(instructions)
        self.resume.set()
        return accepted

    def close(self):
        with self._lock:
            self.closed = True
        self.resume.set()

    async def finish(self, stop_reason=None):
        if stop_reason in GOAL_RUN_HARD_STOP_REASONS:
            self.close()
            return None
        while True:
            update = await self.boundary()
            if update is not None:
                return {**update, "jump_to": "model"}
            with self._lock:
                if not self._instructions and self.resume.is_set():
                    self.closed = True
                    return None


def _dispatch_message_id(request) -> str | None:
    """Return the id of the latest AIMessage in the tool request's state that issued its call."""
    state = getattr(request, "state", None)
    messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
    call_id = request.tool_call["id"]
    for message in reversed(messages or []):
        if isinstance(message, AIMessage):
            if any(isinstance(call, dict) and call.get("id") == call_id for call in message.tool_calls or ()):
                return message.id if isinstance(message.id, str) and message.id else None
    return None


@dataclass(eq=False)
class ChildInvocation:
    """One server-owned dispatch, independent of a provider's reusable ID."""

    call_id: str
    gate: ChildInputGate
    dispatch: AIMessage | None = None
    invocation_id: str = field(default_factory=lambda: str(uuid4()))
    execution_id: str | None = None
    pending: bool = False
    finished: bool = False
    cancel_requested: bool = False

    @property
    def dispatch_message_id(self) -> str | None:
        return self.dispatch.id if self.dispatch is not None else None


_child_invocation: ContextVar[tuple[RunInputControl, ChildInvocation] | None] = ContextVar("deerflow_child_invocation", default=None)


class RunInputControl:
    def __init__(self, inputs: RunInputs, *, agent_runs, thread_id: str, checkpointer, on_result=None, on_replan=None):
        self.inputs, self.agent_runs, self.thread_id, self.checkpointer = inputs, agent_runs, thread_id, checkpointer
        self.delivered: set[str] = set()
        self.acknowledged: set[str] = set()
        self.delegations: list[dict] = []
        self.current_input: str | None = None
        self.steering_active = False
        self.tasks: set[asyncio.Task] = set()
        self.observed_tasks: set[asyncio.Task] = set()
        self.children: dict[str, ChildInvocation] = {}
        self.interrupted_children: set[str] = set()
        self.receipts: list[HumanMessage] = []
        self.deferred_usage: list[DeferredSubagentUsage] = []
        self.on_result = on_result
        self.on_replan = on_replan
        self.abandoned = False
        self._closed = False

    def create_invocation(self, call_id: str, dispatch: AIMessage | None = None) -> ChildInvocation:
        if self._closed:
            raise RuntimeError("Run input controller is closed")
        # A delivered steer holds only the invocations it interrupted. A new
        # dispatch starts released, even if its provider ID names held work.
        gate = ChildInputGate(can_queue=not any(not child.gate.resume.is_set() and not child.gate.closed for child in self.children.values()))
        child = ChildInvocation(call_id=call_id, gate=gate, dispatch=dispatch)
        self.children[child.invocation_id] = child
        return child

    def current_invocation(self, call_id: str) -> ChildInvocation | None:
        bound = _child_invocation.get()
        if bound is None:
            return None
        owner, child = bound
        # Context is inherited by tasks. A nested tool or another controller
        # must not borrow a parent's execution just because it has a binding.
        if owner is self and child.call_id == call_id and not child.finished and self.children.get(child.invocation_id) is child:
            return child
        return None

    @contextmanager
    def invocation_scope(self, child: ChildInvocation):
        if self.children.get(child.invocation_id) is not child:
            raise ValueError("Child invocation does not belong to this Run")
        token = _child_invocation.set((self, child))
        try:
            yield child
        finally:
            _child_invocation.reset(token)

    def child(self, call_id: str) -> ChildInputGate:
        """Read the gate of this handler; never resolve ownership by call ID."""
        child = self.current_invocation(call_id)
        if child is None:
            raise RuntimeError("No child invocation is bound to this task handler")
        return child.gate

    def ensure_invocation_active(self, child: ChildInvocation):
        """Fence executor admission after asynchronous preflight/assembly.

        Direct callers are not necessarily tasks supervised by wait_tool. A
        parent close or replace can run while they await assembly, so retain
        cancellation on the captured record even after the registry is cleared.
        """
        if self._closed or child.cancel_requested:
            raise asyncio.CancelledError
        if self.children.get(child.invocation_id) is not child or child.finished:
            raise ValueError("Child invocation is no longer active in this Run")

    def bind_execution(self, child: ChildInvocation, execution_id: str):
        from deerflow.subagents.executor import request_cancel_background_task

        if self.children.get(child.invocation_id) is not child:
            raise ValueError("Child invocation does not belong to this Run")
        child.execution_id = execution_id
        # A replace may arrive while preflight is still running, before an
        # executor exists. Keep that cancellation attached to the same dispatch.
        if child.cancel_requested:
            request_cancel_background_task(execution_id)

    async def pending(self):
        state = await self.inputs.read()
        return [x for x in state["items"] if x["mode"] == "steer" and x["status"] in ("pending", "applying") and x["id"] not in self.delivered]

    async def deliver(self, state):
        from deerflow.agents.middlewares.token_usage_middleware import attribute_deferred_subagent_usage

        entries = await self.pending()
        if entries:
            entries = await self.inputs.claim_steer([x["id"] for x in entries])
        messages = [*attribute_deferred_subagent_usage(state.get("messages", []), self.deferred_usage), *self.receipts]
        self.receipts.clear()
        self.deferred_usage.clear()
        if entries:
            self.abandoned = False
            self.steering_active = True
            self.interrupted_children = set(self.children)
        else:
            # A steer withdrawn before delivery starts no turn whose end would
            # resume the children that wait_tool paused for it. Only the
            # children a delivered steer interrupted may stay paused.
            held = self.interrupted_children if self.steering_active else set()
            for invocation_id, child in self.children.items():
                if invocation_id not in held:
                    child.gate.release()
        for entry in entries:
            self.delivered.add(entry["id"])
            direct = entry.get("source", "user") == "user"
            if direct:
                self.current_input = entry["id"]
            messages.append(
                HumanMessage(
                    content=entry["text"],
                    id=entry["message_id"],
                    name=None if direct else "extension-input",
                    additional_kwargs={"run_input_id": entry["id"], "run_input_source": entry.get("source", "user"), "run_id": self.inputs.run_id, **({"hide_from_ui": True, "untrusted_input": True} if not direct else {})},
                )
            )
        if not messages:
            return None
        update = {"messages": messages, "applied_run_inputs": {"run_id": self.inputs.run_id, "ids": sorted(self.delivered)}}
        if self.delegations:
            update["delegations"] = self.delegations[:]
            self.delegations.clear()
        return update

    async def confirm_checkpoint(self):
        # Confirm the graph's own durable write, including when summaries have
        # removed the original HumanMessage. Acceptance is never an ack.
        if self.checkpointer is None or self.delivered <= self.acknowledged:
            return
        value = await self.checkpointer.aget_tuple({"configurable": {"thread_id": self.thread_id, "checkpoint_ns": ""}})
        progress = value.checkpoint.get("channel_values", {}).get("applied_run_inputs", {}) if value else {}
        if progress.get("run_id") == self.inputs.run_id:
            ids = progress.get("ids", [])
            await self.inputs.acknowledge(ids)
            self.acknowledged.update(ids)

    async def wait_tool(self, request, handler):
        # Name the dispatching AIMessage, as the graph's own capture does, so
        # the steered entry and the captured one are the same delegation. Held
        # per wait, not per call id: a later response reusing the id while this
        # call is still observed must not take over its args or dispatch.
        dispatch = AIMessage(content="", id=_dispatch_message_id(request), tool_calls=[dict(request.tool_call)])
        # Create the gate before scheduling: an immediately available input
        # can arrive before the tool handler reaches the native executor.
        child = self.create_invocation(request.tool_call["id"], dispatch)

        async def invoke():
            with self.invocation_scope(child):
                return await handler(request)

        native = asyncio.create_task(invoke())
        # This callback also covers cancellation before invoke's first step.
        native.add_done_callback(lambda _: child.gate.close())
        self.tasks.add(native)
        try:
            while not native.done():
                if await self.pending():
                    for active in self.children.values():
                        if not active.gate.closed:
                            active.gate.resume.clear()
                    child.pending = True
                    self.observed_tasks.add(native)
                    watcher = asyncio.create_task(self._observe(native, child))
                    self.tasks.add(watcher)
                    return ToolMessage(
                        id=child.gate.result_id,
                        content="The subagent result is pending and will arrive in this Run. The user has sent an updated requirement.",
                        tool_call_id=child.call_id,
                        name="task",
                        additional_kwargs={"subagent_pending": True, "run_id": self.inputs.run_id},
                    )
                await asyncio.wait([native], timeout=0.5)
            result = await native
            child.finished = True
            return result
        except BaseException:
            native.cancel()
            await asyncio.gather(native, return_exceptions=True)
            child.finished = True
            raise

    async def _observe(self, native, child: ChildInvocation):
        try:
            result = await native
            message = result.update["messages"][0] if hasattr(result, "update") else result
        except asyncio.CancelledError:
            # Cancelling this observer belongs to parent shutdown, whose close
            # emits any missing terminal result. Cancellation of the child
            # itself (for example a replace during assembly) still needs its
            # own report while other invocations continue running.
            observer = asyncio.current_task()
            if observer is not None and observer.cancelling():
                raise
            if child.finished:
                return
            message = self._failure(child, "cancelled", "The subagent stopped before its result was collected")
        except Exception:
            if child.finished:
                return
            message = self._failure(child, "failed", "The subagent result could not be collected")
        from deerflow.agents.middlewares.delegation_ledger import extract_delegations
        from deerflow.agents.middlewares.token_usage_middleware import DeferredSubagentUsage
        from deerflow.subagents.status_contract import SUBAGENT_TOKEN_USAGE_KEY, normalize_token_usage

        if child.finished:
            return
        child.finished = True
        dispatch_messages = [child.dispatch, message] if child.dispatch is not None else [message]
        self.delegations.extend({**entry, "run_id": self.inputs.run_id} for entry in extract_delegations(dispatch_messages))
        usage = normalize_token_usage(message.additional_kwargs.get(SUBAGENT_TOKEN_USAGE_KEY))
        if usage:
            self.deferred_usage.append(DeferredSubagentUsage(tool_call_id=child.call_id, dispatch_message_id=child.dispatch_message_id, usage=usage))
        self.receipts.append(
            HumanMessage(
                content=json.dumps({"source": "subagent", "task_call_id": child.call_id, "result": message.content}, ensure_ascii=False),
                name=SUBAGENT_RESULT_MESSAGE_NAME,
                id="run-input-result-" + self.inputs.run_id + "-" + child.invocation_id,
                additional_kwargs={"hide_from_ui": True, "untrusted_input": True, "origin_task_id": child.call_id, "run_id": self.inputs.run_id},
            )
        )

    def _failure(self, child: ChildInvocation, status, text):
        from deerflow.subagents.status_contract import make_subagent_additional_kwargs

        message = ToolMessage(id=child.gate.result_id, content=text, tool_call_id=child.call_id, name="task", additional_kwargs=make_subagent_additional_kwargs(status, error=text))
        if self.on_result is not None:
            self.on_result(message)
        return message

    def resume_children(self, instructions=""):
        accepted = []
        for invocation_id, child in self.children.items():
            if invocation_id in self.interrupted_children:
                if child.gate.release(instructions):
                    accepted.append(child.call_id)
        return accepted

    async def stop_children(self, *, all_children=False):
        from deerflow.subagents.executor import get_background_task_result, request_cancel_background_task

        results = []
        for invocation_id, child in list(self.children.items()):
            if not all_children and invocation_id not in self.interrupted_children:
                continue
            child.cancel_requested = True
            if child.execution_id:
                result = get_background_task_result(child.execution_id)
                request_cancel_background_task(child.execution_id)
                if result is not None:
                    results.append(result)
            child.gate.release()
        for result in results:
            while not result.execution_done_event.is_set():
                await asyncio.sleep(0.05)

    async def finish_graph(self, state, runtime):
        await self.confirm_checkpoint()
        if runtime.context.get("stop_reason") in GOAL_RUN_HARD_STOP_REASONS:
            await self.stop_children(all_children=True)
            return None
        if self.steering_active:
            self.steering_active = False
            self.current_input = None
            if not self.abandoned:
                self.resume_children()
        while True:
            if await self.pending() or self.receipts:
                return {"jump_to": "model"}
            active = [x for x in self.tasks if not x.done()]
            if not active:
                # Input admission and this close serialize in the same store
                # transaction. A concurrent accepted steer must get a turn.
                if await self.inputs.close(self.delivered):
                    return None
                continue
            done, _ = await asyncio.wait(active, timeout=0.5, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task not in self.observed_tasks and not task.cancelled() and task.exception() is not None:
                    raise task.exception()

    async def close(self):
        from deerflow.subagents.executor import request_cancel_background_task

        # Fence direct callers before the first cleanup await. They may still
        # hold this controller while its graph and registry are being released.
        self._closed = True
        for child in self.children.values():
            child.cancel_requested = True
            if child.execution_id:
                request_cancel_background_task(child.execution_id)
            child.gate.close()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for child in self.children.values():
            if child.pending and not child.finished:
                self._failure(child, "cancelled", "The parent Run stopped before this subagent result was collected")
                child.finished = True
        self.on_result = None
        self.on_replan = None
        self.tasks.clear()
        self.observed_tasks.clear()
        self.children.clear()


def run_input_control(context) -> RunInputControl | None:
    from .inputs import INPUT_CONTEXT_KEY

    value = context.get(INPUT_CONTEXT_KEY) if isinstance(context, dict) else None
    return value if isinstance(value, RunInputControl) else None
