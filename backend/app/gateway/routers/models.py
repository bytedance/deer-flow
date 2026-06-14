import logging
import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig, reload_app_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["models"])

OPENAI_COMPATIBLE_USE = "langchain_openai:ChatOpenAI"


class ModelResponse(BaseModel):
    """Response model for model information."""

    name: str = Field(..., description="Unique identifier for the model")
    model: str = Field(..., description="Actual provider model identifier")
    display_name: str | None = Field(None, description="Human-readable name")
    description: str | None = Field(None, description="Model description")
    base_url: str | None = Field(None, description="OpenAI-compatible provider base URL")
    context_length: int | None = Field(None, description="Context window size, when known")
    modalities: list[str] = Field(default_factory=list, description="Supported modalities, when known")
    supports_thinking: bool = Field(default=False, description="Whether model supports thinking mode")
    supports_reasoning_effort: bool = Field(default=False, description="Whether model supports reasoning effort")
    supports_vision: bool = Field(default=False, description="Whether model supports vision/image inputs")


class TokenUsageResponse(BaseModel):
    """Token usage display configuration."""

    enabled: bool = Field(default=False, description="Whether token usage display is enabled")


class ModelsListResponse(BaseModel):
    """Response model for listing all models."""

    models: list[ModelResponse]
    token_usage: TokenUsageResponse


class ModelUpsertRequest(BaseModel):
    """Request for creating or updating a UI-managed model."""

    name: str = Field(..., description="Unique DeerFlow model name")
    model: str = Field(..., description="Provider model identifier")
    display_name: str | None = None
    description: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    context_length: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    supports_thinking: bool = False
    supports_reasoning_effort: bool = False
    supports_vision: bool = False
    modalities: list[str] = Field(default_factory=list)


def _public_model_response(model: Any) -> ModelResponse:
    return ModelResponse(
        name=model.name,
        model=model.model,
        display_name=model.display_name,
        description=model.description,
        base_url=getattr(model, "base_url", None) or getattr(model, "openai_api_base", None),
        context_length=getattr(model, "context_length", None),
        modalities=getattr(model, "modalities", []) or [],
        supports_thinking=model.supports_thinking,
        supports_reasoning_effort=model.supports_reasoning_effort,
        supports_vision=getattr(model, "supports_vision", False),
    )


def _resolve_writable_config_path() -> Path:
    try:
        return AppConfig.resolve_config_path()
    except FileNotFoundError:
        return Path.cwd() / "config.yaml"


def _load_config_data() -> tuple[Path, dict[str, Any]]:
    config_path = _resolve_writable_config_path()
    if not config_path.exists():
        return config_path, {
            "config_version": 7,
            "log_level": "info",
            "models": [],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        }
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="config.yaml must contain a mapping at the top level")
    data.setdefault("models", [])
    if not isinstance(data["models"], list):
        raise HTTPException(status_code=500, detail="config.yaml models section must be a list")
    return config_path, data


def _write_config_data(config_path: Path, data: dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    reload_app_config(str(config_path))


def _slugify_model_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-").lower()
    return slug or "model"


def _request_to_config(request: ModelUpsertRequest, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {
        "name": request.name,
        "display_name": request.display_name or request.name,
        "description": request.description,
        "use": OPENAI_COMPATIBLE_USE,
        "model": request.model,
        "base_url": request.base_url,
        "api_key": request.api_key,
        "context_length": request.context_length,
        "temperature": request.temperature,
        "top_p": request.top_p,
        "frequency_penalty": request.frequency_penalty,
        "supports_thinking": request.supports_thinking,
        "supports_reasoning_effort": request.supports_reasoning_effort,
        "supports_vision": request.supports_vision,
        "modalities": request.modalities,
    }
    if existing and not request.api_key:
        config["api_key"] = existing.get("api_key")
    return {key: value for key, value in config.items() if value not in (None, "", [])}


@router.get(
    "/models",
    response_model=ModelsListResponse,
    summary="List All Models",
    description="Retrieve a list of all available AI models configured in the system.",
)
async def list_models(config: AppConfig = Depends(get_config)) -> ModelsListResponse:
    """List all available models from configuration.

    Returns model information suitable for frontend display,
    excluding sensitive fields like API keys and internal configuration.

    Returns:
        A list of all configured models with their metadata and token usage display settings.

    Example Response:
        ```json
        {
            "models": [
                {
                    "name": "gpt-4",
                    "model": "gpt-4",
                    "display_name": "GPT-4",
                    "description": "OpenAI GPT-4 model",
                    "supports_thinking": false,
                    "supports_reasoning_effort": false
                },
                {
                    "name": "claude-3-opus",
                    "model": "claude-3-opus",
                    "display_name": "Claude 3 Opus",
                    "description": "Anthropic Claude 3 Opus model",
                    "supports_thinking": true,
                    "supports_reasoning_effort": false
                }
            ],
            "token_usage": {
                "enabled": true
            }
        }
        ```
    """
    models = [_public_model_response(model) for model in config.models]
    return ModelsListResponse(
        models=models,
        token_usage=TokenUsageResponse(enabled=config.token_usage.enabled),
    )


@router.get(
    "/models/{model_name}",
    response_model=ModelResponse,
    summary="Get Model Details",
    description="Retrieve detailed information about a specific AI model by its name.",
)
async def get_model(model_name: str, config: AppConfig = Depends(get_config)) -> ModelResponse:
    """Get a specific model by name.

    Args:
        model_name: The unique name of the model to retrieve.

    Returns:
        Model information if found.

    Raises:
        HTTPException: 404 if model not found.

    Example Response:
        ```json
        {
            "name": "gpt-4",
            "display_name": "GPT-4",
            "description": "OpenAI GPT-4 model",
            "supports_thinking": false
        }
        ```
    """
    model = config.get_model_config(model_name)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    return _public_model_response(model)


@router.post(
    "/models",
    response_model=ModelResponse,
    summary="Create Model",
    description="Add an OpenAI-compatible model to config.yaml and reload the active configuration.",
)
@require_permission("models", "write")
async def create_model(body: ModelUpsertRequest, request: Request) -> ModelResponse:
    config_path, data = _load_config_data()
    model_name = _slugify_model_name(body.name)
    if any(model.get("name") == model_name for model in data["models"] if isinstance(model, dict)):
        raise HTTPException(status_code=409, detail=f"Model '{model_name}' already exists")
    body.name = model_name
    data["models"].append(_request_to_config(body))
    _write_config_data(config_path, data)
    model = get_app_config().get_model_config(model_name)
    if model is None:
        raise HTTPException(status_code=500, detail=f"Model '{model_name}' was saved but could not be reloaded")
    return _public_model_response(model)


@router.put(
    "/models/{model_name}",
    response_model=ModelResponse,
    summary="Update Model",
    description="Update a model in config.yaml and reload the active configuration.",
)
@require_permission("models", "write")
async def update_model(model_name: str, body: ModelUpsertRequest, request: Request) -> ModelResponse:
    config_path, data = _load_config_data()
    index = next((idx for idx, model in enumerate(data["models"]) if isinstance(model, dict) and model.get("name") == model_name), None)
    if index is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")
    body.name = _slugify_model_name(body.name)
    if body.name != model_name and any(model.get("name") == body.name for model in data["models"] if isinstance(model, dict)):
        raise HTTPException(status_code=409, detail=f"Model '{body.name}' already exists")
    data["models"][index] = _request_to_config(body, data["models"][index])
    _write_config_data(config_path, data)
    model = get_app_config().get_model_config(body.name)
    if model is None:
        raise HTTPException(status_code=500, detail=f"Model '{body.name}' was saved but could not be reloaded")
    return _public_model_response(model)


@router.delete(
    "/models/{model_name}",
    summary="Delete Model",
    description="Remove a model from config.yaml and reload the active configuration.",
)
@require_permission("models", "write")
async def delete_model(model_name: str, request: Request) -> dict[str, str]:
    config_path, data = _load_config_data()
    if len([model for model in data["models"] if isinstance(model, dict)]) <= 1:
        raise HTTPException(status_code=409, detail="Cannot delete the last configured model")
    original_len = len(data["models"])
    data["models"] = [model for model in data["models"] if not (isinstance(model, dict) and model.get("name") == model_name)]
    if len(data["models"]) == original_len:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")
    _write_config_data(config_path, data)
    return {"status": "ok"}
