"""A new send must not race an interrupted run that is still writing its thread.

Textual cannot kill a thread worker, so after Ctrl+C the synchronous agent
stream keeps running until its next event. When it is inside a long tool call,
that step still completes and checkpoints. A new run on the same thread started
meanwhile forks from the older checkpoint, and whichever run checkpoints last
becomes the thread's state, so the other turn silently drops out of it.

These tests drive the real TUI through Textual's pilot with a client that
streams a real compiled LangGraph graph backed by a checkpointer.
"""

import asyncio
import operator
import threading
from typing import Annotated, TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from deerflow.client import StreamEvent
from deerflow.tui.app import DeerFlowTUI
from deerflow.tui.cli import LaunchPlan
from deerflow.tui.session import Session

STILL_STOPPING = "The interrupted run is still stopping on this thread"


class _State(TypedDict):
    messages: Annotated[list, operator.add]


class _GraphClient:
    """Streams a real checkpointed graph; "old question" blocks in a tool step."""

    def __init__(self):
        self.old_in_tool = threading.Event()
        self.release_old_tool = threading.Event()
        self.calls: list[tuple[str, str | None]] = []
        self.finished: set[str] = set()
        self.active: dict[str | None, int] = {}
        self.max_active_per_thread = 0
        self._lock = threading.Lock()

        def tool_step(state):
            last = state["messages"][-1]
            if last == "old question":
                self.old_in_tool.set()
                if not self.release_old_tool.wait(10):
                    raise TimeoutError("old tool step was not released")
                return {"messages": ["old tool result"]}
            return {"messages": [f"answer to {last}"]}

        graph = StateGraph(_State)
        graph.add_node("tool_step", tool_step)
        graph.add_edge(START, "tool_step")
        graph.add_edge("tool_step", END)
        self.graph = graph.compile(checkpointer=InMemorySaver())

    def list_models(self):
        return {"models": []}

    def list_skills(self, **kwargs):
        return {"skills": []}

    def list_threads(self, **kwargs):
        return {"thread_list": []}

    def messages(self, thread_id: str) -> list:
        return self.graph.get_state({"configurable": {"thread_id": thread_id}}).values.get("messages", [])

    def stream(self, message, *, thread_id=None, **kwargs):
        self.calls.append((message, thread_id))
        with self._lock:
            self.active[thread_id] = self.active.get(thread_id, 0) + 1
            self.max_active_per_thread = max(self.max_active_per_thread, self.active[thread_id])
        try:
            for _ in self.graph.stream({"messages": [message]}, {"configurable": {"thread_id": thread_id}}, stream_mode="values"):
                yield StreamEvent(type="values", data={})
            yield StreamEvent(type="end", data={"usage": {}})
        finally:
            with self._lock:
                self.active[thread_id] -= 1
            self.finished.add(message)


async def _settle(pilot, predicate):
    for _ in range(500):
        await pilot.pause()
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Expected controlled UI event did not arrive")


async def _submit(app, pilot, text: str) -> None:
    app.query_one("#composer").value = text
    await pilot.press("enter")


def _system_texts(app) -> list[str]:
    return [row.text for row in app.state.rows if row.kind == "system"]


async def _interrupt_old_run_in_its_tool_step(app, pilot, client) -> None:
    await _submit(app, pilot, "old question")
    await _settle(pilot, client.old_in_tool.is_set)
    await pilot.press("ctrl+c")


@pytest.mark.asyncio
async def test_send_waits_for_the_interrupted_run_before_reusing_its_thread():
    client = _GraphClient()
    app = DeerFlowTUI(Session(client=client, writer=None), LaunchPlan(mode="tui", thread_id="thread-a"))
    async with app.run_test() as pilot:
        try:
            await pilot.pause()
            await _interrupt_old_run_in_its_tool_step(app, pilot, client)

            await _submit(app, pilot, "new question")
            await pilot.pause()
            assert any(STILL_STOPPING in text for text in _system_texts(app))
            assert [message for message, _ in client.calls] == ["old question"]
            assert not app._streaming
            assert app.query_one("#composer").value == "new question"

            client.release_old_tool.set()
            await _settle(pilot, lambda: "old question" in client.finished and app._run.stopped.is_set())
            await pilot.press("enter")
            await _settle(pilot, lambda: "new question" in client.finished and not app._streaming)
        finally:
            client.release_old_tool.set()

    assert client.max_active_per_thread == 1
    assert client.messages(app._conv_thread_id) == ["old question", "old tool result", "new question", "answer to new question"]


@pytest.mark.asyncio
async def test_a_stopping_run_does_not_block_another_thread():
    client = _GraphClient()
    app = DeerFlowTUI(Session(client=client, writer=None), LaunchPlan(mode="tui", thread_id="thread-a"))
    async with app.run_test() as pilot:
        try:
            await pilot.pause()
            await _interrupt_old_run_in_its_tool_step(app, pilot, client)
            old_thread = app._conv_thread_id

            await _submit(app, pilot, "/new")
            await _submit(app, pilot, "new question")
            await _settle(pilot, lambda: "new question" in client.finished and not app._streaming)
            new_thread = app._conv_thread_id

            assert not any(STILL_STOPPING in text for text in _system_texts(app))
            assert not client.release_old_tool.is_set()
        finally:
            client.release_old_tool.set()
        await _settle(pilot, lambda: "old question" in client.finished)

    assert new_thread != old_thread
    assert client.messages(new_thread) == ["new question", "answer to new question"]


@pytest.mark.asyncio
async def test_an_interrupt_before_the_worker_starts_does_not_block_the_thread(monkeypatch):
    # Textual may cancel a queued thread worker before its function runs; that
    # run never touches the backend and must not hold its thread.
    client = _GraphClient()
    app = DeerFlowTUI(Session(client=client, writer=None), LaunchPlan(mode="tui", thread_id="thread-a"))
    async with app.run_test() as pilot:
        await pilot.pause()
        original_run_worker = app.run_worker
        monkeypatch.setattr(app, "run_worker", lambda *args, **kwargs: None)
        await _submit(app, pilot, "never started")
        await pilot.press("ctrl+c")
        monkeypatch.setattr(app, "run_worker", original_run_worker)

        await _submit(app, pilot, "new question")
        await _settle(pilot, lambda: "new question" in client.finished and not app._streaming)

    assert not any(STILL_STOPPING in text for text in _system_texts(app))
    assert [message for message, _ in client.calls] == ["new question"]


@pytest.mark.asyncio
async def test_a_completed_run_still_saving_its_title_does_not_block_the_next_send():
    # Only interrupted runs are waited for: after a normal completion the agent
    # stream is done and the worker only writes the thread title.
    class _BlockingTitleWriter:
        def __init__(self):
            self.writing = threading.Event()
            self.release = threading.Event()

        def ensure_created(self, *args, **kwargs):
            pass

        def set_title(self, thread_id, title):
            self.writing.set()
            self.release.wait(10)

    class _TitledClient(_GraphClient):
        def stream(self, message, *, thread_id=None, **kwargs):
            yield StreamEvent(type="values", data={"title": f"title for {message}"})
            yield from super().stream(message, thread_id=thread_id, **kwargs)

    client, writer = _TitledClient(), _BlockingTitleWriter()
    app = DeerFlowTUI(Session(client=client, writer=writer), LaunchPlan(mode="tui", thread_id="thread-a"))
    async with app.run_test() as pilot:
        try:
            await pilot.pause()
            await _submit(app, pilot, "first question")
            await _settle(pilot, writer.writing.is_set)
            await _settle(pilot, lambda: not app._streaming)

            await _submit(app, pilot, "second question")
            await _settle(pilot, lambda: "second question" in client.finished)
        finally:
            writer.release.set()

    assert not any(STILL_STOPPING in text for text in _system_texts(app))
