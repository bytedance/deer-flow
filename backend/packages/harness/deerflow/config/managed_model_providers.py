"""Provider defaults for administrator-managed OpenAI-compatible endpoints."""

from typing import Any
from urllib.parse import urlsplit


def _is_official_deepseek_endpoint(base_url: str) -> bool:
    endpoint = urlsplit(base_url)
    if endpoint.scheme != "https" or endpoint.hostname != "api.deepseek.com":
        return False
    return endpoint.port in (None, 443) and endpoint.path.rstrip("/") in ("", "/v1")


def resolve_managed_model_provider(base_url: str) -> dict[str, Any]:
    """Derive settings from a validated endpoint, never from the model name.

    Only the official Chat Completions endpoint opts into DeepSeek semantics;
    third-party proxies retain the generic OpenAI-compatible contract.
    """
    if _is_official_deepseek_endpoint(base_url):
        return {
            "use": "deerflow.models.patched_deepseek:PatchedChatDeepSeek",
            "api_base": base_url,
            "supports_thinking": True,
            "supports_reasoning_effort": True,
            "when_thinking_enabled": {"extra_body": {"thinking": {"type": "enabled"}}},
            "when_thinking_disabled": {"extra_body": {"thinking": {"type": "disabled"}}},
        }
    return {"use": "langchain_openai:ChatOpenAI", "base_url": base_url}
