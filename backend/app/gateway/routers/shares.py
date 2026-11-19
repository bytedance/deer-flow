"""Owner-managed snapshots, public read capabilities, and authenticated imports."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from deerflow_extension_api import AgentRunError
from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.routers.artifacts import _build_content_disposition, _slice_byte_range
from app.gateway.services import reserve_checkpoint_write
from app.gateway.share_fork import fork_share
from app.gateway.share_snapshot import capture_share
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.thread_shares.sql import ThreadShareRepository
from deerflow.runtime import ConflictError
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.utils.file_io import await_drained
from deerflow.utils.thread_id import ThreadId

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["shares"])
ShareToken = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{43}$")]
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow", "X-Content-Type-Options": "nosniff"}


class ShareCreateRequest(BaseModel):
    checkpoint_id: str | None = Field(default=None, max_length=128)
    expires_in_seconds: int = Field(default=7 * 86400, ge=3600, le=30 * 86400)


class ShareForkRequest(BaseModel):
    request_id: UUID


def share_repository() -> ThreadShareRepository:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(503, "Sharing requires SQL persistence")
    return ThreadShareRepository(factory)


@router.post("/threads/{thread_id}/shares", status_code=201)
@require_permission("threads", "write", owner_check=True, require_existing=True)
@require_permission("runs", "read")
async def create_share(thread_id: ThreadId, body: ShareCreateRequest, request: Request):
    async def create():
        repo = share_repository()
        async with reserve_checkpoint_write(request, thread_id, user_id=get_effective_user_id()):
            if await repo.count_active(thread_id, get_effective_user_id()) >= 10:
                raise HTTPException(409, "Revoke an existing link before creating another")
            captured = await capture_share(request, thread_id, body.checkpoint_id)
            return await repo.create(**captured, expires_at=datetime.now(UTC) + timedelta(seconds=body.expires_in_seconds))

    try:
        result = await await_drained(create())
        return JSONResponse(result, status_code=201, headers=PRIVATE_HEADERS)
    except ConflictError:
        raise HTTPException(409, "Thread has work in flight; share it after the work finishes") from None
    except AgentRunError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create conversation share")
        raise HTTPException(500, "Unable to create share") from None


@router.get("/threads/{thread_id}/shares")
@require_permission("threads", "read", owner_check=True, require_existing=True)
async def list_shares(thread_id: ThreadId, request: Request):
    return JSONResponse(await share_repository().list_owned(thread_id, get_effective_user_id()), headers=PRIVATE_HEADERS)


@router.delete("/threads/{thread_id}/shares/{share_id}", status_code=204)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def revoke_share(thread_id: ThreadId, share_id: str, request: Request):
    if not await await_drained(share_repository().revoke(thread_id, share_id, get_effective_user_id())):
        raise HTTPException(404, "Share not found")
    return Response(status_code=204, headers=PRIVATE_HEADERS)


@router.get("/shares/{share_token}")
async def read_share(share_token: ShareToken):
    share = await share_repository().get_public(share_token)
    if share is None:
        raise HTTPException(404, "Share unavailable", headers=PRIVATE_HEADERS)
    return JSONResponse({**share["snapshot"], "checkpoint_id": share["checkpoint_id"], "seq": share["seq"], "created_at": share["created_at"], "expires_at": share["expires_at"], "artifacts": share["artifacts"]}, headers=PRIVATE_HEADERS)


@router.get("/shares/{share_token}/artifacts/{path:path}")
@router.head("/shares/{share_token}/artifacts/{path:path}")
async def read_share_artifact(share_token: ShareToken, path: str, request: Request, download: bool = False):
    artifact = await share_repository().get_artifact(share_token, path)
    if artifact is None:
        raise HTTPException(404, "Shared artifact unavailable", headers=PRIVATE_HEADERS)
    content, status, range_headers = _slice_byte_range(artifact["content"], request.headers.get("range"))
    # Even a direct tab navigation cannot run active content with our origin.
    # HTML previews render in an opaque sandbox and cannot contact the network.
    headers = {
        **PRIVATE_HEADERS,
        **range_headers,
        "Content-Disposition": _build_content_disposition("attachment" if download else "inline", path.rsplit("/", 1)[-1]),
        "Content-Length": str(len(content)),
    }
    # Chromium's built-in PDF viewer cannot load in a CSP sandbox. The PDF
    # media type and nosniff keep it outside the active HTML document surface.
    if artifact["mime_type"] != "application/pdf":
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'"
    return Response(content if request.method != "HEAD" else b"", status_code=status, media_type=artifact["mime_type"], headers=headers)


@router.post("/shares/{share_token}/fork")
@require_permission("threads", "write")
async def import_share(share_token: ShareToken, body: ShareForkRequest, request: Request):
    try:
        return JSONResponse(await await_drained(fork_share(request, share_repository(), share_token, str(body.request_id))), headers=PRIVATE_HEADERS)
    except ConflictError:
        raise HTTPException(409, "Import is already in progress; retry shortly") from None
    except AgentRunError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to import conversation share")
        raise HTTPException(500, "Unable to import share") from None
