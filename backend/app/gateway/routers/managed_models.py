"""Admin-only shared model management. Credentials never leave the server."""

import asyncio
import logging
from contextlib import aclosing

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict, model_validator

from app.gateway.deps import require_admin_user
from app.gateway.persistent_writes import run_drained_write
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.managed_model_providers import PROVIDERS
from deerflow.config.managed_models import ManagedModel, ManagedModelInputError, ManagedModelStore, retained_api_key
from deerflow.models.factory import create_chat_model
from deerflow.models.reasoning import resolve_reasoning_contract

logger = logging.getLogger(__name__)


class RedactedModelRoute(APIRoute):
    """Pydantic model-level errors can echo an entire draft, including its key."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(422, {"code": "invalid_model", "message": "Invalid model configuration; check provider, model ID and capability fields"}) from None

        return handler


router = APIRouter(prefix="/api/managed-models", tags=["models"], route_class=RedactedModelRoute)
_ADMIN = "Admin privileges are required to manage shared models."


class SaveModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: ManagedModel
    expected_revision: str | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_preset_routes(cls, value):
        if isinstance(value, dict):
            config = value.get("config")
            if isinstance(config, dict) and config.get("provider", "openai-compatible") != "openai-compatible" and "base_url" in config:
                raise ValueError("Preset endpoints cannot be overridden")
        return value


def _catalog():
    config = get_app_config()
    yaml_models = [item for item in config.models if item.name not in config._managed_model_names]
    yaml_names = {item.name for item in yaml_models}
    return {
        "models": [{"name": item.name, "display_name": item.display_name or item.name, "model": item.model, "source": "config", "enabled": True} for item in yaml_models]
        + [{**item.public(), "conflict": item.name in yaml_names} for item in ManagedModelStore().list()]
    }


@router.get("/providers")
async def list_model_providers(request: Request):
    await require_admin_user(request, detail=_ADMIN)
    return {"providers": [provider.public() for provider in PROVIDERS]}


@router.get("")
async def list_managed_models(request: Request):
    await require_admin_user(request, detail=_ADMIN)
    try:
        return await asyncio.to_thread(_catalog)
    except ValueError:
        raise HTTPException(503, "Managed model storage is unavailable; check the catalog and encryption key") from None


def _save(body: SaveModelRequest):
    config = get_app_config()
    if any(item.name == body.config.name and item.name not in config._managed_model_names for item in config.models):
        raise HTTPException(409, "This model name is reserved by config.yaml")
    reserved_names = {item.name for item in config.models if item.name not in config._managed_model_names}
    try:
        return ManagedModelStore().save(body.config, expected_revision=body.expected_revision, reserved_names=reserved_names).public()
    except ManagedModelInputError as exc:
        raise HTTPException(422, {"code": "model_key_or_capabilities", "message": str(exc)}) from None
    except FileExistsError:
        raise HTTPException(409, "Model changed or already exists; reload before saving") from None
    except FileNotFoundError:
        raise HTTPException(404, "Model no longer exists") from None
    except (ValueError, OSError):
        raise HTTPException(503, "Managed model storage is unavailable") from None


def _save_with_failure_logging(body: SaveModelRequest):
    """Record save failures before a cancelled caller consumes the worker result."""
    try:
        return _save(body)
    except HTTPException as exc:
        if exc.status_code >= 500:
            logger.error("Managed model save failed (HTTP %d)", exc.status_code)
        raise
    except Exception as exc:
        # Storage exceptions can contain credentials; retain only the type.
        logger.error("Managed model save failed (%s)", type(exc).__name__)
        raise


@router.put("")
async def save_model(request: Request, body: SaveModelRequest):
    await require_admin_user(request, detail=_ADMIN)
    return await run_drained_write("Save managed model", _save_with_failure_logging, (HTTPException,), body)


def _probe_config(body: SaveModelRequest):
    profile = body.config
    previous = None
    if body.expected_revision is not None:
        previous = next((item for item in ManagedModelStore().list() if item.name == profile.name), None)
        if previous is None or previous.revision != body.expected_revision:
            raise HTTPException(409, "Model changed; reload before testing")
    profile = profile.model_copy(update={"api_key": retained_api_key(profile, previous)})
    if profile.provider != "openai-compatible" and not (profile.api_key and profile.api_key.get_secret_value()):
        raise ManagedModelInputError("This provider requires an API key")
    return profile.runtime_config()


def _build_probe(body: SaveModelRequest):
    """Use exactly the same resolution, reasoning transforms and factory as chat."""
    config = _probe_config(body)
    contract = resolve_reasoning_contract(config)
    # Required-thinking models cannot accept forced tool selection. Keep the
    # bounded probe honest: auto selection may report tool_call_missing.
    required = contract.thinking_required
    # For an unrecognized model on a third-party preset, tool_choice forcing
    # is not a verified capability. Use auto instead of inventing a contract.
    force_tool = not required and (body.config.provider in {"openai-compatible", "openai", "anthropic"} or config.when_thinking_disabled is not None)
    app_config = AppConfig.model_validate({"models": [config], "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}})
    model = create_chat_model(
        name=config.name,
        app_config=app_config,
        thinking_enabled=False,
        attach_tracing=False,
        model_overrides={"timeout": 15, "max_retries": 0, "max_tokens": 2048 if required else 32},
    )
    return model.bind_tools(
        [{"type": "function", "function": {"name": "connection_check", "description": "Check the connection", "parameters": {"type": "object", "properties": {}}}}], tool_choice="connection_check" if force_tool else "auto"
    )


@router.post("/test")
async def test_model(request: Request, body: SaveModelRequest):
    """Send a bounded streaming tool-call probe without saving the profile."""
    await require_admin_user(request, detail=_ADMIN)
    try:
        response = None
        size = 0
        chunks = 0
        async with asyncio.timeout(20):
            probe = await asyncio.to_thread(_build_probe, body)
            async with aclosing(probe.astream([HumanMessage(content="Call connection_check.")], config={"callbacks": []})) as stream:
                async for chunk in stream:
                    size += len(str(chunk.content)) + len(str(chunk.tool_call_chunks)) + len(str(chunk.additional_kwargs))
                    chunks += 1
                    if size > 16384 or chunks > 256:
                        return {"ok": False, "message": "response_limit"}
                    response = chunk if response is None else response + chunk
        if response is None or not any(call["name"] == "connection_check" and call["args"] == {} for call in response.tool_calls):
            return {"ok": False, "message": "tool_call_missing"}
        return {"ok": True, "message": "success"}
    except HTTPException:
        raise
    except ManagedModelInputError:
        return {"ok": False, "message": "missing_api_key"}
    except Exception as exc:
        # Provider exception strings may contain keys, URLs or response bodies.
        return {"ok": False, "message": "authentication_failed" if getattr(exc, "status_code", None) in (401, 403) else "connection_failed"}
