"""Per-run delivery through the real Textual worker, pilot and view reducer."""

import asyncio
import threading

import pytest

from deerflow.client import StreamEvent
from deerflow.tui.app import DeerFlowTUI
from deerflow.tui.cli import LaunchPlan
from deerflow.tui.session import Session
from deerflow.tui.view_state import AssistantDelta, RunEnded, RunStarted, ThreadTitle


class _Client:
    def __init__(self):
        self.release_old = threading.Event()
        self.release_new = threading.Event()
        self.new_started = threading.Event()
        self.old_terminal_emitted = threading.Event()
        self.calls = []

    def list_models(self):
        return {"models": []}

    def list_skills(self, **kwargs):
        return {"skills": []}

    def list_threads(self, **kwargs):
        return {"thread_list": [{"thread_id": "thread-a", "title": "A"}, {"thread_id": "thread-b", "title": "B"}]}

    def stream(self, message, *, thread_id=None, **kwargs):
        self.calls.append((message, thread_id))
        old = message == "old question"
        prefix = "old" if old else "new"
        if not old:
            yield StreamEvent(type="values", data={"title": "New title"})
        yield StreamEvent(type="messages-tuple", data={"type": "ai", "content": f"{prefix}-before ", "id": f"{prefix}-answer"})
        if not old:
            self.new_started.set()
        release = self.release_old if old else self.release_new
        if not release.wait(10):
            raise TimeoutError("Controlled stream was not released")
        yield StreamEvent(type="messages-tuple", data={"type": "ai", "content": f"{prefix}-tail", "id": f"{prefix}-answer"})
        if old:
            yield StreamEvent(type="values", data={"title": "Old title"})
            self.old_terminal_emitted.set()
        yield StreamEvent(type="end", data={"usage": {"total_tokens": 111 if old else 222}})


class _Writer:
    def __init__(self):
        self.titles = []

    def ensure_created(self, *args, **kwargs):
        pass

    def set_title(self, thread_id, title):
        self.titles.append((thread_id, title, threading.get_ident()))


async def _settle(pilot, predicate):
    for _ in range(200):
        await pilot.pause()
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Expected controlled UI event did not arrive")


async def _late_delivery(monkeypatch, gate, switch_thread=False, restart=True):
    client, writer = _Client(), _Writer()
    app = DeerFlowTUI(Session(client=client, writer=writer), LaunchPlan(mode="tui", thread_id="thread-a"))
    queued, deliver, old_done, new_done = (threading.Event() for _ in range(4))
    old_worker_id = None
    original_worker, original_callback = app._stream_worker, app.call_from_thread

    def observed_worker(text, *args):
        nonlocal old_worker_id
        if text == "old question":
            old_worker_id = threading.get_ident()
        try:
            return original_worker(text, *args)
        finally:
            (old_done if text == "old question" else new_done).set()

    def gated_callback(callback, *args):
        action = args[-1]
        is_old = threading.get_ident() == old_worker_id
        pause = (gate == "delta" and isinstance(action, AssistantDelta) and action.text == "old-tail") or (gate == "title" and isinstance(action, ThreadTitle)) or (gate == "end" and isinstance(action, RunEnded))
        if is_old and pause:
            queued.set()
            if not deliver.wait(10):
                raise TimeoutError("Controlled UI delivery was not released")
        return original_callback(callback, *args)

    monkeypatch.setattr(app, "_stream_worker", observed_worker)
    monkeypatch.setattr(app, "call_from_thread", gated_callback)
    async with app.run_test() as pilot:
        try:
            await pilot.pause()
            app.query_one("#composer").value = "old question"
            await pilot.press("enter")
            await _settle(pilot, lambda: app._streaming and any(row.kind == "assistant" for row in app.state.rows))
            client.release_old.set()
            await _settle(pilot, queued.is_set)
            if gate == "end":
                # The old source has emitted its terminal event; only UI delivery
                # is pending, so this case needs no overlapping backend runs.
                assert client.old_terminal_emitted.is_set()
            await pilot.press("ctrl+c")
            if restart:
                if switch_thread:
                    app.query_one("#composer").value = "/resume thread-b"
                    await pilot.press("enter")
                else:
                    # The old worker is still running on this thread, so a
                    # send there waits for it (see
                    # test_tui_interrupted_run_drain.py); its late action is
                    # still discarded once delivered.
                    app.query_one("#composer").value = "new question"
                    await pilot.press("enter")
                    await pilot.pause()
                    assert client.calls == [("old question", "thread-a")]
                    assert any("still stopping" in row.text for row in app.state.rows if row.kind == "system")
                    deliver.set()
                    await _settle(pilot, old_done.is_set)
                app.query_one("#composer").value = "new question"
                await pilot.press("enter")
                await _settle(pilot, lambda: client.new_started.is_set() and app._streaming)
            deliver.set()
            await _settle(pilot, old_done.is_set)
            snapshot = {
                "streaming": app._streaming,
                "state_streaming": app.state.streaming,
                "usage": app.state.usage,
                "title": app.state.title,
                "assistant_rows": [(row.id, row.text) for row in app.state.rows if row.kind == "assistant"],
                "written_titles": list(writer.titles),
            }
            if restart:
                assert not client.release_new.is_set()
                client.release_new.set()
                await _settle(pilot, new_done.is_set)
                assert not app._streaming
                assert app.state.usage == {"total_tokens": 222}
                assert app.state.title == "New title"
                assert any(row.kind == "assistant" and row.text == "new-before new-tail" for row in app.state.rows)
            return snapshot, writer.titles
        finally:
            client.release_old.set()
            client.release_new.set()
            deliver.set()
            await _settle(pilot, old_done.is_set)
            if restart and client.new_started.is_set():
                await _settle(pilot, new_done.is_set)


@pytest.mark.asyncio
@pytest.mark.parametrize("gate", ["delta", "title", "end"])
@pytest.mark.parametrize("switch_thread", [False, True])
async def test_interrupted_run_does_not_change_new_run(monkeypatch, gate, switch_thread):
    state, _ = await _late_delivery(monkeypatch, gate, switch_thread)
    assert state["streaming"]
    assert state["state_streaming"]
    assert state["usage"] is None
    assert state["title"] == "New title"
    if gate == "delta":
        assert not any("old-tail" in text for _, text in state["assistant_rows"])


@pytest.mark.asyncio
@pytest.mark.parametrize("switch_thread", [False, True])
async def test_cancelled_worker_cannot_write_its_title_after_new_run(monkeypatch, switch_thread):
    state, titles = await _late_delivery(monkeypatch, "end", switch_thread)
    assert state["written_titles"] == []
    assert [(thread_id, title) for thread_id, title, _ in titles] == [("thread-b" if switch_thread else "thread-a", "New title")]
    assert titles[0][2] != threading.get_ident()


@pytest.mark.asyncio
async def test_interrupt_without_restart_discards_pending_delta(monkeypatch):
    state, titles = await _late_delivery(monkeypatch, "delta", restart=False)
    assert not state["streaming"]
    assert state["assistant_rows"] == [("old-answer", "old-before ")]
    assert titles == []


@pytest.mark.asyncio
async def test_send_reserves_busy_state_before_worker_starts(monkeypatch):
    client = _Client()
    app = DeerFlowTUI(Session(client=client), LaunchPlan(mode="tui", thread_id="thread-a"))
    queued, release, done = (threading.Event() for _ in range(3))
    original_worker = app._stream_worker

    def delayed_worker(*args):
        queued.set()
        try:
            if not release.wait(10):
                raise TimeoutError("Worker start was not released")
            return original_worker(*args)
        finally:
            done.set()

    monkeypatch.setattr(app, "_stream_worker", delayed_worker)
    async with app.run_test() as pilot:
        try:
            app.query_one("#composer").value = "old question"
            await pilot.press("enter")
            await _settle(pilot, queued.is_set)
            assert app._streaming
            app.query_one("#composer").value = "new question"
            await pilot.press("enter")
            assert any(row.kind == "system" and "Still working" in row.text for row in app.state.rows)
            assert app.query_one("#composer").value == "new question"
            await pilot.press("ctrl+c")
            release.set()
            client.release_old.set()
            await _settle(pilot, done.is_set)
            assert client.calls == []
        finally:
            release.set()
            client.release_old.set()
            client.release_new.set()
            await _settle(pilot, done.is_set)


@pytest.mark.asyncio
async def test_worker_start_failure_restores_idle_state_and_allows_retry(monkeypatch):
    client, writer = _Client(), _Writer()
    client.release_new.set()
    app = DeerFlowTUI(Session(client=client, writer=writer), LaunchPlan(mode="tui", thread_id="thread-a"))
    failed_runs = []
    original_start = app.run_worker

    def fail_first_agent_worker(*args, **kwargs):
        if kwargs.get("group") == "agent" and not failed_runs:
            failed_runs.append(app._run)
            raise RuntimeError("private worker startup detail")
        return original_start(*args, **kwargs)

    monkeypatch.setattr(app, "run_worker", fail_first_agent_worker)
    async with app.run_test() as pilot:
        app.query_one("#composer").value = "old question"
        await pilot.press("enter")
        assert not app._streaming
        assert not app.state.streaming
        assert app._run is None
        assert failed_runs[0].cancelled.is_set()
        assert any(row.kind == "system" and row.tone == "error" for row in app.state.rows)
        assert "private worker startup detail" not in str(app.state.rows)
        assert client.calls == []
        assert app.query_one("#composer").value == "old question"

        idle_state = app.state
        for action in [RunStarted(), AssistantDelta(id="failed-answer", text="stale"), ThreadTitle("Failed title"), RunEnded(usage={"total_tokens": 999})]:
            assert not app._on_stream_action(failed_runs[0], action)
            assert app.state == idle_state
            assert not app._streaming
        app._stream_worker("old question", failed_runs[0])
        assert client.calls == []

        app.query_one("#composer").value = "new question"
        await pilot.press("enter")
        await _settle(pilot, lambda: writer.titles and not app._streaming)
        assert client.calls == [("new question", "thread-a")]
        assert app.state.usage == {"total_tokens": 222}
        assert any(row.kind == "assistant" and row.text == "new-before new-tail" for row in app.state.rows)
        assert not any(row.kind == "system" and "Still working" in row.text for row in app.state.rows)


@pytest.mark.asyncio
async def test_launch_message_that_fails_to_start_stays_in_the_composer(monkeypatch):
    client = _Client()
    app = DeerFlowTUI(Session(client=client), LaunchPlan(mode="tui", thread_id="thread-a", message="launch question"))
    original_start = app.run_worker

    def fail_agent_worker(*args, **kwargs):
        if kwargs.get("group") == "agent":
            raise RuntimeError("Cannot start the launch worker")
        return original_start(*args, **kwargs)

    monkeypatch.setattr(app, "run_worker", fail_agent_worker)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not app._streaming
        assert any(row.kind == "system" and row.tone == "error" for row in app.state.rows)
        composer = app.query_one("#composer")
        assert composer.value == "launch question"
        assert composer.cursor_position == len("launch question")
        assert client.calls == []


@pytest.mark.asyncio
async def test_completed_run_rejects_a_duplicate_terminal_callback(monkeypatch):
    client, writer = _Client(), _Writer()
    client.release_old.set()
    app = DeerFlowTUI(Session(client=client, writer=writer), LaunchPlan(mode="tui", thread_id="thread-a"))
    delivered = []
    original = app.call_from_thread

    def remember(callback, *args):
        result = original(callback, *args)
        if isinstance(args[-1], RunEnded):
            delivered.append((callback, args))
        return result

    monkeypatch.setattr(app, "call_from_thread", remember)
    async with app.run_test() as pilot:
        app.query_one("#composer").value = "old question"
        await pilot.press("enter")
        await _settle(pilot, lambda: delivered and writer.titles)
        assert app.state.usage == {"total_tokens": 111}
        callback, args = delivered[0]
        completed = app.state
        for action in [RunStarted(), AssistantDelta(id="old-answer", text="stale"), ThreadTitle("Stale title"), RunEnded(usage={"total_tokens": 999})]:
            callback(*args[:-1], action)
            assert app.state == completed
            assert not app._streaming
        assert [(thread_id, title) for thread_id, title, _ in writer.titles] == [("thread-a", "Old title")]


@pytest.mark.asyncio
@pytest.mark.parametrize("next_action", ["switch", "send", "failed-send"])
async def test_completed_run_keeps_title_write_after_ui_moves_on(monkeypatch, next_action):
    client, writer = _Client(), _Writer()
    client.release_old.set()
    app = DeerFlowTUI(Session(client=client, writer=writer), LaunchPlan(mode="tui", thread_id="thread-a"))
    terminal_delivered, release, old_done, new_done = (threading.Event() for _ in range(4))
    original_worker, original_callback = app._stream_worker, app.call_from_thread
    old_worker_id = None

    def observed_worker(text, *args):
        nonlocal old_worker_id
        if text == "old question":
            old_worker_id = threading.get_ident()
        try:
            return original_worker(text, *args)
        finally:
            (old_done if text == "old question" else new_done).set()

    def pause_after_terminal(callback, *args):
        result = original_callback(callback, *args)
        if isinstance(args[-1], RunEnded) and threading.get_ident() == old_worker_id:
            terminal_delivered.set()
            if not release.wait(10):
                raise TimeoutError("Completed worker was not released")
        return result

    monkeypatch.setattr(app, "_stream_worker", observed_worker)
    monkeypatch.setattr(app, "call_from_thread", pause_after_terminal)
    async with app.run_test() as pilot:
        try:
            app.query_one("#composer").value = "old question"
            await pilot.press("enter")
            await _settle(pilot, terminal_delivered.is_set)
            assert not app._streaming
            if next_action == "failed-send":

                def fail_to_start(*args, **kwargs):
                    raise RuntimeError("Cannot start the next worker")

                monkeypatch.setattr(app, "run_worker", fail_to_start)
            app.query_one("#composer").value = "/resume thread-b" if next_action == "switch" else "new question"
            await pilot.press("enter")
            if next_action == "failed-send":
                assert not app._streaming
                assert not app.state.streaming
                assert app._run is None
                assert app.state.usage == {"total_tokens": 111}
            if next_action == "send":
                await _settle(pilot, client.new_started.is_set)
            release.set()
            await _settle(pilot, old_done.is_set)
            assert [(thread_id, title) for thread_id, title, _ in writer.titles] == [("thread-a", "Old title")]
            assert app._streaming == (next_action == "send")
        finally:
            release.set()
            client.release_new.set()
            await _settle(pilot, old_done.is_set)
            if client.new_started.is_set():
                await _settle(pilot, new_done.is_set)
