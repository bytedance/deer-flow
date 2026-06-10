"""Browser-facing APIs for user-owned IM channel bindings."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from deerflow.config.channel_connections_config import ChannelConnectionsConfig
from deerflow.persistence.channel_connections import ChannelConnectionRepository
from deerflow.persistence.engine import get_session_factory

router = APIRouter(prefix="/api/channels", tags=["channel-connections"])

_STATE_TTL_SECONDS = 600


class ChannelProviderResponse(BaseModel):
    provider: str
    display_name: str
    enabled: bool
    configured: bool
    connectable: bool
    unavailable_reason: str | None = None
    auth_mode: str
    connection_status: str


class ChannelProvidersResponse(BaseModel):
    enabled: bool
    providers: list[ChannelProviderResponse]


class ChannelConnectionResponse(BaseModel):
    id: str
    provider: str
    status: str
    external_account_id: str | None = None
    external_account_name: str | None = None
    workspace_id: str | None = None
    workspace_name: str | None = None
    scopes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChannelConnectionsResponse(BaseModel):
    connections: list[ChannelConnectionResponse]


class ChannelConnectResponse(BaseModel):
    provider: str
    mode: str
    url: str | None = None
    code: str
    instruction: str
    expires_in: int


_PROVIDER_META: dict[str, dict[str, str]] = {
    "telegram": {"display_name": "Telegram", "auth_mode": "deep_link"},
    "slack": {"display_name": "Slack", "auth_mode": "binding_code"},
    "discord": {"display_name": "Discord", "auth_mode": "binding_code"},
}

_RUNTIME_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "telegram": ("bot_token",),
    "slack": ("bot_token", "app_token"),
    "discord": ("bot_token",),
}


def _get_user_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user.id)


def _get_app_config():
    from deerflow.config.app_config import get_app_config

    return get_app_config()


def _get_channel_connections_config(request: Request) -> ChannelConnectionsConfig:
    config = getattr(request.app.state, "channel_connections_config", None)
    if isinstance(config, ChannelConnectionsConfig):
        return config
    return _get_app_config().channel_connections


def _get_channels_config(request: Request) -> dict[str, Any]:
    state_config = getattr(request.app.state, "channels_config", None)
    if isinstance(state_config, dict):
        return state_config

    app_config = _get_app_config()
    extra = app_config.model_extra or {}
    channels_config = extra.get("channels")
    return dict(channels_config) if isinstance(channels_config, dict) else {}


def _get_repository(request: Request, config: ChannelConnectionsConfig) -> ChannelConnectionRepository:
    repo = getattr(request.app.state, "channel_connection_repo", None)
    if isinstance(repo, ChannelConnectionRepository):
        return repo

    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Channel connection persistence is not available")

    repo = ChannelConnectionRepository(sf)
    request.app.state.channel_connection_repo = repo
    return repo


def _provider_config(config: ChannelConnectionsConfig, provider: str):
    provider_config = getattr(config, provider, None)
    if provider_config is None:
        raise HTTPException(status_code=404, detail="Unknown channel provider")
    return provider_config


def _runtime_channel_configured(provider: str, channels_config: dict[str, Any]) -> bool:
    runtime_config = channels_config.get(provider)
    if not isinstance(runtime_config, dict) or not runtime_config.get("enabled", False):
        return False
    return all(str(runtime_config.get(key) or "").strip() for key in _RUNTIME_REQUIREMENTS[provider])


def _runtime_unavailable_reason(provider: str) -> str:
    keys = " and ".join(f"channels.{provider}.{key}" for key in _RUNTIME_REQUIREMENTS[provider])
    return f"Enable and configure channels.{provider} with {keys}."


def _provider_unavailable_reason(
    config: ChannelConnectionsConfig,
    channels_config: dict[str, Any],
    provider: str,
) -> str | None:
    provider_config = _provider_config(config, provider)
    if not provider_config.enabled:
        return None
    if not provider_config.configured:
        if provider == "telegram":
            return "Configure channel_connections.telegram.bot_username for Telegram deep links."
        return f"Configure channel_connections.{provider}."
    if not _runtime_channel_configured(provider, channels_config):
        return _runtime_unavailable_reason(provider)
    return None


def _provider_status(
    config: ChannelConnectionsConfig,
    channels_config: dict[str, Any],
    provider: str,
) -> tuple[dict[str, bool], str | None]:
    declared = config.provider_status(provider)
    unavailable_reason = _provider_unavailable_reason(config, channels_config, provider)
    configured = declared["configured"] and _runtime_channel_configured(provider, channels_config)
    return {"enabled": declared["enabled"], "configured": configured}, unavailable_reason


def _new_binding_code() -> str:
    return secrets.token_hex(4)


async def _create_state(
    repo: ChannelConnectionRepository,
    *,
    owner_user_id: str,
    provider: str,
) -> str:
    state = _new_binding_code()
    await repo.create_oauth_state(
        owner_user_id=owner_user_id,
        provider=provider,
        state=state,
        expires_at=datetime.now(UTC) + timedelta(seconds=_STATE_TTL_SECONDS),
    )
    return state


def _connect_instruction(provider: str, code: str) -> str:
    if provider == "telegram":
        return f"Send /start {code} to the DeerFlow Telegram bot."
    if provider == "slack":
        return f"Send /connect {code} to the DeerFlow Slack bot."
    if provider == "discord":
        return f"Send /connect {code} to the DeerFlow Discord bot."
    raise HTTPException(status_code=404, detail="Unknown channel provider")


def _connect_url(config: ChannelConnectionsConfig, provider: str, code: str) -> str | None:
    if provider == "telegram":
        provider_config = _provider_config(config, provider)
        return f"https://t.me/{provider_config.bot_username}?start={code}"
    if provider in {"slack", "discord"}:
        return None
    raise HTTPException(status_code=404, detail="Unknown channel provider")


@router.get("/providers", response_model=ChannelProvidersResponse)
async def get_channel_providers(request: Request) -> ChannelProvidersResponse:
    config = _get_channel_connections_config(request)
    channels_config = _get_channels_config(request)
    repo = None
    if config.enabled:
        try:
            repo = _get_repository(request, config)
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
    owner_user_id = _get_user_id(request)
    connections = await repo.list_connections(owner_user_id) if repo is not None else []
    by_provider = {item["provider"]: item for item in connections}

    providers: list[ChannelProviderResponse] = []
    for provider, meta in _PROVIDER_META.items():
        status, unavailable_reason = _provider_status(config, channels_config, provider)
        connection = by_provider.get(provider)
        providers.append(
            ChannelProviderResponse(
                provider=provider,
                display_name=meta["display_name"],
                enabled=status["enabled"],
                configured=status["configured"],
                connectable=status["enabled"] and status["configured"] and unavailable_reason is None,
                unavailable_reason=unavailable_reason,
                auth_mode=meta["auth_mode"],
                connection_status=connection["status"] if connection else "not_connected",
            )
        )
    return ChannelProvidersResponse(enabled=config.enabled, providers=providers)


@router.get("/connections", response_model=ChannelConnectionsResponse)
async def get_channel_connections(request: Request) -> ChannelConnectionsResponse:
    config = _get_channel_connections_config(request)
    if not config.enabled:
        return ChannelConnectionsResponse(connections=[])
    repo = _get_repository(request, config)
    rows = await repo.list_connections(_get_user_id(request))
    return ChannelConnectionsResponse(connections=[ChannelConnectionResponse(**row) for row in rows])


@router.delete("/connections/{connection_id}", status_code=204)
async def disconnect_channel_connection(connection_id: str, request: Request) -> Response:
    config = _get_channel_connections_config(request)
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Channel connections are disabled")

    repo = _get_repository(request, config)
    disconnected = await repo.disconnect_connection(
        connection_id=connection_id,
        owner_user_id=_get_user_id(request),
    )
    if not disconnected:
        raise HTTPException(status_code=404, detail="Channel connection not found")
    return Response(status_code=204)


@router.post("/{provider}/connect", response_model=ChannelConnectResponse)
async def connect_channel_provider(provider: str, request: Request) -> ChannelConnectResponse:
    config = _get_channel_connections_config(request)
    channels_config = _get_channels_config(request)
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Channel connections are disabled")

    status, unavailable_reason = _provider_status(config, channels_config, provider)
    if not status["enabled"]:
        raise HTTPException(status_code=400, detail="Channel provider is not enabled")
    if unavailable_reason:
        raise HTTPException(status_code=400, detail=unavailable_reason)
    if not status["configured"]:
        raise HTTPException(status_code=400, detail="Channel provider is not configured")

    repo = _get_repository(request, config)
    code = await _create_state(
        repo,
        owner_user_id=_get_user_id(request),
        provider=provider,
    )
    return ChannelConnectResponse(
        provider=provider,
        mode=_PROVIDER_META[provider]["auth_mode"],
        url=_connect_url(config, provider, code),
        code=code,
        instruction=_connect_instruction(provider, code),
        expires_in=_STATE_TTL_SECONDS,
    )
