"""Gateway router for IM channel management."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.gateway.deps import require_admin_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/channels", tags=["channels"])

_ADMIN_REQUIRED_DETAIL = "Admin privileges required to manage channel runtime workers."


class ChannelStatusResponse(BaseModel):
    service_running: bool
    channels: dict[str, dict]


class ChannelRestartResponse(BaseModel):
    success: bool
    message: str


@router.get("/", response_model=ChannelStatusResponse)
async def get_channels_status() -> ChannelStatusResponse:
    """Get the status of all IM channels."""
    from app.channels.service import get_channel_service

    service = get_channel_service()
    if service is None:
        return ChannelStatusResponse(service_running=False, channels={})
    status = service.get_status()
    return ChannelStatusResponse(**status)


@router.post("/{name}/restart", response_model=ChannelRestartResponse)
async def restart_channel(name: str, request: Request) -> ChannelRestartResponse:
    """Restart a specific IM channel."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)

    from app.channels.service import get_channel_service

    service = get_channel_service()
    if service is None:
        raise HTTPException(status_code=503, detail="Channel service is not running")

    success = await service.restart_channel(name)
    if success:
        logger.info("Channel %s restarted successfully", name)
        return ChannelRestartResponse(success=True, message=f"Channel {name} restarted successfully")
    leader = service.leader_of(name) if hasattr(service, "leader_of") else None
    if isinstance(leader, str) and leader != getattr(service, "lease_owner_id", None):
        # channels.leader_lease: only the instance holding the provider's lease
        # runs its transport, and this request reached a different instance.
        logger.info("Channel %s restart declined: Gateway instance %s holds its leader lease", name, leader)
        return ChannelRestartResponse(success=False, message=f"Channel {name} is connected by another Gateway instance ({leader}); it can only be restarted there")
    logger.warning("Failed to restart channel %s", name)
    return ChannelRestartResponse(success=False, message=f"Failed to restart channel {name}")
