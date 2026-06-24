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
