"""Patched ChatDeepSeek that preserves reasoning_content in multi-turn conversations.

This module provides a patched version of ChatDeepSeek that properly handles
reasoning_content when sending messages back to the API. The original implementation
stores reasoning_content in additional_kwargs but doesn't include it when making
subsequent API calls, which causes errors with APIs that require reasoning_content
on all assistant messages when thinking mode is enabled.
"""

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_deepseek import ChatDeepSeek

from deerflow.config.managed_model_providers import MOONSHOT_K31_MODELS
from deerflow.models.assistant_payload_replay import restore_assistant_payloads, restore_reasoning_content


def _is_moonshot_k31_request(api_base: str | None, payload: dict[str, Any]) -> bool:
    """Match the official endpoint and model that the SDK will actually send."""
    extra_body = payload.get("extra_body")
    model = extra_body.get("model", payload.get("model")) if isinstance(extra_body, Mapping) else payload.get("model")
    if not isinstance(model, str) or model not in MOONSHOT_K31_MODELS:
        return False
    try:
        endpoint = urlsplit(api_base or "")
        return endpoint.scheme == "https" and endpoint.hostname == "api.moonshot.cn" and endpoint.port in (None, 443) and endpoint.path.rstrip("/") == "/v1"
    except ValueError:
        return False


def _normalize_moonshot_k31_payload(payload: dict[str, Any]) -> None:
    """Let K3.1 supply its fixed sampling values; it accepts no thinking switch."""
    omitted = {"thinking", "temperature", "top_p", "n", "presence_penalty", "frequency_penalty"}
    for key in omitted:
        payload.pop(key, None)
    extra_body = payload.get("extra_body")
    if isinstance(extra_body, Mapping):
        # The SDK merges extra_body last. Copy it to preserve caller-owned values.
        payload["extra_body"] = {key: value for key, value in extra_body.items() if key not in omitted}


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

        moonshot_k31 = _is_moonshot_k31_request(self.api_base, payload)
        if moonshot_k31:
            _normalize_moonshot_k31_payload(payload)

        request_thinking_enabled = moonshot_k31 or _thinking_enabled(
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
