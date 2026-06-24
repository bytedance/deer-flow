"""Integration tests for modal overlays: /model picker and /threads switcher."""

import asyncio

import pytest

from deerflow.client import StreamEvent
from deerflow.tui.app import DeerFlowTUI, SelectScreen
from deerflow.tui.cli import LaunchPlan


class _FakeClient:
    def list_models(self):
        return {"models": [{"name": "fast", "display_name": "Fast"}, {"name": "smart", "display_name": "Smart"}]}

    def list_skills(self, enabled_only=False):
        return {"skills": []}

    def list_threads(self, limit=10):
        return {
            "thread_list": [
                {"thread_id": "thread-aaaaaaaa", "title": "Refactor bridge"},
                {"thread_id": "thread-bbbbbbbb", "title": "Write docs"},
            ]
        }

    def stream(self, *args, **kwargs):
        yield StreamEvent(type="end", data={})


class _FakeSession:
    def __init__(self):
        self.client = _FakeClient()

    def resolve_thread(self, plan):
        return None

    def recent_threads(self, limit=20):
        return self.client.list_threads(limit=limit)["thread_list"]


async def _settle(pilot, predicate, timeout=2.0):
    elapsed = 0.0
    while elapsed < timeout:
        await pilot.pause()
        if predicate():
            return True
        await asyncio.sleep(0.02)
        elapsed += 0.02
    return predicate()


@pytest.mark.asyncio
async def test_model_command_opens_picker_and_sets_override():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        for ch in ("slash", "m", "o", "d", "e", "l"):
            await pilot.press(ch)
        await _settle(pilot, lambda: app._palette_open and any(c.name == "model" for c in app._palette_items))
        await pilot.press("enter")  # run /model -> opens picker
        await _settle(pilot, lambda: isinstance(app.screen, SelectScreen))
        await pilot.press("enter")  # choose first model (Fast)
        await _settle(pilot, lambda: app._model_override is not None)
    assert app._model_override == "fast"
    assert any(r.kind == "system" and "Fast" in r.text or "fast" in r.text for r in app.state.rows)


@pytest.mark.asyncio
async def test_threads_command_opens_switcher_and_resumes():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        for ch in ("slash", "t", "h", "r", "e", "a", "d", "s"):
            await pilot.press(ch)
        await _settle(pilot, lambda: app._palette_open and any(c.name == "threads" for c in app._palette_items))
        await pilot.press("enter")  # run /threads -> opens switcher
        await _settle(pilot, lambda: isinstance(app.screen, SelectScreen))
        await pilot.press("enter")  # choose first thread
        await _settle(pilot, lambda: app._conv_thread_id == "thread-aaaaaaaa")
    assert app._conv_thread_id == "thread-aaaaaaaa"


@pytest.mark.asyncio
async def test_picker_escape_cancels_without_change():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        for ch in ("slash", "m", "o", "d", "e", "l"):
            await pilot.press(ch)
        await _settle(pilot, lambda: app._palette_open)
        await pilot.press("enter")
        await _settle(pilot, lambda: isinstance(app.screen, SelectScreen))
        await pilot.press("escape")
        await _settle(pilot, lambda: not isinstance(app.screen, SelectScreen))
    assert app._model_override is None
