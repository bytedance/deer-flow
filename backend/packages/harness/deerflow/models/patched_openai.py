"""OpenAI-compatible adapter that survives gateway-specific assistant fields.

Two fields that some OpenAI-compatible gateways issue on assistant messages must be
echoed back verbatim on the next request:

* Gemini's tool-call ``thought_signature`` (required whenever thinking is enabled), and
* DeepSeek-style ``reasoning_content`` (required by reasoning models such as Kimi/Qwen
  behind a gateway).

Neither survives the round trip on its own:

1. **Inbound.** ``langchain_openai`` parses responses with
   ``_convert_dict_to_message`` / ``_convert_delta_to_message_chunk``, which keep only
   ``function_call``/``audio`` in ``additional_kwargs`` and normalise tool calls down to
   ``{name, args, id, type}``. Gateway fields are dropped at parse time, so they never reach
   ``additional_kwargs`` on their own.
2. **Outbound.** The payload serialiser only emits the standard tool-call fields, so even
   a field that did reach ``additional_kwargs`` would not be sent back.

The mixin below closes both gaps: it captures the raw gateway fields while the response
payload is still in hand, then re-injects them into the outgoing request. Without the
capture half the replay half is a permanent no-op, which is what issues #1180 and #1790
kept hitting.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

from deerflow.models.assistant_payload_replay import restore_assistant_payloads, restore_reasoning_content


def _capture_replayable_fields(message: Any, payload_message: Mapping[str, Any]) -> None:
    """Stash gateway-issued fields that the parser would drop.

    Applied while the raw response payload is still available, for the same reason
    ``patched_minimax`` rebuilds its own messages: what the parser discards cannot be
    recovered later. Streaming calls this per delta, and ``AIMessageChunk`` merging
    concatenates ``reasoning_content`` and appends tool-call entries, which is the shape
    the replay expects.
    """
    additional_kwargs = message.additional_kwargs

    reasoning = payload_message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        existing = additional_kwargs.get("reasoning_content")
        additional_kwargs["reasoning_content"] = f"{existing}{reasoning}" if isinstance(existing, str) else reasoning

    raw_tool_calls = payload_message.get("tool_calls")
    if isinstance(raw_tool_calls, list):
        signed = [tool_call for tool_call in raw_tool_calls if isinstance(tool_call, Mapping) and (tool_call.get("thought_signature") or tool_call.get("thoughtSignature"))]
        if signed:
            existing_calls = additional_kwargs.get("tool_calls")
            additional_kwargs["tool_calls"] = [*(existing_calls if isinstance(existing_calls, list) else []), *signed]


class AssistantReplayMixin:
    """Capture and replay gateway-issued assistant fields.

    Mixed into OpenAI-compatible clients by ``deerflow.models.factory``. Providers that
    already build their own messages (DeepSeek, MiMo, MiniMax, StepFun, vLLM) are never
    wrapped, so their explicit handling still wins.
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

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ) -> ChatResult:
        """Capture gateway fields from a non-streaming response before they are lost."""
        result = super()._create_chat_result(response, generation_info)
        payload = response if isinstance(response, Mapping) else response.model_dump()
        choices = payload.get("choices") or []
        for index, generation in enumerate(result.generations):
            choice = choices[index] if index < len(choices) else {}
            raw_message = choice.get("message") if isinstance(choice, Mapping) else None
            if isinstance(raw_message, Mapping):
                _capture_replayable_fields(generation.message, raw_message)
        return result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        """Capture gateway fields from a streaming delta before they are lost."""
        generation_chunk = super()._convert_chunk_to_generation_chunk(chunk, default_chunk_class, base_generation_info)
        if generation_chunk is None:
            return generation_chunk
        choices = chunk.get("choices") or (chunk.get("chunk") or {}).get("choices") or []
        delta = choices[0].get("delta") if choices else None
        if isinstance(delta, Mapping):
            _capture_replayable_fields(generation_chunk.message, delta)
        return generation_chunk


class PatchedChatOpenAI(AssistantReplayMixin, ChatOpenAI):
    """ChatOpenAI with gateway-issued assistant fields captured and replayed.

    Kept for profiles that name the class explicitly. A stock ``ChatOpenAI`` profile
    receives the same behaviour from ``deerflow.models.factory``, so naming this class is
    no longer required.
    """


def _restore_replayable_assistant_fields(payload_msg: dict, orig_msg: AIMessage) -> None:
    """Restore every captured assistant field the stock serialiser drops.

    Gemini gateways require the tool-call ``thought_signature`` back (issue #1180);
    DeepSeek-style reasoning gateways reject a replayed assistant tool call whose
    ``reasoning_content`` is missing, which is the failure reported in issue #1790
    for Kimi/Qwen-style gateways. Each field is restored only when the captured message
    carries it, so a provider that never issued it gets nothing extra.
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
