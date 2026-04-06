"""Custom vLLM provider built on top of LangChain ChatOpenAI.

vLLM 0.19.0 exposes reasoning models through an OpenAI-compatible API, but
LangChain's default OpenAI adapter drops the non-standard ``reasoning`` field
from assistant messages and streaming deltas. That breaks interleaved
thinking/tool-call flows because vLLM expects the assistant's prior reasoning to
be echoed back on subsequent turns.

This provider preserves ``reasoning`` on:
- non-streaming responses
- streaming deltas
- multi-turn request payloads
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

import openai
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessageChunk,
    ChatMessageChunk,
    FunctionMessageChunk,
    HumanMessageChunk,
    SystemMessageChunk,
    ToolMessageChunk,
)
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import _create_usage_metadata


def _normalize_vllm_chat_template_kwargs(payload: dict[str, Any]) -> None:
    """Map DeerFlow's legacy ``thinking`` toggle to vLLM/Qwen's ``enable_thinking``.

    DeerFlow originally documented ``extra_body.chat_template_kwargs.thinking``
    for vLLM, but vLLM 0.19.0's Qwen reasoning parser reads
    ``chat_template_kwargs.enable_thinking``. Normalize the payload just before
    it is sent so existing configs keep working and flash mode can truly
    disable reasoning.
    """
    extra_body = payload.get("extra_body")
    if not isinstance(extra_body, dict):
        return

    chat_template_kwargs = extra_body.get("chat_template_kwargs")
    if not isinstance(chat_template_kwargs, dict):
        return

    if "thinking" not in chat_template_kwargs:
        return

    normalized_chat_template_kwargs = dict(chat_template_kwargs)
    normalized_chat_template_kwargs.setdefault("enable_thinking", normalized_chat_template_kwargs["thinking"])
    normalized_chat_template_kwargs.pop("thinking", None)
    extra_body["chat_template_kwargs"] = normalized_chat_template_kwargs


def _reasoning_to_text(reasoning: Any) -> str:
    """Best-effort extraction of readable reasoning text from vLLM payloads."""
    if isinstance(reasoning, str):
        return reasoning

    if isinstance(reasoning, list):
        parts = [_reasoning_to_text(item) for item in reasoning]
        return "".join(part for part in parts if part)

    if isinstance(reasoning, dict):
        for key in ("text", "content", "reasoning"):
            value = reasoning.get(key)
            if isinstance(value, str):
                return value
            if value is not None:
                text = _reasoning_to_text(value)
                if text:
                    return text
        try:
            return json.dumps(reasoning, ensure_ascii=False)
        except TypeError:
            return str(reasoning)

    try:
        return json.dumps(reasoning, ensure_ascii=False)
    except TypeError:
        return str(reasoning)


def _convert_delta_to_message_chunk_with_reasoning(_dict: Mapping[str, Any], default_class: type[BaseMessageChunk]) -> BaseMessageChunk:
    """Convert a streaming delta to a LangChain message chunk while preserving reasoning."""
    id_ = _dict.get("id")
    role = cast(str, _dict.get("role"))
    content = cast(str, _dict.get("content") or "")
    additional_kwargs: dict[str, Any] = {}

    if _dict.get("function_call"):
        function_call = dict(_dict["function_call"])
        if "name" in function_call and function_call["name"] is None:
            function_call["name"] = ""
        additional_kwargs["function_call"] = function_call

    reasoning = _dict.get("reasoning")
    if reasoning is not None:
        additional_kwargs["reasoning"] = reasoning
        reasoning_text = _reasoning_to_text(reasoning)
        if reasoning_text:
            additional_kwargs["reasoning_content"] = reasoning_text

    tool_call_chunks = []
    if raw_tool_calls := _dict.get("tool_calls"):
        try:
            tool_call_chunks = [
                tool_call_chunk(
                    name=rtc["function"].get("name"),
                    args=rtc["function"].get("arguments"),
                    id=rtc.get("id"),
                    index=rtc["index"],
                )
                for rtc in raw_tool_calls
            ]
        except KeyError:
            pass

    if role == "user" or default_class == HumanMessageChunk:
        return HumanMessageChunk(content=content, id=id_)
    if role == "assistant" or default_class == AIMessageChunk:
        return AIMessageChunk(
            content=content,
            additional_kwargs=additional_kwargs,
            id=id_,
            tool_call_chunks=tool_call_chunks,  # type: ignore[arg-type]
        )
    if role in ("system", "developer") or default_class == SystemMessageChunk:
        role_kwargs = {"__openai_role__": "developer"} if role == "developer" else {}
        return SystemMessageChunk(content=content, id=id_, additional_kwargs=role_kwargs)
    if role == "function" or default_class == FunctionMessageChunk:
        return FunctionMessageChunk(content=content, name=_dict["name"], id=id_)
    if role == "tool" or default_class == ToolMessageChunk:
        return ToolMessageChunk(content=content, tool_call_id=_dict["tool_call_id"], id=id_)
    if role or default_class == ChatMessageChunk:
        return ChatMessageChunk(content=content, role=role, id=id_)  # type: ignore[arg-type]
    return default_class(content=content, id=id_)  # type: ignore[call-arg]


def _restore_reasoning_field(payload_msg: dict[str, Any], orig_msg: AIMessage) -> None:
    """Re-inject vLLM reasoning onto outgoing assistant messages."""
    reasoning = orig_msg.additional_kwargs.get("reasoning")
    if reasoning is None:
        reasoning = orig_msg.additional_kwargs.get("reasoning_content")
    if reasoning is not None:
        payload_msg["reasoning"] = reasoning


class VllmChatModel(ChatOpenAI):
    """ChatOpenAI variant that preserves vLLM reasoning fields across turns."""

    model_config = {"arbitrary_types_allowed": True}

    @property
    def _llm_type(self) -> str:
        return "vllm-openai-compatible"

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Restore assistant reasoning in request payloads for interleaved thinking."""
        original_messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        _normalize_vllm_chat_template_kwargs(payload)
        payload_messages = payload.get("messages", [])

        if len(payload_messages) == len(original_messages):
            for payload_msg, orig_msg in zip(payload_messages, original_messages):
                if payload_msg.get("role") == "assistant" and isinstance(orig_msg, AIMessage):
                    _restore_reasoning_field(payload_msg, orig_msg)
        else:
            ai_messages = [message for message in original_messages if isinstance(message, AIMessage)]
            assistant_payloads = [message for message in payload_messages if message.get("role") == "assistant"]
            for payload_msg, ai_msg in zip(assistant_payloads, ai_messages):
                _restore_reasoning_field(payload_msg, ai_msg)

        return payload

    def _create_chat_result(self, response: dict | openai.BaseModel, generation_info: dict | None = None) -> ChatResult:
        """Preserve vLLM reasoning on non-streaming responses."""
        result = super()._create_chat_result(response, generation_info=generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()

        for generation, choice in zip(result.generations, response_dict.get("choices", [])):
            if not isinstance(generation, ChatGeneration):
                continue
            message = generation.message
            if not isinstance(message, AIMessage):
                continue
            reasoning = choice.get("message", {}).get("reasoning")
            if reasoning is None:
                continue
            message.additional_kwargs["reasoning"] = reasoning
            reasoning_text = _reasoning_to_text(reasoning)
            if reasoning_text:
                message.additional_kwargs["reasoning_content"] = reasoning_text

        return result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        """Preserve vLLM reasoning on streaming deltas."""
        if chunk.get("type") == "content.delta":
            return None

        token_usage = chunk.get("usage")
        choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])
        usage_metadata = _create_usage_metadata(token_usage, chunk.get("service_tier")) if token_usage else None

        if len(choices) == 0:
            generation_chunk = ChatGenerationChunk(message=default_chunk_class(content="", usage_metadata=usage_metadata), generation_info=base_generation_info)
            if self.output_version == "v1":
                generation_chunk.message.content = []
                generation_chunk.message.response_metadata["output_version"] = "v1"
            return generation_chunk

        choice = choices[0]
        if choice["delta"] is None:
            return None

        message_chunk = _convert_delta_to_message_chunk_with_reasoning(choice["delta"], default_chunk_class)
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

        if usage_metadata and isinstance(message_chunk, AIMessageChunk):
            message_chunk.usage_metadata = usage_metadata

        message_chunk.response_metadata["model_provider"] = "openai"
        return ChatGenerationChunk(message=message_chunk, generation_info=generation_info or None)
