"""Pure Rich renderers for the transcript, status line and header.

These take a :class:`ViewState` (plus light session info) and return Rich
renderables. No Textual import, so they can be unit-tested by rendering to a
Rich ``Console`` and inspecting the text.
"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from .theme import SYMBOLS, THEME
from .view_state import AssistantRow, Row, SystemRow, ToolRow, UserRow, ViewState

_EMPTY_HINT = "Type a message to begin.  Press / for commands, ? for help."

_TOOL_STATUS_SYMBOL = {"running": SYMBOLS["running"], "ok": SYMBOLS["ok"], "error": SYMBOLS["error"]}
_TOOL_STATUS_STYLE = {"running": THEME.warning, "ok": THEME.accent, "error": THEME.error}


def render_transcript(state: ViewState) -> RenderableType:
    if not state.rows:
        return Text(_EMPTY_HINT, style=f"italic {THEME.dim}")

    # Only the message being generated right now renders as plain text (to avoid
    # Markdown reflow jumpiness). Every other message — all history — renders as
    # Markdown, so a follow-up turn never reverts prior answers to raw text.
    blocks: list[RenderableType] = []
    for row in state.rows:
        streaming_now = state.streaming and isinstance(row, AssistantRow) and row.id is not None and row.id == state.streaming_id
        blocks.append(render_row(row, as_markdown=not streaming_now))
        blocks.append(Text(""))  # one blank line between blocks for breathing room
    return Group(*blocks[:-1])


def render_row(row: Row, *, as_markdown: bool = True) -> RenderableType:
    if isinstance(row, UserRow):
        text = Text()
        text.append(f"{SYMBOLS['user']} ", style=f"bold {THEME.user}")
        text.append(row.text, style=f"bold {THEME.user}")
        return text

    if isinstance(row, AssistantRow):
        if not row.error and as_markdown and row.text.strip():
            return _assistant_markdown(row.text)
        style = THEME.error if row.error else THEME.assistant
        text = Text()
        text.append(f"{SYMBOLS['assistant']} ", style=f"bold {style}")
        text.append(row.text or "…", style=style)
        return text

    if isinstance(row, ToolRow):
        return _render_tool(row)

    if isinstance(row, SystemRow):
        style = THEME.error if row.tone == "error" else THEME.dim
        return Text(f"{SYMBOLS['system']} {row.text}", style=f"italic {style}")

    return Text(str(row))


def _assistant_markdown(text: str) -> RenderableType:
    """A ``●`` speaker marker aligned to the top of the Markdown-rendered body."""
    grid = Table.grid(padding=(0, 1, 0, 0))
    grid.add_column(width=1, vertical="top")  # marker
    grid.add_column(ratio=1)  # markdown body
    grid.add_row(
        Text(SYMBOLS["assistant"], style=f"bold {THEME.assistant}"),
        Markdown(text),
    )
    return grid


def _render_tool(row: ToolRow) -> RenderableType:
    head = Text()
    head.append(f"  {SYMBOLS['tool']} ", style=THEME.tool)
    head.append(row.title, style=f"bold {THEME.tool}")
    if row.detail:
        head.append(f"  {row.detail}", style=THEME.dim)
    head.append(f"   {_TOOL_STATUS_SYMBOL[row.status]}", style=_TOOL_STATUS_STYLE[row.status])

    if row.result and row.status != "running":
        return Group(head, Text(f"    {row.result}", style=THEME.dim))
    return head


def render_status(state: ViewState, *, model: str, thread_label: str, spinner: str = "", elapsed: str = "") -> Text:
    text = Text(no_wrap=True, overflow="ellipsis")
    if state.streaming:
        text.append(f"{spinner} working", style=f"bold {THEME.warning}")
    else:
        text.append("● ready", style=f"bold {THEME.accent}")
    if state.title:
        text.append("  ")
        text.append(state.title, style=f"italic {THEME.muted}")
    text.append("   ")
    text.append(model or "default", style=THEME.primary)
    text.append("   ")
    text.append(thread_label, style=THEME.muted)
    if elapsed:
        text.append("   ")
        text.append(elapsed, style=THEME.dim)
    usage = state.usage or {}
    total = usage.get("total_tokens")
    if total:
        text.append("   ")
        text.append(f"{total} tok", style=THEME.dim)
    if state.streaming:
        text.append("   esc interrupt", style=THEME.dim)
    return text


def render_palette(items, index: int, limit: int = 8) -> RenderableType:
    """Render the slash-command picker: a windowed list with one highlighted row."""
    if not items:
        return Text("")
    index = max(0, min(index, len(items) - 1))
    start = index - limit + 1 if index >= limit else 0
    window = items[start : start + limit]
    selected_in_window = index - start

    lines: list[RenderableType] = []
    for i, command in enumerate(window):
        selected = i == selected_in_window
        line = Text(no_wrap=True, overflow="ellipsis")
        line.append("▌ " if selected else "  ", style=THEME.primary)
        line.append(f"/{command.name}", style=(f"bold {THEME.primary}" if selected else THEME.text))
        if command.description:
            line.append("  ")
            line.append(command.description, style=THEME.dim)
        lines.append(line)
    if len(items) > limit:
        lines.append(Text(f"  … {len(items) - limit} more", style=f"italic {THEME.dim}"))
    return Group(*lines)


def render_header(*, model: str, thread_label: str, cwd: str, skills: int = 0) -> Text:
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(" DeerFlow ", style=f"bold {THEME.bg} on {THEME.primary}")
    text.append("  ")
    text.append(model or "default", style=f"bold {THEME.primary}")
    text.append("  ·  ", style=THEME.dim)
    text.append(thread_label, style=THEME.muted)
    text.append("  ·  ", style=THEME.dim)
    text.append(cwd, style=THEME.dim)
    if skills:
        text.append("  ·  ", style=THEME.dim)
        text.append(f"{skills} skills", style=THEME.dim)
    return text
