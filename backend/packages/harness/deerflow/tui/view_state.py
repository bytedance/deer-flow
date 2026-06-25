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


Action = UserSubmitted | RunStarted | RunEnded | AssistantDelta | AssistantError | ToolStarted | ToolResult | SystemMessage | ThreadTitle | ClearRows


# --------------------------------------------------------------------------- #
# State.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ViewState:
    rows: tuple[Row, ...] = ()
    streaming: bool = False
    usage: dict | None = None
    title: str | None = None
    # Id of the message currently being generated this turn. Only this row renders
    # as plain text while streaming; everything else (history) stays Markdown.
    streaming_id: str | None = None


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
        # New turn: no message is actively streaming yet (the client re-emits
        # prior messages first; those must not be treated as the active one).
        return replace(state, streaming=True, streaming_id=None)

    if isinstance(action, RunEnded):
        return replace(
            state,
            streaming=False,
            streaming_id=None,
            usage=action.usage if action.usage is not None else state.usage,
        )

    if isinstance(action, AssistantDelta):
        return _apply_assistant_delta(state, action)

    if isinstance(action, AssistantError):
        return _append(state, AssistantRow(text=action.text, error=True))

    if isinstance(action, ToolStarted):
        return _apply_tool_started(state, action)

    if isinstance(action, ToolResult):
        return _apply_tool_result(state, action)

    if isinstance(action, SystemMessage):
        return _append(state, SystemRow(text=action.text, tone=action.tone))

    if isinstance(action, ThreadTitle):
        return replace(state, title=action.title)

    if isinstance(action, ClearRows):
        return replace(state, rows=(), title=None, streaming_id=None)

    return state


def _apply_assistant_delta(state: ViewState, action: AssistantDelta) -> ViewState:
    """Update the assistant row with this id (anywhere in the transcript), or
    start a new one.

    On a thread with history, the client re-emits every prior message on each
    new turn (its dedup is per-turn), and a re-emitted *older* message can arrive
    after a newer one has started — so we must match by id across the whole
    transcript, not just the most recent assistant row, or prior answers get
    duplicated.

    Updates also merge by content rather than blindly concatenating, to absorb
    full re-sends / cumulative snapshots vs. genuine incremental deltas:

    * new text == accumulated, or starts with it  -> cumulative/re-send: replace
    * accumulated starts with new text            -> stale/shorter re-send: keep
    * otherwise                                   -> a real delta: append
    """

    rows = list(state.rows)
    for i, row in enumerate(rows):
        # ``not row.error``: error rows are appended without an id, so they never
        # match here anyway — the guard is belt-and-suspenders to keep an error
        # row from being merged into if a future change ever gives it an id.
        if isinstance(row, AssistantRow) and row.id == action.id and not row.error:
            merged = _merge_stream_text(row.text, action.text)
            if merged == row.text:
                # No-op re-send (e.g. a values snapshot re-emitting history) —
                # don't mark this as the actively-streaming message.
                return state
            rows[i] = replace(row, text=merged)
            return _mark_streaming(replace(state, rows=tuple(rows)), action.id)
    return _mark_streaming(_append(state, AssistantRow(text=action.text, id=action.id)), action.id)


def _mark_streaming(state: ViewState, message_id: str) -> ViewState:
    """Record the actively-streaming message id (only while a run is active)."""
    if state.streaming:
        return replace(state, streaming_id=message_id)
    return state


def _merge_stream_text(existing: str, incoming: str) -> str:
    if not existing:
        return incoming
    if incoming.startswith(existing):
        return incoming  # cumulative snapshot or exact full re-send
    if existing.startswith(incoming):
        return existing  # shorter/stale re-send
    return existing + incoming  # genuine incremental delta


def _apply_tool_started(state: ViewState, action: ToolStarted) -> ViewState:
    """Create or update a tool card, de-duplicated by ``tool_call_id``.

    Streaming tool calls arrive as multiple chunks for one call id (name first,
    then growing arguments), and the client may re-emit the call via a values
    snapshot. Chunks with no id are argument-fragment noise and are dropped.
    """
    if not action.tool_call_id:
        return state

    rows = list(state.rows)
    for i, row in enumerate(rows):
        if isinstance(row, ToolRow) and row.tool_call_id == action.tool_call_id:
            name = action.tool_name or row.tool_name
            detail = format_tool_detail(name, action.args) or row.detail
            rows[i] = replace(row, tool_name=name, title=summarize_tool_title(name), detail=detail)
            return replace(state, rows=tuple(rows))

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


def _apply_tool_result(state: ViewState, action: ToolResult) -> ViewState:
    if not action.tool_call_id:
        return state

    rows = list(state.rows)
    for i, row in enumerate(rows):
        if isinstance(row, ToolRow) and row.tool_call_id == action.tool_call_id:
            rows[i] = replace(
                row,
                status="error" if action.is_error else "ok",
                result=format_tool_result(action.content),
            )
            return replace(state, rows=tuple(rows))

    # No matching tool card (started chunks missed) -> surface the result anyway.
    return _append(
        state,
        ToolRow(
            tool_call_id=action.tool_call_id,
            tool_name=action.tool_name,
            title=summarize_tool_title(action.tool_name),
            status="error" if action.is_error else "ok",
            result=format_tool_result(action.content),
        ),
    )
