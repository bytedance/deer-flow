"""Tests for multiline paste and CJK-aware composer cursor offsets."""

import pytest
from textual import events
from textual.app import App, ComposeResult
from textual.geometry import Offset

from deerflow.tui.widgets.composer import ComposerInput


class _Harness(App):
    def compose(self) -> ComposeResult:
        yield ComposerInput(id="c")


@pytest.mark.asyncio
async def test_cursor_offset_after_cjk_has_no_off_by_one():
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        comp = app.query_one("#c", ComposerInput)
        comp.value = "总结一下"  # 4 wide chars = 8 cells
        comp.cursor_position = len(comp.value)
        # Stock Input would report 9 here (unconditional +1); the fix reports 8,
        # so the hardware/IME cursor sits exactly after the last character.
        assert comp._cursor_offset == Offset(8, 0)


@pytest.mark.asyncio
async def test_cursor_offset_mid_text_is_unchanged():
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        comp = app.query_one("#c", ComposerInput)
        comp.value = "总结一下"
        comp.cursor_position = 3  # not at end -> 3 wide chars = 6 cells
        assert comp._cursor_offset == Offset(6, 0)


@pytest.mark.asyncio
async def test_cursor_offset_ascii_end_is_exact():
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        comp = app.query_one("#c", ComposerInput)
        comp.value = "abcd"
        comp.cursor_position = 4
        assert comp._cursor_offset == Offset(4, 0)


@pytest.mark.asyncio
async def test_paste_preserves_newlines_and_indentation():
    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        comp = app.query_one("#c", ComposerInput)
        comp.focus()
        app.post_message(events.Paste("if ready:\n    run()\nelse:\n    wait()"))
        await pilot.pause()

        assert comp.value == "if ready:\n    run()\nelse:\n    wait()"
        assert comp.cursor_location == (3, 10)
