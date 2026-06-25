"""Tests for the slash-command palette renderer (pure)."""

from rich.console import Console

from deerflow.tui.command_registry import build_registry
from deerflow.tui.render import render_palette


def _text(renderable) -> str:
    console = Console(width=80, no_color=True)
    with console.capture() as cap:
        console.print(renderable)
    return cap.get()


def test_empty_items_render_nothing():
    assert _text(render_palette([], 0)).strip() == ""


def test_lists_commands_with_descriptions():
    registry = build_registry([])
    out = _text(render_palette(registry, 0, limit=5))
    assert "/help" in out
    assert "Show commands" in out


def test_highlight_marker_present_on_selected_row():
    registry = build_registry([])
    out = _text(render_palette(registry, 0, limit=5))
    assert "▌" in out


def test_windowing_shows_more_indicator_when_truncated():
    registry = build_registry([])
    out = _text(render_palette(registry, 0, limit=3))
    assert "more" in out


def test_window_follows_selection_index():
    registry = build_registry([])
    # Selecting an index beyond the first window must keep that command visible.
    target = registry[6]
    out = _text(render_palette(registry, 6, limit=4))
    assert f"/{target.name}" in out
