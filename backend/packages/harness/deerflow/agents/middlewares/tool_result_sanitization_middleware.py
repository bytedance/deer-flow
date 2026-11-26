"""Neutralize prompt-injection control tokens in untrusted tool results.

DeerFlow already treats the genuine user message as untrusted and neutralizes
framework/injection tags in it (see ``InputSanitizationMiddleware``). Remote
content that the agent *fetches* — web page bodies and search snippets returned
by ``web_fetch`` / ``web_search`` / ``image_search``, plus the target site's
response-status text surfaced by ``web_capture`` — is equally untrusted, yet
it entered the model context verbatim. A page the attacker controls could embed
a forged ``<system-reminder>`` block (or a ``--- END USER INPUT ---`` marker) and
have it reach the model as authoritative framework context.

This middleware narrows that gap by applying the *same* structural
neutralization (``neutralize_untrusted_tags``) to the results of the first-party
network tools, so a fetched ``<system-reminder>`` is escaped to
``&lt;system-reminder&gt;`` exactly like it would be in direct user input. It
deliberately targets only the remote-content tools: local tool output (bash,
file reads) is left untouched so legitimate code/log content is never mangled.

Scope: the built-in network tools are matched by name
(``_REMOTE_CONTENT_TOOL_NAMES``), and MCP-sourced tools are matched by their
``deerflow_mcp`` metadata tag (third-party remote code, untrusted by default).
Local tool output (bash, file reads) is left untouched so legitimate code/log
content is never mangled.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace as dc_replace
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.tool_transform_meta import append_tool_transform
from deerflow.tools.mcp_metadata import is_mcp_tool

logger = logging.getLogger(__name__)

# Tool names whose results are attacker-influenceable remote content. The
# first-party search/fetch providers all normalize to ``web_fetch`` /
# ``web_search`` / ``image_search`` (see community/*/tools.py), so the set stays
# provider-agnostic. ``web_capture`` (Browserless screenshot) additionally
# surfaces the target site's response-status text (``X-Response-Status``, a
# free-form reason phrase controlled by whatever server is being captured) into
# its result message, so it is untrusted remote content too and belongs here.
# The gate is name-based for the first-party web tools; MCP-sourced tools are
# covered by their ``deerflow_mcp`` metadata tag instead (every MCP server is
# third-party remote code, so its results are untrusted regardless of what the
# tool is named). A name heuristic for MCP tools (matching fetch/search/crawl
# substrings) is intentionally avoided because it would also mangle legitimate
# *local* tool output (e.g. a ``file_search`` result).
_REMOTE_CONTENT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "web_fetch",
        "web_search",
        "image_search",
        "web_capture",
    }
)


def _has_untrusted_json_text(
    value: object,
    neutralize: Callable[[str], str],
    seen: set[int],
) -> bool:
    """Return whether *value* contains any string key or value that *neutralize* rewrites."""
    if isinstance(value, str):
        return neutralize(value) != value
    if isinstance(value, (list, tuple)):
        obj_id = id(value)
        if obj_id in seen:
            return False
        seen.add(obj_id)
        return any(_has_untrusted_json_text(item, neutralize, seen) for item in value)
    if isinstance(value, dict):
        obj_id = id(value)
        if obj_id in seen:
            return False
        seen.add(obj_id)
        return any((isinstance(key, str) and neutralize(key) != key) or _has_untrusted_json_text(item, neutralize, seen) for key, item in value.items())
    return False


def _disambiguate_sanitized_key(base_key: object, used_keys: set[object]) -> str:
    """Return a unique string key derived from *base_key* not present in *used_keys*."""
    suffix = 2
    candidate = f"{base_key} ({suffix})"
    while candidate in used_keys:
        suffix += 1
        candidate = f"{base_key} ({suffix})"
    return candidate


def _clone_neutralized_json(
    value: object,
    neutralize: Callable[[str], str],
    memo: dict[int, object],
) -> object:
    """Clone a structured JSON-like payload with every string key and value neutralized."""
    if isinstance(value, str):
        return neutralize(value)
    if isinstance(value, list):
        obj_id = id(value)
        if obj_id in memo:
            return memo[obj_id]
        rebuilt_list: list[object] = []
        memo[obj_id] = rebuilt_list
        for item in value:
            rebuilt_list.append(_clone_neutralized_json(item, neutralize, memo))
        return rebuilt_list
    if isinstance(value, tuple):
        obj_id = id(value)
        if obj_id in memo:
            return memo[obj_id]
        # A tuple can self-reference only through a mutable descendant; a placeholder
        # list breaks that cycle without leaking unsanitized references.
        placeholder: list[object] = []
        memo[obj_id] = placeholder
        items = [_clone_neutralized_json(item, neutralize, memo) for item in value]
        placeholder.extend(items)
        rebuilt_tuple = tuple(items)
        memo[obj_id] = rebuilt_tuple
        return rebuilt_tuple
    if isinstance(value, dict):
        obj_id = id(value)
        if obj_id in memo:
            return memo[obj_id]
        rebuilt_dict: dict[object, object] = {}
        memo[obj_id] = rebuilt_dict
        # Reserve unchanged keys first so a rewritten key colliding with an
        # existing clean key never displaces or silently overwrites it.
        reserved_keys: set[object] = set()
        transformed_entries: list[tuple[object, object, object]] = []
        for key, item in value.items():
            new_key = neutralize(key) if isinstance(key, str) else key
            if new_key == key:
                reserved_keys.add(key)
            transformed_entries.append((key, new_key, _clone_neutralized_json(item, neutralize, memo)))

        used_keys: set[object] = set(reserved_keys)
        for key, new_key, sanitized_item in transformed_entries:
            if new_key == key:
                final_key = key
            elif new_key not in used_keys:
                final_key = new_key
                used_keys.add(final_key)
            else:
                final_key = _disambiguate_sanitized_key(new_key, used_keys)
                used_keys.add(final_key)
            rebuilt_dict[final_key] = sanitized_item
        return rebuilt_dict
    return value


def _neutralize_json_value(
    value: object,
    neutralize: Callable[[str], str],
) -> tuple[object, bool]:
    """Neutralize string keys and values in a structured JSON payload without mutating it."""
    if not _has_untrusted_json_text(value, neutralize, set()):
        return value, False
    return _clone_neutralized_json(value, neutralize, {}), True


def _neutralize_content_checked(content: object) -> tuple[object, bool]:
    """Return ``(neutralized_content, changed)`` while preserving content shape.

    Handles the shapes a ToolMessage content can take:

    * plain ``str`` (what every built-in web tool returns today);
    * a list of content blocks — bare ``str`` elements, any dict block carrying
      a string ``"text"`` field (matching ``ToolOutputBudgetMiddleware`` and
      ``PiiRedactionMiddleware``), and structured ``"json"`` payloads (all
      nested string keys and values recursively neutralized without mutating
      the input). Media and other non-text blocks pass through untouched.
    """
    # Imported lazily so this module can be loaded even when a test stubs the
    # input-sanitization module, and to mirror the codebase's deferred-import style.
    from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags

    if isinstance(content, str):
        neutralized = neutralize_untrusted_tags(content)
        return neutralized, neutralized != content
    if isinstance(content, list):
        rebuilt: list[object] = []
        changed = False
        for block in content:
            if isinstance(block, str):
                neutralized = neutralize_untrusted_tags(block)
                changed = changed or neutralized != block
                rebuilt.append(neutralized)
            elif isinstance(block, dict):
                updated_block = block
                block_changed = False
                if isinstance(block.get("text"), str):
                    neutralized_text = neutralize_untrusted_tags(block["text"])
                    if neutralized_text != block["text"]:
                        updated_block = {**updated_block, "text": neutralized_text}
                        block_changed = True
                if "json" in block:
                    neutralized_json, json_changed = _neutralize_json_value(block["json"], neutralize_untrusted_tags)
                    if json_changed:
                        updated_block = {**updated_block, "json": neutralized_json}
                        block_changed = True
                changed = changed or block_changed
                rebuilt.append(updated_block)
            else:
                rebuilt.append(block)
        return (rebuilt, True) if changed else (content, False)
    return content, False


def _neutralize_content(content: object) -> object:
    """Return *content* with untrusted tags neutralized, preserving its shape."""
    return _neutralize_content_checked(content)[0]


def _sanitize_tool_message(message: ToolMessage) -> ToolMessage:
    """Return a copy of *message* with its content neutralized, or the original."""
    new_content, changed = _neutralize_content_checked(message.content)
    if not changed:
        return message
    new_kwargs = dict(message.additional_kwargs or {})
    append_tool_transform(new_kwargs, "sanitized", by="ToolResultSanitizationMiddleware")
    return message.model_copy(update={"content": new_content, "additional_kwargs": new_kwargs})


def _sanitize_result(result: ToolMessage | Command) -> ToolMessage | Command:
    """Neutralize a tool-call result (``ToolMessage`` or ``Command``)."""
    if isinstance(result, ToolMessage):
        return _sanitize_tool_message(result)
    update = getattr(result, "update", None)
    if isinstance(update, dict):
        messages = update.get("messages")
        if isinstance(messages, list) and any(isinstance(m, ToolMessage) for m in messages):
            new_messages = [_sanitize_tool_message(m) if isinstance(m, ToolMessage) else m for m in messages]
            if any(new is not old for new, old in zip(new_messages, messages, strict=True)):
                return dc_replace(result, update={**update, "messages": new_messages})
    return result


class ToolResultSanitizationMiddleware(AgentMiddleware[AgentState]):
    """Escape injection/framework tags in remote tool results before the model sees them.

    Results of the first-party network tools (``web_fetch`` / ``web_search`` /
    ``image_search`` / ``web_capture``) are rewritten; every other tool's output
    is returned unchanged. Mirrors the user-input guardrail so untrusted remote
    content and untrusted user input receive the same structural neutralization.

    Scope: the built-in web tools are covered by name (``_REMOTE_CONTENT_TOOL_NAMES``),
    and every MCP-sourced tool is covered via its ``deerflow_mcp`` metadata tag —
    an MCP server is third-party remote code, so its results are untrusted by
    default. Neutralization only touches structural control tokens, so benign MCP
    content passes through unchanged.
    """

    def _should_sanitize(self, request: ToolCallRequest) -> bool:
        if request.tool_call.get("name") in _REMOTE_CONTENT_TOOL_NAMES:
            return True
        return is_mcp_tool(getattr(request, "tool", None))

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        result = handler(request)
        if not self._should_sanitize(request):
            return result
        return _sanitize_result(result)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        result = await handler(request)
        if not self._should_sanitize(request):
            return result
        return _sanitize_result(result)
