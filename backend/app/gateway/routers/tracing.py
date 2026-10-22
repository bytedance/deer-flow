"""Authorized, redacted tracing configuration; a committed save is not delivery proof."""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.gateway.authz import get_auth_context, require_permission
from app.gateway.deps import is_admin_user
from app.gateway.persistent_writes import run_drained_write
from app.gateway.routers.agents import _require_agents_api_enabled, _validate_agent_name
from deerflow.config.agents_config import load_agent_config
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.tracing.profiles import ProviderConfig, TracingControlError, TracingInputError, TracingUnavailableError, canonical_agent_name, get_profile_service

logger = logging.getLogger(__name__)


class RedactedTracingRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(422, {"code": "invalid_tracing_configuration", "message": "Invalid tracing configuration"}) from None

        return handler


router = APIRouter(prefix="/api", tags=["tracing"], route_class=RedactedTracingRoute)


class ProfileWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    providers: tuple[ProviderConfig, ...] = Field(min_length=1, max_length=3)
    allowed_user_ids: list[str] = Field(default_factory=list, max_length=1000)
    expected_revision: StrictInt = Field(default=0, ge=0)


class AgentTracingWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["inherit", "disabled", "configured"]
    profile_id: str | None = Field(default=None, max_length=128)
    expected_revision: StrictInt = Field(ge=0)


async def _can_manage(request: Request) -> bool:
    # require_permission has already authenticated this request. Reuse the
    # canonical admin predicate, including its explicit PAT denial.
    if getattr(request.state, "user", None) is None:
        request.state.user = request.state.auth.user
    return await is_admin_user(request)


def _http_error(error: TracingControlError) -> HTTPException:
    return HTTPException(error.status_code, {"code": error.code, "message": str(error)})


async def _read(func, *args, **kwargs):
    try:
        return await asyncio.to_thread(func, *args, **kwargs)
    except TracingControlError as exc:
        raise _http_error(exc) from None
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Tracing authority read failed (%s)", type(exc).__name__)
        raise _http_error(TracingUnavailableError("Tracing authority is unavailable")) from None


async def _write(func, *args, **kwargs):
    try:
        return await run_drained_write("Save tracing configuration", func, (TracingControlError, HTTPException), *args, **kwargs)
    except TracingControlError as exc:
        raise _http_error(exc) from None
    except HTTPException:
        raise
    except Exception:
        raise _http_error(TracingUnavailableError("Tracing authority is unavailable")) from None


def _require_agent(name: str, owner: str) -> str:
    _require_agents_api_enabled()
    normalized = canonical_agent_name(name)
    if normalized == "lead_agent":
        return normalized
    _validate_agent_name(name)
    try:
        load_agent_config(normalized, user_id=owner)
    except FileNotFoundError:
        raise HTTPException(404, "Agent not found") from None
    return normalized


@router.get("/tracing/profiles")
@require_permission("agents", "read")
async def list_profiles(request: Request):
    can_manage = await _can_manage(request)
    owner = get_effective_user_id()

    def _list():
        try:
            return {"profiles": get_profile_service().list_profiles(owner, is_admin=can_manage), "can_manage": can_manage, "available": True, "reason": None}
        except TracingUnavailableError:
            return {"profiles": [], "can_manage": can_manage, "available": False, "reason": "Tracing profiles require available durable storage and the deployment credentials key"}

    return await _read(_list)


@router.post("/tracing/profiles")
@require_permission("agents", "write")
async def create_profile(body: ProfileWriteRequest, request: Request):
    if not await _can_manage(request):
        raise HTTPException(403, "Admin privileges are required to manage tracing profiles")
    if body.expected_revision != 0:
        raise _http_error(TracingInputError("New tracing profiles require expected_revision=0"))

    def _save():
        return get_profile_service().save_profile(profile_id=body.id, name=body.name, providers=body.providers, allowed_user_ids=body.allowed_user_ids, expected_revision=0)

    return await _write(_save)


@router.put("/tracing/profiles/{profile_id}")
@require_permission("agents", "write")
async def update_profile(profile_id: str, body: ProfileWriteRequest, request: Request):
    if not await _can_manage(request):
        raise HTTPException(403, "Admin privileges are required to manage tracing profiles")
    if body.expected_revision == 0 or (body.id is not None and body.id != profile_id):
        raise _http_error(TracingInputError("Update requires the current profile revision and matching ID"))

    def _save():
        return get_profile_service().save_profile(profile_id=profile_id, name=body.name, providers=body.providers, allowed_user_ids=body.allowed_user_ids, expected_revision=body.expected_revision)

    return await _write(_save)


@router.get("/agents/{name}/tracing")
@require_permission("agents", "read")
async def get_agent_tracing(name: str, request: Request):
    owner = get_effective_user_id()
    can_manage = await _can_manage(request)

    def _get():
        normalized = _require_agent(name, owner)
        try:
            return get_profile_service().get_binding(normalized, owner, is_admin=can_manage)
        except TracingUnavailableError:
            return {
                "mode": "inherit",
                "profile_id": None,
                "revision": 0,
                "effective_revision": "",
                "source": "global",
                "destinations": [],
                "status": "unavailable",
                "error": "tracing_unavailable",
                "delivery_verified": False,
                "can_select": False,
            }

    result = await _read(_get)
    auth = get_auth_context(request)
    result["can_select"] = result["can_select"] and auth is not None and auth.has_permission("agents", "write")
    return result


@router.put("/agents/{name}/tracing")
@require_permission("agents", "write")
async def set_agent_tracing(name: str, body: AgentTracingWriteRequest, request: Request):
    owner = get_effective_user_id()
    can_manage = await _can_manage(request)

    def _save():
        normalized = _require_agent(name, owner)
        return get_profile_service().set_binding(normalized, owner, mode=body.mode, profile_id=body.profile_id, expected_revision=body.expected_revision, is_admin=can_manage)

    return await _write(_save)
