"""OpenAI-compatible adapters that preserve structured response failures."""

from __future__ import annotations

from typing import Any

from langchain_core.outputs import ChatResult
from langchain_openai import ChatOpenAI

from deerflow.models.response_errors import EmptyModelResponseError


class OpenAIEmptyChoicesMixin:
    """Raise a typed error before LangChain indexes an empty choices list."""

    def _create_chat_result(self, response: Any, generation_info: dict | None = None) -> ChatResult:
        choices = response.get("choices") if isinstance(response, dict) else getattr(response, "choices", None)
        if isinstance(choices, (list, tuple)) and not choices:
            raise EmptyModelResponseError("Model returned an HTTP-success response with an empty choices list")
        return super()._create_chat_result(response, generation_info=generation_info)


class GuardedChatOpenAI(OpenAIEmptyChoicesMixin, ChatOpenAI):
    """ChatOpenAI with typed handling for valid HTTP responses with no choices."""
