"""Browser-facing APIs for user-owned IM channel connections."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.responses import PlainTextResponse, RedirectResponse

from app.channels.message_bus import InboundMessage, InboundMessageType
from app.channels.providers import discord_connect, slack_connect
from deerflow.config.channel_connections_config import ChannelConnectionsConfig
from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher
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
    url: str
    expires_in: int


_PROVIDER_META: dict[str, dict[str, str]] = {
    "telegram": {"display_name": "Telegram", "auth_mode": "deep_link"},
    "slack": {"display_name": "Slack", "auth_mode": "oauth"},
    "discord": {"display_name": "Discord", "auth_mode": "oauth_and_bot_install"},
}


def _get_user_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user.id)


def _get_channel_connections_config(request: Request) -> ChannelConnectionsConfig:
    config = getattr(request.app.state, "channel_connections_config", None)
    if isinstance(config, ChannelConnectionsConfig):
        return config

    from deerflow.config.app_config import get_app_config

    return get_app_config().channel_connections


def _get_repository(request: Request, config: ChannelConnectionsConfig) -> ChannelConnectionRepository:
    repo = getattr(request.app.state, "channel_connection_repo", None)
    if isinstance(repo, ChannelConnectionRepository):
        return repo

    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Channel connection persistence is not available")

    cipher = ChannelCredentialCipher.from_key(config.encryption_key) if config.encryption_key else None
    repo = ChannelConnectionRepository(sf, cipher=cipher)
    request.app.state.channel_connection_repo = repo
    return repo


def _provider_config(config: ChannelConnectionsConfig, provider: str):
    provider_config = getattr(config, provider, None)
    if provider_config is None:
        raise HTTPException(status_code=404, detail="Unknown channel provider")
    return provider_config


def _provider_unavailable_reason(config: ChannelConnectionsConfig, provider: str) -> str | None:
    provider_config = _provider_config(config, provider)
    if not provider_config.enabled or not provider_config.configured:
        return None

    if provider == "telegram" and getattr(provider_config, "delivery", "polling") == "webhook":
        if not provider_config.webhook_secret:
            return "Telegram webhook delivery requires channel_connections.telegram.webhook_secret"
        if not config.public_base_url:
            return "Telegram webhook delivery requires channel_connections.public_base_url; use polling for local/private deployments"

    if provider == "slack" and getattr(provider_config, "event_delivery", "http") == "http" and not config.public_base_url:
        return "Slack HTTP Events require channel_connections.public_base_url; use a public URL/tunnel or Slack Socket Mode for private deployments"

    if provider in {"slack", "discord"} and not config.encryption_key:
        display_name = _PROVIDER_META[provider]["display_name"]
        return f"{display_name} connections require channel_connections.encryption_key to store OAuth credentials"

    return None


def _require_provider_connectable(config: ChannelConnectionsConfig, provider: str) -> None:
    reason = _provider_unavailable_reason(config, provider)
    if reason:
        raise HTTPException(status_code=400, detail=reason)


def _callback_base_url(config: ChannelConnectionsConfig, request: Request) -> str:
    if config.public_base_url:
        return config.public_base_url.rstrip("/")
    return str(request.base_url).rstrip("/")


def _callback_redirect_uri(config: ChannelConnectionsConfig, request: Request, provider: str) -> str:
    return f"{_callback_base_url(config, request)}/api/channels/{provider}/callback"


async def _create_state(
    repo: ChannelConnectionRepository,
    *,
    owner_user_id: str,
    provider: str,
    requested_scopes: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    state = secrets.token_urlsafe(32)
    await repo.create_oauth_state(
        owner_user_id=owner_user_id,
        provider=provider,
        state=state,
        requested_scopes=requested_scopes,
        metadata=metadata,
        expires_at=datetime.now(UTC) + timedelta(seconds=_STATE_TTL_SECONDS),
    )
    return state


def _build_connect_url(config: ChannelConnectionsConfig, request: Request, provider: str, state: str) -> str:
    provider_config = _provider_config(config, provider)
    if provider == "telegram":
        return f"https://t.me/{provider_config.bot_username}?start={state}"

    redirect_uri = _callback_redirect_uri(config, request, provider)
    if provider == "slack":
        query = urlencode(
            {
                "client_id": provider_config.client_id,
                "scope": ",".join(provider_config.scopes),
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )
        return f"https://slack.com/oauth/v2/authorize?{query}"

    if provider == "discord":
        scopes = "identify guilds bot applications.commands"
        query = urlencode(
            {
                "client_id": provider_config.client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": scopes,
                "state": state,
                "permissions": provider_config.permissions,
            }
        )
        return f"https://discord.com/oauth2/authorize?{query}"

    raise HTTPException(status_code=404, detail="Unknown channel provider")


def _callback_redirect(provider: str, state_data: dict[str, Any]) -> RedirectResponse:
    redirect_after = state_data.get("redirect_after")
    if isinstance(redirect_after, str) and redirect_after:
        return RedirectResponse(redirect_after)
    return RedirectResponse(f"/workspace?channel_connected={provider}")


def _get_message_bus(request: Request):
    bus = getattr(request.app.state, "channel_message_bus", None)
    if bus is not None:
        return bus
    try:
        from app.channels.service import get_channel_service
    except Exception:
        return None
    service = get_channel_service()
    return service.bus if service is not None else None


def _get_channel_instance(request: Request, name: str):
    channel_instances = getattr(request.app.state, "channel_instances", None)
    if isinstance(channel_instances, dict) and name in channel_instances:
        return channel_instances[name]
    try:
        from app.channels.service import get_channel_service
    except Exception:
        return None
    service = get_channel_service()
    return service.get_channel(name) if service is not None else None


async def _publish_slack_event(
    *,
    repo: ChannelConnectionRepository,
    bus: Any,
    payload: dict[str, Any],
) -> bool:
    event = payload.get("event") or {}
    event_type = event.get("type")
    if event_type not in {"message", "app_mention"}:
        return False
    if event.get("bot_id") or event.get("subtype"):
        return False

    text = str(event.get("text") or "").strip()
    user_id = str(event.get("user") or "")
    channel_id = str(event.get("channel") or "")
    team_id = str(payload.get("team_id") or event.get("team") or event.get("team_id") or "")
    if not text or not user_id or not channel_id or not team_id:
        return False

    connection = await repo.find_connection_by_external_identity(
        provider="slack",
        external_account_id=user_id,
        workspace_id=team_id,
    )
    if connection is None:
        return False

    thread_ts = str(event.get("thread_ts") or event.get("ts") or "")
    inbound = InboundMessage(
        channel_name="slack",
        chat_id=channel_id,
        user_id=user_id,
        text=text,
        msg_type=InboundMessageType.COMMAND if text.startswith("/") else InboundMessageType.CHAT,
        thread_ts=thread_ts,
        metadata={"team_id": team_id, "event_id": payload.get("event_id")},
        connection_id=connection["id"],
        owner_user_id=connection["owner_user_id"],
        workspace_id=team_id,
    )
    inbound.topic_id = thread_ts or None
    await bus.publish_inbound(inbound)
    return True


@router.get("/providers", response_model=ChannelProvidersResponse)
async def get_channel_providers(request: Request) -> ChannelProvidersResponse:
    config = _get_channel_connections_config(request)
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
        status = config.provider_status(provider)
        connection = by_provider.get(provider)
        unavailable_reason = _provider_unavailable_reason(config, provider)
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


@router.get("/slack/callback")
async def slack_oauth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(status_code=400, detail=f"Slack OAuth failed: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Slack OAuth callback is missing code or state")

    config = _get_channel_connections_config(request)
    provider_config = _provider_config(config, "slack")
    if not config.enabled or not provider_config.enabled or not provider_config.configured:
        raise HTTPException(status_code=400, detail="Channel provider is not configured")

    repo = _get_repository(request, config)
    state_data = await repo.consume_oauth_state(provider="slack", state=state)
    if state_data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    redirect_uri = _callback_redirect_uri(config, request, "slack")
    install = await slack_connect.exchange_slack_oauth_code(
        client_id=provider_config.client_id,
        client_secret=provider_config.client_secret,
        code=code,
        redirect_uri=redirect_uri,
    )
    connection = await repo.upsert_connection(
        owner_user_id=state_data["owner_user_id"],
        provider="slack",
        external_account_id=install.authed_user_id,
        workspace_id=install.team_id,
        workspace_name=install.team_name,
        bot_user_id=install.bot_user_id,
        scopes=install.scopes or state_data.get("requested_scopes", []),
        metadata={"team_id": install.team_id, "team_name": install.team_name},
        status="connected",
    )
    await repo.store_credentials(
        connection["id"],
        access_token=install.bot_access_token,
        token_type="Bearer",
        extra={"bot_user_id": install.bot_user_id, "team_id": install.team_id},
    )
    return _callback_redirect("slack", state_data)


@router.get("/discord/callback")
async def discord_oauth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(status_code=400, detail=f"Discord OAuth failed: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Discord OAuth callback is missing code or state")

    config = _get_channel_connections_config(request)
    provider_config = _provider_config(config, "discord")
    if not config.enabled or not provider_config.enabled or not provider_config.configured:
        raise HTTPException(status_code=400, detail="Channel provider is not configured")

    repo = _get_repository(request, config)
    state_data = await repo.consume_oauth_state(provider="discord", state=state)
    if state_data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    redirect_uri = _callback_redirect_uri(config, request, "discord")
    identity = await discord_connect.complete_discord_oauth(
        client_id=provider_config.client_id,
        client_secret=provider_config.client_secret,
        code=code,
        redirect_uri=redirect_uri,
    )
    connection = await repo.upsert_connection(
        owner_user_id=state_data["owner_user_id"],
        provider="discord",
        external_account_id=identity.user_id,
        external_account_name=identity.display_name or identity.username,
        scopes=identity.scopes or state_data.get("requested_scopes", []),
        capabilities={"message_content_intent_required": provider_config.require_message_content_intent},
        metadata={"username": identity.username, "guilds": identity.guilds},
        status="connected",
    )
    await repo.store_credentials(
        connection["id"],
        access_token=identity.access_token,
        refresh_token=identity.refresh_token,
        token_type=identity.token_type,
        expires_at=identity.expires_at,
        extra={"guilds": identity.guilds},
    )
    return _callback_redirect("discord", state_data)


@router.post("/webhooks/slack/events")
async def slack_events_webhook(request: Request):
    config = _get_channel_connections_config(request)
    provider_config = _provider_config(config, "slack")
    if not config.enabled or not provider_config.enabled or not provider_config.configured:
        raise HTTPException(status_code=400, detail="Channel provider is not configured")

    body = await request.body()
    if not slack_connect.verify_slack_signature(
        signing_secret=provider_config.signing_secret,
        timestamp=request.headers.get("X-Slack-Request-Timestamp"),
        body=body,
        signature=request.headers.get("X-Slack-Signature"),
    ):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid Slack payload") from exc

    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge")
        if not isinstance(challenge, str):
            raise HTTPException(status_code=400, detail="Slack challenge is missing")
        return PlainTextResponse(challenge)

    repo = _get_repository(request, config)
    delivery_id = str(payload.get("event_id") or hashlib.sha256(body).hexdigest())
    payload_hash = hashlib.sha256(body).hexdigest()
    event = payload.get("event") or {}
    is_new = await repo.record_webhook_delivery(
        provider="slack",
        delivery_id=delivery_id,
        payload_sha256=payload_hash,
        event_type=event.get("type"),
    )
    if not is_new:
        return {"ok": True, "duplicate": True, "processed": False}

    bus = _get_message_bus(request)
    processed = False
    if bus is not None:
        processed = await _publish_slack_event(repo=repo, bus=bus, payload=payload)
    return {"ok": True, "processed": processed}


@router.post("/webhooks/telegram")
async def telegram_webhook(request: Request):
    config = _get_channel_connections_config(request)
    provider_config = _provider_config(config, "telegram")
    if not config.enabled or not provider_config.enabled or not provider_config.configured:
        raise HTTPException(status_code=400, detail="Channel provider is not configured")

    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not secret_header or not secrets.compare_digest(secret_header, provider_config.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")

    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid Telegram payload") from exc

    repo = _get_repository(request, config)
    delivery_id = str(payload.get("update_id") or hashlib.sha256(body).hexdigest())
    is_new = await repo.record_webhook_delivery(
        provider="telegram",
        delivery_id=delivery_id,
        payload_sha256=hashlib.sha256(body).hexdigest(),
        event_type="update",
    )
    if not is_new:
        return {"ok": True, "duplicate": True, "processed": False}

    processed = False
    channel = _get_channel_instance(request, "telegram")
    process_update = getattr(channel, "process_webhook_update", None)
    if process_update is not None:
        processed = bool(await process_update(payload))
    return {"ok": True, "processed": processed}


@router.post("/{provider}/connect", response_model=ChannelConnectResponse)
async def connect_channel_provider(provider: str, request: Request) -> ChannelConnectResponse:
    config = _get_channel_connections_config(request)
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Channel connections are disabled")

    provider_config = _provider_config(config, provider)
    if not provider_config.enabled or not provider_config.configured:
        raise HTTPException(status_code=400, detail="Channel provider is not configured")
    _require_provider_connectable(config, provider)

    repo = _get_repository(request, config)
    state = await _create_state(
        repo,
        owner_user_id=_get_user_id(request),
        provider=provider,
        requested_scopes=getattr(provider_config, "scopes", []),
    )
    return ChannelConnectResponse(
        provider=provider,
        mode=_PROVIDER_META[provider]["auth_mode"],
        url=_build_connect_url(config, request, provider, state),
        expires_in=_STATE_TTL_SECONDS,
    )
