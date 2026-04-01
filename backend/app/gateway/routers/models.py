import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from deerflow.config import get_app_config
from deerflow.config.model_config import ModelConfig
from deerflow.lm_studio import (
    decode_lm_studio_model_name,
    encode_lm_studio_model_name,
    ensure_lm_studio_model_loaded,
    fetch_lm_studio_model_ids_async,
    openai_base_url_to_rest_base,
)

router = APIRouter(prefix="/api", tags=["models"])
logger = logging.getLogger(__name__)


class ModelResponse(BaseModel):
    """Response model for model information."""

    name: str = Field(..., description="Unique identifier for the model")
    model: str = Field(..., description="Actual provider model identifier")
    display_name: str | None = Field(None, description="Human-readable name")
    description: str | None = Field(None, description="Model description")
    supports_thinking: bool = Field(default=False, description="Whether model supports thinking mode")
    supports_reasoning_effort: bool = Field(default=False, description="Whether model supports reasoning effort")


class ModelsListResponse(BaseModel):
    """Response model for listing all models."""

    models: list[ModelResponse]


class PrepareModelResponse(BaseModel):
    """Result of asking the backend to preload a local model (e.g. LM Studio)."""

    ok: bool = Field(..., description="Whether the prepare step completed without error")
    loaded: bool = Field(..., description="True if a request was sent to load weights locally")
    model: str | None = Field(None, description="Provider model id that was targeted, if any")


def _model_config_to_response(model: ModelConfig) -> ModelResponse:
    return ModelResponse(
        name=model.name,
        model=model.model,
        display_name=model.display_name,
        description=model.description,
        supports_thinking=model.supports_thinking,
        supports_reasoning_effort=model.supports_reasoning_effort,
    )


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
        A list of all configured models with their metadata.

    Example Response:
        ```json
        {
            "models": [
                {
                    "name": "gpt-4",
                    "display_name": "GPT-4",
                    "description": "OpenAI GPT-4 model",
                    "supports_thinking": false
                },
                {
                    "name": "claude-3-opus",
                    "display_name": "Claude 3 Opus",
                    "description": "Anthropic Claude 3 Opus model",
                    "supports_thinking": true
                }
            ]
        }
        ```
    """
    config = get_app_config()
    models: list[ModelResponse] = []
    for model in config.models:
        if getattr(model, "lm_studio_discovery", None) is True:
            openai_base = getattr(model, "base_url", None)
            api_key = getattr(model, "api_key", None)
            if not openai_base:
                continue
            try:
                ids = await fetch_lm_studio_model_ids_async(str(openai_base), str(api_key) if api_key else None)
                if not ids:
                    models.append(_model_config_to_response(model))
                    continue
                for mid in ids:
                    models.append(
                        ModelResponse(
                            name=encode_lm_studio_model_name(mid),
                            model=mid,
                            display_name=f"LM Studio · {mid}",
                            description=model.description,
                            supports_thinking=model.supports_thinking,
                            supports_reasoning_effort=model.supports_reasoning_effort,
                        )
                    )
            except Exception as e:
                logger.warning("LM Studio model discovery failed; using template row only: %s", e)
                models.append(_model_config_to_response(model))
            continue
        models.append(_model_config_to_response(model))

    return ModelsListResponse(models=models)


@router.post(
    "/models/{model_name}/prepare",
    response_model=PrepareModelResponse,
    summary="Prepare / load local model",
    description=(
        "For LM Studio-backed models, triggers POST /api/v1/models/load so weights are ready before chat. "
        "No-op for other providers."
    ),
)
async def prepare_model(model_name: str) -> PrepareModelResponse:
    config = get_app_config()
    mc = config.resolve_model_config(model_name)
    if mc is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    lm_id = decode_lm_studio_model_name(model_name)
    if lm_id is None and getattr(mc, "lm_studio_discovery", None) is True:
        lm_id = mc.model
    if lm_id is None:
        return PrepareModelResponse(ok=True, loaded=False, model=None)

    base_url = getattr(mc, "base_url", None)
    if not base_url:
        return PrepareModelResponse(ok=True, loaded=False, model=str(lm_id))

    api_key = getattr(mc, "api_key", None)
    try:

        def _load() -> None:
            ensure_lm_studio_model_loaded(
                rest_base_url=openai_base_url_to_rest_base(str(base_url)),
                model_id=str(lm_id),
                api_key=str(api_key) if api_key else None,
            )

        await run_in_threadpool(_load)
    except Exception as e:
        logger.warning("LM Studio prepare failed for %s: %s", lm_id, e)
        raise HTTPException(status_code=503, detail=f"LM Studio could not load model: {e!s}") from e

    return PrepareModelResponse(ok=True, loaded=True, model=str(lm_id))


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
    model = config.resolve_model_config(model_name)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    return ModelResponse(
        name=model_name,
        model=model.model,
        display_name=model.display_name,
        description=model.description,
        supports_thinking=model.supports_thinking,
        supports_reasoning_effort=model.supports_reasoning_effort,
    )
