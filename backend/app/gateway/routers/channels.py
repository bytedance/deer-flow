"""Gateway router for IM channel management."""

from __future__ import annotations

import logging
from typing import Optional, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/channels", tags=["channels"])


class ChannelStatusResponse(BaseModel):
    service_running: bool
    channels: dict[str, dict]


class ChannelRestartResponse(BaseModel):
    success: bool
    message: str


# Feishu Bot Management Models
class FeishuBotConfigRequest(BaseModel):
    """Request model for creating/updating a Feishu bot."""

    app_id: str
    app_secret: str
    verification_token: str = ""
    encrypt_key: str = ""
    agent_id: str = "lead_agent"
    enabled: bool = True
    name: str = ""
    description: str = ""
    recursion_limit: int = 100
    thinking_enabled: bool = True
    subagent_enabled: bool = False
    is_plan_mode: bool = False
    domain: str = "https://open.feishu.cn"


class FeishuBotResponse(BaseModel):
    """Response model for Feishu bot operations."""

    success: bool
    message: str
    data: Optional[dict[str, Any]] = None


class FeishuBotsListResponse(BaseModel):
    """Response model for listing Feishu bots."""

    success: bool
    bots: dict[str, dict[str, Any]]


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
async def restart_channel(name: str) -> ChannelRestartResponse:
    """Restart a specific IM channel."""
    from app.channels.service import get_channel_service

    service = get_channel_service()
    if service is None:
        raise HTTPException(status_code=503, detail="Channel service is not running")

    success = await service.restart_channel(name)
    if success:
        logger.info("Channel %s restarted successfully", name)
        return ChannelRestartResponse(success=True, message=f"Channel {name} restarted successfully")
    else:
        logger.warning("Failed to restart channel %s", name)
        return ChannelRestartResponse(success=False, message=f"Failed to restart channel {name}")


# ==================== Feishu Bot Management Endpoints ====================


@router.get("/feishu/bots", response_model=FeishuBotsListResponse)
async def list_feishu_bots() -> FeishuBotsListResponse:
    """List all configured Feishu bots with their status."""
    from app.channels.service import get_channel_service

    service = get_channel_service()
    if service is None:
        raise HTTPException(status_code=503, detail="Channel service is not running")

    bot_manager = service.get_feishu_bot_manager()
    if bot_manager is None:
        # Lazy initialize FeishuBotManager to support dynamic bot creation
        from app.channels.feishu import FeishuBotManager
        bot_manager = FeishuBotManager()
        service.set_feishu_bot_manager(bot_manager)
        await bot_manager.start()

    bots_status = bot_manager.get_bot_status()
    return FeishuBotsListResponse(success=True, bots=bots_status)


@router.post("/feishu/bots", response_model=FeishuBotResponse)
async def create_feishu_bot(req: FeishuBotConfigRequest) -> FeishuBotResponse:
    """Create or update a Feishu bot configuration."""
    from app.channels.service import get_channel_service
    from app.channels.feishu import FeishuBotConfig

    service = get_channel_service()
    if service is None:
        raise HTTPException(status_code=503, detail="Channel service is not running")

    bot_manager = service.get_feishu_bot_manager()
    if bot_manager is None:
        # Lazy initialize FeishuBotManager to support dynamic bot creation
        from app.channels.feishu import FeishuBotManager
        bot_manager = FeishuBotManager()
        service.set_feishu_bot_manager(bot_manager)
        await bot_manager.start()

    try:
        config = FeishuBotConfig(**req.model_dump())
        success = await bot_manager.add_bot(config)

        if success:
            logger.info("Feishu bot added/updated: %s", config.app_id)
            # Redact sensitive fields before returning
            redacted_config = config.model_dump()
            for sensitive_key in ["app_secret", "verification_token", "encrypt_key"]:
                if sensitive_key in redacted_config:
                    redacted_config[sensitive_key] = "***MASKED***"
            return FeishuBotResponse(success=True, message=f"Bot {config.name or config.app_id} configured successfully", data=redacted_config)
        else:
            return FeishuBotResponse(success=False, message=f"Failed to configure bot {config.app_id}")
    except Exception as e:
        logger.exception("Failed to create/update Feishu bot: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to configure bot: {str(e)}")


@router.delete("/feishu/bots/{app_id}", response_model=FeishuBotResponse)
async def delete_feishu_bot(app_id: str) -> FeishuBotResponse:
    """Delete a Feishu bot configuration."""
    from app.channels.service import get_channel_service

    service = get_channel_service()
    if service is None:
        raise HTTPException(status_code=503, detail="Channel service is not running")

    bot_manager = service.get_feishu_bot_manager()
    if bot_manager is None:
        raise HTTPException(status_code=400, detail="FeishuBotManager is not available")

    try:
        success = await bot_manager.remove_bot(app_id)

        if success:
            logger.info("Feishu bot deleted: %s", app_id)
            return FeishuBotResponse(success=True, message=f"Bot {app_id} deleted successfully")
        else:
            return FeishuBotResponse(success=False, message=f"Bot {app_id} not found")
    except Exception as e:
        logger.exception("Failed to delete Feishu bot: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to delete bot: {str(e)}")


@router.post("/feishu/bots/{app_id}/restart", response_model=FeishuBotResponse)
async def restart_feishu_bot(app_id: str) -> FeishuBotResponse:
    """Restart a specific Feishu bot."""
    from app.channels.service import get_channel_service

    service = get_channel_service()
    if service is None:
        raise HTTPException(status_code=503, detail="Channel service is not running")

    bot_manager = service.get_feishu_bot_manager()
    if bot_manager is None:
        raise HTTPException(status_code=400, detail="FeishuBotManager is not available")

    try:
        success = await bot_manager.restart_bot(app_id)

        if success:
            logger.info("Feishu bot restarted: %s", app_id)
            return FeishuBotResponse(success=True, message=f"Bot {app_id} restarted successfully")
        else:
            return FeishuBotResponse(success=False, message=f"Bot {app_id} not found or failed to restart")
    except Exception as e:
        logger.exception("Failed to restart Feishu bot: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to restart bot: {str(e)}")


@router.get("/feishu/health")
async def get_feishu_health() -> dict[str, Any]:
    """Get health status for Feishu bots."""
    from app.channels.service import get_channel_service

    service = get_channel_service()
    if service is None:
        return {"status": "unhealthy", "message": "Channel service is not running"}

    bot_manager = service.get_feishu_bot_manager()
    if bot_manager is None:
        # Lazy initialize FeishuBotManager to support dynamic bot creation
        from app.channels.feishu import FeishuBotManager
        bot_manager = FeishuBotManager()
        service.set_feishu_bot_manager(bot_manager)
        await bot_manager.start()

    bots_status = bot_manager.get_bot_status()
    total_bots = len(bots_status)
    enabled_bots = sum(1 for bot in bots_status.values() if bot.get("enabled", False))
    connected_bots = sum(1 for bot in bots_status.values() if bot.get("running", False))

    return {
        "status": "healthy",
        "total_bots": total_bots,
        "enabled_bots": enabled_bots,
        "connected_bots": connected_bots,
        "bots": bots_status,
    }
