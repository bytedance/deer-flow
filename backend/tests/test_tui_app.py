"""Integration tests for the Textual app via the pilot harness.

Uses a fake in-process session so no real model is invoked. Exercises the full
loop: keypress -> submit -> worker thread -> stream_actions -> reducer -> state.
"""

import asyncio

import pytest

from deerflow.client import StreamEvent
from deerflow.tui.app import DeerFlowTUI
from deerflow.tui.cli import LaunchPlan


class _FakeClient:
    def list_models(self):
        return {"models": [{"name": "fake-model", "display_name": "Fake Model"}]}

    def list_skills(self, enabled_only=False):
        return {"skills": [{"name": "tdd", "enabled": True}]}

    def stream(self, message, *, thread_id=None, **kwargs):
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
    # /help must not produce a user turn or start streaming.
    assert not any(r.kind == "user" for r in app.state.rows)


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
