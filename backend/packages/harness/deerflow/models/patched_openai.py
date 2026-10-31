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
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from deerflow.models.assistant_payload_replay import restore_assistant_payloads, restore_reasoning_content


class AssistantReplayMixin:
    """Re-inject gateway-issued assistant fields into an outgoing request payload.

    Mixed into OpenAI-compatible clients whose payload builder would otherwise drop
    fields the gateway itself issued on the previous turn (see the module docstring).
    Clients that keep langchain's stock builder receive it automatically from
    ``deerflow.models.factory``.
    """

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Return the request payload with replayable assistant fields preserved."""
        # Capture the original LangChain messages *before* conversion so we can
        # access fields that the serialiser might drop.
        original_messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        restore_assistant_payloads(payload.get("messages", []), original_messages, _restore_replayable_assistant_fields)
        return payload


class PatchedChatOpenAI(AssistantReplayMixin, ChatOpenAI):
    """ChatOpenAI with ``thought_signature`` preservation for Gemini thinking via OpenAI gateway.

    When using Gemini with thinking enabled via an OpenAI-compatible gateway,
    the API expects ``thought_signature`` to be present on tool-call objects in
    multi-turn conversations.  This patched version restores those signatures
    from ``AIMessage.additional_kwargs["tool_calls"]`` into the serialised
    request payload before it is sent to the API.

    See the Gemini example in ``config.example.yaml`` for Google's official
    OpenAI-compatible endpoint and its reasoning configuration.
    """


def _restore_replayable_assistant_fields(payload_msg: dict, orig_msg: AIMessage) -> None:
    """Restore every provider-issued assistant field the stock serialiser drops.

    Gemini gateways require the tool-call ``thought_signature`` back (issue #1180);
    DeepSeek-style reasoning gateways reject a replayed assistant tool call whose
    ``reasoning_content`` is missing, which is the failure reported in issue #1790 for
    Kimi/Qwen-style gateways behind ``PatchedChatOpenAI``. Both fields are echoed only when
    the message carries them, so a provider that never issued them gets nothing extra.
    """
    _restore_tool_call_signatures(payload_msg, orig_msg)
    restore_reasoning_content(payload_msg, orig_msg)


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
