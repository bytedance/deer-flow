import logging
import re
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig, reload_app_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["models"])

OPENAI_COMPATIBLE_USE = "langchain_openai:ChatOpenAI"
CAPABILITY_CONTEXT_KEYS = (
    "context_length",
    "context_window",
    "max_context_length",
    "max_context_tokens",
    "max_input_tokens",
    "input_token_limit",
    "n_ctx",
)


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


class DetectedModelResponse(BaseModel):
    """Model discovered from an OpenAI-compatible /models endpoint."""

    id: str
    name: str
    display_name: str
    context_length: int | None = None
    modalities: list[str] = Field(default_factory=list)
    supports_thinking: bool = False
    supports_reasoning_effort: bool = False
    supports_vision: bool = False


class DetectModelsRequest(BaseModel):
    """Request for probing an OpenAI-compatible provider."""

    base_url: str = Field(..., description="OpenAI-compatible base URL")
    api_key: str | None = Field(default=None, description="API key used only for the detection request")


class DetectModelsResponse(BaseModel):
    """Response for OpenAI-compatible model detection."""

    models: list[DetectedModelResponse]
    endpoint: str


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
    system_prompt: str | None = None
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


def _first_int(payload: dict[str, Any]) -> int | None:
    for key in CAPABILITY_CONTEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    for nested_key in ("info", "metadata", "details", "capabilities"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            value = _first_int(nested)
            if value is not None:
                return value
    return None


def _extract_modalities(payload: dict[str, Any], model_id: str) -> list[str]:
    raw_values: list[Any] = []
    for key in ("modalities", "input_modalities", "output_modalities"):
        value = payload.get(key)
        if isinstance(value, list):
            raw_values.extend(value)
    capabilities = payload.get("capabilities")
    if isinstance(capabilities, dict):
        for key, enabled in capabilities.items():
            if enabled is True:
                raw_values.append(key)
    modalities = {str(value).lower() for value in raw_values if isinstance(value, str)}
    if not modalities:
        modalities.add("text")
    if "vision" in model_id.lower() or "image" in model_id.lower():
        modalities.add("vision")
    return sorted(modalities)


def _detect_reasoning_effort(model_id: str) -> bool:
    lowered = model_id.lower()
    return lowered.startswith(("o1", "o3", "o4")) or lowered.startswith("gpt-5")


def _detect_thinking(model_id: str) -> bool:
    lowered = model_id.lower()
    return _detect_reasoning_effort(model_id) or any(marker in lowered for marker in ("reason", "thinking", "deepseek-r1", "qwen3"))


def _model_payload_to_detected(payload: dict[str, Any]) -> DetectedModelResponse | None:
    raw_id = payload.get("id") or payload.get("name")
    if not isinstance(raw_id, str) or not raw_id.strip():
        return None
    model_id = raw_id.strip()
    display_name = payload.get("display_name") or payload.get("name") or model_id
    modalities = _extract_modalities(payload, model_id)
    return DetectedModelResponse(
        id=model_id,
        name=_slugify_model_name(model_id),
        display_name=str(display_name),
        context_length=_first_int(payload),
        modalities=modalities,
        supports_thinking=_detect_thinking(model_id),
        supports_reasoning_effort=_detect_reasoning_effort(model_id),
        supports_vision=bool({"vision", "image"} & set(modalities)),
    )


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
        "system_prompt": request.system_prompt,
        "supports_thinking": request.supports_thinking,
        "supports_reasoning_effort": request.supports_reasoning_effort,
        "supports_vision": request.supports_vision,
        "modalities": request.modalities,
    }
    if existing and not request.api_key:
        config["api_key"] = existing.get("api_key")
    return {key: value for key, value in config.items() if value not in (None, "", [])}


async def _fetch_models(base_url: str, api_key: str | None) -> tuple[str, dict[str, Any]]:
    normalized_base = base_url.rstrip("/")
    candidates = [f"{normalized_base}/models"]
    if not normalized_base.endswith("/v1"):
        candidates.append(f"{normalized_base}/v1/models")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        for endpoint in candidates:
            try:
                response = await client.get(endpoint, headers=headers)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Provider returned a non-object response")
                return endpoint, data
            except Exception as exc:
                last_error = exc
                logger.debug("Model detection failed for %s: %s", endpoint, exc)
    raise HTTPException(status_code=502, detail=f"Failed to detect models: {last_error}")


@router.get(
    "/models",
    response_model=ModelsListResponse,
    summary="List All Models",
    description="Retrieve a list of all available AI models configured in the system.",
)
async def list_models() -> ModelsListResponse:
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
    config = get_app_config()
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
async def get_model(model_name: str) -> ModelResponse:
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
    config = get_app_config()
    model = config.get_model_config(model_name)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    return _public_model_response(model)


@router.post(
    "/models/detect",
    response_model=DetectModelsResponse,
    summary="Detect OpenAI-Compatible Models",
    description="Probe an OpenAI-compatible provider /models endpoint and return discovered model metadata.",
)
async def detect_models(request: DetectModelsRequest) -> DetectModelsResponse:
    endpoint, data = await _fetch_models(str(request.base_url), request.api_key)
    raw_models = data.get("data", data.get("models", []))
    if not isinstance(raw_models, list):
        raise HTTPException(status_code=502, detail="Provider response did not include a model list")
    models = [model for item in raw_models if isinstance(item, dict) and (model := _model_payload_to_detected(item))]
    return DetectModelsResponse(models=models, endpoint=endpoint)


@router.post(
    "/models",
    response_model=ModelResponse,
    summary="Create Model",
    description="Add an OpenAI-compatible model to config.yaml and reload the active configuration.",
)
async def create_model(request: ModelUpsertRequest) -> ModelResponse:
    config_path, data = _load_config_data()
    model_name = _slugify_model_name(request.name)
    if any(model.get("name") == model_name for model in data["models"] if isinstance(model, dict)):
        raise HTTPException(status_code=409, detail=f"Model '{model_name}' already exists")
    request.name = model_name
    data["models"].append(_request_to_config(request))
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
async def update_model(model_name: str, request: ModelUpsertRequest) -> ModelResponse:
    config_path, data = _load_config_data()
    index = next((idx for idx, model in enumerate(data["models"]) if isinstance(model, dict) and model.get("name") == model_name), None)
    if index is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")
    request.name = _slugify_model_name(request.name)
    data["models"][index] = _request_to_config(request, data["models"][index])
    _write_config_data(config_path, data)
    model = get_app_config().get_model_config(request.name)
    if model is None:
        raise HTTPException(status_code=500, detail=f"Model '{request.name}' was saved but could not be reloaded")
    return _public_model_response(model)


@router.delete(
    "/models/{model_name}",
    summary="Delete Model",
    description="Remove a model from config.yaml and reload the active configuration.",
)
async def delete_model(model_name: str) -> dict[str, str]:
    config_path, data = _load_config_data()
    original_len = len(data["models"])
    data["models"] = [model for model in data["models"] if not (isinstance(model, dict) and model.get("name") == model_name)]
    if len(data["models"]) == original_len:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")
    _write_config_data(config_path, data)
    return {"status": "ok"}
