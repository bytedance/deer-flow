"""Multiline TUI composer with the existing Enter-to-submit contract."""

from __future__ import annotations

from dataclasses import dataclass

from textual.binding import Binding
from textual.message import Message
from textual.widgets import TextArea


class ComposerInput(TextArea):
    """A ``TextArea`` that submits on Enter and exposes input-like helpers.

    ``TextArea`` preserves bracketed multiline pastes and computes its hardware
    cursor from display-cell widths, including CJK. The small compatibility
    surface keeps the surrounding palette/history code independent of Textual's
    document locations.
    """

    BINDINGS = [Binding("enter", "submit", show=False, priority=True)]

    @dataclass
    class Submitted(Message):
        input: ComposerInput
        value: str

        @property
        def control(self) -> ComposerInput:
            return self.input

    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, value: str) -> None:
        self.load_text(value)

    @property
    def cursor_position(self) -> int:
        row, column = self.cursor_location
        return sum(len(line) + 1 for line in self.document.lines[:row]) + column

    @cursor_position.setter
    def cursor_position(self, position: int) -> None:
        position = max(0, min(position, len(self.text)))
        prefix = self.text[:position]
        row = prefix.count("\n")
        column = len(prefix.rsplit("\n", 1)[-1])
        self.move_cursor((row, column))

    @property
    def can_move_up(self) -> bool:
        return self.cursor_location[0] > 0

    @property
    def can_move_down(self) -> bool:
        return self.cursor_location[0] < self.document.line_count - 1

    def action_submit(self) -> None:
        self.post_message(self.Submitted(self, self.text))
