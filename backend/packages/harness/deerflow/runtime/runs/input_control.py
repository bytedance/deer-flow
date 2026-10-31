"""Run-owned input delivery and native task supervision; no model polling."""

from __future__ import annotations

import asyncio
import json
import threading
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from .inputs import RunInputs
from .schemas import GOAL_RUN_HARD_STOP_REASONS


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


class RunInputControl:
    def __init__(self, inputs: RunInputs, *, agent_runs, thread_id: str, checkpointer, on_result=None, on_replan=None):
        self.inputs, self.agent_runs, self.thread_id, self.checkpointer = inputs, agent_runs, thread_id, checkpointer
        self.delivered: set[str] = set()
        self.acknowledged: set[str] = set()
        self.calls: dict[str, dict] = {}
        self.delegations: list[dict] = []
        self.current_input: str | None = None
        self.steering_active = False
        self.tasks: set[asyncio.Task] = set()
        self.observed_tasks: set[asyncio.Task] = set()
        self.children: dict[str, tuple[ChildInputGate, str | None]] = {}
        self.interrupted_children: set[str] = set()
        self.receipts: list[HumanMessage] = []
        self.pending_calls: set[str] = set()
        self.finished_calls: set[str] = set()
        self.on_result = on_result
        self.on_replan = on_replan
        self.abandoned = False

    def child(self, call_id):
        if call_id in self.children and not self.children[call_id][0].closed:
            return self.children[call_id][0]
        gate = ChildInputGate(can_queue=not any(not old.resume.is_set() and not old.closed for old, _ in self.children.values()))
        self.children[call_id] = (gate, None)
        return gate

    def bind_execution(self, call_id, execution_id):
        gate, _ = self.children[call_id]
        self.children[call_id] = (gate, execution_id)

    async def pending(self):
        state = await self.inputs.read()
        return [x for x in state["items"] if x["mode"] == "steer" and x["status"] in ("pending", "applying") and x["id"] not in self.delivered]

    async def deliver(self, state):
        entries = await self.pending()
        if entries:
            entries = await self.inputs.claim_steer([x["id"] for x in entries])
        messages = self.receipts[:]
        self.receipts.clear()
        if entries:
            self.abandoned = False
            self.steering_active = True
            self.interrupted_children = set(self.children)
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
        self.calls[request.tool_call["id"]] = dict(request.tool_call)
        self.finished_calls.discard(request.tool_call["id"])
        # Create the gate before scheduling: an immediately available input
        # can arrive before the tool handler reaches the native executor.
        gate = self.child(request.tool_call["id"])
        native = asyncio.create_task(handler(request))
        native.add_done_callback(lambda _: gate.close())
        self.tasks.add(native)
        try:
            while not native.done():
                if await self.pending():
                    for gate, _ in self.children.values():
                        gate.resume.clear()
                    call_id = request.tool_call["id"]
                    self.pending_calls.add(call_id)
                    self.observed_tasks.add(native)
                    watcher = asyncio.create_task(self._observe(native, call_id))
                    self.tasks.add(watcher)
                    return ToolMessage(
                        id=gate.result_id,
                        content="The subagent result is pending and will arrive in this Run. The user has sent an updated requirement.",
                        tool_call_id=call_id,
                        name="task",
                        additional_kwargs={"subagent_pending": True, "run_id": self.inputs.run_id},
                    )
                await asyncio.wait([native], timeout=0.5)
            return await native
        except BaseException:
            native.cancel()
            await asyncio.gather(native, return_exceptions=True)
            raise

    async def _observe(self, native, call_id):
        try:
            result = await native
            message = result.update["messages"][0] if hasattr(result, "update") else result
        except asyncio.CancelledError:
            raise
        except Exception:
            message = self._failure(call_id, "failed", "The subagent result could not be collected")
        from deerflow.agents.middlewares.delegation_ledger import extract_delegations

        self.finished_calls.add(call_id)
        self.delegations.extend({**entry, "run_id": self.inputs.run_id} for entry in extract_delegations([AIMessage(content="", tool_calls=[self.calls[call_id]]), message]))
        self.receipts.append(
            HumanMessage(
                content=json.dumps({"source": "subagent", "task_call_id": call_id, "result": message.content}, ensure_ascii=False),
                name="subagent-result",
                id="run-input-result-" + self.inputs.run_id + "-" + call_id,
                additional_kwargs={"hide_from_ui": True, "untrusted_input": True, "origin_task_id": call_id, "run_id": self.inputs.run_id},
            )
        )

    def _failure(self, call_id, status, text):
        from deerflow.subagents.status_contract import make_subagent_additional_kwargs

        child = self.children.get(call_id)
        message = ToolMessage(id=child[0].result_id if child else None, content=text, tool_call_id=call_id, name="task", additional_kwargs=make_subagent_additional_kwargs(status, error=text))
        if self.on_result is not None:
            self.on_result(message)
        return message

    def resume_children(self, instructions=""):
        accepted = []
        for call_id, (gate, _) in self.children.items():
            if call_id in self.interrupted_children:
                if gate.release(instructions):
                    accepted.append(call_id)
        return accepted

    async def stop_children(self, *, all_children=False):
        from deerflow.subagents.executor import get_background_task_result, request_cancel_background_task

        results = []
        for call_id, (gate, execution_id) in list(self.children.items()):
            if not all_children and call_id not in self.interrupted_children:
                continue
            if execution_id:
                result = get_background_task_result(execution_id)
                request_cancel_background_task(execution_id)
                if result is not None:
                    results.append(result)
            gate.release()
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

        for gate, execution_id in self.children.values():
            if execution_id:
                request_cancel_background_task(execution_id)
            gate.release()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for call_id in self.pending_calls - self.finished_calls:
            self._failure(call_id, "cancelled", "The parent Run stopped before this subagent result was collected")
        self.on_result = None
        self.on_replan = None
        self.tasks.clear()
        self.observed_tasks.clear()
        self.children.clear()


def run_input_control(context) -> RunInputControl | None:
    from .inputs import INPUT_CONTEXT_KEY

    value = context.get(INPUT_CONTEXT_KEY) if isinstance(context, dict) else None
    return value if isinstance(value, RunInputControl) else None
