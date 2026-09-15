"""Integration tests for the slash-command palette via the pilot harness."""

import asyncio

import pytest

from deerflow.client import StreamEvent
from deerflow.tui.app import DeerFlowTUI
from deerflow.tui.cli import LaunchPlan


class _FakeClient:
    def list_models(self):
        return {"models": [{"name": "m"}]}

    def list_skills(self, enabled_only=False):
        return {"skills": [{"name": "tdd", "description": "Test first", "enabled": True}]}

    def stream(self, *args, **kwargs):
        yield StreamEvent(type="end", data={})


class _FakeSession:
    def __init__(self):
        self.client = _FakeClient()

    def resolve_thread(self, plan):
        return None


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
async def test_typing_slash_opens_palette_with_matches():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash", "h", "e")
        await _settle(pilot, lambda: app._palette_open)
    assert app._palette_open
    assert "help" in [c.name for c in app._palette_items]


@pytest.mark.asyncio
async def test_palette_index_resets_when_filter_changes():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash", "m")  # memory / mcp / model …
        await _settle(pilot, lambda: app._palette_open and len(app._palette_items) > 1)
        await pilot.press("down", "down")
        await pilot.pause()
        assert app._palette_index > 0
        await pilot.press("e")  # filter narrows ("/me") -> highlight must reset
        await pilot.pause()
    assert app._palette_index == 0


@pytest.mark.asyncio
async def test_palette_enter_runs_builtin_and_closes():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        for ch in ("slash", "h", "e", "l", "p"):
            await pilot.press(ch)
        await _settle(pilot, lambda: app._palette_open and bool(app._palette_items))
        await pilot.press("enter")
        await _settle(pilot, lambda: any(r.kind == "system" for r in app.state.rows))
    assert any(r.kind == "system" for r in app.state.rows)
    assert not app._palette_open
    # /help is a builtin and must not have triggered an agent user turn.
    assert not any(r.kind == "user" for r in app.state.rows)


@pytest.mark.asyncio
async def test_escape_closes_palette():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash", "m")
        await _settle(pilot, lambda: app._palette_open)
        await pilot.press("escape")
        await _settle(pilot, lambda: not app._palette_open)
    assert not app._palette_open


@pytest.mark.asyncio
async def test_skill_command_tab_completes_with_trailing_space():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash", "t", "d", "d")
        await _settle(pilot, lambda: app._palette_open and any(c.name == "tdd" for c in app._palette_items))
        await pilot.press("tab")
        await _settle(pilot, lambda: not app._palette_open)
        value = app.query_one("#composer").value
    assert value == "/tdd "


@pytest.mark.asyncio
async def test_normal_text_does_not_open_palette():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("h", "i")
        await pilot.pause()
    assert not app._palette_open
