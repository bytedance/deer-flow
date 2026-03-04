from __future__ import annotations

from collections.abc import Iterable

import httpx
from pydantic import BaseModel, ConfigDict, Field

from src.config import get_app_config
from src.config.provider_model_catalog_config import SUPPORTED_PROVIDER_IDS, ProviderCatalogEntry, ProviderModelCatalogConfig

DEFAULT_TIMEOUT_SECONDS = 12.0


class ProviderModelInfo(BaseModel):
    id: str = Field(..., description="Stable unique identifier for the model option")
    provider: str = Field(..., description="Provider identifier")
    model_id: str = Field(..., description="Provider model identifier")
    display_name: str = Field(..., description="Display name for UI")
    description: str | None = Field(default=None, description="Optional model description")
    supports_thinking: bool = Field(default=False, description="Backward-compatible thinking capability flag")
    thinking_enabled: bool = Field(default=False, description="Whether thinking is always enabled for this model")
    supports_vision: bool = Field(default=False, description="Whether model supports vision inputs")
    supports_adaptive_thinking: bool = Field(default=False, description="Whether model supports adaptive effort")
    adaptive_thinking_efforts: list[str] = Field(default_factory=list, description="Allowed adaptive thinking efforts")
    default_thinking_effort: str | None = Field(default=None, description="Default adaptive thinking effort")
    tier: str | None = Field(default=None, description="Optional tier identifier")
    tier_label: str | None = Field(default=None, description="Human-readable tier label")
    model_config = ConfigDict(extra="forbid")


class ProviderCatalogInfo(BaseModel):
    id: str = Field(..., description="Provider identifier")
    display_name: str = Field(..., description="Provider display name")
    description: str | None = Field(default=None, description="Provider description")
    enabled_by_default: bool = Field(default=False, description="Whether provider is enabled by default in UI")
    requires_api_key: bool = Field(default=True, description="Whether using provider requires API key")
    models: list[ProviderModelInfo] = Field(default_factory=list, description="Configured model options")
    model_config = ConfigDict(extra="forbid")


class ProviderCatalogResponse(BaseModel):
    providers: list[ProviderCatalogInfo] = Field(default_factory=list, description="Configured providers and their model catalogs")
    model_config = ConfigDict(extra="forbid")


class ProviderCatalogError(RuntimeError):
    pass


SUPPORTED_PROVIDERS = set(SUPPORTED_PROVIDER_IDS)


DEFAULT_PROVIDER_CATALOG = ProviderModelCatalogConfig.model_validate(
    {
        "providers": [
            {
                "id": "openai",
                "display_name": "OpenAI",
                "description": "OpenAI API models",
                "enabled_by_default": False,
                "requires_api_key": True,
                "models": [
                    {
                        "model_id": "gpt-5.2",
                        "display_name": "GPT-5.2",
                        "thinking_enabled": True,
                        "adaptive_thinking": {
                            "efforts": ["low", "medium", "high", "xhigh"],
                            "default_effort": "medium",
                        },
                    }
                ],
            },
            {
                "id": "anthropic",
                "display_name": "Anthropic",
                "description": "Claude models from Anthropic",
                "enabled_by_default": False,
                "requires_api_key": True,
                "models": [
                    {
                        "model_id": "claude-opus-4-6",
                        "display_name": "Claude Opus 4.6",
                        "thinking_enabled": True,
                        "supports_vision": True,
                        "adaptive_thinking": {
                            "efforts": ["low", "medium", "high", "max"],
                            "default_effort": "medium",
                        },
                    },
                    {
                        "model_id": "claude-sonnet-4-6",
                        "display_name": "Claude Sonnet 4.6",
                        "thinking_enabled": True,
                        "supports_vision": True,
                        "adaptive_thinking": {
                            "efforts": ["low", "medium", "high", "max"],
                            "default_effort": "medium",
                        },
                    },
                ],
            },
        ]
    }
)

ZAI_BASE_URL = "https://api.z.ai/api/paas/v4"
MINIMAX_BASE_URL = "https://api.minimax.io/v1"
EPFL_RCP_BASE_URL = "https://inference-rcp.epfl.ch/v1"


def _build_model_id(provider: str, model_id: str, tier: str | None = None) -> str:
    return f"{provider}:{model_id}:{tier or 'standard'}"


def _format_display_name(model_id: str) -> str:
    if model_id.startswith("gpt-"):
        return f"GPT-{model_id[4:]}"
    if model_id.startswith("claude-"):
        return model_id.replace("claude-", "Claude ").replace("-", " ").title()
    if model_id.startswith("gemini-"):
        return model_id.replace("gemini-", "Gemini ").replace("-", " ").title()
    if model_id.startswith("deepseek-"):
        return model_id.replace("deepseek-", "DeepSeek ").replace("-", " ").title()
    if model_id.startswith("kimi-"):
        return model_id.replace("kimi-", "Kimi ").replace("-", " ").title()
    if model_id.startswith("glm-"):
        return model_id.replace("glm-", "GLM-").upper()
    return model_id.replace("-", " ").title()


def _supports_vision(model_id: str) -> bool:
    lowered = model_id.lower()
    if "vision" in lowered:
        return True
    if lowered.endswith(("v", "v-preview")):
        return True
    if lowered.startswith(("gpt-4o", "gpt-4.1", "gpt-4.5")):
        return True
    return False


def _effective_catalog() -> ProviderModelCatalogConfig:
    configured = get_app_config().provider_models
    if configured.providers:
        return configured
    return DEFAULT_PROVIDER_CATALOG


def _iter_configured_models(provider: ProviderCatalogEntry) -> Iterable[ProviderModelInfo]:
    for model in provider.models:
        adaptive_efforts = list(model.adaptive_thinking.efforts) if model.adaptive_thinking else []
        default_effort = model.adaptive_thinking.default_effort if model.adaptive_thinking else None
        yield ProviderModelInfo(
            id=_build_model_id(provider.id, model.model_id),
            provider=provider.id,
            model_id=model.model_id,
            display_name=model.display_name or _format_display_name(model.model_id),
            description=model.description,
            supports_thinking=model.thinking_enabled,
            thinking_enabled=model.thinking_enabled,
            supports_vision=model.supports_vision or _supports_vision(model.model_id),
            supports_adaptive_thinking=bool(adaptive_efforts),
            adaptive_thinking_efforts=adaptive_efforts,
            default_thinking_effort=default_effort,
        )


def _get_provider_or_raise(provider: str) -> ProviderCatalogEntry:
    normalized = provider.lower()
    if normalized not in SUPPORTED_PROVIDERS:
        raise ProviderCatalogError(f"Unsupported provider: {provider}")
    provider_config = _effective_catalog().get_provider(normalized)
    if provider_config is None:
        raise ProviderCatalogError(f"Provider {provider} is not allowed by config.")
    return provider_config


def get_provider_catalog() -> ProviderCatalogResponse:
    providers = []
    for provider in _effective_catalog().providers:
        models = sorted(_iter_configured_models(provider), key=lambda item: item.display_name.lower())
        providers.append(
            ProviderCatalogInfo(
                id=provider.id,
                display_name=provider.display_name or provider.id,
                description=provider.description,
                enabled_by_default=provider.enabled_by_default,
                requires_api_key=provider.requires_api_key,
                models=models,
            )
        )
    return ProviderCatalogResponse(providers=providers)


async def list_provider_models(provider: str, api_key: str | None, base_url: str | None = None) -> list[ProviderModelInfo]:
    provider_config = _get_provider_or_raise(provider)
    return sorted(_iter_configured_models(provider_config), key=lambda item: item.display_name.lower())


def _first_catalog_model_id(provider: str) -> str | None:
    provider_config = _effective_catalog().get_provider(provider)
    if provider_config and provider_config.models:
        return provider_config.models[0].model_id
    return None


def _provider_base_url(provider: str, base_url: str | None) -> str | None:
    if base_url:
        return base_url
    if provider == "zai":
        return ZAI_BASE_URL
    if provider == "minimax":
        return MINIMAX_BASE_URL
    if provider == "epfl-rcp":
        return EPFL_RCP_BASE_URL
    if provider == "openai":
        return "https://api.openai.com/v1"
    if provider == "deepseek":
        return "https://api.deepseek.com/v1"
    if provider == "kimi":
        return "https://api.moonshot.ai/v1"
    return None


async def _validate_openai_models_endpoint(provider: str, api_key: str, base_url: str | None) -> None:
    probe_base = _provider_base_url(provider, base_url) or ""
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.get(
            f"{probe_base.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()


async def _validate_anthropic_models_endpoint(api_key: str) -> None:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        response.raise_for_status()


async def _validate_gemini_models_endpoint(api_key: str) -> None:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key},
        )
        response.raise_for_status()


async def _validate_chat_completions_endpoint(provider: str, api_key: str, base_url: str | None) -> None:
    probe_base = _provider_base_url(provider, base_url)
    if not probe_base:
        raise ProviderCatalogError(f"No base URL configured for provider {provider}")
    probe_model = _first_catalog_model_id(provider)
    if not probe_model:
        raise ProviderCatalogError(f"Provider {provider} has no configured models for validation probe.")
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{probe_base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": probe_model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
        )
        response.raise_for_status()


async def validate_provider_key(provider: str, api_key: str | None, base_url: str | None = None) -> tuple[bool, str]:
    if not api_key:
        return False, "API key is required."
    normalized = provider.lower()
    try:
        _get_provider_or_raise(normalized)
    except ProviderCatalogError as exc:
        return False, str(exc)

    try:
        if normalized in {"openai", "deepseek", "kimi"}:
            await _validate_openai_models_endpoint(normalized, api_key, base_url)
        elif normalized == "anthropic":
            await _validate_anthropic_models_endpoint(api_key)
        elif normalized == "gemini":
            await _validate_gemini_models_endpoint(api_key)
        elif normalized in {"zai", "minimax", "epfl-rcp"}:
            await _validate_chat_completions_endpoint(normalized, api_key, base_url)
        else:
            return False, f"Unsupported provider: {provider}"
        return True, "API key is valid."
    except httpx.HTTPError as exc:
        return False, f"API request failed: {exc}"
    except ProviderCatalogError as exc:
        return False, str(exc)

