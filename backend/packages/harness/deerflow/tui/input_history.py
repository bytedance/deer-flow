"""Bounded composer input history with up/down navigation (pure).

No persistence and no Textual dependency here; the app may seed/save entries
elsewhere. Navigation stashes the in-progress draft so walking back through
history and forward again restores what the user was typing.
"""

from __future__ import annotations

DEFAULT_LIMIT = 200


class InputHistory:
    def __init__(self, entries: list[str] | None = None, limit: int = DEFAULT_LIMIT) -> None:
        self._limit = max(1, limit)
        self._entries: list[str] = list(entries or [])[-self._limit :]
        self._cursor: int | None = None  # None => not navigating
        self._draft: str = ""

    def entries(self) -> list[str]:
        return list(self._entries)

    def add(self, text: str) -> None:
        """Record a submitted entry. Ignores blank and consecutive-duplicate lines."""
        self._cursor = None
        self._draft = ""
        if not text.strip():
            return
        if self._entries and self._entries[-1] == text:
            return
        self._entries.append(text)
        if len(self._entries) > self._limit:
            self._entries = self._entries[-self._limit :]

    def up(self, draft: str = "") -> str:
        """Move one entry older. Returns the entry (or ``draft`` if empty)."""
        if not self._entries:
            return draft
        if self._cursor is None:
            self._draft = draft
            self._cursor = len(self._entries) - 1
        elif self._cursor > 0:
            self._cursor -= 1
        return self._entries[self._cursor]

    def down(self) -> str:
        """Move one entry newer. Past the newest entry, restores the draft."""
        if self._cursor is None:
            return self._draft
        if self._cursor < len(self._entries) - 1:
            self._cursor += 1
            return self._entries[self._cursor]
        self._cursor = None
        return self._draft

    def reset(self) -> None:
        self._cursor = None
        self._draft = ""
