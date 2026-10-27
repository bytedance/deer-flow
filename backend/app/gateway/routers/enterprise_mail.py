"""Session-only AliMail configuration and read-only inbox previews."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.gateway.deps import get_current_user_from_request
from app.gateway.routers.auth import require_session_source
from deerflow.authz.principal import build_principal_from_context
from deerflow.integrations.enterprise.access import authorize, make_store
from deerflow.integrations.enterprise.mail import MailService
from deerflow.integrations.enterprise.providers import EnterpriseError


async def _private_response(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/mail", dependencies=[Depends(require_session_source), Depends(_private_response)])


def _error(exc):
    status = 403 if exc.code == "access_denied" else 404 if exc.code == "target_not_found" else 503 if exc.code in {"not_configured", "single_node_required", "mail_busy", "mail_unavailable", "mail_timeout"} else 400
    return HTTPException(status, {"code": exc.code})


async def _access(request):
    user = await get_current_user_from_request(request)
    principal = build_principal_from_context({"user_id": str(user.id), "user_role": user.system_role}, default_role="user")
    try:
        config = await authorize(principal, tool_name="enterprise_mail")
    except EnterpriseError as exc:
        raise _error(exc) from None
    return principal.user_id, MailService(make_store(config))


class MailConnect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr
    host: str = "imap.qiye.aliyun.com"


@router.get("")
async def accounts(request: Request):
    owner, service = await _access(request)
    return {"accounts": await asyncio.to_thread(service.store.list_targets, owner, provider="alimail"), "read_only": True}


@router.post("/accounts")
async def connect(request: Request):
    owner, service = await _access(request)
    # Authorize before accepting credentials; never echo Pydantic's raw inputs.
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 8192:
            raise HTTPException(413, {"code": "invalid_mail_account"})
    try:
        body = MailConnect.model_validate(json.loads(data))
    except (ValueError, ValidationError):
        raise HTTPException(400, {"code": "invalid_mail_account"}) from None
    try:
        return await service.connect(owner, body.name, {"email": body.email.strip(), "password": body.password.get_secret_value(), "host": body.host})
    except EnterpriseError as exc:
        raise _error(exc) from None


@router.delete("/accounts/{account_id}")
async def disconnect(request: Request, account_id: str):
    owner, service = await _access(request)
    try:
        target = await asyncio.to_thread(service.store.target, owner, account_id)
        if target["provider"] != "alimail":
            raise EnterpriseError("target_not_found")
        await asyncio.to_thread(service.store.delete_target, owner, account_id)
        return {"deleted": True}
    except EnterpriseError as exc:
        raise _error(exc) from None


@router.get("/accounts/{account_id}/messages")
async def messages(request: Request, account_id: str, days: int = 7, limit: int = 20, unread_only: bool = False, before_uid: int | None = None, uidvalidity: str | None = None):
    owner, service = await _access(request)
    try:
        return await service.read(owner, account_id, days=days, limit=limit, unread_only=unread_only, before_uid=before_uid, uidvalidity=uidvalidity)
    except EnterpriseError as exc:
        raise _error(exc) from None
