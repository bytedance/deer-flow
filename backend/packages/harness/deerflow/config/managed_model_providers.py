"""Server-owned routing for managed models; never infer a provider from its ID.

Endpoints are verified against the vendors' SDKs and operator examples; see the
source links in CONFIGURATION.md. Catalog entries contain no routing overrides.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

_OPENAI = "langchain_openai:ChatOpenAI"
_DEEPSEEK = "deerflow.models.patched_deepseek:PatchedChatDeepSeek"
_MINIMAX = "deerflow.models.patched_minimax:PatchedChatMiniMax"


@dataclass(frozen=True)
class ManagedModelProvider:
    id: str
    display_name: str
    endpoint: str | None
    adapter: str = _OPENAI
    protocol: str = "openai-chat"
    endpoint_parameter: str = "base_url"
    auth_parameter: str = "api_key"
    defaults: dict[str, Any] = field(default_factory=dict)
    authentication: str = "bearer"

    def public(self) -> dict[str, Any]:
        # Only form metadata is public. Routing/adapter/defaults stay server-owned.
        return {"id": self.id, "display_name": self.display_name, "requires_api_key": self.endpoint is not None, "custom_endpoint": self.endpoint is None}


PROVIDERS = (
    ManagedModelProvider("openai", "OpenAI", "https://api.openai.com/v1"),
    ManagedModelProvider("anthropic", "Anthropic", "https://api.anthropic.com", "langchain_anthropic:ChatAnthropic", "anthropic-messages", defaults={"max_tokens": 4096}, authentication="x-api-key"),
    ManagedModelProvider("deepseek", "DeepSeek", "https://api.deepseek.com", _DEEPSEEK, endpoint_parameter="api_base"),
    ManagedModelProvider("qwen-cn", "Alibaba Cloud Bailian / Qwen (China)", "https://dashscope.aliyuncs.com/compatible-mode/v1", _DEEPSEEK, endpoint_parameter="api_base"),
    ManagedModelProvider("doubao", "Volcengine / Doubao (Beijing, API)", "https://ark.cn-beijing.volces.com/api/v3", _DEEPSEEK, endpoint_parameter="api_base"),
    ManagedModelProvider("doubao-coding", "Volcengine (Coding Plan)", "https://ark.cn-beijing.volces.com/api/coding/v3", _DEEPSEEK, endpoint_parameter="api_base"),
    ManagedModelProvider("moonshot-cn", "Moonshot / Kimi (China)", "https://api.moonshot.cn/v1", _DEEPSEEK, endpoint_parameter="api_base"),
    ManagedModelProvider("zhipu-cn", "Zhipu (China, API)", "https://open.bigmodel.cn/api/paas/v4", _DEEPSEEK, endpoint_parameter="api_base"),
    ManagedModelProvider("zai", "Z.AI (International, API)", "https://api.z.ai/api/paas/v4", _DEEPSEEK, endpoint_parameter="api_base"),
    ManagedModelProvider("minimax", "MiniMax (International, API)", "https://api.minimax.io/v1", _MINIMAX, defaults={"temperature": 1.0}),
    ManagedModelProvider("minimax-cn", "MiniMax (China, API)", "https://api.minimaxi.com/v1", _MINIMAX, defaults={"temperature": 1.0}),
    ManagedModelProvider("openai-compatible", "Custom OpenAI-compatible", None),
)
_PROVIDER_BY_ID = {provider.id: provider for provider in PROVIDERS}


def get_managed_model_provider(provider: str) -> ManagedModelProvider:
    try:
        return _PROVIDER_BY_ID[provider]
    except KeyError:
        raise ValueError("Unknown model provider") from None


def _is_official_deepseek_endpoint(base_url: str) -> bool:
    endpoint = urlsplit(base_url)
    if endpoint.scheme != "https" or endpoint.hostname != "api.deepseek.com":
        return False
    return endpoint.port in (None, 443) and endpoint.path.rstrip("/") in ("", "/v1")


def resolve_managed_model_provider(base_url: str) -> dict[str, Any]:
    """Legacy endpoint contract, kept intact for old encrypted custom profiles."""
    if _is_official_deepseek_endpoint(base_url):
        return {
            "use": _DEEPSEEK,
            "api_base": base_url,
            "supports_thinking": True,
            "supports_reasoning_effort": True,
            "when_thinking_enabled": {"extra_body": {"thinking": {"type": "enabled"}}},
            "when_thinking_disabled": {"extra_body": {"thinking": {"type": "disabled"}}},
        }
    return {"use": _OPENAI, "base_url": base_url}


def _capabilities(provider: str, model: str) -> dict[str, Any]:
    """Exact opt-in rules. Unknown IDs get no fabricated window or capabilities.

    Adapter choice is provider-wide because it preserves wire/history fields;
    thinking/vision/effort is model-specific. Do not broaden these to substrings.
    """
    result: dict[str, Any] = {"reasoning": {"thinking": "unsupported", "dialect": "none"}}
    if provider == "openai" and model in {"gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano"}:
        result["supports_vision"] = True
    elif provider == "anthropic" and model in {"claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-sonnet-4-5-20250929"}:
        result.update(
            supports_vision=True, reasoning={"thinking": "optional", "dialect": "anthropic"}, when_thinking_enabled={"thinking": {"type": "enabled", "budget_tokens": 1024}}, when_thinking_disabled={"thinking": {"type": "disabled"}}
        )
    elif provider == "deepseek" and model in {"deepseek-v4-flash", "deepseek-v4-pro", "deepseek-flash"}:
        result.update(
            reasoning={"thinking": "optional", "dialect": "openai_extra_body", "history": "preserve"},
            when_thinking_enabled={"extra_body": {"thinking": {"type": "enabled"}}},
            when_thinking_disabled={"extra_body": {"thinking": {"type": "disabled"}}},
        )
        result["reasoning"]["effort"] = {"values": ["high", "max"], "default": "high", "aliases": {"minimal": "high", "low": "high", "medium": "high"}}
    elif provider in {"zai", "zhipu-cn"} and model in {"glm-4.5", "glm-4.6", "glm-4.7", "glm-5.3-flash"}:
        result.update(
            reasoning={"thinking": "optional", "dialect": "openai_extra_body", "history": "preserve"},
            when_thinking_enabled={"extra_body": {"thinking": {"type": "enabled"}}},
            when_thinking_disabled={"extra_body": {"thinking": {"type": "disabled"}}},
        )
    elif provider == "doubao" and model == "doubao-seed-1-8-251228":
        result.update(
            supports_vision=True,
            reasoning={"thinking": "optional", "dialect": "openai_extra_body", "history": "preserve"},
            when_thinking_enabled={"extra_body": {"thinking": {"type": "enabled"}}},
            when_thinking_disabled={"extra_body": {"thinking": {"type": "disabled"}}},
        )
    elif provider == "moonshot-cn" and model == "kimi-k2.5":
        result.update(
            supports_vision=True,
            reasoning={"thinking": "optional", "dialect": "openai_extra_body", "history": "preserve"},
            temperature=1.0,
            when_thinking_enabled={"extra_body": {"thinking": {"type": "enabled"}}, "temperature": 1.0},
            when_thinking_disabled={"extra_body": {"thinking": {"type": "disabled"}}, "temperature": 0.6},
        )
    elif provider in {"minimax", "minimax-cn"} and model in {"MiniMax-M2.7", "MiniMax-M2.7-highspeed"}:
        result["reasoning"] = {"thinking": "required", "dialect": "none", "history": "preserve"}
    elif provider in {"minimax", "minimax-cn"} and model == "MiniMax-M3":
        result.update(
            supports_vision=True,
            reasoning={"thinking": "optional", "dialect": "none", "history": "preserve"},
            when_thinking_enabled={"extra_body": {"thinking": {"type": "adaptive"}}},
            when_thinking_disabled={"extra_body": {"thinking": {"type": "disabled"}}},
        )
    return result


def resolve_preset_model(provider: str, model: str, api_key: str) -> dict[str, Any]:
    preset = get_managed_model_provider(provider)
    if preset.endpoint is None:
        raise ValueError("Custom providers require an endpoint")
    return {"use": preset.adapter, preset.endpoint_parameter: preset.endpoint, preset.auth_parameter: api_key, **deepcopy(preset.defaults), **_capabilities(provider, model)}
