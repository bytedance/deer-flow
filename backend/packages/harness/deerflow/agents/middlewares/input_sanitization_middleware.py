"""Input guardrail middleware for prompt-injection defense (issue #3630).

Escapes blocked XML-like tags in the last genuine user message (e.g.
``<system>`` → ``&lt;system&gt;``) so they render as literal text instead
of structured-context markers.  This preserves the user's intent ("how do
I use DeerFlow's <think> tag?") while neutralizing injection attempts —
the same de-identify-don't-reject strategy as AWS Bedrock's PII ANONYMIZE.

Blocked: system-reserved tags (memory, analysis, etc.) + common injection
tags (system, instruction, role, etc.). Normal HTML/XML tags (<div>,
<span>) are NOT escaped.

Clean input is wrapped in plain-text boundary markers as a secondary
semantic defense (OWASP structured-prompt guidance).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelCallResult,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphBubbleUp

from deerflow.agents.human_input import read_human_input_response
from deerflow.utils.input_sanitization import (
    _USER_INPUT_BEGIN,
    _USER_INPUT_END,
    neutralize_untrusted_tags,
)
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY, message_content_to_text

logger = logging.getLogger(__name__)

_SUMMARY_MESSAGE_NAME = "summary"


def _is_genuine_user_message(message: object) -> bool:
    """Return True for real user messages, excluding system-injected HumanMessages.

    ``hide_from_ui`` is also used by hidden UI replies from HumanInputCard, so
    only skip hidden HumanMessages that do not carry a valid user response.
    """
    if not isinstance(message, HumanMessage):
        return False
    if message.name == _SUMMARY_MESSAGE_NAME:
        return False
    if message.additional_kwargs.get("hide_from_ui") and read_human_input_response(message.additional_kwargs) is None:
        return False
    return True


def _check_user_content(text: str) -> str:
    """Sanitize user content: escape blocked tags, then wrap in boundary markers.

    * Empty/whitespace-only → return unchanged (no marker noise).
    * Blocked tags → HTML-escape ``<``/``>`` (e.g. ``<system>`` → ``&lt;system&gt;``).
    * Boundary tokens in user text → neutralized so they cannot forge boundaries.
    * Already wrapped (strict prefix+suffix) → return text unchanged (idempotent).
    * Otherwise → wrap in boundary markers.
    """
    if not text.strip():
        return text
    # Idempotency: only skip if text is *exactly* wrapped (prefix+suffix),
    # not if the user merely typed the begin token somewhere.
    if text.startswith(_USER_INPUT_BEGIN) and text.endswith(_USER_INPUT_END):
        # Still neutralize boundary tokens in the inner content — a user
        # can forge the outer wrapping to bypass the neutralization below
        # and inject inner boundary markers (break-out attack).
        inner = text[len(_USER_INPUT_BEGIN) : -len(_USER_INPUT_END)]
        neutralized_inner = neutralize_untrusted_tags(inner)
        if neutralized_inner == inner:
            return text
        return f"{_USER_INPUT_BEGIN}{neutralized_inner}{_USER_INPUT_END}"
    # Neutralize any boundary tokens the user may have embedded, preventing
    # both self-suppression (begin token skips wrapping) and break-out
    # (end token creates a premature boundary inside the payload).
    text = neutralize_untrusted_tags(text)
    return f"{_USER_INPUT_BEGIN}\n{text}\n{_USER_INPUT_END}"


class InputSanitizationMiddleware(AgentMiddleware[AgentState]):
    """Guardrail middleware that escapes prompt-injection tags in user input.

    Blocked tags are HTML-escaped (not rejected) so the user's intent is
    preserved while the tags lose their semantic significance. Clean input
    is wrapped in plain-text boundary markers. Transformation is temporary
    (wrap_model_call) — never written to state.
    """

    @staticmethod
    def _extract_text_from_content(content: str | list) -> tuple[str, list | None]:
        """Extract concatenated text from a plain-string or content-block-list.

        Returns ``(text, extracted_blocks)``. *extracted_blocks* is None when
        *content* is a string, or the list of text-content blocks when a list.

        A list can hold bare ``str`` items next to content-block dicts
        (``message_content_to_text`` treats both as text, and some IM/SDK
        clients send exactly that shape), so bare strings are collected too —
        skipping them would skip sanitization entirely for that message.
        """
        if isinstance(content, str):
            return content, None
        if not isinstance(content, list):
            return "", None
        text_parts: list[str] = []
        text_blocks: list[dict | str] = []
        for block in content:
            if isinstance(block, str):
                if not block:  # skip empty items — matches message_content_to_text behaviour
                    continue
                text_parts.append(block)
                text_blocks.append(block)
            elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                text = block["text"]
                if not text:  # skip empty blocks — matches message_content_to_text behaviour
                    continue
                text_parts.append(text)
                text_blocks.append(block)
        return "\n".join(text_parts), text_blocks

    @staticmethod
    def _rebuild_content(
        original_content: list,
        processed_text: str,
        text_blocks: list,
    ) -> list:
        """Replace text blocks with a single merged text block, preserving interleaved non-text blocks.

        For ``[text, image, text]`` the image block between the two text blocks
        is kept in place — only the text blocks are collapsed into one.
        """
        text_block_ids = {id(b) for b in text_blocks}
        first = last = None
        for i, block in enumerate(original_content):
            if id(block) in text_block_ids:
                if first is None:
                    first = i
                last = i
        if first is None:
            return original_content
        result: list = [*original_content[:first], {"type": "text", "text": processed_text}]
        # Re-insert any non-text blocks that sat between text blocks
        for i in range(first + 1, last + 1):
            if id(original_content[i]) not in text_block_ids:
                result.append(original_content[i])
        result.extend(original_content[last + 1 :])
        return result

    def _process_request(self, request: ModelRequest) -> ModelRequest:
        """Return a request with the last genuine user message sanitized.

        Blocked tags are HTML-escaped (not rejected) so the user's intent is
        preserved while the tags lose their semantic significance. Transformation
        is temporary — the original request is never mutated.
        """
        messages = list(request.messages)
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if not _is_genuine_user_message(msg):
                if isinstance(msg, HumanMessage):
                    logger.debug(
                        "_process_request: skipping non-genuine HumanMessage at pos=%d name=%s hide_from_ui=%s content_preview=%.80r",
                        i,
                        msg.name,
                        msg.additional_kwargs.get("hide_from_ui"),
                        msg.content,
                    )
                continue
            content = msg.content
            logger.debug("_process_request: found genuine user message at pos=%d content=%.120r", i, content)

            text_content, text_blocks = self._extract_text_from_content(content)

            # No text at all (e.g. image-only message) — pass through
            if not text_content and not isinstance(content, str):
                logger.debug("_process_request: no text content in message — passing through")
                return request

            # Sanitize only the user's original input when available (set by
            # UploadsMiddleware before it prepends the <current_uploads> block),
            # so server-injected trusted blocks are never scanned for blocked
            # tags.  Fall back to full-content scanning only when the marker is
            # absent — UploadsMiddleware sets it on upload turns, so plain text
            # messages without uploads won't have it.  Full-content scanning is
            # safe for those: no server-injected <current_uploads> block exists
            # to accidentally escape.
            preserved_kwargs = dict(msg.additional_kwargs or {})
            original_user_content = preserved_kwargs.get(ORIGINAL_USER_CONTENT_KEY)
            if isinstance(original_user_content, str) and original_user_content:
                processed_user = _check_user_content(original_user_content)
                if processed_user != original_user_content:
                    # Replace only the user's text suffix within the full
                    # content — server-prepended blocks stay untouched.
                    idx = text_content.rfind(original_user_content)
                    if idx >= 0:
                        processed = text_content[:idx] + processed_user
                    else:
                        # _extract_text_from_content and message_content_to_text
                        # disagreed on text extraction — rfind failed (only
                        # reachable for multimodal list content; see Decision 18).
                        if isinstance(content, list) and len(content) >= 2:
                            # content[0] is the server-injected
                            # <current_uploads> block (UploadsMiddleware
                            # prepends it as the first element for list
                            # content).  Sanitize only user blocks (content[1:])
                            # and rebuild directly — _rebuild_content only
                            # handles type:"text" blocks and would miss raw
                            # strings or non-standard dict blocks that
                            # message_content_to_text sees.
                            logger.warning(
                                "rfind failed on multimodal content; sanitizing user content blocks individually",
                            )
                            new_content: list = [content[0]]
                            for block in content[1:]:
                                if isinstance(block, str):
                                    new_content.append(neutralize_untrusted_tags(block))
                                elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                                    sanitized = neutralize_untrusted_tags(block["text"])
                                    if sanitized != block["text"]:
                                        new_content.append({**block, "text": sanitized})
                                    else:
                                        new_content.append(block)
                                else:
                                    new_content.append(block)
                            messages[i] = HumanMessage(
                                content=new_content,
                                id=msg.id,
                                name=msg.name,
                                additional_kwargs=preserved_kwargs,
                            )
                            return request.override(messages=messages)
                        else:
                            # Cannot distinguish server block from user blocks
                            # (non-list content or len(content) < 2).
                            # Degrade to full-content sanitization — server
                            # block may be escaped (UX degradation) but user
                            # forgeries are still neutralized (no security
                            # regression).
                            logger.warning(
                                "rfind failed with original_user_content set; cannot distinguish blocks, falling back to full-content sanitization",
                            )
                            processed = _check_user_content(text_content)
                else:
                    processed = text_content  # no change needed
            elif isinstance(original_user_content, str):
                # Key is present but empty string (e.g. file upload with no
                # text input).  No user text to sanitize; server-injected
                # blocks must survive untouched.
                processed = text_content
            else:
                processed = _check_user_content(text_content)  # fallback

            if processed == text_content:
                # Already clean / already wrapped — no override needed
                return request

            if text_blocks:
                new_content = self._rebuild_content(content, processed, text_blocks)
            else:
                new_content = processed

            # Preserve the pre-sanitization user text so downstream consumers that
            # must see the genuine input (slash skill activation, regenerate) can
            # recover it after the BEGIN/END wrapping. Keep a valid value set by
            # UploadsMiddleware or an IM channel, but repair malformed metadata so
            # persistence never falls back to the wrapped model-facing content.
            if not isinstance(original_user_content, str):
                if ORIGINAL_USER_CONTENT_KEY in preserved_kwargs:
                    logger.warning(
                        "InputSanitizationMiddleware replaced non-string %s metadata: type=%s",
                        ORIGINAL_USER_CONTENT_KEY,
                        type(original_user_content).__name__,
                    )
                preserved_kwargs[ORIGINAL_USER_CONTENT_KEY] = message_content_to_text(content)
            messages[i] = HumanMessage(
                content=new_content,
                id=msg.id,
                name=msg.name,
                additional_kwargs=preserved_kwargs,
            )
            logger.debug(
                "InputSanitizationMiddleware: original=%r -> processed=%r",
                content if isinstance(content, str) else "[content-blocks]",
                processed,
            )
            return request.override(messages=messages)
        return request

    def _try_process(self, request: ModelRequest) -> ModelRequest:
        """Sanitize request; fail-open on unexpected errors.

        GraphBubbleUp propagates; other exceptions return the original request.
        """
        try:
            return self._process_request(request)
        except GraphBubbleUp:
            raise
        except Exception:
            logger.warning(
                "Input guardrail processing failed; passing original request to model",
                exc_info=True,
            )
            return request

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._try_process(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._try_process(request))
