"""Patched ChatOpenAI that preserves thought_signature for Gemini thinking models.

When using Gemini with thinking enabled via an OpenAI-compatible gateway (e.g.
Vertex AI, Google AI Studio, or any proxy), the API requires that the
``thought_signature`` field on tool-call objects is echoed back verbatim in
every subsequent request.

The OpenAI-compatible gateway stores the raw tool-call dicts (including
``thought_signature``) in ``additional_kwargs["tool_calls"]``, but standard
``langchain_openai.ChatOpenAI`` only serialises the standard fields (``id``,
``type``, ``function``) into the outgoing payload, silently dropping the
signature.  That causes an HTTP 400 ``INVALID_ARGUMENT`` error:

    Unable to submit request because function call `<tool>` in the N. content
    block is missing a `thought_signature`.

This module fixes the problem by overriding ``_get_request_payload`` to
re-inject tool-call signatures back into the outgoing payload for any assistant
message that originally carried them.

Fix for issue #1515
-------------------
Google's **official** OpenAI-compatible endpoint
(``https://generativelanguage.googleapis.com/v1beta/openai/``) does **not**
accept a ``thinking`` key inside ``extra_body`` — submitting one produces:

    openai.BadRequestError: 400 Invalid JSON payload received.
    Unknown name "thinking": Cannot find field.

The ``thinking`` parameter only applies to the native Gemini SDK path; on the
OpenAI-compat path the model's reasoning behaviour is selected implicitly by
model name (e.g. ``gemini-3.1-pro-preview``).  This class therefore strips
``extra_body.thinking`` from every outgoing request so that users can keep a
single config entry with ``supports_thinking: true`` and
``when_thinking_enabled.extra_body.thinking`` without triggering the 400.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# ``extra_body`` keys to remove when building requests for the Google
# OpenAI-compatible Gemini path. Sending any of these causes HTTP 400
# INVALID_ARGUMENT there, but this constant itself carries no endpoint context.
_GEMINI_OPENAI_COMPAT_UNSUPPORTED_EXTRA_BODY_KEYS: frozenset[str] = frozenset({"thinking"})


class PatchedChatOpenAI(ChatOpenAI):
    """ChatOpenAI with ``thought_signature`` preservation for Gemini thinking via OpenAI gateway.

    When using Gemini with thinking enabled via an OpenAI-compatible gateway,
    the API expects ``thought_signature`` to be present on tool-call objects in
    multi-turn conversations.  This patched version restores those signatures
    from ``AIMessage.additional_kwargs["tool_calls"]`` into the serialised
    request payload before it is sent to the API.

    It also strips ``extra_body`` keys that are unsupported by Google's official
    OpenAI-compatible endpoint (``generativelanguage.googleapis.com/v1beta/openai/``),
    most notably the ``thinking`` field that only applies to the native Gemini SDK
    path.  See issue #1515 for details.

    Usage in ``config.yaml``::

        - name: gemini-3.1-pro-thinking
          display_name: Gemini 3.1 Pro (Thinking)
          use: deerflow.models.patched_openai:PatchedChatOpenAI
          model: gemini-3.1-pro-preview
          api_key: $GEMINI_API_KEY
          base_url: https://generativelanguage.googleapis.com/v1beta/openai/
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
        """Get request payload with ``thought_signature`` preserved and unsupported
        ``extra_body`` keys stripped.

        Overrides the parent method to:

        1. Strip ``extra_body`` keys that are not accepted by the Google
           OpenAI-compatible endpoint (e.g. ``thinking``).  Sending these
           causes HTTP 400 "Unknown name" errors (issue #1515).
        2. Re-inject ``thought_signature`` fields on tool-call objects that
           were stored in ``additional_kwargs["tool_calls"]`` by LangChain
           but dropped during serialisation.
        """
        # Capture the original LangChain messages *before* conversion so we can
        # access fields that the serialiser might drop.
        original_messages = self._convert_input(input_).to_messages()

        # Obtain the base payload from the parent implementation.
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        # --- Fix #1515: strip unsupported extra_body keys ---
        payload = _strip_unsupported_extra_body(payload)

        # --- Fix thought_signature preservation ---
        payload_messages = payload.get("messages", [])

        if len(payload_messages) == len(original_messages):
            for payload_msg, orig_msg in zip(payload_messages, original_messages):
                if payload_msg.get("role") == "assistant" and isinstance(orig_msg, AIMessage):
                    _restore_tool_call_signatures(payload_msg, orig_msg)
        else:
            # Fallback: match assistant-role entries positionally against AIMessages.
            ai_messages = [m for m in original_messages if isinstance(m, AIMessage)]
            assistant_payloads = [(i, m) for i, m in enumerate(payload_messages) if m.get("role") == "assistant"]
            for (_, payload_msg), ai_msg in zip(assistant_payloads, ai_messages):
                _restore_tool_call_signatures(payload_msg, ai_msg)

        return payload


def _strip_unsupported_extra_body(payload: dict) -> dict:
    """Remove module-defined unsupported keys from ``payload["extra_body"]``.

    This helper strips any keys listed in
    ``_GEMINI_OPENAI_COMPAT_UNSUPPORTED_EXTRA_BODY_KEYS`` whenever they appear
    in ``extra_body``. It does not determine which endpoint is being targeted;
    any endpoint-specific decision about whether this cleanup is appropriate
    must be made by the caller. This keeps the helper's behaviour aligned with
    its implementation while still avoiding HTTP 400 errors for Gemini
    OpenAI-compatible requests (issue #1515).

    The ``payload`` dict is never mutated in-place; a new dict is returned only
    when a modification is needed.
    """
    extra_body = payload.get("extra_body")
    if not isinstance(extra_body, dict):
        return payload

    keys_to_remove = _GEMINI_OPENAI_COMPAT_UNSUPPORTED_EXTRA_BODY_KEYS & extra_body.keys()
    if not keys_to_remove:
        return payload

    logger.debug(
        "Stripping configured unsupported extra_body key(s): %s",
        sorted(keys_to_remove),
    )

    cleaned_extra_body = {k: v for k, v in extra_body.items() if k not in keys_to_remove}
    payload = dict(payload)
    if cleaned_extra_body:
        payload["extra_body"] = cleaned_extra_body
    else:
        del payload["extra_body"]
    return payload


def _restore_tool_call_signatures(payload_msg: dict, orig_msg: AIMessage) -> None:
    """Re-inject ``thought_signature`` onto tool-call objects in *payload_msg*.

    When the Gemini OpenAI-compatible gateway returns a response with function
    calls, each tool-call object may carry a ``thought_signature``.  LangChain
    stores the raw tool-call dicts in ``additional_kwargs["tool_calls"]`` but
    only serialises the standard fields (``id``, ``type``, ``function``) into
    the outgoing payload, silently dropping the signature.

    This function matches raw tool-call entries (by ``id``, falling back to
    positional order) and copies the signature back onto the serialised
    payload entries.
    """
    raw_tool_calls: list[dict] = orig_msg.additional_kwargs.get("tool_calls") or []
    payload_tool_calls: list[dict] = payload_msg.get("tool_calls") or []

    if not raw_tool_calls or not payload_tool_calls:
        return

    # Build an id → raw_tc lookup for efficient matching.
    raw_by_id: dict[str, dict] = {}
    for raw_tc in raw_tool_calls:
        tc_id = raw_tc.get("id")
        if tc_id:
            raw_by_id[tc_id] = raw_tc

    for idx, payload_tc in enumerate(payload_tool_calls):
        # Try matching by id first, then fall back to positional.
        raw_tc = raw_by_id.get(payload_tc.get("id", ""))
        if raw_tc is None and idx < len(raw_tool_calls):
            raw_tc = raw_tool_calls[idx]

        if raw_tc is None:
            continue

        # The gateway may use either snake_case or camelCase.
        sig = raw_tc.get("thought_signature") or raw_tc.get("thoughtSignature")
        if sig:
            payload_tc["thought_signature"] = sig
