"""Provider-first model services configuration."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from deerflow.config.model_config import ModelConfig

ProviderType = Literal[
    "openai-compatible",
    "anthropic-native",
    "gemini-native",
    "custom",
]
ProviderModality = Literal["text", "image", "video", "audio"]
ApiKeyMode = Literal["preserve", "replace", "clear"]


class ModelServiceModelConfig(BaseModel):
    """Provider-owned model configuration managed by the UI."""

    id: str
    name: str
    display_name: str | None = None
    model: str
    enabled: bool = True
    modalities: list[ProviderModality] = Field(default_factory=lambda: ["text"])
    supports_thinking: bool = False
    supports_reasoning_effort: bool = False
    supports_vision: bool = False
    use_responses_api: bool | None = None
    output_version: str | None = None
    extra_body: dict[str, Any] | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    description: str | None = None
    model_config = ConfigDict(extra="allow")


class ModelServiceProviderConfig(BaseModel):
    """Provider configuration."""

    id: str
    name: str
    provider_type: ProviderType = "openai-compatible"
    enabled: bool = True
    base_url: str = ""
    api_key: str = ""
    api_key_mode: ApiKeyMode = "preserve"
    headers: dict[str, str] = Field(default_factory=dict)
    homepage: str | None = None
    notes: str | None = None
    modalities: list[ProviderModality] = Field(default_factory=lambda: ["text"])
    models: list[ModelServiceModelConfig] = Field(default_factory=list)
    model_config = ConfigDict(extra="allow")

    def masked_api_key(self) -> str | None:
        if not self.api_key:
            return None
        if len(self.api_key) <= 8:
            return "*" * len(self.api_key)
        return f"{self.api_key[:4]}{'*' * max(4, len(self.api_key) - 8)}{self.api_key[-4:]}"


class ModelServiceDefaults(BaseModel):
    text_model_name: str | None = None
    image_model_name: str | None = None
    video_model_name: str | None = None
    audio_model_name: str | None = None


class ModelServicesConfig(BaseModel):
    providers: list[ModelServiceProviderConfig] = Field(default_factory=list)
    defaults: ModelServiceDefaults = Field(default_factory=ModelServiceDefaults)

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path | None:
        if config_path:
            path = Path(config_path)
            return path

        if os.getenv("DEER_FLOW_MODEL_SERVICES_CONFIG_PATH"):
            path = Path(os.getenv("DEER_FLOW_MODEL_SERVICES_CONFIG_PATH"))
            return path

        current = Path(os.getcwd()) / "model_services.json"
        if current.exists():
            return current

        parent = Path(os.getcwd()).parent / "model_services.json"
        if parent.exists():
            return parent

        return None

    @classmethod
    def default_write_path(cls) -> Path:
        if env_path := os.getenv("DEER_FLOW_MODEL_SERVICES_CONFIG_PATH"):
            return Path(env_path)
        cwd = Path(os.getcwd())
        if (cwd / "config.yaml").exists():
            return cwd / "model_services.json"
        if (cwd.parent / "config.yaml").exists():
            return cwd.parent / "model_services.json"
        return cwd / "model_services.json"

    @classmethod
    def from_file(cls, config_path: str | None = None) -> "ModelServicesConfig":
        resolved_path = cls.resolve_config_path(config_path)
        if resolved_path is None or not resolved_path.exists():
            return cls()

        with open(resolved_path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    def to_file(self, config_path: str | Path | None = None) -> Path:
        path = Path(config_path) if config_path is not None else self.default_write_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(mode="json", exclude_none=True), f, indent=2)
        return path

    def get_provider(self, provider_id: str) -> ModelServiceProviderConfig | None:
        return next((provider for provider in self.providers if provider.id == provider_id), None)

    def upsert_provider(self, provider: ModelServiceProviderConfig) -> None:
        existing = self.get_provider(provider.id)
        if existing is None:
            self.providers.append(provider)
            return
        index = self.providers.index(existing)
        self.providers[index] = provider

    def delete_provider(self, provider_id: str) -> bool:
        provider = self.get_provider(provider_id)
        if provider is None:
            return False
        self.providers.remove(provider)
        defaults = self.defaults
        for field_name in ("text_model_name", "image_model_name", "video_model_name", "audio_model_name"):
            model_name = getattr(defaults, field_name)
            if model_name and any(model.name == model_name for model in provider.models):
                setattr(defaults, field_name, None)
        return True

    def all_provider_model_names(self) -> set[str]:
        return {model.name for provider in self.providers for model in provider.models}

    def all_enabled_provider_models(self) -> list[tuple[ModelServiceProviderConfig, ModelServiceModelConfig]]:
        return [
            (provider, model)
            for provider in self.providers
            if provider.enabled
            for model in provider.models
            if model.enabled
        ]


def model_services_to_runtime_models(
    base_models: list[ModelConfig],
    model_services: ModelServicesConfig,
) -> list[ModelConfig]:
    """Merge static config models with enabled provider text models."""

    static_names = {model.name for model in base_models}
    provider_model_names = [model.name for provider in model_services.providers for model in provider.models]
    if len(provider_model_names) != len(set(provider_model_names)):
        duplicates = sorted({name for name in provider_model_names if provider_model_names.count(name) > 1})
        duplicate_list = ", ".join(duplicates)
        raise ValueError(f"Duplicate model.name values found inside model_services.json: {duplicate_list}")
    provider_names = set(provider_model_names)
    duplicates = static_names & provider_names
    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates))
        raise ValueError(f"Duplicate model.name values found between config.yaml and model_services.json: {duplicate_list}")

    runtime_models = list(base_models)
    for provider, model in model_services.all_enabled_provider_models():
        if provider.provider_type != "openai-compatible":
            continue
        if "text" not in model.modalities:
            continue
        runtime_models.append(
            ModelConfig(
                name=model.name,
                display_name=model.display_name or model.name,
                description=model.description,
                use="langchain_openai:ChatOpenAI",
                model=model.model,
                provider=normalize_provider_key(provider.name),
                provider_label=provider.name,
                provider_url=provider.homepage,
                modalities=list(model.modalities),
                supports_thinking=model.supports_thinking,
                supports_reasoning_effort=model.supports_reasoning_effort,
                supports_vision=model.supports_vision or "image" in model.modalities,
                use_responses_api=model.use_responses_api,
                output_version=model.output_version,
                base_url=provider.base_url,
                api_key=provider.api_key,
                default_headers=provider.headers or None,
                extra_body=model.extra_body,
                max_tokens=model.max_tokens,
                temperature=model.temperature,
            )
        )

    default_text = model_services.defaults.text_model_name
    if default_text:
        runtime_models.sort(key=lambda model: (model.name != default_text, model.display_name or model.name))

    return runtime_models


def list_registered_models(
    base_models: list[ModelConfig],
    model_services: ModelServicesConfig,
) -> list[dict[str, Any]]:
    """Return all registered models for UI usage.

    Static config models are always treated as enabled text models.
    Provider-managed models preserve their enabled/modalities flags.
    """

    static_names = {model.name for model in base_models}
    provider_model_names = [model.name for provider in model_services.providers for model in provider.models]
    if len(provider_model_names) != len(set(provider_model_names)):
        duplicates = sorted({name for name in provider_model_names if provider_model_names.count(name) > 1})
        duplicate_list = ", ".join(duplicates)
        raise ValueError(f"Duplicate model.name values found inside model_services.json: {duplicate_list}")
    provider_names = set(provider_model_names)
    duplicates = static_names & provider_names
    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates))
        raise ValueError(f"Duplicate model.name values found between config.yaml and model_services.json: {duplicate_list}")

    registered: list[dict[str, Any]] = []
    for model in base_models:
        registered.append(
            {
                "id": model.name,
                "name": model.name,
                "display_name": model.display_name or model.name,
                "model": model.model,
                "description": model.description,
                "provider": model.provider,
                "provider_label": model.provider_label,
                "provider_url": model.provider_url,
                "modalities": list(model.modalities or ["text"]),
                "supports_thinking": model.supports_thinking,
                "supports_reasoning_effort": model.supports_reasoning_effort,
                "supports_vision": model.supports_vision,
                "enabled": True,
                "source": "config",
                "provider_id": None,
            }
        )

    for provider in model_services.providers:
        for model in provider.models:
            registered.append(
                {
                    "id": model.id,
                    "name": model.name,
                    "display_name": model.display_name or model.name,
                    "model": model.model,
                    "description": model.description,
                    "provider": normalize_provider_key(provider.name),
                    "provider_label": provider.name,
                    "provider_url": provider.homepage,
                    "modalities": list(model.modalities),
                    "supports_thinking": model.supports_thinking,
                    "supports_reasoning_effort": model.supports_reasoning_effort,
                    "supports_vision": model.supports_vision,
                    "enabled": provider.enabled and model.enabled,
                    "source": "provider",
                    "provider_id": provider.id,
                }
            )

    return registered


def resolve_modality_model_name(
    modality: ProviderModality,
    app_config_models: list[ModelConfig],
    model_services: ModelServicesConfig,
) -> str:
    if modality == "text":
        if model_services.defaults.text_model_name:
            return model_services.defaults.text_model_name
        if app_config_models:
            return app_config_models[0].name
        raise ValueError("No enabled text model configured")

    default_name = getattr(model_services.defaults, f"{modality}_model_name")
    if default_name:
        return default_name

    for _, model in model_services.all_enabled_provider_models():
        if modality in model.modalities:
            return model.name

    raise ValueError(f"No enabled {modality} model configured")


def normalize_provider_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "provider"


def build_provider_model_name(provider_id: str, model_id: str, existing_names: set[str]) -> str:
    base = normalize_provider_key(f"{provider_id}-{model_id}")
    candidate = base
    suffix = 2
    while candidate in existing_names:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


_model_services_config: ModelServicesConfig | None = None
_model_services_config_path: Path | None = None
_model_services_config_mtime: float | None = None


def _get_config_mtime(path: Path | None) -> float | None:
    if path is None:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def get_model_services_config() -> ModelServicesConfig:
    global _model_services_config, _model_services_config_path, _model_services_config_mtime

    resolved_path = ModelServicesConfig.resolve_config_path()
    current_mtime = _get_config_mtime(resolved_path)
    should_reload = (
        _model_services_config is None
        or _model_services_config_path != resolved_path
        or _model_services_config_mtime != current_mtime
    )
    if should_reload:
        _model_services_config = ModelServicesConfig.from_file()
        _model_services_config_path = resolved_path
        _model_services_config_mtime = current_mtime
    return _model_services_config


def reload_model_services_config(config_path: str | None = None) -> ModelServicesConfig:
    global _model_services_config, _model_services_config_path, _model_services_config_mtime
    _model_services_config = ModelServicesConfig.from_file(config_path)
    _model_services_config_path = ModelServicesConfig.resolve_config_path(config_path)
    _model_services_config_mtime = _get_config_mtime(_model_services_config_path)
    return _model_services_config


def reset_model_services_config() -> None:
    global _model_services_config, _model_services_config_path, _model_services_config_mtime
    _model_services_config = None
    _model_services_config_path = None
    _model_services_config_mtime = None
