"""Session-only enterprise connector management. Targets are strictly personal."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.gateway.deps import get_current_user_from_request
from app.gateway.routers.auth import require_session_source
from app.gateway.routers.enterprise_mail import router as mail_router
from app.gateway.routers.enterprise_mail_outbox import router as mail_outbox_router
from deerflow.authz.principal import build_principal_from_context
from deerflow.integrations.enterprise.access import authorize, make_store
from deerflow.integrations.enterprise.providers import EnterpriseError
from deerflow.integrations.enterprise.service import EnterpriseService

router = APIRouter(prefix="/api/enterprise", tags=["enterprise"], dependencies=[Depends(require_session_source)])
router.include_router(mail_router)
router.include_router(mail_outbox_router)


def _http_error(exc):
    status = 403 if exc.code == "access_denied" else 404 if exc.code == "target_not_found" else 503 if exc.code in {"not_configured", "scheduler_unavailable", "single_node_required"} else 400
    return HTTPException(status, {"code": exc.code})


async def _access(request, *, schedule=False):
    user = await get_current_user_from_request(request)
    principal = build_principal_from_context({"user_id": str(user.id), "user_role": user.system_role}, default_role="user")
    try:
        config = await authorize(principal, schedule=schedule)
    except EnterpriseError as exc:
        raise _http_error(exc) from None
    service = EnterpriseService(make_store(config), task_repo=getattr(request.app.state, "scheduled_task_repo", None), scheduler_config=config.scheduler)
    return principal, service


class TargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    provider: Literal["wecom_webhook"] = "wecom_webhook"
    webhook: SecretStr = Field(min_length=1, max_length=512)


class SendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=2048)
    request_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ScheduleRequest(SendRequest):
    schedule_type: Literal["once", "cron"]
    schedule_spec: dict[str, str]
    timezone: str = Field(default="Asia/Shanghai", max_length=80)


@router.get("")
async def overview(request: Request):
    principal, service = await _access(request)
    targets, deliveries = await asyncio.gather(asyncio.to_thread(service.store.list_targets, principal.user_id), asyncio.to_thread(service.store.deliveries, principal.user_id))
    return {
        "targets": targets,
        "deliveries": deliveries,
        "scheduler_enabled": bool(service.scheduler_config.enabled and service.task_repo is not None),
        "providers": [{"id": "wecom_webhook", "status": "available"}, {"id": "alimail", "status": "available"}],
    }


@router.post("/targets")
async def create_target(request: Request, body: TargetCreate):
    principal, service = await _access(request)
    try:
        return await asyncio.to_thread(service.store.create_target, principal.user_id, body.name, body.provider, body.webhook.get_secret_value())
    except EnterpriseError as exc:
        raise _http_error(exc) from None


@router.delete("/targets/{target_id}")
async def delete_target(request: Request, target_id: str):
    principal, service = await _access(request)
    try:
        target = await asyncio.to_thread(service.store.target, principal.user_id, target_id)
        if target["provider"] != "wecom_webhook":
            raise EnterpriseError("target_not_found")
    except EnterpriseError as exc:
        raise _http_error(exc) from None
    await asyncio.to_thread(service.store.delete_target, principal.user_id, target_id)
    return {"deleted": True}


@router.post("/send")
async def send(request: Request, body: SendRequest):
    principal, service = await _access(request)
    try:
        return await service.send(principal.user_id, body.target_id, body.content, "ui:" + body.request_key)
    except EnterpriseError as exc:
        raise _http_error(exc) from None


@router.post("/schedule")
async def schedule(request: Request, body: ScheduleRequest):
    principal, service = await _access(request, schedule=True)
    try:
        return await service.schedule(principal.user_id, body.target_id, body.content, "ui:" + body.request_key, schedule_type=body.schedule_type, schedule_spec=body.schedule_spec, timezone=body.timezone)
    except EnterpriseError as exc:
        raise _http_error(exc) from None


async def schedule_from_tool(app, *, principal, **kwargs):
    config = await authorize(principal, schedule=True)
    service = EnterpriseService(make_store(config), task_repo=getattr(app.state, "scheduled_task_repo", None), scheduler_config=config.scheduler)
    return await service.schedule(principal.user_id, **kwargs)
