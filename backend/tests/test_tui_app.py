"""Integration tests for the Textual app via the pilot harness.

Uses a fake in-process session so no real model is invoked. Exercises the full
loop: keypress -> submit -> worker thread -> stream_actions -> reducer -> state.
"""

import asyncio
import threading

import pytest

from deerflow.client import StreamEvent
from deerflow.tui.app import DeerFlowTUI
from deerflow.tui.cli import LaunchPlan
from deerflow.tui.view_state import SystemMessage


class _FakeClient:
    def __init__(self):
        self.stream_calls: list[tuple] = []

    def list_models(self):
        return {"models": [{"name": "fake-model", "display_name": "Fake Model"}]}

    def list_skills(self, enabled_only=False):
        return {"skills": [{"name": "tdd", "enabled": True}]}

    def stream(self, message, *, thread_id=None, **kwargs):
        self.stream_calls.append((message, thread_id, kwargs))
        yield StreamEvent(type="messages-tuple", data={"type": "ai", "content": "Hello ", "id": "m1"})
        yield StreamEvent(type="messages-tuple", data={"type": "ai", "content": "world", "id": "m1"})
        yield StreamEvent(type="end", data={"usage": {"total_tokens": 3}})


class _FakeSession:
    def __init__(self):
        self.client = _FakeClient()

    def resolve_thread(self, plan):
        return None


async def _wait_until(predicate, pilot, *, timeout=3.0):
    deadline = 0.0
    while deadline < timeout:
        await pilot.pause()
        if predicate():
            return True
        await asyncio.sleep(0.02)
        deadline += 0.02
    return predicate()


@pytest.mark.asyncio
async def test_app_runs_a_turn_and_renders_streamed_assistant():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("h", "i")
        await pilot.press("enter")
        await _wait_until(
            lambda: not app._streaming and any(r.kind == "assistant" for r in app.state.rows),
            pilot,
        )

    kinds = [r.kind for r in app.state.rows]
    assert "user" in kinds
    assert "assistant" in kinds
    assistant = [r for r in app.state.rows if r.kind == "assistant"][-1]
    assert assistant.text == "Hello world"
    assert app.state.usage == {"total_tokens": 3}


@pytest.mark.asyncio
async def test_app_assigns_thread_id_on_first_send():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._conv_thread_id is None
        await pilot.press("y", "o")
        await pilot.press("enter")
        await _wait_until(lambda: app._conv_thread_id is not None, pilot)
    assert app._conv_thread_id is not None


@pytest.mark.asyncio
async def test_help_command_renders_system_row_without_calling_agent():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        for ch in "/help":
            await pilot.press(ch)
        await pilot.press("enter")
        await _wait_until(lambda: any(r.kind == "system" for r in app.state.rows), pilot)

    assert any(r.kind == "system" for r in app.state.rows)
    assert any(r.kind == "system" and "/clear" in r.text for r in app.state.rows)
    # Commands previously missing from the hardcoded help string must now appear,
    # since the help text is derived from the command registry.
    help_rows = [r for r in app.state.rows if r.kind == "system"]
    for command in ("/help", "/resume", "/switch", "/uploads", "/artifacts", "/details"):
        assert any(command in r.text for r in help_rows), command
    # /help must not produce a user turn or start streaming.
    assert not any(r.kind == "user" for r in app.state.rows)


@pytest.mark.asyncio
async def test_help_text_matches_command_registry():
    from deerflow.tui.command_registry import format_command_help

    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        for ch in "/help":
            await pilot.press(ch)
        await pilot.press("enter")
        await _wait_until(lambda: any(r.kind == "system" for r in app.state.rows), pilot)

    expected = format_command_help()
    assert any(r.kind == "system" and expected in r.text for r in app.state.rows)


@pytest.mark.asyncio
async def test_clear_command_clears_display_without_resetting_thread_or_calling_agent():
    session = _FakeSession()
    app = DeerFlowTUI(session, LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        app._conv_thread_id = "thread-123"
        app._dispatch(SystemMessage("visible row"))
        await pilot.pause()

        app._handle_submit("/clear")
        await pilot.pause()

    assert app.state.rows == ()
    assert app._conv_thread_id == "thread-123"
    assert session.client.stream_calls == []


@pytest.mark.asyncio
async def test_up_arrow_recalls_previous_input_from_history():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        for ch in "remember me":
            await pilot.press("space" if ch == " " else ch)
        await pilot.press("enter")
        await _wait_until(lambda: any(r.kind == "user" for r in app.state.rows), pilot)
        # Composer is empty after submit; Up should recall the last entry.
        await pilot.press("up")
        await pilot.pause()
        assert app.query_one("#composer").value == "remember me"


@pytest.mark.asyncio
async def test_escape_interrupts_an_active_run():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        app._streaming = True
        app._refresh_status()
        await pilot.press("escape")
        await pilot.pause()
    assert app._streaming is False
    assert any(r.kind == "system" and "Interrupt" in r.text for r in app.state.rows)


# --------------------------------------------------------------------------- #
# /quit vs. Ctrl+C during an active stream
# --------------------------------------------------------------------------- #


class _BlockedClient(_FakeClient):
    """A client whose stream() blocks mid-run until the test releases it.

    Unlike ``_FakeClient``, which finishes a turn synchronously, this lets a
    test catch the app while a real worker thread is genuinely stuck inside
    the streaming generator — the same shape as a live agent turn — instead
    of only flipping the ``_streaming`` flag by hand.
    """

    def __init__(self):
        self.release = threading.Event()

    def stream(self, message, *, thread_id=None, **kwargs):
        self.release.wait(timeout=5)
        yield StreamEvent(type="messages-tuple", data={"type": "ai", "content": "done", "id": "m1"})
        yield StreamEvent(type="end", data={"usage": {"total_tokens": 1}})


class _BlockedSession(_FakeSession):
    def __init__(self):
        self.client = _BlockedClient()


@pytest.mark.asyncio
async def test_clear_command_is_blocked_during_active_stream():
    session = _BlockedSession()
    app = DeerFlowTUI(session, LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("h", "i")
        await pilot.press("enter")
        await _wait_until(lambda: app._streaming, pilot)

        app._handle_submit("/clear")
        await pilot.pause()

        assert app._streaming is True
        assert any(r.kind == "user" and r.text == "hi" for r in app.state.rows)
        assert any(r.kind == "system" and "Still working" in r.text for r in app.state.rows)

        session.client.release.set()
        await _wait_until(lambda: not app._streaming, pilot)


@pytest.mark.asyncio
async def test_new_command_is_blocked_during_active_stream():
    session = _BlockedSession()
    app = DeerFlowTUI(session, LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("h", "i")
        await pilot.press("enter")
        await _wait_until(lambda: app._streaming and app._conv_thread_id is not None, pilot)
        active_thread_id = app._conv_thread_id

        app._handle_submit("/new")
        await pilot.pause()

        assert app._streaming is True
        assert app._conv_thread_id == active_thread_id
        assert any(r.kind == "user" and r.text == "hi" for r in app.state.rows)
        assert any(r.kind == "system" and "Still working" in r.text for r in app.state.rows)
        assert not any(r.kind == "system" and "Started a new thread" in r.text for r in app.state.rows)

        session.client.release.set()
        await _wait_until(lambda: not app._streaming, pilot)


@pytest.mark.asyncio
async def test_quit_interrupts_an_active_stream_before_exiting():
    """/quit during a run must interrupt first, mirroring Ctrl+C.

    Regression test: ``_handle_builtin``'s "quit" branch used to call
    ``self.exit()`` unconditionally, unlike ``action_interrupt`` (Ctrl+C),
    which checks ``self._streaming`` and interrupts before any teardown.
    Left unfixed, the worker thread survives the app's exit; its next
    ``call_from_thread`` call then fails silently and the in-flight turn is
    abandoned without a trace.
    """
    session = _BlockedSession()
    app = DeerFlowTUI(session, LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("h", "i")
        await pilot.press("enter")
        await _wait_until(lambda: app._streaming, pilot)

        for ch in "/quit":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()

        # The run must be interrupted (state cleaned up, message surfaced)
        # before the app is allowed to exit — /quit still quits, but safely.
        assert app._streaming is False
        assert any(r.kind == "system" and "Interrupt" in r.text for r in app.state.rows)
        assert app._exit is True

    # Unblock the worker thread so it doesn't leak past the test.
    session.client.release.set()


@pytest.mark.asyncio
async def test_ctrl_c_interrupts_an_active_stream_without_exiting():
    """Contrast/control: Ctrl+C on a real blocked worker interrupts but stays open."""
    session = _BlockedSession()
    app = DeerFlowTUI(session, LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("h", "i")
        await pilot.press("enter")
        await _wait_until(lambda: app._streaming, pilot)

        await pilot.press("ctrl+c")
        await pilot.pause()

        assert app._streaming is False
        assert any(r.kind == "system" and "Interrupt" in r.text for r in app.state.rows)
        assert app._exit is False

    session.client.release.set()


@pytest.mark.asyncio
async def test_tab_keeps_focus_on_composer_when_palette_closed():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        composer = app.query_one("#composer")
        assert app.focused is composer
        await pilot.press("tab")
        await pilot.pause()
        # Tab must not move focus off the composer to the scroll region.
        assert app.focused is composer


@pytest.mark.asyncio
async def test_unknown_command_shows_error_system_row():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        for ch in "/nope":
            await pilot.press(ch)
        await pilot.press("enter")
        await _wait_until(
            lambda: any(r.kind == "system" and getattr(r, "tone", "") == "error" for r in app.state.rows),
            pilot,
        )
    assert any(r.kind == "system" and r.tone == "error" for r in app.state.rows)


# --------------------------------------------------------------------------- #
# /goal handler
# --------------------------------------------------------------------------- #


class _GoalClient(_FakeClient):
    """Records goal API calls and keeps an in-memory active goal."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.goal: dict | None = None

    def get_goal(self, thread_id):
        self.calls.append(("get", thread_id))
        return {"goal": self.goal}

    def set_goal(self, thread_id, objective):
        self.calls.append(("set", thread_id, objective))
        self.goal = {"objective": objective, "status": "active"}
        return {"goal": self.goal}

    def clear_goal(self, thread_id):
        self.calls.append(("clear", thread_id))
        self.goal = None
        return {"goal": None}


class _GoalSession(_FakeSession):
    def __init__(self):
        self.client = _GoalClient()


def _system_rows(app):
    return [r for r in app.state.rows if r.kind == "system"]


@pytest.mark.asyncio
async def test_goal_set_mints_thread_and_reports_objective():
    session = _GoalSession()
    app = DeerFlowTUI(session, LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._conv_thread_id is None
        app._handle_goal("finish the work")
        await pilot.pause()
    assert app._conv_thread_id is not None
    assert ("set", app._conv_thread_id, "finish the work") in session.client.calls
    assert any("Goal set: finish the work" in r.text for r in _system_rows(app))


@pytest.mark.asyncio
async def test_goal_status_without_thread_reports_no_active_goal():
    session = _GoalSession()
    app = DeerFlowTUI(session, LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        app._handle_goal("")
        await pilot.pause()
    # No thread yet -> no gateway round-trip.
    assert session.client.calls == []
    assert any(r.text == "No active goal." for r in _system_rows(app))


@pytest.mark.asyncio
async def test_goal_status_reports_active_objective():
    session = _GoalSession()
    session.client.goal = {"objective": "ship it", "status": "active"}
    app = DeerFlowTUI(session, LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        app._conv_thread_id = "t-1"
        app._handle_goal("")
        await pilot.pause()
    assert ("get", "t-1") in session.client.calls
    assert any("Goal: ship it" in r.text for r in _system_rows(app))


@pytest.mark.asyncio
async def test_goal_clear_calls_gateway_and_confirms():
    session = _GoalSession()
    session.client.goal = {"objective": "ship it", "status": "active"}
    app = DeerFlowTUI(session, LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        app._conv_thread_id = "t-1"
        app._handle_goal("clear")
        await pilot.pause()
    assert ("clear", "t-1") in session.client.calls
    assert any(r.text == "Goal cleared." for r in _system_rows(app))


@pytest.mark.asyncio
async def test_goal_set_failure_shows_error_tone():
    class _Boom(_GoalClient):
        def set_goal(self, thread_id, objective):
            raise RuntimeError("gateway down")

    session = _GoalSession()
    session.client = _Boom()
    app = DeerFlowTUI(session, LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        app._conv_thread_id = "t-1"
        app._handle_goal("do it")
        await pilot.pause()
    errors = [r for r in _system_rows(app) if r.tone == "error"]
    assert any("Could not set goal." in r.text for r in errors)
