"""Patched ChatOpenAI for MiMo reasoning-mode history round-tripping.

MiMo's OpenAI-compatible thinking mode returns ``reasoning_content`` on
assistant messages. Standard ``langchain_openai.ChatOpenAI`` ignores that
provider-specific field when parsing responses, so subsequent turns have
nothing to send back even if the transport layer tries to preserve it.

This adapter fixes both halves of the protocol:

1. Parse ``reasoning_content`` from full responses and streaming deltas into
   ``AIMessage.additional_kwargs``.
2. Re-inject that field into assistant messages when building the next request.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import (
    _convert_delta_to_message_chunk,
    _create_usage_metadata,
)


class PatchedMimoChatModel(ChatOpenAI):
    """ChatOpenAI with MiMo ``reasoning_content`` preservation."""

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        original_messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        payload_messages = payload.get("messages", [])

        if len(payload_messages) == len(original_messages):
            for payload_msg, orig_msg in zip(payload_messages, original_messages):
                if payload_msg.get("role") == "assistant" and isinstance(orig_msg, AIMessage):
                    _restore_reasoning_content(payload_msg, orig_msg)
        else:
            ai_messages = [m for m in original_messages if isinstance(m, AIMessage)]
            assistant_payloads = [m for m in payload_messages if m.get("role") == "assistant"]
            for payload_msg, ai_msg in zip(assistant_payloads, ai_messages):
                _restore_reasoning_content(payload_msg, ai_msg)

        if _thinking_enabled(payload):
            payload["messages"] = _drop_legacy_messages_missing_reasoning(payload_messages)
        return payload

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        token_usage = chunk.get("usage")
        choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])
        usage_metadata = _create_usage_metadata(token_usage, chunk.get("service_tier")) if token_usage else None

        if len(choices) == 0:
            generation_chunk = ChatGenerationChunk(
                message=default_chunk_class(content="", usage_metadata=usage_metadata),
                generation_info=base_generation_info,
            )
            return generation_chunk

        choice = choices[0]
        delta = choice.get("delta")
        if delta is None:
            return None

        message_chunk = _convert_delta_to_message_chunk(delta, default_chunk_class)
        generation_info = {**base_generation_info} if base_generation_info else {}

        if finish_reason := choice.get("finish_reason"):
            generation_info["finish_reason"] = finish_reason
            if model_name := chunk.get("model"):
                generation_info["model_name"] = model_name
            if system_fingerprint := chunk.get("system_fingerprint"):
                generation_info["system_fingerprint"] = system_fingerprint
            if service_tier := chunk.get("service_tier"):
                generation_info["service_tier"] = service_tier

        if logprobs := choice.get("logprobs"):
            generation_info["logprobs"] = logprobs

        if isinstance(message_chunk, AIMessageChunk):
            if usage_metadata:
                message_chunk.usage_metadata = usage_metadata
            if isinstance(delta.get("reasoning_content"), str) and delta["reasoning_content"].strip():
                message_chunk = _with_reasoning_content(
                    message_chunk,
                    delta["reasoning_content"],
                    preserve_whitespace=True,
                )

        message_chunk.response_metadata["model_provider"] = "openai"
        return ChatGenerationChunk(
            message=message_chunk,
            generation_info=generation_info or None,
        )

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices", [])

        generations: list[ChatGeneration] = []
        for index, generation in enumerate(result.generations):
            choice = choices[index] if index < len(choices) else {}
            message = generation.message
            if isinstance(message, AIMessage):
                choice_message = choice.get("message", {}) if isinstance(choice, dict) else {}
                reasoning_content = choice_message.get("reasoning_content")

                if isinstance(reasoning_content, str) and reasoning_content.strip():
                    message = _with_reasoning_content(message, reasoning_content)
                    generation = ChatGeneration(
                        message=message,
                        generation_info=generation.generation_info,
                    )

            generations.append(generation)

        return ChatResult(generations=generations, llm_output=result.llm_output)


def _restore_reasoning_content(payload_msg: dict, orig_msg: AIMessage) -> None:
    reasoning_content = orig_msg.additional_kwargs.get("reasoning_content")
    if reasoning_content is not None:
        payload_msg["reasoning_content"] = reasoning_content


def _drop_legacy_messages_missing_reasoning(payload_messages: list[dict]) -> list[dict]:
    """Remove assistant turns that cannot satisfy MiMo's history contract.

    Older persisted threads may contain assistant messages created before this
    adapter existed, so they have no ``reasoning_content`` to echo back. MiMo
    rejects the entire request in that case. We prefer dropping those legacy
    turns over failing the whole conversation.
    """
    cleaned: list[dict] = []
    skipped_tool_call_ids: set[str] = set()

    for message in payload_messages:
        role = message.get("role")

        if role == "tool":
            tool_call_id = message.get("tool_call_id")
            if isinstance(tool_call_id, str) and tool_call_id in skipped_tool_call_ids:
                continue
            cleaned.append(message)
            continue

        if role == "assistant" and not _has_reasoning_content(message):
            for tool_call in message.get("tool_calls") or []:
                if isinstance(tool_call, dict):
                    tool_call_id = tool_call.get("id")
                    if isinstance(tool_call_id, str) and tool_call_id:
                        skipped_tool_call_ids.add(tool_call_id)
            continue

        cleaned.append(message)

    return cleaned


def _has_reasoning_content(message: dict) -> bool:
    reasoning_content = message.get("reasoning_content")
    return isinstance(reasoning_content, str) and bool(reasoning_content.strip())


def _thinking_enabled(payload: dict) -> bool:
    extra_body = payload.get("extra_body")
    if not isinstance(extra_body, dict):
        return False

    thinking = extra_body.get("thinking")
    if not isinstance(thinking, dict):
        return False

    return thinking.get("type") == "enabled"


def _merge_reasoning(*values: str | None) -> str | None:
    merged: list[str] = []
    for value in values:
        if not value:
            continue
        normalized = value.strip()
        if normalized and normalized not in merged:
            merged.append(normalized)
    return "\n\n".join(merged) if merged else None


def _with_reasoning_content(
    message: AIMessage | AIMessageChunk,
    reasoning: str | None,
    *,
    preserve_whitespace: bool = False,
):
    if not reasoning:
        return message

    additional_kwargs = dict(message.additional_kwargs)
    if preserve_whitespace:
        existing = additional_kwargs.get("reasoning_content")
        additional_kwargs["reasoning_content"] = f"{existing}{reasoning}" if isinstance(existing, str) else reasoning
    else:
        additional_kwargs["reasoning_content"] = _merge_reasoning(
            additional_kwargs.get("reasoning_content"),
            reasoning,
        )
    return message.model_copy(update={"additional_kwargs": additional_kwargs})
