"""Build compact subagent step payloads for streaming + persistence.

Issue #3779: subagent (subtask) execution steps were only visible as the
latest streamed frame and were never persisted, so users could not review
what tools a subagent ran or what each step produced after a reload.

This module is the pure data-shaping layer. It converts a captured subagent
message dict — the ``model_dump()`` of an ``AIMessage`` (an assistant turn:
text + tool-call requests) or a ``ToolMessage`` (a tool's output) — into the
small, JSON-serializable ``step`` payload that is:

- streamed live inside the ``task_running`` custom event (``task_tool.py``), and
- persisted as a ``subagent.step`` run event (``runtime/runs/worker.py``).

Keeping it pure means it is unit-tested without spinning up a graph, and both
the streaming and persistence call sites share one definition of a "step".
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from deerflow.utils.messages import message_content_to_text

from .status_contract import normalize_token_usage

#: Default per-step character cap for the ``text`` field. Tool outputs (web
#: search results, file contents) can be large; this cap bounds the persisted
#: run-event row and the streamed frame. It only affects display/storage — the
#: subagent's own LLM context is bounded separately by ToolOutputBudgetMiddleware.
SUBAGENT_STEP_MAX_CHARS = 8192

#: ``RunEvent.category`` for persisted subagent steps. A dedicated category (not
#: ``"message"``) keeps these events out of ``list_messages`` (the thread message
#: feed) while still being returned by ``list_events`` for fetch-on-expand (#3779).
SUBAGENT_EVENT_CATEGORY = "subagent"

#: Map of ``task_*`` terminal custom-event types to their persisted status.
_TERMINAL_EVENT_STATUS: dict[str, str] = {
    "task_completed": "completed",
    "task_failed": "failed",
    "task_cancelled": "cancelled",
    "task_timed_out": "timed_out",
}


def capture_step_message(
    message: BaseMessage,
    captured: list[dict[str, Any]],
    seen_ids: set[str],
) -> bool:
    """Append ``message.model_dump()`` to ``captured`` if it is a new step.

    A "step" is an assistant turn (``AIMessage``) or a tool result
    (``ToolMessage``) — issue #3779 added the latter so tool outputs survive.
    Other message types (e.g. ``HumanMessage``) are ignored. Dedup is by id
    when present, falling back to a full-dict compare for id-less messages so
    ``stream_mode="values"`` re-yielding the same trailing message stays O(1).

    Returns ``True`` when a message was appended.
    """
    if not isinstance(message, (AIMessage, ToolMessage)):
        return False

    message_dict = message.model_dump()
    message_id = message_dict.get("id")
    if message_id:
        if message_id in seen_ids:
            return False
    elif message_dict in captured:
        return False

    captured.append(message_dict)
    if message_id:
        seen_ids.add(message_id)
    return True


def capture_new_step_messages(
    messages: list[BaseMessage],
    captured: list[dict[str, Any]],
    seen_ids: set[str],
    processed_count: int,
) -> int:
    """Capture every step message appended since ``processed_count`` (#3779).

    ``stream_mode="values"`` re-yields the full message history on each chunk,
    and a single LangGraph super-step can append several messages at once — most
    importantly one ``ToolMessage`` per tool call when the model emits multiple
    tool calls in one turn. Capturing only ``messages[-1]`` (the previous
    behaviour) silently dropped all but the last tool output.

    When the history grew, walk every newly-appended message. When it did not
    grow, re-examine only the trailing message so an id-less in-place replacement
    (same length, new content) is still captured — ``capture_step_message``'s
    dedup makes an unchanged re-yield a no-op. Returns the new cursor.

    When the history *contracted* (``total < processed_count``) — which happens
    when ``DeerFlowSummarizationMiddleware`` rewrites the channel via
    ``RemoveMessage(id=REMOVE_ALL_MESSAGES)`` (#3875 Phase 3) — reset the cursor
    to the new tail and let ``capture_step_message``'s id/content dedup prevent
    re-emitting steps captured before the compaction. Without this reset, every
    step appended after the compaction point is dropped until ``total`` overtakes
    the stale cursor.

    INVARIANT: after the reset the no-growth branch only re-examines
    ``messages[-1]``, so a genuinely new AIMessage/ToolMessage inserted at an
    index BELOW the reset cursor in a compacted list would be missed. This is
    not reachable today: the summarization middleware puts the summary into a
    separate ``summary_text`` state key, and the messages channel after
    compaction holds only already-seen preserved tail messages — compaction
    never inserts a NEW capturable message below the cursor. If a future
    middleware violates this invariant, the reset branch needs a full re-scan.
    """
    total = len(messages)
    if total < processed_count:
        processed_count = total
    if total > processed_count:
        for message in messages[processed_count:total]:
            capture_step_message(message, captured, seen_ids)
        return total
    if messages:
        capture_step_message(messages[-1], captured, seen_ids)
    return max(processed_count, total)


def truncate_step_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Return ``(text, truncated)``, clipping to ``max_chars`` when longer."""
    if max_chars >= 0 and len(text) > max_chars:
        return text[:max_chars], True
    return text, False


def _bounded_tool_call(call: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """Return ``{name, args}`` for a captured tool call, capping large args (#3779).

    ``build_subagent_step`` caps the ``text`` field, but tool-call ``args`` were
    copied verbatim, so a ``write_file``/``bash`` call carrying a big payload (full
    file contents, a heredoc) produced an unbounded persisted ``subagent.step``
    row and streamed frame. When the JSON-serialized args exceed ``max_chars`` we
    replace the structured value with a truncated serialized preview and flag it
    with ``args_truncated`` — small args stay structured for the card to inspect.
    """
    name = call.get("name")
    args = call.get("args")
    serialized = args if isinstance(args, str) else json.dumps(args, default=str, ensure_ascii=False)
    if max_chars >= 0 and len(serialized) > max_chars:
        return {"name": name, "args": serialized[:max_chars], "args_truncated": True}
    return {"name": name, "args": args}


def build_subagent_step(
    message: dict[str, Any],
    *,
    task_id: str,
    message_index: int,
    max_chars: int = SUBAGENT_STEP_MAX_CHARS,
) -> dict[str, Any]:
    """Build the compact step payload from a captured subagent message dict.

    ``kind`` is ``"tool"`` for a ToolMessage (``type == "tool"``) and ``"ai"``
    otherwise. AI steps carry their ``tool_calls`` (name + args only, with large
    args capped to ``max_chars`` — see ``_bounded_tool_call``); tool steps carry
    the originating ``tool_name``. ``text`` is truncated to ``max_chars`` with the
    ``truncated`` flag set accordingly.
    """
    kind = "tool" if message.get("type") == "tool" else "ai"
    # ``... or ""`` keeps a tool-call-only turn's content=None rendering as ""
    # (message_content_to_text would otherwise str()-ify it to "None").
    text, truncated = truncate_step_text(message_content_to_text(message.get("content") or ""), max_chars)

    step: dict[str, Any] = {
        "task_id": task_id,
        "message_index": message_index,
        "kind": kind,
        "text": text,
        "truncated": truncated,
    }

    if kind == "tool":
        step["tool_name"] = message.get("name")
    else:
        step["tool_calls"] = [_bounded_tool_call(call, max_chars) for call in (message.get("tool_calls") or [])]

    return step


def subagent_run_event(chunk: Any) -> dict[str, Any] | None:
    """Map a ``task_*`` custom stream chunk to ``RunEventStore.put`` kwargs.

    Returns the ``event_type`` / ``category`` / ``content`` / ``metadata`` for a
    persistable subagent lifecycle event, or ``None`` for any chunk that is not a
    subagent event (so the worker only persists what it recognizes). ``thread_id``
    / ``run_id`` are filled in by the caller.
    """
    if not isinstance(chunk, dict):
        return None

    event = chunk.get("type")
    if not isinstance(event, str) or not event.startswith("task_"):
        return None

    task_id = chunk.get("task_id")

    if event == "task_started":
        return {
            "event_type": "subagent.start",
            "category": SUBAGENT_EVENT_CATEGORY,
            "content": {"task_id": task_id, "description": chunk.get("description")},
            "metadata": {"task_id": task_id},
        }

    if event == "task_running":
        message_index = chunk.get("message_index")
        return {
            "event_type": "subagent.step",
            "category": SUBAGENT_EVENT_CATEGORY,
            "content": build_subagent_step(chunk.get("message") or {}, task_id=task_id, message_index=message_index),
            "metadata": {"task_id": task_id, "message_index": message_index},
        }

    status = _TERMINAL_EVENT_STATUS.get(event)
    if status is not None:
        content: dict[str, Any] = {"task_id": task_id, "status": status}
        model_name = chunk.get("model_name")
        if isinstance(model_name, str) and model_name.strip():
            content["model_name"] = model_name.strip()
        usage = normalize_token_usage(chunk.get("usage"))
        if usage is not None:
            content["usage"] = usage
        # The final result/error can be a multi-page report; cap it so the
        # persisted run-event row stays bounded (it is also kept verbatim on the
        # terminal ToolMessage, which the card reads separately).
        if chunk.get("result") is not None:
            result, result_truncated = truncate_step_text(str(chunk["result"]), SUBAGENT_STEP_MAX_CHARS)
            content["result"] = result
            if result_truncated:
                content["result_truncated"] = True
        if chunk.get("error") is not None:
            error, error_truncated = truncate_step_text(str(chunk["error"]), SUBAGENT_STEP_MAX_CHARS)
            content["error"] = error
            if error_truncated:
                content["error_truncated"] = True
        return {
            "event_type": "subagent.end",
            "category": SUBAGENT_EVENT_CATEGORY,
            "content": content,
            "metadata": {"task_id": task_id},
        }

    return None
