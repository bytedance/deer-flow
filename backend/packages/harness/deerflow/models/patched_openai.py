"""Patched ChatOpenAI that preserves thought_signature for Gemini thinking models.

When using Gemini with thinking enabled via an OpenAI-compatible gateway (e.g.
Vertex AI, Google AI Studio, or any proxy), the API requires that the
``thought_signature`` attached to tool-call objects is echoed back verbatim in
every subsequent request.

Google's official endpoint returns it as
``tool_calls[i].extra_content.google.thought_signature``; some gateways use a
top-level ``thought_signature`` (or ``thoughtSignature``) instead.
``langchain_openai.ChatOpenAI`` (1.x) keeps neither: it parses tool calls into
``AIMessage.tool_calls`` without storing the raw dicts, and only serialises the
standard fields (``id``, ``type``, ``function``) into the outgoing payload.
That causes an HTTP 400 ``INVALID_ARGUMENT`` error:

    Function call is missing a thought_signature in functionCall parts.

This module fixes the problem in two steps:

1. Capture: signed raw tool-call dicts from streaming deltas and non-streaming
   responses are stored in ``additional_kwargs["tool_calls"]``, the raw
   provider payload that the tool-call middlewares keep in sync with
   ``AIMessage.tool_calls``.
2. Replay: ``_get_request_payload`` re-injects the signatures into the outgoing
   payload for any assistant message that originally carried them.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

from deerflow.models.assistant_payload_replay import restore_assistant_payloads


class PatchedChatOpenAI(ChatOpenAI):
    """ChatOpenAI with ``thought_signature`` preservation for Gemini thinking via OpenAI gateway.

    When using Gemini with thinking enabled via an OpenAI-compatible gateway,
    the API expects ``thought_signature`` to be present on tool-call objects in
    multi-turn conversations.  This patched version captures signed raw tool
    calls into ``AIMessage.additional_kwargs["tool_calls"]`` and restores those
    signatures into the serialised request payload before it is sent to the API.

    See the Gemini example in ``config.example.yaml`` for Google's official
    OpenAI-compatible endpoint and its reasoning configuration.
    """

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Get request payload with ``thought_signature`` preserved on tool-call objects.

        Overrides the parent method to re-inject ``thought_signature`` fields
        on tool-call objects that were stored in
        ``additional_kwargs["tool_calls"]`` but dropped during serialisation.
        """
        # Capture the original LangChain messages *before* conversion so we can
        # access fields that the serialiser might drop.
        original_messages = self._convert_input(input_).to_messages()

        # Obtain the base payload from the parent implementation.
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        restore_assistant_payloads(payload.get("messages", []), original_messages, _restore_tool_call_signatures)

        return payload

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        """Capture signed raw tool calls from streaming deltas."""
        generation_chunk = super()._convert_chunk_to_generation_chunk(chunk, default_chunk_class, base_generation_info)
        if generation_chunk is None or not isinstance(generation_chunk.message, AIMessageChunk):
            return generation_chunk

        choices = chunk.get("choices") or []
        delta = choices[0].get("delta") if choices and isinstance(choices[0], Mapping) else None
        signed = _signed_raw_tool_calls(delta.get("tool_calls") if isinstance(delta, Mapping) else None)
        if signed is None or "tool_calls" in generation_chunk.message.additional_kwargs:
            return generation_chunk

        return ChatGenerationChunk(
            message=_with_raw_tool_calls(generation_chunk.message, signed),
            generation_info=generation_chunk.generation_info,
        )

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ) -> ChatResult:
        """Capture signed raw tool calls from non-streaming responses."""
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices") or []

        patched_generations: list[ChatGeneration] | None = None
        for index, generation in enumerate(result.generations):
            choice = choices[index] if index < len(choices) else None
            message_dict = choice.get("message") if isinstance(choice, Mapping) else None
            signed = _signed_raw_tool_calls(message_dict.get("tool_calls") if isinstance(message_dict, Mapping) else None)
            message = generation.message
            if signed is None or not isinstance(message, AIMessage) or "tool_calls" in message.additional_kwargs:
                continue
            if patched_generations is None:
                patched_generations = list(result.generations)
            patched_generations[index] = ChatGeneration(
                message=_with_raw_tool_calls(message, signed),
                generation_info=generation.generation_info,
            )

        if patched_generations is None:
            return result
        return ChatResult(generations=patched_generations, llm_output=result.llm_output)


def _has_thought_signature(raw_tc: Any) -> bool:
    """Return whether a raw tool-call dict carries a Gemini thought signature."""
    if not isinstance(raw_tc, Mapping):
        return False
    if raw_tc.get("thought_signature") or raw_tc.get("thoughtSignature"):
        return True
    extra_content = raw_tc.get("extra_content")
    google = extra_content.get("google") if isinstance(extra_content, Mapping) else None
    return isinstance(google, Mapping) and bool(google.get("thought_signature"))


def _signed_raw_tool_calls(raw_tool_calls: Any) -> list[dict] | None:
    """Return copies of *raw_tool_calls* if at least one carries a thought signature.

    The streaming ``index`` is dropped: LangChain merges list entries that share
    an integer ``index`` by concatenating their strings, while each captured
    entry here is already a complete tool call (Gemini sends ``index: null``).
    """
    if not isinstance(raw_tool_calls, list) or not any(_has_thought_signature(raw_tc) for raw_tc in raw_tool_calls):
        return None
    return [{key: value for key, value in raw_tc.items() if key != "index"} for raw_tc in raw_tool_calls if isinstance(raw_tc, Mapping)]


def _with_raw_tool_calls(message: AIMessage, raw_tool_calls: list[dict]) -> AIMessage:
    """Return a copy of *message* with *raw_tool_calls* stored in additional_kwargs."""
    return message.model_copy(update={"additional_kwargs": {**message.additional_kwargs, "tool_calls": raw_tool_calls}})


def _restore_tool_call_signatures(payload_msg: dict, orig_msg: AIMessage) -> None:
    """Re-inject ``thought_signature`` onto tool-call objects in *payload_msg*.

    When the Gemini OpenAI-compatible gateway returns a response with function
    calls, each tool-call object may carry a ``thought_signature`` (top-level,
    or under ``extra_content.google`` on Google's official endpoint).  The raw
    tool-call dicts are stored in ``additional_kwargs["tool_calls"]`` but
    LangChain only serialises the standard fields (``id``, ``type``,
    ``function``) into the outgoing payload, silently dropping the signature.

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

        # Google's official endpoint expects extra_content echoed back verbatim.
        extra_content = raw_tc.get("extra_content")
        if isinstance(extra_content, Mapping) and extra_content:
            payload_tc["extra_content"] = copy.deepcopy(dict(extra_content))
