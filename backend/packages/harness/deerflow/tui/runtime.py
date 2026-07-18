"""Runtime bridge between ``DeerFlowClient`` streaming and the view-state reducer.

Two layers, both kept free of Textual:

* :func:`translate` — pure: one ``StreamEvent`` -> zero or more reducer actions.
* :func:`stream_actions` — drives ``client.stream()`` and yields a bracketed
  action sequence (``RunStarted`` … translated actions … ``RunEnded``), turning
  model errors into an ``AssistantError`` row instead of crashing.

The Textual app runs :func:`stream_actions` in a worker thread and applies each
yielded action to the reducer on the UI thread.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

from .view_state import (
    Action,
    AssistantDelta,
    AssistantError,
    RunEnded,
    RunStarted,
    ThreadTitle,
    ToolResult,
    ToolStarted,
)


class _StreamEventLike(Protocol):
    type: str
    data: dict


class _ClientLike(Protocol):
    def stream(self, message: str, *, thread_id: str | None = None, **kwargs: Any) -> Iterator[Any]:
        """Yield streaming events for *message* (see ``DeerFlowClient.stream``)."""


def translate(event: _StreamEventLike) -> list[Action]:
    """Map a single ``StreamEvent`` to reducer actions. Pure."""
    if event.type == "messages-tuple":
        return _translate_message(event.data)
    if event.type == "end":
        usage = event.data.get("usage") if isinstance(event.data, dict) else None
        return [RunEnded(usage=usage)]
    if event.type == "values" and isinstance(event.data, dict):
        title = event.data.get("title")
        if isinstance(title, str) and title.strip():
            return [ThreadTitle(title=title.strip())]
        return []
    # "custom" events are not rendered incrementally.
    return []


def _translate_message(data: Any) -> list[Action]:
    if not isinstance(data, dict):
        return []

    message_type = data.get("type")
    actions: list[Action] = []

    if message_type == "ai":
        text = _extract_text(data.get("content"))
        if text:
            actions.append(AssistantDelta(id=_as_str(data.get("id")), text=text))
        for tool_call in data.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            actions.append(
                ToolStarted(
                    tool_call_id=_as_str(tool_call.get("id")),
                    tool_name=_as_str(tool_call.get("name")),
                    args=tool_call.get("args") or {},
                )
            )
    elif message_type == "tool":
        is_error = bool(data.get("is_error")) or data.get("status") == "error"
        actions.append(
            ToolResult(
                tool_call_id=_as_str(data.get("tool_call_id")),
                content=_extract_text(data.get("content")),
                is_error=is_error,
                tool_name=_as_str(data.get("name")),
            )
        )

    return actions


def _as_str(value: Any) -> str:
    # Provider stream chunks can carry an explicit ``None`` id/name (the key is
    # present, so ``.get(k, "")`` would return None, and ``str(None) == "None"``
    # — a truthy value that would defeat the empty-id guard downstream).
    return "" if value is None else str(value)


def stream_actions(client: _ClientLike, message: str, *, thread_id: str | None = None, **kwargs: Any) -> Iterator[Action]:
    """Yield a bracketed action stream for one agent run.

    Always begins with ``RunStarted`` and ends with ``RunEnded`` (even on error,
    where an ``AssistantError`` row is emitted first).
    """
    yield RunStarted()
    try:
        for event in client.stream(message, thread_id=thread_id, **kwargs):
            yield from translate(event)
            if event.type == "end":
                return  # RunEnded already emitted by translate()
        yield RunEnded()
    except Exception as exc:  # noqa: BLE001 - surface any model/runtime error in-UI
        yield AssistantError(str(exc) or exc.__class__.__name__)
        yield RunEnded()


def _extract_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content)
