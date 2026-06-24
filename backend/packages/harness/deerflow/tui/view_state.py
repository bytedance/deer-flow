"""Pure view-state reducer for the DeerFlow TUI.

This module has **no** Textual / rendering dependency. It models the visible
conversation as an immutable list of typed rows and a small set of actions,
and exposes a single pure ``reduce(state, action) -> state`` function.

Keeping this layer pure makes the interesting behaviour (streaming deltas,
tool cards, error rows) testable with plain ``pytest`` and a handful of
synthetic actions, independent of any terminal.

The runtime bridge (``deerflow.tui.runtime``) is responsible for translating
``DeerFlowClient`` ``StreamEvent`` objects into these actions; the Textual app
renders ``ViewState`` into widgets. Both sides depend on this module, not on
each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from .message_format import format_tool_detail, format_tool_result, summarize_tool_title

# --------------------------------------------------------------------------- #
# Rows — the immutable units the transcript is built from.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UserRow:
    text: str
    kind: Literal["user"] = "user"


@dataclass(frozen=True)
class AssistantRow:
    text: str
    id: str | None = None
    error: bool = False
    kind: Literal["assistant"] = "assistant"


@dataclass(frozen=True)
class ToolRow:
    tool_call_id: str
    tool_name: str
    title: str
    detail: str = ""
    result: str = ""
    status: Literal["running", "ok", "error"] = "running"
    kind: Literal["tool"] = "tool"


@dataclass(frozen=True)
class SystemRow:
    text: str
    tone: Literal["info", "error"] = "info"
    kind: Literal["system"] = "system"


Row = UserRow | AssistantRow | ToolRow | SystemRow


# --------------------------------------------------------------------------- #
# Actions — the only ways the state can change.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UserSubmitted:
    text: str


@dataclass(frozen=True)
class RunStarted:
    pass


@dataclass(frozen=True)
class RunEnded:
    usage: dict | None = None


@dataclass(frozen=True)
class AssistantDelta:
    id: str
    text: str


@dataclass(frozen=True)
class AssistantError:
    text: str


@dataclass(frozen=True)
class ToolStarted:
    tool_call_id: str
    tool_name: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False
    tool_name: str = ""


@dataclass(frozen=True)
class SystemMessage:
    text: str
    tone: Literal["info", "error"] = "info"


@dataclass(frozen=True)
class ThreadTitle:
    title: str


@dataclass(frozen=True)
class ClearRows:
    pass


Action = (
    UserSubmitted
    | RunStarted
    | RunEnded
    | AssistantDelta
    | AssistantError
    | ToolStarted
    | ToolResult
    | SystemMessage
    | ThreadTitle
    | ClearRows
)


# --------------------------------------------------------------------------- #
# State.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ViewState:
    rows: tuple[Row, ...] = ()
    streaming: bool = False
    usage: dict | None = None
    title: str | None = None


def initial_state(rows: tuple[Row, ...] = ()) -> ViewState:
    return ViewState(rows=tuple(rows))


# --------------------------------------------------------------------------- #
# Reducer.
# --------------------------------------------------------------------------- #


def _append(state: ViewState, row: Row) -> ViewState:
    return replace(state, rows=state.rows + (row,))


def reduce(state: ViewState, action: Action) -> ViewState:
    """Return a new ``ViewState`` after applying ``action``. Pure."""

    if isinstance(action, UserSubmitted):
        return _append(state, UserRow(text=action.text))

    if isinstance(action, RunStarted):
        return replace(state, streaming=True)

    if isinstance(action, RunEnded):
        return replace(state, streaming=False, usage=action.usage if action.usage is not None else state.usage)

    if isinstance(action, AssistantDelta):
        return _apply_assistant_delta(state, action)

    if isinstance(action, AssistantError):
        return _append(state, AssistantRow(text=action.text, error=True))

    if isinstance(action, ToolStarted):
        return _append(
            state,
            ToolRow(
                tool_call_id=action.tool_call_id,
                tool_name=action.tool_name,
                title=summarize_tool_title(action.tool_name),
                detail=format_tool_detail(action.tool_name, action.args),
                status="running",
            ),
        )

    if isinstance(action, ToolResult):
        return _apply_tool_result(state, action)

    if isinstance(action, SystemMessage):
        return _append(state, SystemRow(text=action.text, tone=action.tone))

    if isinstance(action, ThreadTitle):
        return replace(state, title=action.title)

    if isinstance(action, ClearRows):
        return replace(state, rows=(), title=None)

    return state


def _apply_assistant_delta(state: ViewState, action: AssistantDelta) -> ViewState:
    """Append to the existing assistant row with this id, or start a new one.

    Deltas for a given message id are contiguous, so it is enough to match the
    most recent assistant row by id. A new id (e.g. a fresh assistant turn after
    a tool call) starts its own row, preserving transcript order.
    """

    rows = list(state.rows)
    for i in range(len(rows) - 1, -1, -1):
        row = rows[i]
        if isinstance(row, AssistantRow):
            if row.id == action.id and not row.error:
                rows[i] = replace(row, text=row.text + action.text)
                return replace(state, rows=tuple(rows))
            break  # most recent assistant row has a different id -> new row
    return _append(state, AssistantRow(text=action.text, id=action.id))


def _apply_tool_result(state: ViewState, action: ToolResult) -> ViewState:
    rows = list(state.rows)
    for i, row in enumerate(rows):
        if isinstance(row, ToolRow) and row.tool_call_id == action.tool_call_id:
            rows[i] = replace(
                row,
                status="error" if action.is_error else "ok",
                result=format_tool_result(action.content),
            )
            return replace(state, rows=tuple(rows))
    return state  # unknown tool_call_id -> ignore
