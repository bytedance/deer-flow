"""Session-only review and confirmation of immutable personal mail drafts."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request

from app.gateway.deps import get_current_user_from_request
from app.gateway.routers.auth import require_session_source
from app.gateway.routers.enterprise_mail import _private_response
from deerflow.authz.principal import build_principal_from_context
from deerflow.integrations.enterprise.access import authorize, make_store
from deerflow.integrations.enterprise.mail_outbox import MailOutboxService, MailOutboxStore
from deerflow.integrations.enterprise.providers import EnterpriseError

router = APIRouter(prefix="/mail/drafts", dependencies=[Depends(require_session_source), Depends(_private_response)])


def _error(exc):
    status = 403 if exc.code == "access_denied" else 404 if exc.code in {"target_not_found", "draft_not_found"} else 503 if exc.code in {"not_configured", "single_node_required"} else 400
    return HTTPException(status, {"code": exc.code})


async def _access(request):
    user = await get_current_user_from_request(request)
    principal = build_principal_from_context({"user_id": str(user.id), "user_role": user.system_role}, default_role="user")
    try:
        config = await authorize(principal, tool_name="enterprise_mail_compose")
    except EnterpriseError as exc:
        raise _error(exc) from None
    return principal.user_id, MailOutboxService(MailOutboxStore(make_store(config).root))


async def _body(request):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 131072:
            raise HTTPException(413, {"code": "invalid_mail_message"})
    try:
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise HTTPException(400, {"code": "invalid_mail_message"}) from None


async def _call(function, *args):
    try:
        return await asyncio.to_thread(function, *args)
    except EnterpriseError as exc:
        raise _error(exc) from None


@router.get("")
async def list_drafts(request: Request):
    owner, service = await _access(request)
    return {"drafts": await _call(service.store.drafts, owner)}


@router.post("")
async def create_draft(request: Request):
    owner, service = await _access(request)
    value = await _body(request)
    account_id = value.pop("account_id", None)
    if not isinstance(account_id, str) or not 1 <= len(account_id) <= 64:
        raise HTTPException(400, {"code": "invalid_mail_message"})
    return await _call(service.draft, owner, account_id, value)


@router.get("/{draft_id}")
async def get_draft(request: Request, draft_id: str):
    owner, service = await _access(request)
    return await _call(service.store.draft, owner, draft_id)


@router.post("/{draft_id}/send")
async def send_draft(request: Request, draft_id: str):
    owner, service = await _access(request)
    value = await _body(request)
    if set(value) != {"confirmed"} or value["confirmed"] is not True:
        raise HTTPException(400, {"code": "mail_confirmation_required"})
    # CSRF + interactive session gate above; no model-callable send action.
    # Cancellation of the HTTP waiter never retries/stops the worker submission.
    return await _call(service.send, owner, draft_id)


@router.delete("/{draft_id}")
async def discard_draft(request: Request, draft_id: str):
    owner, service = await _access(request)
    return await _call(service.store.discard, owner, draft_id)
