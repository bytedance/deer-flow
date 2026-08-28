"""Read-only conversation share endpoints (#4548).

Owner endpoints live under ``/api/threads/{thread_id}/shares`` and stay
authenticated + owner-checked. The public snapshot read is
``GET /api/shares/{share_token}``, the only route exempted from the auth
middleware in this feature: possession of a valid high-entropy bearer token
grants read access to the immutable snapshot and nothing else. Invalid,
revoked, and expired tokens all return the same 404 — the response must not
disclose which condition occurred.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_config, get_current_user
from app.gateway.shares.snapshot import build_share_snapshot, resolve_share_title
from app.gateway.shares.tokens import generate_share_token, get_share_pepper, share_token_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["shares"])

_TITLE_MAX_LENGTH = 256
_EXPIRY_CHOICES_DAYS = (1, 7, 30)

# Bounded in-memory per-IP throttle for public token resolution. The token is
# high-entropy so guessing is infeasible; this exists to blunt hammering of
# the resolution endpoint (bearer-in-URL compensating control, #4548).
_PUBLIC_RESOLVE_WINDOW_SECONDS = 60.0
_PUBLIC_RESOLVE_MAX_PER_WINDOW = 60
_public_resolve_hits: dict[str, list[float]] = {}


def _public_resolve_throttled(client_ip: str | None) -> bool:
    if not client_ip:
        return False
    now = time.monotonic()
    window_start = now - _PUBLIC_RESOLVE_WINDOW_SECONDS
    hits = [stamp for stamp in _public_resolve_hits.get(client_ip, []) if stamp > window_start]
    if len(hits) >= _PUBLIC_RESOLVE_MAX_PER_WINDOW:
        _public_resolve_hits[client_ip] = hits
        return True
    hits.append(now)
    _public_resolve_hits[client_ip] = hits
    if len(_public_resolve_hits) > 4096:  # bound the tracker itself
        _public_resolve_hits.clear()
    return False


def _sharing_config():
    return get_config().conversation_sharing


def _share_repo(request: Request):
    repo = getattr(request.app.state, "share_repo", None)
    if repo is None:
        # Memory-only persistence: links minted here could never be resolved
        # durably; fail the management surface explicitly.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Conversation sharing requires a configured database")
    return repo


def _require_enabled() -> None:
    if not _sharing_config().enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conversation sharing is disabled by this deployment")


class ShareCreateRequest(BaseModel):
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    never_expires: bool = Field(default=False)
    title: str | None = Field(default=None, max_length=_TITLE_MAX_LENGTH)


class ShareCreatedResponse(BaseModel):
    """Create response — ``share_url`` carries the show-once raw token."""

    share_id: str
    title: str
    expires_at: str | None
    created_at: str
    share_url: str


class ShareSummaryResponse(BaseModel):
    share_id: str
    title: str
    expires_at: str | None
    revoked_at: str | None
    created_at: str


class PublicShareResponse(BaseModel):
    title: str
    snapshot_version: int
    snapshot: dict[str, Any]


def _resolve_expiry(body: ShareCreateRequest):
    config = _sharing_config()
    if body.never_expires:
        if body.expires_in_days is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide either expires_in_days or never_expires, not both")
        if not config.allow_no_expiry:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Non-expiring shares are not allowed by this deployment")
        return None
    days = body.expires_in_days
    if days is None:
        # Operator-configured default is honored as-is (the config field
        # already bounds it); the {1,7,30} choice set applies only to
        # client-supplied values, mirroring the Share dialog's options.
        days = config.default_expiry_days
    elif days not in _EXPIRY_CHOICES_DAYS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"expires_in_days must be one of {list(_EXPIRY_CHOICES_DAYS)}")
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) + timedelta(days=days)


def _summary(record: dict[str, Any]) -> ShareSummaryResponse:
    return ShareSummaryResponse(
        share_id=str(record["id"]),
        title=str(record["title"]),
        expires_at=str(record["expires_at"]) if record.get("expires_at") else None,
        revoked_at=str(record["revoked_at"]) if record.get("revoked_at") else None,
        created_at=str(record["created_at"]),
    )


@router.post("/threads/{thread_id}/shares", response_model=ShareCreatedResponse, status_code=status.HTTP_201_CREATED)
@require_permission("threads", "read", owner_check=True)
async def create_share(thread_id: str, request: Request, body: ShareCreateRequest):
    """Create a read-only snapshot share for a thread the caller owns.

    The raw share URL is returned exactly once; only its HMAC digest is
    persisted. The snapshot is frozen at creation — later messages or edits
    never modify an existing share.
    """
    _require_enabled()
    repo = _share_repo(request)
    user_id = await get_current_user(request)
    if user_id is None:  # pragma: no cover - decorator guarantees auth
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # Publishing is strict-ownership: the thread row must exist and name the
    # caller as its owner. The decorator's owner_check is deliberately
    # permissive for reads (missing rows and user_id=NULL legacy rows pass),
    # which is wrong for a publishing action — any authenticated user could
    # otherwise mint a public link for pre-auth shared data.
    from app.gateway.deps import get_thread_store

    meta = await get_thread_store(request).get(thread_id, user_id=None)
    if meta is None or not meta.get("user_id") or str(meta["user_id"]) != str(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Thread {thread_id} not found")

    snapshot = await build_share_snapshot(thread_id, request=request, user_id=user_id)
    if not snapshot["messages"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This conversation has no visible messages to share")

    title = (body.title or await resolve_share_title(thread_id, request=request)).strip()[:_TITLE_MAX_LENGTH]
    expires_at = _resolve_expiry(body)
    token = generate_share_token()
    record = await repo.create(
        thread_id=thread_id,
        owner_user_id=user_id,
        token_hash=share_token_hash(token, get_share_pepper()),
        title=title or "Shared conversation",
        snapshot_json=snapshot,
        snapshot_version=snapshot["version"],
        source_last_seq=None,
        expires_at=expires_at,
    )
    logger.info("Share created: share_id=%s thread_id=%s expires=%s", record["id"], thread_id, expires_at or "never")
    return ShareCreatedResponse(
        share_id=str(record["id"]),
        title=str(record["title"]),
        expires_at=str(record["expires_at"]) if record.get("expires_at") else None,
        created_at=str(record["created_at"]),
        share_url=f"/share/{token}",
    )


@router.get("/threads/{thread_id}/shares", response_model=list[ShareSummaryResponse])
@require_permission("threads", "read", owner_check=True)
async def list_shares(thread_id: str, request: Request):
    """List the caller's shares for a thread. Never returns token hashes.

    Read-side owner_check stays permissive by design (matches every other
    thread read): foreign-owned threads 404 at the decorator, and on a
    null-owner thread the repository's owner scoping already returns only
    the caller's own (strict-ownership create guarantees there are none).
    """
    _require_enabled()
    user_id = await get_current_user(request)
    records = await _share_repo(request).list_by_thread(thread_id, user_id or "")
    return [_summary(record) for record in records]


@router.delete("/threads/{thread_id}/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("threads", "read", owner_check=True)
async def revoke_share(thread_id: str, share_id: str, request: Request):
    """Revoke one of the caller's shares. Effective on the next public request."""
    _require_enabled()
    user_id = await get_current_user(request)
    revoked = await _share_repo(request).revoke(share_id, thread_id, user_id or "")
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    return None


@router.get("/shares/{share_token}", response_model=PublicShareResponse)
async def get_public_share(share_token: str, request: Request, response: Response):
    """Resolve a bearer share token into its public snapshot DTO.

    Deliberately unauthenticated (the token *is* the credential). Returns
    404 — indistinguishably — for disabled deployments, unknown tokens,
    revoked links, and expired links. Reads only the dedicated share record;
    never touches thread state or history under any synthetic principal.
    """
    # The token rides in the URL path, so outbound leakage must be blunted:
    # a strict referrer policy keeps the URL out of Referer on any link the
    # rendered page follows (nginx access-log masking is a deployment-side
    # control documented with this feature).
    response.headers["Referrer-Policy"] = "no-referrer"
    if not _sharing_config().enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    repo = getattr(request.app.state, "share_repo", None)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if _public_resolve_throttled(request.client.host if request.client else None):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    record = await repo.get_active_by_token_hash(share_token_hash(share_token, get_share_pepper()))
    if record is None:
        # Never log the token itself; hash-side failures stay generic.
        logger.debug("Share token did not resolve")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    snapshot = record.get("snapshot_json") or {}
    return PublicShareResponse(
        title=str(record["title"]),
        snapshot_version=int(record.get("snapshot_version") or 1),
        snapshot=snapshot,
    )
