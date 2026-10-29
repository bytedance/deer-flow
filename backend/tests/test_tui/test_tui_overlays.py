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

    def resolve_ref(self, ref):
        threads = self.client.list_threads(limit=100)["thread_list"]
        if any(t["thread_id"] == ref for t in threads):
            return ref
        for t in threads:
            if (t.get("title") or "") == ref:
                return t["thread_id"]
        return ref


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
async def test_resume_command_with_title_switches_thread():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        # Resolve a thread by its title (not id) — the by-title resume path.
        app.query_one("#composer").value = "/resume Refactor bridge"
        await pilot.press("enter")
        await _settle(pilot, lambda: app._conv_thread_id == "thread-aaaaaaaa")
    assert app._conv_thread_id == "thread-aaaaaaaa"
    assert any(r.kind == "system" and "Resumed" in r.text for r in app.state.rows)


def test_resume_without_arg_routes_to_thread_switcher():
    # /resume with no id/title falls back to the thread switcher.
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    calls = []
    app._open_thread_switcher = lambda: calls.append("switcher")
    app._handle_builtin("resume", "")
    assert calls == ["switcher"]


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


# Square brackets are Textual content markup when a widget receives a plain
# str. Thread titles come from the user's first message and model names from
# config, so the pickers must show them as written.
_BRACKETED_THREADS = [
    {"thread_id": "thread-cccccccc", "title": "Fix [/bold] in parser"},
    {"thread_id": "thread-dddddddd", "title": "Index [a] then [b]"},
]
_BRACKETED_MODELS = [{"name": "beta", "display_name": "Qwen [beta]"}, {"name": "italic", "display_name": "x [/i] y"}]


class _BracketedClient(_FakeClient):
    def list_models(self):
        return {"models": _BRACKETED_MODELS}

    def list_threads(self, limit=10):
        return {"thread_list": _BRACKETED_THREADS}


class _BracketedSession(_FakeSession):
    def __init__(self):
        self.client = _BracketedClient()


def _picker_lines(app) -> list[str]:
    options = app.screen.query_one("#dialog-list")
    return [strip.text.strip() for strip in options.render_lines(options.region.reset_offset)[: options.option_count]]


@pytest.mark.asyncio
async def test_thread_switcher_shows_bracketed_titles_as_written():
    app = DeerFlowTUI(_BracketedSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#composer").value = "/threads"
        await pilot.press("enter")
        assert await _settle(pilot, lambda: isinstance(app.screen, SelectScreen))
        assert _picker_lines(app) == ["Fix [/bold] in parser   ·   thread-c", "Index [a] then [b]   ·   thread-d"]
        await pilot.press("down", "enter")
        await _settle(pilot, lambda: app._conv_thread_id == "thread-dddddddd")
    assert app._conv_thread_id == "thread-dddddddd"


@pytest.mark.asyncio
async def test_model_picker_shows_bracketed_names_as_written():
    app = DeerFlowTUI(_BracketedSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#composer").value = "/model"
        await pilot.press("enter")
        assert await _settle(pilot, lambda: isinstance(app.screen, SelectScreen))
        assert _picker_lines(app) == ["Qwen [beta]", "x [/i] y"]
        await pilot.press("down", "enter")
        await _settle(pilot, lambda: app._model_override is not None)
    assert app._model_override == "italic"


@pytest.mark.asyncio
async def test_select_screen_title_is_shown_as_written():
    app = DeerFlowTUI(_FakeSession(), LaunchPlan(mode="tui"))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SelectScreen("Pick [/b] one", [("only", "Only")]))
        assert await _settle(pilot, lambda: isinstance(app.screen, SelectScreen))
        title = app.screen.query_one("#dialog-title")
        assert title.render_line(0).text.strip() == "Pick [/b] one"
