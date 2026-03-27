import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import yaml

from deerflow.config.app_config import AppConfig, reload_app_config
from deerflow.config.model_config import ModelConfig
from deerflow.config.model_services_config import (
    ModelServiceDefaults,
    ModelServiceModelConfig,
    ModelServiceProviderConfig,
    ModelServicesConfig,
    build_provider_model_name,
    get_model_services_config,
    list_registered_models,
    normalize_provider_key,
    reload_model_services_config,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/model-services", tags=["model-services"])


class ModelServiceModelResponse(BaseModel):
    id: str
    name: str
    display_name: str | None = None
    model: str
    enabled: bool = True
    modalities: list[str] = Field(default_factory=list)
    supports_thinking: bool = False
    supports_reasoning_effort: bool = False
    supports_vision: bool = False
    use_responses_api: bool | None = None
    output_version: str | None = None
    extra_body: dict[str, Any] | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    description: str | None = None


class ModelServiceProviderResponse(BaseModel):
    id: str
    name: str
    provider_type: str
    enabled: bool = True
    base_url: str = ""
    api_key_masked: str | None = None
    api_key_configured: bool = False
    headers: dict[str, str] = Field(default_factory=dict)
    homepage: str | None = None
    notes: str | None = None
    modalities: list[str] = Field(default_factory=list)
    models: list[ModelServiceModelResponse] = Field(default_factory=list)


class RegisteredModelResponse(BaseModel):
    id: str
    name: str
    display_name: str | None = None
    model: str
    description: str | None = None
    provider: str | None = None
    provider_label: str | None = None
    provider_url: str | None = None
    provider_id: str | None = None
    modalities: list[str] = Field(default_factory=list)
    supports_thinking: bool = False
    supports_reasoning_effort: bool = False
    supports_vision: bool = False
    enabled: bool = True
    source: str


class ModelServicesResponse(BaseModel):
    providers: list[ModelServiceProviderResponse] = Field(default_factory=list)
    defaults: ModelServiceDefaults = Field(default_factory=ModelServiceDefaults)
    registered_models: list[RegisteredModelResponse] = Field(default_factory=list)


class ProviderTestResponse(BaseModel):
    ok: bool
    models_url_ok: bool = False
    chat_ok: bool = False
    discovered_models: list[str] = Field(default_factory=list)
    message: str = ""


class DiscoveredModelResponse(BaseModel):
    id: str
    display_name: str
    owned_by: str | None = None
    already_configured: bool = False


class DiscoveredModelsResponse(BaseModel):
    models: list[DiscoveredModelResponse] = Field(default_factory=list)


def _provider_to_response(provider: ModelServiceProviderConfig) -> ModelServiceProviderResponse:
    return ModelServiceProviderResponse(
        id=provider.id,
        name=provider.name,
        provider_type=provider.provider_type,
        enabled=provider.enabled,
        base_url=provider.base_url,
        api_key_masked=provider.masked_api_key(),
        api_key_configured=bool(provider.api_key),
        headers=provider.headers,
        homepage=provider.homepage,
        notes=provider.notes,
        modalities=list(provider.modalities),
        models=[ModelServiceModelResponse(**model.model_dump()) for model in provider.models],
    )


def _load_static_models() -> list[ModelConfig]:
    config_path = AppConfig.resolve_config_path()
    with open(config_path, encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}
    resolved = AppConfig.resolve_env_variables(config_data)
    return [ModelConfig.model_validate(model) for model in resolved.get("models", [])]


def _build_response(config: ModelServicesConfig | None = None) -> ModelServicesResponse:
    config = config or get_model_services_config()
    static_models = _load_static_models()
    return ModelServicesResponse(
        providers=[_provider_to_response(provider) for provider in config.providers],
        defaults=config.defaults,
        registered_models=[RegisteredModelResponse(**item) for item in list_registered_models(static_models, config)],
    )


def _save_and_reload(config: ModelServicesConfig, path: str | Path | None = None) -> ModelServicesConfig:
    saved_path = config.to_file(path)
    reloaded = reload_model_services_config(str(saved_path))
    reload_app_config()
    return reloaded


def _validate_model_services(config: ModelServicesConfig) -> None:
    provider_ids = [provider.id for provider in config.providers]
    if len(provider_ids) != len(set(provider_ids)):
        raise HTTPException(status_code=400, detail="Provider ids must be unique")

    static_model_names = {model.name for model in _load_static_models()}
    model_names: list[str] = []
    for provider in config.providers:
        model_names.extend(model.name for model in provider.models)
    if len(model_names) != len(set(model_names)):
        raise HTTPException(status_code=400, detail="Model names must be globally unique")
    duplicate_static_names = sorted(static_model_names & set(model_names))
    if duplicate_static_names:
        duplicate_list = ", ".join(duplicate_static_names)
        raise HTTPException(
            status_code=400,
            detail=f"Model names conflict with config.yaml: {duplicate_list}",
        )

    registered_names = set(model_names) | static_model_names
    for field_name in ("text_model_name", "image_model_name", "video_model_name", "audio_model_name"):
        value = getattr(config.defaults, field_name)
        if value and value not in registered_names:
            raise HTTPException(status_code=400, detail=f"Default model '{value}' for {field_name} does not exist")


def _request_json(url: str, method: str = "GET", headers: dict[str, str] | None = None, body: dict[str, Any] | None = None) -> Any:
    request_headers = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, headers=request_headers, data=data, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _provider_request_headers(provider: ModelServiceProviderConfig) -> dict[str, str]:
    headers = dict(provider.headers)
    if provider.api_key:
        headers.setdefault("Authorization", f"Bearer {provider.api_key}")
    return headers


def _normalize_base_url(base_url: str, suffix: str) -> str:
    return f"{base_url.rstrip('/')}/{suffix.lstrip('/')}"


def _get_provider_for_openai_requests(
    provider_id: str,
) -> ModelServiceProviderConfig:
    config = get_model_services_config()
    provider = config.get_provider(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    if provider.provider_type != "openai-compatible":
        raise HTTPException(status_code=400, detail="Only openai-compatible providers are supported in this version")
    if not provider.base_url:
        raise HTTPException(status_code=400, detail="Provider base_url is required")
    return provider


def _discover_provider_models(
    provider: ModelServiceProviderConfig,
) -> list[DiscoveredModelResponse]:
    try:
        models_payload = _request_json(
            _normalize_base_url(provider.base_url, "/models"),
            headers=_provider_request_headers(provider),
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to discover models: {exc.code} {detail}".strip(),
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to discover models: {exc}") from exc

    existing_model_ids = {model.model for model in provider.models}
    discovered: list[DiscoveredModelResponse] = []
    for item in models_payload.get("data", []):
        model_id = item.get("id")
        if not model_id:
            continue
        discovered.append(
            DiscoveredModelResponse(
                id=model_id,
                display_name=item.get("display_name")
                or item.get("name")
                or model_id,
                owned_by=item.get("owned_by") or item.get("provider"),
                already_configured=model_id in existing_model_ids,
            )
        )

    return sorted(
        discovered,
        key=lambda item: (
            (item.owned_by or "").lower(),
            item.display_name.lower(),
            item.id.lower(),
        ),
    )


@router.get("", response_model=ModelServicesResponse)
async def get_model_services() -> ModelServicesResponse:
    return _build_response()


@router.put("", response_model=ModelServicesResponse)
async def put_model_services(request: ModelServicesConfig) -> ModelServicesResponse:
    config = get_model_services_config()
    merged_providers: list[ModelServiceProviderConfig] = []
    for incoming in request.providers:
        existing = config.get_provider(incoming.id)
        if existing and incoming.api_key_mode == "preserve":
            incoming.api_key = existing.api_key
        elif incoming.api_key_mode == "clear":
            incoming.api_key = ""
        elif incoming.api_key_mode == "replace":
            incoming.api_key = incoming.api_key or ""
        merged_providers.append(incoming)

    next_config = ModelServicesConfig(providers=merged_providers, defaults=request.defaults)
    _validate_model_services(next_config)
    reloaded = _save_and_reload(next_config)
    return _build_response(reloaded)


@router.post("/providers", response_model=ModelServiceProviderResponse)
async def create_provider(request: ModelServiceProviderConfig) -> ModelServiceProviderResponse:
    config = get_model_services_config()
    if config.get_provider(request.id):
        raise HTTPException(status_code=409, detail=f"Provider '{request.id}' already exists")
    if request.api_key_mode == "clear":
        request.api_key = ""
    next_config = config.model_copy(deep=True)
    next_config.providers.append(request)
    _validate_model_services(next_config)
    reloaded = _save_and_reload(next_config)
    provider = reloaded.get_provider(request.id)
    return _provider_to_response(provider)


@router.patch("/providers/{provider_id}", response_model=ModelServiceProviderResponse)
async def update_provider(provider_id: str, request: ModelServiceProviderConfig) -> ModelServiceProviderResponse:
    config = get_model_services_config()
    existing = config.get_provider(provider_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    updated = request.model_copy(deep=True)
    updated.id = provider_id
    if request.api_key_mode == "preserve":
        updated.api_key = existing.api_key
    elif request.api_key_mode == "clear":
        updated.api_key = ""
    else:
        updated.api_key = request.api_key or ""
    next_config = config.model_copy(deep=True)
    next_config.upsert_provider(updated)
    _validate_model_services(next_config)
    reloaded = _save_and_reload(next_config)
    return _provider_to_response(reloaded.get_provider(provider_id))


@router.delete("/providers/{provider_id}", response_model=ModelServicesResponse)
async def delete_provider(provider_id: str) -> ModelServicesResponse:
    config = get_model_services_config()
    next_config = config.model_copy(deep=True)
    if not next_config.delete_provider(provider_id):
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    reloaded = _save_and_reload(next_config)
    return _build_response(reloaded)


@router.patch("/defaults", response_model=ModelServicesResponse)
async def update_defaults(request: ModelServiceDefaults) -> ModelServicesResponse:
    config = get_model_services_config()
    next_config = config.model_copy(deep=True)
    next_config.defaults = request
    _validate_model_services(next_config)
    reloaded = _save_and_reload(next_config)
    return _build_response(reloaded)


@router.post("/providers/{provider_id}/test", response_model=ProviderTestResponse)
async def test_provider(provider_id: str) -> ProviderTestResponse:
    provider = _get_provider_for_openai_requests(provider_id)

    headers = _provider_request_headers(provider)
    try:
        models_payload = _request_json(_normalize_base_url(provider.base_url, "/models"), headers=headers)
        discovered_models = [item.get("id", "") for item in models_payload.get("data", []) if item.get("id")]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return ProviderTestResponse(ok=False, message=f"/models failed: {exc.code} {detail}".strip())
    except Exception as exc:
        return ProviderTestResponse(ok=False, message=f"/models failed: {exc}")

    model_id = next((model.model for model in provider.models if model.enabled and "text" in model.modalities), None)
    if model_id is None:
        model_id = discovered_models[0] if discovered_models else None
    if model_id is None:
        return ProviderTestResponse(ok=False, models_url_ok=True, discovered_models=discovered_models, message="No text model available for chat test")

    try:
        _request_json(
            _normalize_base_url(provider.base_url, "/chat/completions"),
            method="POST",
            headers=headers,
            body={
                "model": model_id,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 8,
            },
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return ProviderTestResponse(
            ok=False,
            models_url_ok=True,
            discovered_models=discovered_models,
            message=f"/chat/completions failed: {exc.code} {detail}".strip(),
        )
    except Exception as exc:
        return ProviderTestResponse(
            ok=False,
            models_url_ok=True,
            discovered_models=discovered_models,
            message=f"/chat/completions failed: {exc}",
        )

    return ProviderTestResponse(
        ok=True,
        models_url_ok=True,
        chat_ok=True,
        discovered_models=discovered_models,
        message="Provider connection test succeeded",
    )


@router.post("/providers/{provider_id}/sync-models", response_model=ModelServiceProviderResponse)
async def sync_provider_models(provider_id: str) -> ModelServiceProviderResponse:
    config = get_model_services_config()
    provider = _get_provider_for_openai_requests(provider_id)

    try:
        models_payload = _request_json(
            _normalize_base_url(provider.base_url, "/models"),
            headers=_provider_request_headers(provider),
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=400, detail=f"Failed to sync models: {exc.code} {detail}".strip()) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to sync models: {exc}") from exc

    discovered = [item.get("id", "") for item in models_payload.get("data", []) if item.get("id")]
    existing_by_model = {model.model: model for model in provider.models}
    all_names = {item["name"] for item in list_registered_models(_load_static_models(), config)}
    merged_models: list[ModelServiceModelConfig] = []

    for model_id in discovered:
        existing = existing_by_model.get(model_id)
        if existing is not None:
            merged_models.append(existing)
            continue
        generated_name = build_provider_model_name(provider.id, model_id, all_names)
        all_names.add(generated_name)
        merged_models.append(
            ModelServiceModelConfig(
                id=generated_name,
                name=generated_name,
                display_name=model_id,
                model=model_id,
                enabled=True,
                modalities=["text"],
            )
        )

    # preserve any local-only models that were not returned by /models
    for model in provider.models:
        if model.model not in discovered:
            merged_models.append(model)

    updated_provider = provider.model_copy(deep=True)
    updated_provider.models = merged_models
    next_config = config.model_copy(deep=True)
    next_config.upsert_provider(updated_provider)
    _validate_model_services(next_config)
    reloaded = _save_and_reload(next_config)
    return _provider_to_response(reloaded.get_provider(provider_id))


@router.post(
    "/providers/{provider_id}/discover-models",
    response_model=DiscoveredModelsResponse,
)
async def discover_provider_models(provider_id: str) -> DiscoveredModelsResponse:
    provider = _get_provider_for_openai_requests(provider_id)
    return DiscoveredModelsResponse(models=_discover_provider_models(provider))
