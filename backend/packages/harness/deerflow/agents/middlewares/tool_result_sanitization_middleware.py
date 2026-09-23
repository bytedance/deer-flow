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


def _neutralize_content(content: object) -> object:
    """Return *content* with untrusted tags neutralized, preserving its shape.

    Handles the two shapes a ToolMessage content can take:

    * plain ``str`` (what every web tool returns today);
    * a list of content blocks — bare ``str`` elements and
      ``{"type": "text", "text": ...}`` text blocks are rewritten; non-text
      blocks (images, etc.) pass through untouched. The bare-``str`` case
      mirrors ``ToolOutputBudgetMiddleware._message_text``, which already
      anticipates ``str`` items inside a content list.
    """
    # Imported lazily so this module can be loaded even when a test stubs the
    # input-sanitization module, and to mirror the codebase's deferred-import style.
    from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags

    if isinstance(content, str):
        return neutralize_untrusted_tags(content)
    if isinstance(content, list):
        rebuilt: list[object] = []
        for block in content:
            if isinstance(block, str):
                rebuilt.append(neutralize_untrusted_tags(block))
            elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                rebuilt.append({**block, "text": neutralize_untrusted_tags(block["text"])})
            else:
                rebuilt.append(block)
        return rebuilt
    return content


def _sanitize_tool_message(message: ToolMessage) -> ToolMessage:
    """Return a copy of *message* with its content neutralized, or the original."""
    new_content = _neutralize_content(message.content)
    if new_content == message.content:
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
            if new_messages != messages:
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
