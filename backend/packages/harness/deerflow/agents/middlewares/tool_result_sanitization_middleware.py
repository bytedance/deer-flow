"""Neutralize prompt-injection control tokens in untrusted tool results.

DeerFlow already treats the genuine user message as untrusted and neutralizes
framework/injection tags in it (see ``InputSanitizationMiddleware``). Remote
content that the agent *fetches* — web page bodies and search snippets returned
by ``web_fetch`` / ``web_search`` / ``image_search`` — is equally untrusted, yet
it entered the model context verbatim. A page the attacker controls could embed
a forged ``<system-reminder>`` block (or a ``--- END USER INPUT ---`` marker) and
have it reach the model as authoritative framework context.

This middleware closes that gap by applying the *same* structural neutralization
(``neutralize_untrusted_tags``) to the results of network-sourced tools, so a
fetched ``<system-reminder>`` is escaped to ``&lt;system-reminder&gt;`` exactly
like it would be in direct user input. It deliberately targets only the
remote-content tools: local tool output (bash, file reads) is left untouched so
legitimate code/log content is never mangled.
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

from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags

logger = logging.getLogger(__name__)

# Tool names whose results are attacker-influenceable remote content. All web
# providers normalize to these three names (see community/*/tools.py), so the
# set stays provider-agnostic.
_REMOTE_CONTENT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "web_fetch",
        "web_search",
        "image_search",
    }
)


def _neutralize_content(content: object) -> object:
    """Return *content* with untrusted tags neutralized, preserving its shape.

    Handles the two shapes a ToolMessage content can take:

    * plain ``str`` (what every web tool returns today);
    * a list of content blocks — only ``{"type": "text", "text": ...}`` blocks
      are rewritten; non-text blocks (images, etc.) pass through untouched.
    """
    if isinstance(content, str):
        return neutralize_untrusted_tags(content)
    if isinstance(content, list):
        rebuilt: list[object] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
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

    Only results of network-sourced tools (``web_fetch`` / ``web_search`` /
    ``image_search``) are rewritten; every other tool's output is returned
    unchanged. Mirrors the user-input guardrail so untrusted remote content and
    untrusted user input receive the same structural neutralization.
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
