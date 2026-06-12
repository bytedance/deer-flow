"""Patched ChatOpenAI adapter for StepFun reasoning models.

StepFun returns ``reasoning`` (or ``reasoning_content`` with deepseek-style) in
both streaming deltas and non-streaming responses. Standard ``ChatOpenAI``
ignores these non-standard fields, so reasoning content is silently dropped.
This adapter captures reasoning from all response paths and replays it on
historical assistant messages for multi-turn tool-call conversations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

from deerflow.models.assistant_payload_replay import (
    restore_assistant_payloads,
    restore_reasoning_content,
)

_MISSING = object()


def _extract_reasoning(value: Any) -> str | object:
    """Return reasoning content from a dict/Pydantic object.

    StepFun may return reasoning via ``reasoning`` (default) or
    ``reasoning_content`` (deepseek-style). Check both fields.
    """
    if isinstance(value, Mapping):
        # Check reasoning_content first (deepseek-style), then reasoning (default)
        for field in ("reasoning_content", "reasoning"):
            if field in value and value[field] is not None:
                return value[field]
        return _MISSING

    # Pydantic / SDK object attributes
    for field in ("reasoning_content", "reasoning"):
        attr = getattr(value, field, _MISSING)
        if attr is not _MISSING and attr is not None:
            return attr

    # Some SDK versions store extra fields in model_extra
    model_extra = getattr(value, "model_extra", None)
    if isinstance(model_extra, Mapping):
        for field in ("reasoning_content", "reasoning"):
            if field in model_extra and model_extra[field] is not None:
                return model_extra[field]

    return _MISSING


def _with_reasoning_content(message: AIMessage | AIMessageChunk, reasoning: str) -> AIMessage | AIMessageChunk:
    """Return a copy of *message* with reasoning_content stored in additional_kwargs."""
    additional_kwargs = dict(message.additional_kwargs)
    if additional_kwargs.get("reasoning_content") != reasoning:
        additional_kwargs["reasoning_content"] = reasoning
    return message.model_copy(update={"additional_kwargs": additional_kwargs})


def _get_typed_choice_message(response: Any, index: int) -> Any:
    """Extract the SDK-typed choice message at *index*, if available."""
    choices = getattr(response, "choices", None)
    if choices is None:
        return None
    try:
        return choices[index].message
    except (AttributeError, IndexError, TypeError):
        return None


class PatchedChatStepFun(ChatOpenAI):
    """ChatOpenAI with full reasoning support for StepFun models.

    Captures ``reasoning`` / ``reasoning_content`` from both streaming and
    non-streaming responses and replays it on historical assistant messages in
    multi-turn tool-call conversations.
    """

    @classmethod
    def is_lc_serializable(cls) -> bool:
        return True

    @property
    def lc_secrets(self) -> dict[str, str]:
        return {"api_key": "STEPFUN_API_KEY", "openai_api_key": "STEPFUN_API_KEY"}

    # --- Request payload replay ---

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Restore ``reasoning_content`` on historical assistant messages."""
        original_messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        restore_assistant_payloads(
            payload.get("messages", []),
            original_messages,
            restore_reasoning_content,
        )

        return payload

    # --- Streaming reasoning capture ---

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        """Capture ``reasoning`` / ``reasoning_content`` from streaming deltas."""
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        if generation_chunk is None:
            return None

        choices = chunk.get("choices", [])
        if choices:
            delta = choices[0].get("delta") or {}
            reasoning = _extract_reasoning(delta)
            if reasoning is not _MISSING and isinstance(generation_chunk.message, AIMessageChunk):
                generation_chunk = ChatGenerationChunk(
                    message=_with_reasoning_content(generation_chunk.message, reasoning),
                    generation_info=generation_chunk.generation_info,
                )

        return generation_chunk

    # --- Non-streaming reasoning capture ---

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ) -> ChatResult:
        """Extract ``reasoning`` / ``reasoning_content`` from non-streaming responses."""
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices", [])

        patched_generations: list[ChatGeneration] | None = None
        for index, generation in enumerate(result.generations):
            choice = choices[index] if index < len(choices) else {}
            choice_message = choice.get("message", {}) if isinstance(choice, Mapping) else {}
            reasoning = _extract_reasoning(choice_message)

            if reasoning is _MISSING and not isinstance(response, dict):
                reasoning = _extract_reasoning(_get_typed_choice_message(response, index))

            message = generation.message
            if reasoning is not _MISSING and isinstance(message, AIMessage):
                if patched_generations is None:
                    patched_generations = list(result.generations)
                patched_generations[index] = ChatGeneration(
                    message=_with_reasoning_content(message, reasoning),
                    generation_info=generation.generation_info,
                )

        return ChatResult(
            generations=patched_generations or result.generations,
            llm_output=result.llm_output,
        )
