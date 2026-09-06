"""Composer input with a wide-character (CJK) cursor fix.

Textual's ``Input._cursor_offset`` adds an unconditional ``+1`` when the cursor
is at the end of the value. After double-width (CJK) characters that overshoots
by one cell, which misplaces the *hardware / IME* cursor — the visible drift when
typing Chinese in terminals such as iTerm2. (The on-screen block cursor is drawn
separately in ``render_line`` via character-index styling and is unaffected; this
only corrects the terminal cursor anchor that the IME candidate window follows.)

English input never exercises this because it doesn't go through an IME, which is
why the drift only shows up for CJK.
"""

from __future__ import annotations

from textual.widgets import Input


class ComposerInput(Input):
    @property
    def _cursor_offset(self) -> int:
        # True cell offset of the cursor, without Textual's end-of-value +1.
        return self._position_to_cell(self.cursor_position)
