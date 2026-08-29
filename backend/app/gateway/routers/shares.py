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
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.client_ip import get_client_ip
from app.gateway.deps import get_config, get_current_user
from app.gateway.shares.snapshot import (
    ShareSnapshotTooLarge,
    build_share_snapshot,
    resolve_share_title,
    sanitize_share_title,
)
from app.gateway.shares.tokens import generate_share_token, get_share_pepper_async, share_token_hash
from deerflow.config.conversation_sharing_config import ConversationSharingConfig
from deerflow.persistence.conversation_shares.sql import ConversationShareRepository
from deerflow.utils.thread_id import ThreadId

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["shares"])

_TITLE_MAX_LENGTH = 256
_EXPIRY_CHOICES_DAYS = (1, 7, 30)

# Bounded in-memory per-IP throttle for public token resolution. The token is
# high-entropy so guessing is infeasible; this exists to blunt hammering of
# the resolution endpoint (bearer-in-URL compensating control, #4548). The
# bucket key comes from the deployment-wide trusted-proxy model
# (app.gateway.client_ip): behind the shipped nginx, deployments must set
# AUTH_TRUSTED_PROXIES to the proxy network or every anonymous visitor
# shares the proxy's single bucket.
_PUBLIC_RESOLVE_WINDOW_SECONDS = 60.0
_PUBLIC_RESOLVE_MAX_PER_WINDOW = 60
_PUBLIC_RESOLVE_TRACKER_MAX_IPS = 4096
_public_resolve_hits: dict[str, list[float]] = {}
_PUBLIC_RESPONSE_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _public_not_found() -> HTTPException:
    """Return the indistinguishable public 404 with non-cacheable headers."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Not found",
        headers=dict(_PUBLIC_RESPONSE_HEADERS),
    )


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
    _prune_resolve_tracker(now)
    return False


def _prune_resolve_tracker(now: float) -> None:
    """Bound the tracker without flushing it.

    Clearing wholesale would let anyone rotating past the IP cap reset every
    visitor's hit history; stale entries go first, then the longest-idle
    survivors, until the tracker is back under the cap.
    """
    if len(_public_resolve_hits) <= _PUBLIC_RESOLVE_TRACKER_MAX_IPS:
        return
    window_start = now - _PUBLIC_RESOLVE_WINDOW_SECONDS
    for ip in [ip for ip, stamps in _public_resolve_hits.items() if not stamps or stamps[-1] <= window_start]:
        del _public_resolve_hits[ip]
    while len(_public_resolve_hits) > _PUBLIC_RESOLVE_TRACKER_MAX_IPS:
        longest_idle = min(_public_resolve_hits, key=lambda ip: _public_resolve_hits[ip][-1])
        del _public_resolve_hits[longest_idle]


def _sharing_config() -> ConversationSharingConfig:
    return get_config().conversation_sharing


def _share_repo(request: Request) -> ConversationShareRepository:
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


def _resolve_expiry(body: ShareCreateRequest) -> datetime | None:
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
    return datetime.now(UTC) + timedelta(days=days)


def _summary(record: dict[str, Any]) -> ShareSummaryResponse:
    return ShareSummaryResponse(
        share_id=str(record["id"]),
        title=str(record["title"]),
        expires_at=str(record["expires_at"]) if record.get("expires_at") else None,
        revoked_at=str(record["revoked_at"]) if record.get("revoked_at") else None,
        created_at=str(record["created_at"]),
    )


@router.post(
    "/threads/{thread_id}/shares",
    response_model=ShareCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_413_CONTENT_TOO_LARGE: {"description": "Conversation exceeds the share message cap and cannot be shared"}},
)
@require_permission("threads", "read", owner_check=True)
async def create_share(thread_id: ThreadId, request: Request, body: ShareCreateRequest) -> ShareCreatedResponse:
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

    try:
        snapshot = await build_share_snapshot(thread_id, request=request, user_id=user_id)
    except ShareSnapshotTooLarge as exc:
        # A share promises the complete visible transcript; a conversation
        # too long to snapshot is rejected instead of silently truncated.
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="This conversation is too long to share",
        ) from exc
    if not snapshot["messages"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This conversation has no visible messages to share")

    title = sanitize_share_title(
        body.title or await resolve_share_title(thread_id, request=request),
        max_length=_TITLE_MAX_LENGTH,
    )
    expires_at = _resolve_expiry(body)
    token = generate_share_token()
    pepper = await get_share_pepper_async()
    record = await repo.create(
        thread_id=thread_id,
        owner_user_id=user_id,
        token_hash=share_token_hash(token, pepper),
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
async def list_shares(thread_id: ThreadId, request: Request) -> list[ShareSummaryResponse]:
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
async def revoke_share(thread_id: ThreadId, share_id: str, request: Request) -> None:
    """Revoke one of the caller's shares. Effective on the next public request."""
    _require_enabled()
    user_id = await get_current_user(request)
    revoked = await _share_repo(request).revoke(share_id, thread_id, user_id or "")
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    return None


@router.get("/shares/{share_token}", response_model=PublicShareResponse)
async def get_public_share(share_token: str, request: Request, response: Response) -> PublicShareResponse:
    """Resolve a bearer share token into its public snapshot DTO.

    Deliberately unauthenticated (the token *is* the credential). Returns
    404 — indistinguishably — for disabled deployments, unknown tokens,
    revoked links, and expired links. Reads only the dedicated share record;
    never touches thread state or history under any synthetic principal.
    """
    # The token rides in the URL path, so this API response is no-store and
    # carries the strictest referrer policy as defense in depth. This header
    # does not establish the policy of the follow-up frontend `/share/` page;
    # that document must set its own no-referrer policy when Phase 2 lands.
    response.headers.update(_PUBLIC_RESPONSE_HEADERS)
    if not _sharing_config().enabled:
        raise _public_not_found()
    repo = getattr(request.app.state, "share_repo", None)
    if repo is None:
        raise _public_not_found()
    if _public_resolve_throttled(get_client_ip(request)):
        raise _public_not_found()

    pepper = await get_share_pepper_async()
    record = await repo.get_active_by_token_hash(share_token_hash(share_token, pepper))
    if record is None:
        # Never log the token itself; hash-side failures stay generic.
        logger.debug("Share token did not resolve")
        raise _public_not_found()
    snapshot = record.get("snapshot_json") or {}
    return PublicShareResponse(
        title=sanitize_share_title(record["title"]),
        snapshot_version=int(record.get("snapshot_version") or 1),
        snapshot=snapshot,
    )
