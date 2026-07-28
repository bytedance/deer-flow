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

Scope note: matching is a name-based allowlist, so MCP-provided remote-content
tools registered under other names are not yet covered — see
``_REMOTE_CONTENT_TOOL_NAMES``.
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

logger = logging.getLogger(__name__)

# Tool names whose results are attacker-influenceable remote content. The
# first-party search/fetch providers all normalize to ``web_fetch`` /
# ``web_search`` / ``image_search`` (see community/*/tools.py), so the set stays
# provider-agnostic. ``web_capture`` (Browserless screenshot) additionally
# surfaces the target site's response-status text (``X-Response-Status``, a
# free-form reason phrase controlled by whatever server is being captured) into
# its result message, so it is untrusted remote content too and belongs here.
#
# Known limitation: the gate is name-based. An MCP server may expose a
# remote-content tool under an arbitrary name (e.g. ``fetch_url`` /
# ``scrape_page``); its results are equally untrusted but are NOT matched here,
# so they reach the model unneutralized. A name heuristic (matching
# fetch/search/crawl substrings) is intentionally avoided because it would also
# mangle legitimate *local* tool output (e.g. a ``file_search`` result). Robust
# MCP coverage should tag remote-content tools via metadata at registration
# rather than by name; tracked as a follow-up.
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
    return message.model_copy(update={"content": new_content})


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

    Scope is a name-based allowlist (``_REMOTE_CONTENT_TOOL_NAMES``): it reliably
    covers the built-in web tools without false positives on local tools. It does
    NOT cover MCP-provided remote-content tools registered under other names —
    see the note on ``_REMOTE_CONTENT_TOOL_NAMES`` for why a name heuristic is
    avoided and the metadata-tagging follow-up.
    """

    def _should_sanitize(self, request: ToolCallRequest) -> bool:
        return request.tool_call.get("name") in _REMOTE_CONTENT_TOOL_NAMES

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
