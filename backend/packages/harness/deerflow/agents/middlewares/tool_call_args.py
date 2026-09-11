"""Rewrite AIMessage tool-call arguments on every provider surface at once.

Middlewares that shrink or replace a historical tool call's arguments in the
*model-bound request* (never in graph state) share one hazard: a LangChain
``AIMessage`` carries the same arguments on up to four surfaces, and provider
adapters do not all read the same one —

- ``tool_calls``: the structured list most adapters prefer;
- ``additional_kwargs["tool_calls"]``: the raw provider payload (OpenAI
  ``function.arguments`` JSON string) some adapters fall back to;
- ``content`` blocks that carry their own copy of the arguments: Anthropic
  ``tool_use`` (``input`` + ``partial_json``), OpenAI Responses
  ``function_call`` (``arguments`` string, matched by ``call_id``; the
  ``fc_…`` item id is preserved), and LangChain standard-content
  ``tool_call`` / ``tool_call_chunk`` (``args`` plus ``extras.arguments``);
- ``tool_call_chunks`` on an ``AIMessageChunk``.

Rewriting only one surface leaves the original payload reachable through the
others and can hand a strict provider a request whose surfaces disagree. The
content surfaces matter most: ``langchain_openai``'s Responses input builder
emits a content ``function_call`` block *instead of* the structured call
whose ``call_id`` it already carries, and prefers ``extras.arguments`` over
the structured args when translating a v1 ``tool_call`` block, so a rewrite
that touched ``tool_calls`` alone would still send the original payload.
:func:`rewrite_tool_call_args` rewrites them together and returns a
``model_copy`` (or the same object when nothing matched), so callers never
mutate state and the result is identical across model calls. Policy — which
calls, and what replaces their arguments — stays with the caller; see
``read_before_write_middleware.elide_blocked_write_payloads`` for one.

A rewrite also invalidates server-side continuation. With
``use_previous_response_id`` the OpenAI adapter sends only the messages after
the last AIMessage carrying a ``resp_…`` ``response_metadata["id"]`` and lets
the server rebuild the rest from *its* stored copy of the conversation, which
still holds the original arguments; stored responses cannot be edited, and
every response produced after the rewritten call chains back to that history.
So whenever anything was rewritten, :func:`rewrite_messages_tool_call_args`
drops every ``resp_`` id from the model-bound copy and the adapter falls back
to replaying the full rewritten history (the same request shape as
``use_previous_response_id=False``; per OpenAI's docs chained input tokens are
billed either way, so replay costs no more).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langchain_core.messages import AIMessage

#: Replacement args keyed by tool-call id.
ArgsReplacements = Mapping[str, dict[str, Any]]
#: ``(message, tool_call) -> new_args`` or ``None`` to leave the call alone.
ReplacementSelector = Callable[[AIMessage, dict[str, Any]], dict[str, Any] | None]


def rewrite_messages_tool_call_args(messages: list[Any], replacement_for: ReplacementSelector) -> list[Any] | None:
    """Apply ``replacement_for(message, tool_call)`` to every AIMessage tool call in ``messages``.

    Returns a new list with the rewritten AIMessages, or ``None`` when no call
    was replaced. Untouched messages pass through by identity, except that once
    anything was rewritten every AIMessage loses its ``resp_`` response id (see
    the module docstring: the server-side history behind that id still holds
    the original arguments). Only calls with a non-empty string id are offered
    to the selector, since nothing else can be matched across surfaces.
    """
    updated: list[Any] = []
    changed = False
    for message in messages:
        patched = message
        if isinstance(message, AIMessage) and message.tool_calls:
            replacements: dict[str, dict[str, Any]] = {}
            for tool_call in message.tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                call_id = tool_call.get("id")
                if not isinstance(call_id, str) or not call_id:
                    continue
                new_args = replacement_for(message, tool_call)
                if new_args is not None:
                    replacements[call_id] = new_args
            if replacements:
                patched = rewrite_tool_call_args(message, replacements)
        if patched is not message:
            changed = True
        updated.append(patched)
    if not changed:
        return None
    return [_without_response_chain_id(message) for message in updated]


def _without_response_chain_id(message: Any) -> Any:
    """Drop an OpenAI ``resp_`` response id so the adapter replays history instead of chaining to it."""
    if not isinstance(message, AIMessage):
        return message
    response_metadata = message.response_metadata or {}
    response_id = response_metadata.get("id")
    if not (isinstance(response_id, str) and response_id.startswith("resp_")):
        return message
    return message.model_copy(update={"response_metadata": {key: value for key, value in response_metadata.items() if key != "id"}})


def rewrite_tool_call_args(message: AIMessage, replacements: ArgsReplacements) -> AIMessage:
    """Return ``message`` with the args of every tool call in ``replacements`` (by id) rewritten on all surfaces.

    ``message`` is never mutated; the same object comes back when no id matches.
    """
    if not replacements:
        return message
    update: dict[str, Any] = {}

    tool_calls = message.tool_calls or []
    rewritten_calls = [dict(tool_call, args=new_args) if isinstance(tool_call, dict) and (new_args := _replacement_for_id(tool_call.get("id"), replacements)) is not None else tool_call for tool_call in tool_calls]
    if _any_replaced(rewritten_calls, tool_calls):
        update["tool_calls"] = rewritten_calls

    tool_call_chunks = getattr(message, "tool_call_chunks", None)
    if isinstance(tool_call_chunks, list):
        rewritten_chunks = [dict(chunk, args=_serialize(new_args)) if isinstance(chunk, dict) and (new_args := _replacement_for_id(chunk.get("id"), replacements)) is not None else chunk for chunk in tool_call_chunks]
        if _any_replaced(rewritten_chunks, tool_call_chunks):
            update["tool_call_chunks"] = rewritten_chunks

    additional_kwargs = message.additional_kwargs or {}
    raw_tool_calls = additional_kwargs.get("tool_calls")
    if isinstance(raw_tool_calls, list):
        rewritten_raw = [_rewrite_raw_tool_call(entry, replacements) for entry in raw_tool_calls]
        if _any_replaced(rewritten_raw, raw_tool_calls):
            update["additional_kwargs"] = {**additional_kwargs, "tool_calls": rewritten_raw}

    if isinstance(message.content, list):
        rewritten_content = [_rewrite_content_block(block, replacements) for block in message.content]
        if _any_replaced(rewritten_content, message.content):
            update["content"] = rewritten_content

    return message.model_copy(update=update) if update else message


def _replacement_for_id(identifier: Any, replacements: ArgsReplacements) -> dict[str, Any] | None:
    """Non-string ids (malformed provider payloads) never match, and never raise from a membership probe."""
    return replacements.get(identifier) if isinstance(identifier, str) else None


def _any_replaced(rewritten: Sequence[Any], original: Sequence[Any]) -> bool:
    return any(new is not old for new, old in zip(rewritten, original, strict=True))


def _serialize(args: dict[str, Any]) -> str:
    return json.dumps(args, ensure_ascii=False)


def _rewrite_raw_tool_call(entry: Any, replacements: ArgsReplacements) -> Any:
    """Rewrite one raw provider tool-call payload (OpenAI ``function.arguments`` JSON string, or flattened variants)."""
    if not isinstance(entry, dict):
        return entry
    new_args = _replacement_for_id(entry.get("id"), replacements)
    if new_args is None:
        return entry
    function = entry.get("function")
    if isinstance(function, dict):
        return {**entry, "function": {**function, "arguments": _serialize(new_args)}}
    if isinstance(entry.get("arguments"), str):
        return {**entry, "arguments": _serialize(new_args)}
    if isinstance(entry.get("args"), dict):
        return {**entry, "args": new_args}
    return entry


def _rewrite_content_block(block: Any, replacements: ArgsReplacements) -> Any:
    """Rewrite one content block that carries tool-call arguments; anything else passes through by identity."""
    if not isinstance(block, dict):
        return block
    block_type = block.get("type")
    if block_type == "tool_use":
        # Anthropic: ``partial_json`` is dropped so it cannot leak the old payload.
        new_args = _replacement_for_id(block.get("id"), replacements)
        if new_args is None:
            return block
        rewritten = {key: value for key, value in block.items() if key != "partial_json"}
        rewritten["input"] = new_args
        return rewritten
    if block_type == "function_call":
        # OpenAI Responses (``responses/v1``): matched by ``call_id``; the ``fc_…`` item id and status are kept.
        new_args = _replacement_for_id(block.get("call_id"), replacements)
        if new_args is None:
            return block
        return {**block, "arguments": _serialize(new_args)}
    if block_type in ("tool_call", "tool_call_chunk"):
        # LangChain standard content (``v1``): ``args`` is a dict on tool_call and a JSON string on
        # tool_call_chunk; ``extras.arguments`` (raw provider string) wins in the Responses translator.
        new_args = _replacement_for_id(block.get("id"), replacements)
        if new_args is None:
            return block
        rewritten = {**block, "args": new_args if block_type == "tool_call" else _serialize(new_args)}
        extras = block.get("extras")
        if isinstance(extras, dict) and "arguments" in extras:
            rewritten["extras"] = {**extras, "arguments": _serialize(new_args)}
        return rewritten
    return block
