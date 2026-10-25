"""Patched ChatDeepSeek that preserves reasoning_content in multi-turn conversations.

This module provides a patched version of ChatDeepSeek that properly handles
reasoning_content when sending messages back to the API. The original implementation
stores reasoning_content in additional_kwargs but doesn't include it when making
subsequent API calls, which causes errors with APIs that require reasoning_content
on all assistant messages when thinking mode is enabled.
"""

from typing import Any

import openai
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_deepseek import ChatDeepSeek

from deerflow.models.assistant_payload_replay import restore_assistant_payloads, restore_reasoning_content


def _thinking_enabled(*sources: Any) -> bool:
    """Return whether the request explicitly enables DeepSeek thinking mode."""
    for source in sources:
        if not isinstance(source, dict):
            continue
        thinking = source.get("thinking")
        if isinstance(thinking, dict) and thinking.get("type") == "enabled":
            return True
        extra_body = source.get("extra_body")
        if isinstance(extra_body, dict):
            nested = extra_body.get("thinking")
            if isinstance(nested, dict) and nested.get("type") == "enabled":
                return True
    return False


def _restore_deepseek_assistant_payload(
    payload_msg: dict[str, Any],
    orig_msg: AIMessage,
    *,
    thinking_enabled: bool,
) -> None:
    """Restore assistant history and required thinking-mode placeholders."""
    restore_reasoning_content(payload_msg, orig_msg)
    has_tool_calls = bool(payload_msg.get("tool_calls"))
    if has_tool_calls and payload_msg.get("content") is None:
        # DeepSeek requires an empty string, rather than null, for tool-call history.
        payload_msg["content"] = ""
    if thinking_enabled and has_tool_calls and "reasoning_content" not in payload_msg:
        # Thinking-mode tool turns require this field even when no reasoning was emitted.
        payload_msg["reasoning_content"] = ""


class PatchedChatDeepSeek(ChatDeepSeek):
    """ChatDeepSeek with proper reasoning_content preservation.

    When using thinking/reasoning enabled models, the API expects reasoning_content
    to be present on ALL assistant messages in multi-turn conversations. This patched
    version ensures reasoning_content from additional_kwargs is included in the
    request payload.
    """

    @classmethod
    def is_lc_serializable(cls) -> bool:
        return True

    @property
    def lc_secrets(self) -> dict[str, str]:
        return {"api_key": "DEEPSEEK_API_KEY", "openai_api_key": "DEEPSEEK_API_KEY"}

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Get request payload with reasoning_content preserved.

        Overrides the parent method to inject reasoning_content from
        additional_kwargs into assistant messages in the payload.
        """
        original_messages = self._convert_input(input_).to_messages()
        request_messages = [message for message in original_messages if not (isinstance(message, AIMessage) and (message.additional_kwargs or {}).get("deerflow_error_fallback"))]

        # Call parent to get the base payload
        payload = super()._get_request_payload(request_messages, stop=stop, **kwargs)

        request_thinking_enabled = _thinking_enabled(
            payload,
            kwargs,
            {"extra_body": getattr(self, "extra_body", None)},
        )
        restore_assistant_payloads(
            payload.get("messages", []),
            request_messages,
            lambda payload_msg, orig_msg: _restore_deepseek_assistant_payload(
                payload_msg,
                orig_msg,
                thinking_enabled=request_thinking_enabled,
            ),
        )

        return payload

    def _create_chat_result(
        self,
        response: dict | openai.BaseModel,
        generation_info: dict | None = None,
    ) -> ChatResult:
        """Preserve Moonshot's ``cache_write_tokens`` in the usage metadata.

        The locked ``langchain-openai==1.2.1`` conversion reads
        ``prompt_tokens_details.cached_tokens`` (mapped to ``cache_read``) but
        not ``cache_write_tokens``, so providers such as Kimi K3.1 lose their
        cache-creation count before it reaches the usage journal (#7426).
        Restore it as ``input_token_details["cache_creation"]`` from the raw
        SDK response.
        """
        result = super()._create_chat_result(response, generation_info)

        if not isinstance(response, openai.BaseModel):
            return result
        prompt_details = getattr(getattr(response, "usage", None), "prompt_tokens_details", None)
        cache_write_tokens = getattr(prompt_details, "cache_write_tokens", None)
        if cache_write_tokens is None:
            return result
        for generation in result.generations:
            usage = getattr(generation.message, "usage_metadata", None)
            if not usage:
                continue
            input_details = usage.setdefault("input_token_details", {})
            input_details["cache_creation"] = cache_write_tokens
        return result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        """Streaming mirror of ``_create_chat_result``'s cache_write restore.

        Streamed runs (the web UI's ``messages-tuple`` mode) build usage
        metadata in ``_convert_chunk_to_generation_chunk`` ->
        ``_create_usage_metadata``, which ignores ``cache_write_tokens``
        (#7426). Restore it the same way for the final usage chunk.
        """
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        if generation_chunk is None:
            return None
        prompt_details = ((chunk or {}).get("usage") or {}).get("prompt_tokens_details") or {}
        cache_write_tokens = prompt_details.get("cache_write_tokens")
        if cache_write_tokens is None:
            return generation_chunk
        usage = getattr(generation_chunk.message, "usage_metadata", None)
        if not usage:
            return generation_chunk
        input_details = usage.setdefault("input_token_details", {})
        input_details["cache_creation"] = cache_write_tokens
        return generation_chunk
