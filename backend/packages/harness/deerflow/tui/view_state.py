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
    # Row index of the *anonymous* (empty-id) assistant row receiving deltas this
    # turn, if any. A genuine id is a reliable cross-chunk key (see
    # `_apply_assistant_delta`'s whole-transcript id scan), but an empty id ("" —
    # see `runtime._as_str`) is shared by every id-less chunk from every turn, so
    # it cannot be matched the same way: scanning for `row.id == ""` would fold a
    # brand new turn's text into whatever earlier turn's row happened to be
    # id-less too. This index instead pins "this turn's" anonymous row by
    # position, reset alongside `streaming_id` at the start/end of every turn.
    streaming_anonymous_row_index: int | None = None


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
        # New turn: no message is actively streaming until its first delta.
        return replace(state, streaming=True, streaming_id=None, streaming_anonymous_row_index=None)

    if isinstance(action, RunEnded):
        return replace(
            state,
            streaming=False,
            streaming_id=None,
            streaming_anonymous_row_index=None,
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
        return replace(state, rows=(), streaming_id=None, streaming_anonymous_row_index=None)

    return state


def _apply_assistant_delta(state: ViewState, action: AssistantDelta) -> ViewState:
    """Update the assistant row for this delta, or start a new one.

    A genuine (non-empty) id is matched anywhere in the transcript, not just
    the most recent assistant row: every delta for one message belongs to that
    message's row, even after other rows have been appended behind it.

    An empty id ("" — some providers/paths never stamp per-chunk ids, see
    ``runtime._as_str``) is NOT a reliable key for that same scan: unlike a
    genuine id, it is shared by every id-less chunk from *every* turn, so
    matching `row.id == ""` across the whole transcript would fold a brand
    new turn's text into whatever earlier turn's row happened to be id-less
    too — silently vanishing the new turn's answer into a stale row. Empty-id
    deltas are therefore routed to `_apply_assistant_delta_anonymous`, which
    tracks "this turn's" row by position instead of by id.

    Every update is appended verbatim. ``DeerFlowClient.stream`` emits only
    incremental text per message id: it never re-sends delivered text,
    replays prior turns, or sends a cumulative snapshot. A delta that repeats
    or extends the accumulated text is therefore still new text (``"ha"`` +
    ``"ha"``, or a closing ``"**"`` after an opening one), never a re-send.
    """
    if not action.id:
        return _apply_assistant_delta_anonymous(state, action)

    rows = list(state.rows)
    for i, row in enumerate(rows):
        # ``not row.error``: error rows are appended without an id, so they never
        # match here anyway — the guard is belt-and-suspenders to keep an error
        # row from being merged into if a future change ever gives it an id.
        if isinstance(row, AssistantRow) and row.id == action.id and not row.error:
            rows[i] = replace(row, text=row.text + action.text)
            return _mark_streaming(replace(state, rows=tuple(rows)), action.id)
    return _mark_streaming(_append(state, AssistantRow(text=action.text, id=action.id)), action.id)


def _apply_assistant_delta_anonymous(state: ViewState, action: AssistantDelta) -> ViewState:
    """Handle an ``AssistantDelta`` whose id is empty (see `_apply_assistant_delta`).

    Multiple id-less chunks legitimately arrive for a single turn — a provider
    that never stamps per-chunk ids still streams token by token, e.g.
    ``"Hel"`` then ``"lo"`` — so the first empty-id delta of a turn starts a
    new row, and later empty-id deltas keep appending to that row (tracked by
    ``state.streaming_anonymous_row_index``, reset on every
    ``RunStarted``/``RunEnded``/``ClearRows``, not by id, so a later turn
    always starts its own new row instead of matching the previous turn's
    leftover id-less row — the bug this split exists to avoid).

    The tracked row is only reused while it is still the LAST row in the
    transcript. A genuine id naturally changes across a tool round-trip
    (LangGraph gives the post-tool continuation a new AIMessage id), which is
    why an interleaved ``ToolStarted``/``ToolResult`` already starts a new row
    in the id-keyed path (see `test_assistant_delta_with_new_id_after_tool_
    creates_separate_row`). An empty id has no such natural signal — it is
    always ``""`` before and after the tool call — so this function uses row
    *position* as the substitute: once anything else has been appended (a
    tool card, in practice), the anonymous row is no longer the tail, and the
    next empty-id delta starts a fresh row rather than reaching backward past
    the tool card into stale text.
    """
    index = state.streaming_anonymous_row_index
    if index is not None and index == len(state.rows) - 1:
        row = state.rows[index]
        if isinstance(row, AssistantRow) and not row.error:
            # Same append-only semantics as the id-keyed path above.
            rows = list(state.rows)
            rows[index] = replace(row, text=row.text + action.text)
            return _mark_streaming_anonymous(replace(state, rows=tuple(rows)), index)

    new_state = _append(state, AssistantRow(text=action.text, id=action.id))
    return _mark_streaming_anonymous(new_state, len(new_state.rows) - 1)


def _mark_streaming(state: ViewState, message_id: str) -> ViewState:
    """Record the actively-streaming message id (only while a run is active)."""
    if state.streaming:
        return replace(state, streaming_id=message_id)
    return state


def _mark_streaming_anonymous(state: ViewState, index: int) -> ViewState:
    """Record the active turn's anonymous-row index (only while a run is active).

    Deliberately leaves ``streaming_id`` at ``None`` rather than ``""``: unlike
    a genuine id, ``""`` would be shared by every anonymous row across every
    turn, so using it as the render layer's "is this the row actively
    streaming" key (``render.render_transcript``) would flag every past
    anonymous row as actively streaming too, the moment a new one starts. The
    cost is purely cosmetic — an anonymous row never gets the
    raw-text-while-streaming treatment other rows get, only the id-less
    fallback path is affected — in exchange for not reintroducing a cross-turn
    ambiguity into the render layer that this fix removes from ``rows``.
    """
    if state.streaming:
        return replace(state, streaming_id=None, streaming_anonymous_row_index=index)
    return state


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
