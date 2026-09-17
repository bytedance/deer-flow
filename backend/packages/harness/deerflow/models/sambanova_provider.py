"""SambaNova provider using OpenAI-compatible API.

SambaNova provides OpenAI-compatible chat completions endpoint at
https://api.sambanova.ai/v1. This adapter simply configures ChatOpenAI
with the correct base URL and default settings.

Docs: https://docs.sambanova.ai/
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI


class SambaNovaChatModel(ChatOpenAI):
    """ChatOpenAI adapter for SambaNova API.

    Config example:
        - name: sambanova-deepseek-v3.1
          display_name: DeepSeek V3.1 (SambaNova)
          use: deerflow.models.sambanova_provider:SambaNovaChatModel
          model: DeepSeek-V3.1
          api_key: $SAMBANOVA_API_KEY
          base_url: https://api.sambanova.ai/v1
          request_timeout: 600.0
          max_retries: 2
          max_tokens: 4096
          context_window: 131072
          supports_thinking: false
          supports_vision: false
    """

    def __init__(self, **kwargs: Any) -> None:
        if "base_url" not in kwargs and "openai_api_base" not in kwargs:
            kwargs["base_url"] = "https://api.sambanova.ai/v1"
        super().__init__(**kwargs)

    @property
    def _llm_type(self) -> str:
        return "sambanova"
