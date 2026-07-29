import asyncio
import logging
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.deps import require_admin_user
from deerflow.config.app_config import AppConfig, config_yaml_write_lock, get_app_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["models"])

_ADMIN_REQUIRED_DETAIL = "Admin privileges required to manage model configurations."


# ---------------------------------------------------------------------------
# Public (lightweight) models
# ---------------------------------------------------------------------------


class ModelResponse(BaseModel):
    """Response model for model information (public, used by model picker)."""

    name: str = Field(..., description="Unique identifier for the model")
    model: str = Field(..., description="Actual provider model identifier")
    display_name: str | None = Field(None, description="Human-readable name")
    description: str | None = Field(None, description="Model description")
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


# ---------------------------------------------------------------------------
# Admin (full-config) models
# ---------------------------------------------------------------------------

_MASKED_VALUE = "***"


class FullModelConfig(BaseModel):
    """Full model configuration for admin settings UI.

    Includes every commonly-used model field. Arbitrary provider-specific
    extra fields are preserved through ``extra="allow"``.
    """

    name: str = Field(..., description="Unique name for the model")
    display_name: str | None = Field(None, description="Human-readable display name")
    description: str | None = Field(None, description="Optional description")
    use: str = Field(..., description="Provider class path (e.g. langchain_openai:ChatOpenAI)")
    model: str = Field(..., description="Provider model identifier")
    api_key: str | None = Field(None, description="API key (masked on GET; write a real value to store in .env)")
    api_base: str | None = Field(None, description="API base URL")
    base_url: str | None = Field(None, description="Base URL (used by some providers)")
    timeout: float | None = Field(None, description="Request timeout in seconds")
    request_timeout: float | None = Field(None, description="Request timeout (OpenAI-style providers)")
    max_retries: int | None = Field(None, description="Maximum retry attempts")
    max_tokens: int | None = Field(None, description="Maximum output tokens")
    temperature: float | None = Field(None, description="Sampling temperature")
    supports_vision: bool = Field(default=False, description="Whether model supports vision/image inputs")
    supports_thinking: bool = Field(default=False, description="Whether model supports thinking mode")
    supports_reasoning_effort: bool = Field(default=False, description="Whether model supports reasoning effort")
    when_thinking_enabled: dict | None = Field(None, description="Extra settings when thinking is enabled")
    when_thinking_disabled: dict | None = Field(None, description="Extra settings when thinking is disabled")
    model_config = ConfigDict(extra="allow")


class AdminModelsResponse(BaseModel):
    """Response model for admin model listing."""

    models: list[FullModelConfig]
    token_usage: TokenUsageResponse


class AdminModelsUpdateRequest(BaseModel):
    """Request model for updating the full models list."""

    models: list[FullModelConfig] = Field(..., description="Complete list of models to save")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NON_ALPHANUM_RE = re.compile(r"[^a-zA-Z0-9]+")


def _derive_env_var_name(model_name: str) -> str:
    """Derive a conventional env-var name from a model name.

    ``deepseek-v4-flash`` → ``DEEPSEEK_V4_FLASH_API_KEY``.
    """
    normalized = _NON_ALPHANUM_RE.sub("_", model_name).strip("_").upper()
    return f"{normalized}_API_KEY"


def _mask_model_config(model: FullModelConfig) -> FullModelConfig:
    """Return a copy with the api_key field masked."""
    data = model.model_dump()
    if data.get("api_key"):
        data["api_key"] = _MASKED_VALUE
    return FullModelConfig(**data)


# ---------------------------------------------------------------------------
# .env file management
# ---------------------------------------------------------------------------

_ENV_FILE_NAME = ".env"


def _read_env_file(project_root: Path) -> dict[str, str]:
    """Read .env entries from the project root, returning key→value dict."""
    env_path = project_root / _ENV_FILE_NAME
    if not env_path.exists():
        return {}
    return dict(dotenv_values(env_path))


def _write_env_file(project_root: Path, entries: dict[str, str]) -> None:
    """Write .env entries to the project root, preserving order.

    Empty keys or values are skipped. Keys with ``None`` values are removed.
    """
    env_path = project_root / _ENV_FILE_NAME
    cleaned: dict[str, str] = {}
    for k, v in entries.items():
        if v is None:
            continue  # remove
        if not k or not v:
            continue
        cleaned[k] = v
    lines = [f"{k}={v}" for k, v in cleaned.items()]
    if not lines:
        if env_path.exists():
            env_path.unlink()
        return
    content = "\n".join(lines) + "\n"
    env_path.write_text(content, encoding="utf-8")


def _sync_env_file(
    project_root: Path,
    raw_config: dict[str, Any],
    incoming_models: list[FullModelConfig],
) -> None:
    """Synchronize .env entries with the model configs.

    * For each incoming model whose ``api_key`` is a real value (not ``$VAR``
      and not ``***``), write it to .env under a derived key.
    * For models that were present in the raw config but are absent from
      incoming_models (deleted), remove the env var IF no remaining model
      references it.
    """
    env_entries = _read_env_file(project_root)

    # Build a mapping from model name → env var name for models in the
    # raw (on-disk) config, so we can recover the previous $VAR reference
    # when an incoming model sends the masked *** placeholder.
    raw_name_to_env_var: dict[str, str] = {}
    for raw_model in raw_config.get("models", []):
        if isinstance(raw_model, dict):
            raw_key = raw_model.get("api_key", "")
            if isinstance(raw_key, str) and raw_key.startswith("$"):
                raw_name_to_env_var[str(raw_model.get("name", ""))] = raw_key[1:]

    # Collect which $VAR names are referenced by the *incoming* models.
    incoming_env_refs: set[str] = set()
    for m in incoming_models:
        api_key = m.api_key
        if api_key and api_key.startswith("$"):
            incoming_env_refs.add(api_key[1:])
        elif api_key and api_key != _MASKED_VALUE:
            # Real value → write to .env
            var_name = _derive_env_var_name(m.name)
            env_entries[var_name] = api_key
            incoming_env_refs.add(var_name)
        elif api_key == _MASKED_VALUE:
            # Masked round-trip — preserve the previous $VAR reference
            # so it is not treated as orphaned and deleted from .env.
            prev_var = raw_name_to_env_var.get(m.name)
            if prev_var:
                incoming_env_refs.add(prev_var)

    # Collect which $VAR names were referenced by the *previous* config.
    prev_env_refs: set[str] = set()
    for raw_model in raw_config.get("models", []):
        if isinstance(raw_model, dict):
            raw_key = raw_model.get("api_key", "")
            if isinstance(raw_key, str) and raw_key.startswith("$"):
                prev_env_refs.add(raw_key[1:])

    # Remove .env keys that are no longer referenced by any model.
    orphaned = prev_env_refs - incoming_env_refs
    for var_name in orphaned:
        env_entries.pop(var_name, None)

    _write_env_file(project_root, env_entries)


# ---------------------------------------------------------------------------
# Worker-thread body for config writes
# ---------------------------------------------------------------------------


def _apply_models_config_update(body: AdminModelsUpdateRequest) -> list[FullModelConfig]:
    """Worker-thread body: read-modify-write config.yaml and .env.

    Reads the **raw** YAML (before env var resolution) so ``$VAR`` references
    are preserved across writes. Merges incoming API changes, syncs .env, and
    writes the updated YAML atomically.

    Returns the saved model list as ``FullModelConfig`` for the response.
    """
    with config_yaml_write_lock:
        config_path = AppConfig.resolve_config_path()
        project_root = config_path.parent

        # Read raw YAML (unresolved — preserves $VAR placeholders).
        raw_data: dict[str, Any] = {}
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                raw_data = yaml.safe_load(f) or {}

        # Build index of existing raw models by name.
        existing_by_name: dict[str, dict[str, Any]] = {}
        for entry in raw_data.get("models", []):
            if isinstance(entry, dict) and "name" in entry:
                existing_by_name[str(entry["name"])] = entry

        # Merge incoming models into raw data.
        merged_models: list[dict[str, Any]] = []
        for incoming in body.models:
            existing = existing_by_name.get(incoming.name)
            merged = incoming.model_dump(exclude_none=False)

            # Handle api_key field:
            #  - ***  → preserve existing raw value (masked round-trip)
            #  - $VAR → use as-is (explicit env var reference)
            #  - real value → write to .env, store as $VAR_NAME
            api_key = merged.get("api_key")
            if api_key == _MASKED_VALUE:
                if existing and "api_key" in existing:
                    merged["api_key"] = existing["api_key"]
                else:
                    merged.pop("api_key", None)
            elif api_key and not api_key.startswith("$"):
                # Real value — .env sync happens below.
                var_name = _derive_env_var_name(incoming.name)
                merged["api_key"] = f"${var_name}"

            # Preserve extra fields from existing raw entry that are not
            # represented in FullModelConfig (provider-specific kwargs).
            if existing:
                for ek, ev in existing.items():
                    if ek not in merged or merged[ek] is None:
                        merged[ek] = ev

            # Drop None values for known optional keys so they don't
            # clutter the YAML (but keep extra keys intact).
            for opt_key in (
                "display_name",
                "description",
                "api_key",
                "api_base",
                "base_url",
                "timeout",
                "request_timeout",
                "max_retries",
                "max_tokens",
                "temperature",
                "when_thinking_enabled",
                "when_thinking_disabled",
            ):
                if opt_key in merged and merged[opt_key] is None:
                    merged.pop(opt_key)

            merged_models.append(merged)

        raw_data["models"] = merged_models

        # Sync .env file.
        _sync_env_file(project_root, raw_data, body.models)

        # Write config.yaml atomically.
        AppConfig.write_config(config_path, raw_data)

        logger.info("Model configuration updated in %s", config_path)

        # Reload the cached config so subsequent requests see the changes
        # immediately without waiting for the next signature check.
        from deerflow.config.app_config import reload_app_config

        reloaded = reload_app_config(str(config_path))
        return [
            _mask_model_config(
                FullModelConfig(
                    name=m.name,
                    display_name=m.display_name,
                    description=m.description,
                    use=m.use,
                    model=m.model,
                    api_key=getattr(m, "api_key", None),
                    **{
                        k: v
                        for k, v in m.model_dump().items()
                        if k
                        not in (
                            "name",
                            "display_name",
                            "description",
                            "use",
                            "model",
                            "api_key",
                        )
                        and v is not None
                    },
                )
            )
            for m in reloaded.models
        ]


def _delete_model_from_config(model_name: str) -> None:
    """Worker-thread body: remove a model from config.yaml and sync .env."""
    with config_yaml_write_lock:
        config_path = AppConfig.resolve_config_path()
        project_root = config_path.parent

        # Read raw YAML.
        raw_data: dict[str, Any] = {}
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                raw_data = yaml.safe_load(f) or {}

        existing_models: list[dict[str, Any]] = raw_data.get("models", [])
        if not any(
            isinstance(e, dict) and e.get("name") == model_name
            for e in existing_models
        ):
            raise HTTPException(
                status_code=404,
                detail=f"Model '{model_name}' not found in configuration.",
            )

        filtered = [
            e
            for e in existing_models
            if not (isinstance(e, dict) and e.get("name") == model_name)
        ]
        raw_data["models"] = filtered

        # Sync .env: remove orphaned env vars.
        _sync_env_file(project_root, raw_data, [])

        # Write config.yaml atomically.
        AppConfig.write_config(config_path, raw_data)

        logger.info("Model '%s' removed from %s", model_name, config_path)

        # Reload.
        from deerflow.config.app_config import reload_app_config

        reload_app_config(str(config_path))


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/models",
    response_model=ModelsListResponse,
    summary="List All Models",
    description="Retrieve a list of all available AI models configured in the system.",
)
async def list_models(config: AppConfig = Depends(get_app_config)) -> ModelsListResponse:
    """List all available models from configuration (public, lightweight)."""
    models = [
        ModelResponse(
            name=model.name,
            model=model.model,
            display_name=model.display_name,
            description=model.description,
            supports_thinking=model.supports_thinking,
            supports_reasoning_effort=model.supports_reasoning_effort,
            supports_vision=model.supports_vision,
        )
        for model in config.models
    ]
    return ModelsListResponse(
        models=models,
        token_usage=TokenUsageResponse(enabled=config.token_usage.enabled),
    )


# ---------------------------------------------------------------------------
# Admin endpoints (require admin) — must be defined BEFORE /{model_name}
# so that "/models/admin" doesn't match "/models/{model_name}" with
# model_name="admin".
# ---------------------------------------------------------------------------


@router.get(
    "/models/admin",
    response_model=AdminModelsResponse,
    summary="List All Models (Admin)",
    description="Retrieve full model configurations with masked secrets. Requires admin.",
)
async def list_admin_models(
    request: Request,
    config: AppConfig = Depends(get_app_config),
) -> AdminModelsResponse:
    """List all models with full configuration (admin-only, secrets masked)."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)

    models = [
        _mask_model_config(
            FullModelConfig(
                name=m.name,
                display_name=m.display_name,
                description=m.description,
                use=m.use,
                model=m.model,
                **{
                    k: v
                    for k, v in m.model_dump().items()
                    if k
                    not in (
                        "name",
                        "display_name",
                        "description",
                        "use",
                        "model",
                    )
                    and v is not None
                },
            )
        )
        for m in config.models
    ]
    return AdminModelsResponse(
        models=models,
        token_usage=TokenUsageResponse(enabled=config.token_usage.enabled),
    )


@router.put(
    "/models/admin",
    response_model=AdminModelsResponse,
    summary="Update Model Configurations",
    description="Save the full models list. Writes config.yaml and .env. Requires admin.",
)
async def update_models(
    request: Request,
    body: AdminModelsUpdateRequest,
) -> AdminModelsResponse:
    """Replace the complete models list.

    API keys sent as ``***`` preserve existing values. Real values are written
    to ``.env`` and referenced as ``$VAR_NAME`` in ``config.yaml``.
    """
    try:
        await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)

        # Validate required fields.
        for i, m in enumerate(body.models):
            if not m.name or not m.name.strip():
                raise HTTPException(
                    status_code=422,
                    detail=f"Model at index {i}: 'name' is required.",
                )
            if not m.use or not m.use.strip():
                raise HTTPException(
                    status_code=422,
                    detail=f"Model '{m.name}': 'use' (provider class) is required.",
                )
            if not m.model or not m.model.strip():
                raise HTTPException(
                    status_code=422,
                    detail=f"Model '{m.name}': 'model' (provider model ID) is required.",
                )

        saved = await asyncio.to_thread(_apply_models_config_update, body)
        # Re-read config to get the fresh token_usage value.
        config = get_app_config()
        return AdminModelsResponse(
            models=saved,
            token_usage=TokenUsageResponse(enabled=config.token_usage.enabled),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update model configurations: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update model configurations: {e}",
        )


@router.delete(
    "/models/admin/{model_name}",
    summary="Delete a Model",
    description="Remove a model from config.yaml and clean up its .env entry. Requires admin.",
)
async def delete_model(
    request: Request,
    model_name: str,
) -> dict[str, str]:
    """Delete a model configuration by name."""
    try:
        await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
        await asyncio.to_thread(_delete_model_from_config, model_name)
        return {"status": "ok", "message": f"Model '{model_name}' deleted."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete model '%s': %s", model_name, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete model '{model_name}': {e}",
        )


@router.get(
    "/models/{model_name}",
    response_model=ModelResponse,
    summary="Get Model Details",
    description="Retrieve detailed information about a specific AI model by its name.",
)
async def get_model(model_name: str, config: AppConfig = Depends(get_app_config)) -> ModelResponse:
    """Get a specific model by name."""
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
        supports_vision=model.supports_vision,
    )
