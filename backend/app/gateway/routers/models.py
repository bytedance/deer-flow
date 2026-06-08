import asyncio
import ipaddress
import logging
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["models"])
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
    supports_thinking: bool = Field(default=False, description="Whether model supports thinking mode")
    supports_reasoning_effort: bool = Field(default=False, description="Whether model supports reasoning effort")


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


async def _validate_detection_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=422, detail="base_url must be an http(s) URL")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="base_url must not include credentials")

    host = parsed.hostname
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise HTTPException(status_code=422, detail=f"Unable to resolve base_url host: {host}") from exc

    for *_, sockaddr in addresses:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise HTTPException(status_code=422, detail="base_url host must resolve to a public address")


async def _fetch_models(base_url: str, api_key: str | None) -> tuple[str, dict[str, Any]]:
    await _validate_detection_base_url(base_url)
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
    exc_info = (type(last_error), last_error, last_error.__traceback__) if last_error else None
    logger.warning("Model detection failed for all candidate endpoints under %s", normalized_base, exc_info=exc_info)
    raise HTTPException(status_code=502, detail="Failed to detect models from provider")


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
    models = [
        ModelResponse(
            name=model.name,
            model=model.model,
            display_name=model.display_name,
            description=model.description,
            supports_thinking=model.supports_thinking,
            supports_reasoning_effort=model.supports_reasoning_effort,
        )
        for model in config.models
    ]
    return ModelsListResponse(
        models=models,
        token_usage=TokenUsageResponse(enabled=config.token_usage.enabled),
    )


@router.post(
    "/models/detect",
    response_model=DetectModelsResponse,
    summary="Detect OpenAI-Compatible Models",
    description="Probe an OpenAI-compatible provider /models endpoint and return discovered model metadata.",
)
@require_permission("models", "write")
async def detect_models(body: DetectModelsRequest, request: Request) -> DetectModelsResponse:
    endpoint, data = await _fetch_models(str(body.base_url), body.api_key)
    raw_models = data.get("data", data.get("models", []))
    if not isinstance(raw_models, list):
        raise HTTPException(status_code=502, detail="Provider response did not include a model list")
    models = [model for item in raw_models if isinstance(item, dict) and (model := _model_payload_to_detected(item))]
    return DetectModelsResponse(models=models, endpoint=endpoint)


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

    return ModelResponse(
        name=model.name,
        model=model.model,
        display_name=model.display_name,
        description=model.description,
        supports_thinking=model.supports_thinking,
        supports_reasoning_effort=model.supports_reasoning_effort,
    )
