"""Tests for opt-in terminal-background rendering in the TUI."""

import pytest

from deerflow.tui.app import DeerFlowTUI, SelectScreen
from deerflow.tui.cli import LaunchPlan
from deerflow.tui.theme import THEME


class _FakeClient:
    def list_models(self):
        return {"models": []}

    def list_skills(self, enabled_only=False):
        return {"skills": []}


class _FakeSession:
    client = _FakeClient()

    def resolve_thread(self, plan):
        return None


@pytest.mark.asyncio
async def test_transparent_tui_uses_terminal_default_for_background_surfaces():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui", transparent=True))
    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.ansi_color is True
        assert app.screen.styles.background.hex == "ansi_default"
        for selector in ("#header", "#scroll", "#status", "#palette", "#composer"):
            assert app.screen.query_one(selector).styles.background.hex == "ansi_default"

        app.push_screen(SelectScreen("Pick one", [("one", "One")]))
        await pilot.pause()
        assert app.screen.styles.background.hex == "ansi_default"
        assert app.screen.query_one("#dialog").styles.background.hex == "ansi_default"
        assert app.screen.query_one("OptionList").styles.background.hex == "ansi_default"


@pytest.mark.asyncio
async def test_default_tui_keeps_solid_theme_backgrounds():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.styles.background.hex.lower() == THEME.bg
        assert app.screen.query_one("#header").styles.background.hex.lower() == THEME.panel
