"""Conversation-switch boundaries through real Textual events and Session resolution."""

import asyncio
import threading

import pytest

from deerflow.client import StreamEvent
from deerflow.tui.app import DeerFlowTUI, SelectScreen
from deerflow.tui.cli import LaunchPlan
from deerflow.tui.session import Session
from deerflow.tui.view_state import AssistantDelta, RunEnded, RunStarted


class _ControlledClient:
    def __init__(self):
        self.release = threading.Event()
        self.calls = []

    def list_models(self):
        return {"models": []}

    def list_skills(self, **kwargs):
        return {"skills": []}

    def list_threads(self, **kwargs):
        return {"thread_list": [{"thread_id": "thread-b", "title": "Other thread"}, {"thread_id": "thread-a", "title": "Original thread"}]}

    def stream(self, message, *, thread_id=None, **kwargs):
        self.calls.append((message, thread_id))
        yield StreamEvent(type="messages-tuple", data={"type": "ai", "content": "before ", "id": "answer"})
        if not self.release.wait(10):
            raise TimeoutError("Test worker was not released")
        yield StreamEvent(type="messages-tuple", data={"type": "ai", "content": "after", "id": "answer"})
        yield StreamEvent(type="end", data={})


async def _settle(pilot, predicate):
    for _ in range(100):
        await pilot.pause()
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Expected TUI event did not arrive")


@pytest.mark.asyncio
async def test_interrupt_then_resume_discards_old_thread_delivery(monkeypatch):
    client = _ControlledClient()
    app = DeerFlowTUI(Session(client=client), LaunchPlan(mode="tui", thread_id="thread-a"))
    ready = threading.Event()
    deliver = threading.Event()
    delivered = threading.Event()
    original = app.call_from_thread

    def paused_delivery(callback, *args):
        action = args[-1]
        if isinstance(action, AssistantDelta) and action.text == "after":
            ready.set()
            if not deliver.wait(10):
                raise TimeoutError("UI delivery was not released")
            result = original(callback, *args)
            delivered.set()
            return result
        return original(callback, *args)

    # Pause a real stream action after the worker's cancellation check but
    # before Textual executes its callback on the UI thread.
    monkeypatch.setattr(app, "call_from_thread", paused_delivery)
    async with app.run_test() as pilot:
        try:
            await pilot.pause()
            app.query_one("#composer").value = "original question"
            await pilot.press("enter")
            await _settle(pilot, lambda: app._streaming and any(row.kind == "assistant" for row in app.state.rows))
            client.release.set()
            await _settle(pilot, ready.is_set)

            app.action_interrupt()
            app.query_one("#composer").value = "/resume thread-b"
            await pilot.press("enter")
            await _settle(pilot, lambda: app._conv_thread_id == "thread-b")
            deliver.set()
            await _settle(pilot, delivered.is_set)
            assert not any(row.kind == "assistant" for row in app.state.rows)
        finally:
            client.release.set()
            deliver.set()
            await pilot.pause()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/resume thread-b", "/resume", "/threads", "/switch"])
async def test_active_run_rejects_thread_switch_commands(command):
    client = _ControlledClient()
    app = DeerFlowTUI(Session(client=client), LaunchPlan(mode="tui", thread_id="thread-a"))
    async with app.run_test() as pilot:
        try:
            await pilot.pause()
            app.query_one("#composer").value = "original question"
            await pilot.press("enter")
            await _settle(pilot, lambda: app._streaming and any(row.kind == "assistant" for row in app.state.rows))

            app.query_one("#composer").value = command
            await pilot.press("enter")
            await pilot.pause()
            assert not isinstance(app.screen, SelectScreen)
            assert app._conv_thread_id == "thread-a"
            assert any(row.kind == "system" and "Still working" in row.text for row in app.state.rows)
            assert any(row.kind == "user" and row.text == "original question" for row in app.state.rows)

            client.release.set()
            await _settle(pilot, lambda: not app._streaming)
            assert client.calls == [("original question", "thread-a")]
            assert [row.text for row in app.state.rows if row.kind == "assistant"] == ["before after"]

            # The same command must remain available once the run has ended.
            app.query_one("#composer").value = command
            await pilot.press("enter")
            await pilot.pause()
            if isinstance(app.screen, SelectScreen):
                await pilot.press("enter")
            await _settle(pilot, lambda: app._conv_thread_id == "thread-b")
        finally:
            client.release.set()
            await _settle(pilot, lambda: not app._streaming)


@pytest.mark.asyncio
async def test_picker_callback_rechecks_run_state_before_switching():
    client = _ControlledClient()
    app = DeerFlowTUI(Session(client=client), LaunchPlan(mode="tui", thread_id="thread-a"))
    async with app.run_test() as pilot:
        await pilot.pause()
        app._open_thread_switcher()
        await pilot.pause()
        assert isinstance(app.screen, SelectScreen)
        # A pending picker may have been opened before RunStarted reaches the UI.
        app._on_action(RunStarted())
        await pilot.press("enter")
        await pilot.pause()
        assert app._conv_thread_id == "thread-a"
        assert any(row.kind == "system" and "Still working" in row.text for row in app.state.rows)
        app._on_action(RunEnded())


@pytest.mark.asyncio
@pytest.mark.parametrize("ref", ["nonexistent title with spaces", "../outside", "x" * 65])
async def test_invalid_resume_shows_error_and_keeps_app_usable(ref):
    client = _ControlledClient()
    client.release.set()
    app = DeerFlowTUI(Session(client=client), LaunchPlan(mode="tui", thread_id="thread-a"))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#composer").value = f"/resume {ref}"
        await pilot.press("enter")
        await pilot.pause()
        assert app._conv_thread_id == "thread-a"
        assert any(row.kind == "system" and row.tone == "error" and "not a valid thread id" in row.text for row in app.state.rows)

        app.query_one("#composer").value = "still usable"
        await pilot.press("enter")
        await _settle(pilot, lambda: client.calls and not app._streaming)
        assert client.calls == [("still usable", "thread-a")]
        assert any(row.kind == "assistant" and row.text == "before after" for row in app.state.rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("ref", ["Other thread", "thread-b", "new-valid-id"])
async def test_idle_resume_preserves_title_id_and_new_namespace_resolution(ref):
    app = DeerFlowTUI(Session(client=_ControlledClient()), LaunchPlan(mode="tui", thread_id="thread-a"))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#composer").value = f"/resume {ref}"
        await pilot.press("enter")
        expected = "new-valid-id" if ref == "new-valid-id" else "thread-b"
        await _settle(pilot, lambda: app._conv_thread_id == expected)
        assert any(row.kind == "system" and "Resumed thread" in row.text for row in app.state.rows)
