"""Helpers for keeping AIMessage tool-call metadata consistent."""

from __future__ import annotations

from collections import Counter
from typing import Any

from langchain_core.messages import AIMessage

# Content block types that provider adapters re-serialize as tool calls,
# mapped to the keys (in priority order) holding the id that pairs with
# ``AIMessage.tool_calls[*]["id"]``. These mirror the content surfaces in
# ``tool_call_args``. Anthropic re-emits a ``tool_use`` block whose id is
# absent from ``tool_calls``; the OpenAI Responses input builder re-emits
# every ``function_call``/``custom_tool_call`` block, whose ``id`` is the
# ``fc_…`` item id and whose ``call_id`` is the tool-call id; Google GenAI
# ``function_call`` blocks carry the tool-call id in ``id``, or none at all;
# LangChain v1 ``tool_call``/``tool_call_chunk`` blocks convert back to any of
# these shapes.
_CONTENT_TOOL_CALL_ID_KEYS: dict[str, tuple[str, ...]] = {
    "tool_use": ("id",),
    "function_call": ("call_id", "id"),
    "custom_tool_call": ("call_id",),
    "tool_call": ("id",),
    "tool_call_chunk": ("id",),
}


def _raw_tool_call_id(raw_tool_call: Any) -> str | None:
    if not isinstance(raw_tool_call, dict):
        return None

    raw_id = raw_tool_call.get("id")
    return raw_id if isinstance(raw_id, str) and raw_id else None


def _content_block_call_id(block: dict[str, Any], id_keys: tuple[str, ...]) -> str | None:
    for key in id_keys:
        value = block.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _tool_call_block_id_keys(block: Any) -> tuple[str, ...] | None:
    block_type = block.get("type") if isinstance(block, dict) else None
    return _CONTENT_TOOL_CALL_ID_KEYS.get(block_type) if isinstance(block_type, str) else None


def _sync_content_tool_call_blocks(content: Any, retained_calls: list[dict[str, Any]]) -> Any:
    """Drop content tool-call blocks whose call is no longer on the message.

    A block left behind is sent as a tool call with no matching tool result,
    which Anthropic and the OpenAI Responses API reject on every later request
    for the thread. Blocks without an id (Gemini-style ``function_call``) pair
    by name, in order, with the retained calls that no id-bearing block already
    matched. Returns ``content`` itself when no block is dropped.
    """
    if not isinstance(content, list):
        return content

    retained_ids = {call["id"] for call in retained_calls if isinstance(call.get("id"), str) and call["id"]}
    # (block, is a tool-call block, the call id it carries or None when id-less)
    entries: list[tuple[Any, bool, str | None]] = []
    for block in content:
        id_keys = _tool_call_block_id_keys(block)
        entries.append((block, id_keys is not None, _content_block_call_id(block, id_keys) if id_keys is not None else None))
    matched_ids = {call_id for _, _, call_id in entries if call_id in retained_ids}
    idless_budget = Counter(call["name"] for call in retained_calls if isinstance(call.get("name"), str) and not (isinstance(call.get("id"), str) and call["id"] in matched_ids))

    synced: list[Any] = []
    for block, is_tool_call_block, call_id in entries:
        if not is_tool_call_block:
            synced.append(block)
            continue
        if call_id is not None:
            if call_id in retained_ids:
                synced.append(block)
            continue
        name = block.get("name")
        if isinstance(name, str) and idless_budget[name] > 0:
            idless_budget[name] -= 1
            synced.append(block)
    return content if len(synced) == len(content) else synced


def clone_ai_message_with_tool_calls(
    message: AIMessage,
    tool_calls: list[dict[str, Any]],
    *,
    content: Any | None = None,
) -> AIMessage:
    """Clone an AIMessage while keeping every provider tool-call surface in sync.

    Besides ``tool_calls``, the raw ``additional_kwargs`` payload and the
    provider tool-call blocks in ``content`` (including a caller-supplied
    ``content``) are trimmed to the retained calls. Blocks for calls still on
    ``invalid_tool_calls`` are kept, because ``DanglingToolCallMiddleware``
    answers those calls with placeholder tool results.
    """
    kept_ids = {tc["id"] for tc in tool_calls if isinstance(tc.get("id"), str) and tc["id"]}

    update: dict[str, Any] = {"tool_calls": tool_calls}
    invalid_tool_calls = [tc for tc in (getattr(message, "invalid_tool_calls", None) or []) if isinstance(tc, dict)]
    source_content = content if content is not None else message.content
    synced_content = _sync_content_tool_call_blocks(source_content, [*tool_calls, *invalid_tool_calls])
    if content is not None or synced_content is not message.content:
        update["content"] = synced_content

    additional_kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
    raw_tool_calls = additional_kwargs.get("tool_calls")
    if isinstance(raw_tool_calls, list):
        synced_raw_tool_calls = [raw_tc for raw_tc in raw_tool_calls if _raw_tool_call_id(raw_tc) in kept_ids]
        if synced_raw_tool_calls:
            additional_kwargs["tool_calls"] = synced_raw_tool_calls
        else:
            additional_kwargs.pop("tool_calls", None)

    if not tool_calls:
        additional_kwargs.pop("function_call", None)

    update["additional_kwargs"] = additional_kwargs

    response_metadata = dict(getattr(message, "response_metadata", {}) or {})
    if not tool_calls and response_metadata.get("finish_reason") == "tool_calls":
        response_metadata["finish_reason"] = "stop"
    update["response_metadata"] = response_metadata

    return message.model_copy(update=update)
