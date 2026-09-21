"""Admin-only shared model management. Credentials never leave the server."""

import asyncio

from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict

from app.gateway.deps import require_admin_user
from deerflow.config.app_config import get_app_config
from deerflow.config.managed_models import ManagedModel, ManagedModelStore

router = APIRouter(prefix="/api/managed-models", tags=["models"])
_ADMIN = "Admin privileges are required to manage shared models."


class SaveModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: ManagedModel
    expected_revision: str | None = None


def _catalog():
    config = get_app_config()
    yaml_models = [item for item in config.models if item.name not in config._managed_model_names]
    yaml_names = {item.name for item in yaml_models}
    return {
        "models": [{"name": item.name, "display_name": item.display_name or item.name, "model": item.model, "source": "config", "enabled": True} for item in yaml_models]
        + [{**item.public(), "conflict": item.name in yaml_names} for item in ManagedModelStore().list()]
    }


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
    try:
        return ManagedModelStore().save(body.config, expected_revision=body.expected_revision).public()
    except FileExistsError:
        raise HTTPException(409, "Model changed or already exists; reload before saving") from None
    except FileNotFoundError:
        raise HTTPException(404, "Model no longer exists") from None
    except (ValueError, OSError):
        raise HTTPException(503, "Managed model storage is unavailable") from None


@router.put("")
async def save_model(request: Request, body: SaveModelRequest):
    await require_admin_user(request, detail=_ADMIN)
    return await asyncio.to_thread(_save, body)


def _probe_config(body: SaveModelRequest):
    profile = body.config
    if body.expected_revision is not None:
        previous = next((item for item in ManagedModelStore().list() if item.name == profile.name), None)
        if previous is None or previous.revision != body.expected_revision:
            raise HTTPException(409, "Model changed; reload before testing")
        if profile.api_key is None:
            profile = profile.model_copy(update={"api_key": previous.api_key})
    return profile.runtime_config()


@router.post("/test")
async def test_model(request: Request, body: SaveModelRequest):
    """Send a bounded streaming tool-call probe without saving the profile."""
    await require_admin_user(request, detail=_ADMIN)
    try:
        config = await asyncio.to_thread(_probe_config, body)
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(model=config.model, base_url=config.base_url, api_key=config.api_key, timeout=15, max_retries=0, max_tokens=32)
        probe = model.bind_tools([{"type": "function", "function": {"name": "connection_check", "description": "Check the connection", "parameters": {"type": "object", "properties": {}}}}], tool_choice="connection_check")
        response = None
        async with asyncio.timeout(20):
            async for chunk in probe.astream([HumanMessage(content="Call connection_check.")], config={"callbacks": []}):
                response = chunk if response is None else response + chunk
        if response is None or not any(call["name"] == "connection_check" and call["args"] == {} for call in response.tool_calls):
            return {"ok": False, "message": "tool_call_missing"}
        return {"ok": True, "message": "success"}
    except HTTPException:
        raise
    except Exception:
        # Provider exception strings may contain keys, URLs or response bodies.
        return {"ok": False, "message": "connection_failed"}
