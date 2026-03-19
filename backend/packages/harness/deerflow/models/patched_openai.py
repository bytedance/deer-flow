"""Patched ChatOpenAI that preserves thought_signature for Gemini thinking models.

When using Gemini with thinking enabled via an OpenAI-compatible gateway (e.g.
Vertex AI, Google AI Studio, or any proxy), the API requires that the
``thought_signature`` field present on thinking content blocks in the model's
response is echoed back verbatim in every subsequent request that includes those
assistant messages.

Standard ``langchain_openai.ChatOpenAI`` does not know about this Gemini-specific
field and silently drops it when serialising messages for the next API call.
That causes an HTTP 400 ``INVALID_ARGUMENT`` error:

    Unable to submit request because function call `<tool>` in the N. content
    block is missing a `thought_signature`.

This module fixes the problem by overriding ``_get_request_payload`` to
re-inject thinking blocks (with their ``thought_signature``) back into the
outgoing payload for any assistant message that originally carried them.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI


class PatchedChatOpenAI(ChatOpenAI):
    """ChatOpenAI with ``thought_signature`` preservation for Gemini thinking via OpenAI gateway.

    When using Gemini with thinking enabled via an OpenAI-compatible gateway,
    the API expects ``thought_signature`` to be present on thinking content
    blocks in multi-turn conversations.  This patched version ensures those
    blocks are restored in the request payload from wherever LangChain stored
    them on the ``AIMessage``.

    Usage in ``config.yaml``::

        - name: gemini-2.5-pro-thinking
          display_name: Gemini 2.5 Pro (Thinking)
          use: deerflow.models.patched_openai:PatchedChatOpenAI
          model: google/gemini-2.5-pro-preview
          api_key: $GEMINI_API_KEY
          base_url: https://<your-openai-compat-gateway>/v1
          max_tokens: 16384
          supports_thinking: true
          supports_vision: true
          when_thinking_enabled:
            extra_body:
              thinking:
                type: enabled
    """

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Get request payload with ``thought_signature`` preserved in thinking blocks.

        Overrides the parent method to re-inject thinking content blocks (and
        their ``thought_signature``) from the original ``AIMessage`` objects
        into the serialised payload that will be sent to the API.
        """
        # Capture the original LangChain messages *before* conversion so we can
        # access fields that the serialiser might drop.
        original_messages = self._convert_input(input_).to_messages()

        # Obtain the base payload from the parent implementation.
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        payload_messages = payload.get("messages", [])

        if len(payload_messages) == len(original_messages):
            for payload_msg, orig_msg in zip(payload_messages, original_messages):
                if payload_msg.get("role") == "assistant" and isinstance(orig_msg, AIMessage):
                    _restore_thinking_blocks(payload_msg, orig_msg)
        else:
            # Fallback: match assistant-role entries positionally against AIMessages.
            ai_messages = [m for m in original_messages if isinstance(m, AIMessage)]
            assistant_payloads = [
                (i, m) for i, m in enumerate(payload_messages) if m.get("role") == "assistant"
            ]
            for (_, payload_msg), ai_msg in zip(assistant_payloads, ai_messages):
                _restore_thinking_blocks(payload_msg, ai_msg)

        return payload


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _restore_thinking_blocks(payload_msg: dict, orig_msg: AIMessage) -> None:
    """Re-inject thinking content blocks with ``thought_signature`` into *payload_msg*.

    LangChain may store the raw thinking blocks in two places depending on the
    provider library version:

    1. ``additional_kwargs["thinking_blocks"]`` – some gateway/version combos
       store the raw content-block list here.
    2. ``content`` as a ``list`` – newer LangChain versions preserve the full
       content-block list directly on the message.

    We check both locations, collect only blocks that carry a
    ``thought_signature`` (to avoid injecting spurious empty blocks), and
    prepend them to the serialised content so Gemini can validate the
    signature chain.
    """
    # --- 1. Try additional_kwargs["thinking_blocks"] first -----------------
    thinking_blocks: list[dict] = list(orig_msg.additional_kwargs.get("thinking_blocks") or [])

    # --- 2. Fall back to content list if no blocks found above --------------
    if not thinking_blocks and isinstance(orig_msg.content, list):
        thinking_blocks = [
            block
            for block in orig_msg.content
            if isinstance(block, dict) and block.get("type") == "thinking"
        ]

    if not thinking_blocks:
        return

    # Only keep blocks that actually carry a thought_signature; blocks without
    # one do not need special handling and injecting them could cause issues.
    signed_blocks = [b for b in thinking_blocks if b.get("thought_signature")]
    if not signed_blocks:
        return

    # --- Merge signed blocks into the payload content ----------------------
    existing_content = payload_msg.get("content")

    if isinstance(existing_content, list):
        # Remove any stale (unsigned) thinking blocks already in the list,
        # then prepend the correctly-signed ones.
        non_thinking = [b for b in existing_content if b.get("type") != "thinking"]
        payload_msg["content"] = signed_blocks + non_thinking
    elif isinstance(existing_content, str) and existing_content:
        # Content is a plain string; wrap it so we can prepend blocks.
        payload_msg["content"] = signed_blocks + [{"type": "text", "text": existing_content}]
    else:
        # Content is None / empty — just set the thinking blocks directly.
        payload_msg["content"] = signed_blocks
