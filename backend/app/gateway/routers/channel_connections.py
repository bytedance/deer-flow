"""Browser-facing APIs for user-owned IM channel bindings."""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.channels.runtime_config_store import (
    ChannelRuntimeConfigStore,
    apply_runtime_connection_config,
    merge_runtime_channel_configs,
)
from app.gateway.deps import require_admin_user
from deerflow.config.channel_connections_config import ChannelConnectionsConfig
from deerflow.persistence.channel_connections import ChannelConnectionRepository
from deerflow.persistence.engine import get_session_factory

router = APIRouter(prefix="/api/channels", tags=["channel-connections"])
logger = logging.getLogger(__name__)

_STATE_TTL_SECONDS = 600
_MAX_PENDING_CONNECT_CODES_PER_PROVIDER = 5
_MASKED_CREDENTIAL_VALUE = "********"
_ADMIN_REQUIRED_DETAIL = "Admin privileges required to manage channel runtime credentials."


class ChannelCredentialFieldResponse(BaseModel):
    name: str
    label: str
    type: str = "text"
    required: bool = True


class ChannelProviderResponse(BaseModel):
    provider: str
    display_name: str
    enabled: bool
    configured: bool
    connectable: bool
    unavailable_reason: str | None = None
    auth_mode: str
    connection_status: str
    credential_fields: list[ChannelCredentialFieldResponse] = Field(default_factory=list)
    credential_values: dict[str, str] = Field(default_factory=dict)


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


class ChannelRuntimeConfigRequest(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


_PROVIDER_META: dict[str, dict[str, str]] = {
    "telegram": {"display_name": "Telegram", "auth_mode": "deep_link"},
    "slack": {"display_name": "Slack", "auth_mode": "binding_code"},
    "discord": {"display_name": "Discord", "auth_mode": "binding_code"},
    "feishu": {"display_name": "Feishu", "auth_mode": "binding_code"},
    "dingtalk": {"display_name": "DingTalk", "auth_mode": "binding_code"},
    "wechat": {"display_name": "WeChat", "auth_mode": "binding_code"},
    "wecom": {"display_name": "WeCom", "auth_mode": "binding_code"},
}

_CREDENTIAL_FIELDS: dict[str, tuple[dict[str, str], ...]] = {
    "telegram": (
        {"name": "bot_token", "label": "Bot token", "type": "password"},
        {"name": "bot_username", "label": "Bot username", "type": "text"},
    ),
    "slack": (
        {"name": "bot_token", "label": "Bot token", "type": "password"},
        {"name": "app_token", "label": "App token", "type": "password"},
    ),
    "discord": ({"name": "bot_token", "label": "Bot token", "type": "password"},),
    "feishu": (
        {"name": "app_id", "label": "App ID", "type": "text"},
        {"name": "app_secret", "label": "App secret", "type": "password"},
    ),
    "dingtalk": (
        {"name": "client_id", "label": "Client ID", "type": "text"},
        {"name": "client_secret", "label": "Client secret", "type": "password"},
    ),
    "wechat": ({"name": "bot_token", "label": "Bot token", "type": "password"},),
    "wecom": (
        {"name": "bot_id", "label": "Bot ID", "type": "text"},
        {"name": "bot_secret", "label": "Bot secret", "type": "password"},
    ),
}

_RUNTIME_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "telegram": ("bot_token",),
    "slack": ("bot_token", "app_token"),
    "discord": ("bot_token",),
    "feishu": ("app_id", "app_secret"),
    "dingtalk": ("client_id", "client_secret"),
    "wechat": ("bot_token",),
    "wecom": ("bot_id", "bot_secret"),
}


def _get_user_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user.id)


def _get_app_config():
    from deerflow.config.app_config import get_app_config

    return get_app_config()


async def _get_runtime_config_store(request: Request) -> ChannelRuntimeConfigStore:
    store = getattr(request.app.state, "channel_runtime_config_store", None)
    if isinstance(store, ChannelRuntimeConfigStore):
        return store
    # Constructing the store reads its JSON file from disk; keep it off the
    # event loop.
    store = await asyncio.to_thread(ChannelRuntimeConfigStore)
    request.app.state.channel_runtime_config_store = store
    return store


async def _get_channel_connections_config(request: Request) -> ChannelConnectionsConfig:
    config = getattr(request.app.state, "channel_connections_config", None)
    if not isinstance(config, ChannelConnectionsConfig):
        config = _get_app_config().channel_connections
    config = apply_runtime_connection_config(config, store=await _get_runtime_config_store(request))
    request.app.state.channel_connections_config = config
    return config


async def _get_channels_config(request: Request) -> dict[str, Any]:
    state_config = getattr(request.app.state, "channels_config", None)
    if isinstance(state_config, dict):
        return state_config

    result = await _load_channels_config(request, await _get_channel_connections_config(request))
    request.app.state.channels_config = result
    return result


async def _load_channels_config(request: Request, config: ChannelConnectionsConfig) -> dict[str, Any]:
    app_config = _get_app_config()
    extra = app_config.model_extra or {}
    channels_config = extra.get("channels")
    result = dict(channels_config) if isinstance(channels_config, dict) else {}
    merge_runtime_channel_configs(
        result,
        config,
        store=await _get_runtime_config_store(request),
    )
    return result


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
    # Resolve provider configs only for known providers. An unrestricted
    # getattr would let a request-supplied name that happens to match another
    # config attribute (e.g. the "enabled" / "require_bound_identity" bool
    # fields) slip past the 404 and return a non-provider value, which callers
    # then dereference as a provider config (AttributeError -> HTTP 500).
    if provider not in _PROVIDER_META:
        raise HTTPException(status_code=404, detail="Unknown channel provider")
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
    meta = _PROVIDER_META.get(provider)
    display_name = meta["display_name"] if meta else provider
    return f"Enter the required {display_name} credentials to connect this channel."


def _runtime_not_running_reason(provider: str) -> str:
    meta = _PROVIDER_META.get(provider)
    display_name = meta["display_name"] if meta else provider
    return f"{display_name} channel is configured but is not running. Check the credentials and service logs."


def _runtime_channel_running(provider: str) -> bool | None:
    try:
        from app.channels.service import get_channel_service
    except Exception:
        logger.debug("Unable to inspect channel service status", exc_info=True)
        return None

    service = get_channel_service()
    if service is None:
        return None
    try:
        status = service.get_status()
    except Exception:
        logger.debug("Unable to read channel service status", exc_info=True)
        return None

    if not status.get("service_running"):
        return False
    channel_status = status.get("channels", {}).get(provider)
    if not isinstance(channel_status, dict):
        return None
    return bool(channel_status.get("running"))


async def _ensure_runtime_channel_ready_if_available(
    provider: str,
    channels_config: dict[str, Any],
) -> bool | None:
    runtime_config = channels_config.get(provider)
    if not isinstance(runtime_config, dict) or not runtime_config.get("enabled", False):
        return None

    try:
        from app.channels.service import get_channel_service
    except Exception:
        logger.debug("Unable to import channel service for readiness reconciliation", exc_info=True)
        return None

    service = get_channel_service()
    if service is None:
        return None

    ensure_channel_ready = getattr(service, "ensure_channel_ready", None)
    if ensure_channel_ready is None:
        return None

    try:
        return await ensure_channel_ready(provider, runtime_config)
    except Exception:
        logger.exception("Failed to reconcile runtime channel readiness")
        return False


def _provider_unavailable_reason(
    config: ChannelConnectionsConfig,
    channels_config: dict[str, Any],
    provider: str,
) -> str | None:
    provider_config = _provider_config(config, provider)
    if not provider_config.enabled:
        return None
    if not provider_config.configured:
        return _runtime_unavailable_reason(provider)
    if not _runtime_channel_configured(provider, channels_config):
        return _runtime_unavailable_reason(provider)
    if _runtime_channel_running(provider) is False:
        return _runtime_not_running_reason(provider)
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
    return secrets.token_urlsafe(16)


async def _create_state(
    repo: ChannelConnectionRepository,
    *,
    owner_user_id: str,
    provider: str,
) -> str:
    now = datetime.now(UTC)
    state = _new_binding_code()
    # Atomic delete-expired + count + insert so concurrent connect POSTs from one
    # owner cannot each see count < cap and all insert past the cap.
    inserted = await repo.create_oauth_state_within_cap(
        owner_user_id=owner_user_id,
        provider=provider,
        state=state,
        expires_at=now + timedelta(seconds=_STATE_TTL_SECONDS),
        max_pending=_MAX_PENDING_CONNECT_CODES_PER_PROVIDER,
        now=now,
    )
    if not inserted:
        raise HTTPException(
            status_code=429,
            detail="Too many pending channel connection codes. Wait for existing codes to expire or use one of them.",
        )
    return state


def _connect_instruction(provider: str, code: str) -> str:
    if provider == "telegram":
        return f"Send /start {code} to the DeerFlow Telegram bot."
    meta = _PROVIDER_META.get(provider)
    if meta is None:
        raise HTTPException(status_code=404, detail="Unknown channel provider")
    return f"Send /connect {code} to the DeerFlow {meta['display_name']} bot."


def _connect_url(config: ChannelConnectionsConfig, provider: str, code: str) -> str | None:
    if provider == "telegram":
        provider_config = _provider_config(config, provider)
        return f"https://t.me/{provider_config.bot_username}?start={code}"
    if _PROVIDER_META.get(provider, {}).get("auth_mode") == "binding_code":
        return None
    raise HTTPException(status_code=404, detail="Unknown channel provider")


def _connection_updated_at(connection: dict[str, Any]) -> datetime:
    value = connection.get("updated_at")
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=UTC)


def _newest_connection_by_provider(connections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_provider: dict[str, dict[str, Any]] = {}
    for item in connections:
        existing = by_provider.get(item["provider"])
        if existing is None or _connection_updated_at(item) > _connection_updated_at(existing):
            by_provider[item["provider"]] = item
    return by_provider


def _credential_fields(provider: str) -> list[ChannelCredentialFieldResponse]:
    fields = _CREDENTIAL_FIELDS.get(provider)
    if fields is None:
        raise HTTPException(status_code=404, detail="Unknown channel provider")
    return [ChannelCredentialFieldResponse(**field) for field in fields]


def _credential_values(provider: str, channels_config: dict[str, Any]) -> dict[str, str]:
    runtime_config = channels_config.get(provider)
    if not isinstance(runtime_config, dict):
        return {}

    values: dict[str, str] = {}
    for field in _credential_fields(provider):
        value = str(runtime_config.get(field.name) or "").strip()
        if not value:
            continue
        values[field.name] = _MASKED_CREDENTIAL_VALUE if field.type == "password" else value
    return values


def _provider_response(
    config: ChannelConnectionsConfig,
    channels_config: dict[str, Any],
    provider: str,
    meta: dict[str, str],
    connection: dict[str, Any] | None = None,
) -> ChannelProviderResponse:
    from app.gateway.auth_disabled import is_auth_disabled

    status, unavailable_reason = _provider_status(config, channels_config, provider)
    if unavailable_reason is not None:
        # The runtime provider is unavailable, so a stale "connected" row must
        # not be reported as connected. Other statuses (e.g. "revoked") are
        # preserved so consumers can still distinguish a revoked binding from a
        # never-connected one.
        if connection and connection["status"] != "connected":
            connection_status = connection["status"]
        else:
            connection_status = "not_connected"
    elif connection:
        connection_status = connection["status"]
    elif is_auth_disabled() and status["configured"] and unavailable_reason is None:
        # Auth-disabled local mode routes every channel message to the default
        # user, so a configured running channel needs no per-user binding.
        connection_status = "connected"
    else:
        connection_status = "not_connected"
    credential_values = _credential_values(provider, channels_config)
    if provider == "telegram" and not credential_values.get("bot_username"):
        bot_username = str(_provider_config(config, provider).bot_username or "").strip()
        if bot_username:
            credential_values["bot_username"] = bot_username
    return ChannelProviderResponse(
        provider=provider,
        display_name=meta["display_name"],
        enabled=status["enabled"],
        configured=status["configured"],
        connectable=status["enabled"] and status["configured"] and unavailable_reason is None,
        unavailable_reason=unavailable_reason,
        auth_mode=meta["auth_mode"],
        connection_status=connection_status,
        credential_fields=_credential_fields(provider),
        credential_values=credential_values,
    )


def _required_runtime_values(
    provider: str,
    values: dict[str, str],
    existing_config: dict[str, Any] | None = None,
) -> dict[str, str]:
    fields = _credential_fields(provider)
    cleaned: dict[str, str] = {}
    missing: list[str] = []
    existing_config = existing_config or {}
    for field in fields:
        raw_value = values.get(field.name, "")
        if field.type == "password" and raw_value == _MASKED_CREDENTIAL_VALUE:
            existing_value = str(existing_config.get(field.name) or "").strip()
            if existing_value:
                cleaned[field.name] = existing_value
                continue
        value = raw_value.strip() if isinstance(raw_value, str) else str(raw_value or "").strip()
        if field.required and not value:
            missing.append(field.label)
        cleaned[field.name] = value
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required channel configuration: {', '.join(missing)}")
    return cleaned


async def _restart_runtime_channel_if_available(provider: str, runtime_config: dict[str, Any]) -> bool | None:
    try:
        from app.channels.service import get_channel_service
    except Exception:
        logger.exception("Failed to import channel service while configuring a runtime channel")
        return None

    service = get_channel_service()
    if service is None:
        return None
    return await service.configure_channel(provider, runtime_config)


async def _sync_runtime_channel_after_removal(provider: str, channels_config: dict[str, Any]) -> bool | None:
    try:
        from app.channels.service import get_channel_service
    except Exception:
        logger.exception("Failed to import channel service while disconnecting a runtime channel")
        return None

    service = get_channel_service()
    if service is None:
        return None

    runtime_config = channels_config.get(provider)
    if isinstance(runtime_config, dict) and runtime_config.get("enabled", False):
        return await service.configure_channel(provider, runtime_config)
    return await service.remove_channel(provider)


@router.get("/providers", response_model=ChannelProvidersResponse)
async def get_channel_providers(request: Request) -> ChannelProvidersResponse:
    config = await _get_channel_connections_config(request)
    channels_config = await _get_channels_config(request)
    repo = None
    if config.enabled:
        try:
            repo = _get_repository(request, config)
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
    owner_user_id = _get_user_id(request)
    connections = await repo.list_connections(owner_user_id) if repo is not None else []
    by_provider = _newest_connection_by_provider(connections)

    enabled_providers = [provider for provider in _PROVIDER_META if config.provider_status(provider)["enabled"]]
    # Readiness reconciliation is independent per provider; run it
    # concurrently so one slow channel restart does not serialize the
    # whole /providers response.
    await asyncio.gather(
        *(_ensure_runtime_channel_ready_if_available(provider, channels_config) for provider in enabled_providers if _runtime_channel_configured(provider, channels_config)),
    )

    providers: list[ChannelProviderResponse] = []
    for provider in enabled_providers:
        connection = by_provider.get(provider)
        providers.append(_provider_response(config, channels_config, provider, _PROVIDER_META[provider], connection))
    return ChannelProvidersResponse(enabled=config.enabled, providers=providers)


@router.get("/connections", response_model=ChannelConnectionsResponse)
async def get_channel_connections(request: Request) -> ChannelConnectionsResponse:
    config = await _get_channel_connections_config(request)
    if not config.enabled:
        return ChannelConnectionsResponse(connections=[])
    repo = _get_repository(request, config)
    rows = await repo.list_connections(_get_user_id(request))
    return ChannelConnectionsResponse(connections=[ChannelConnectionResponse(**row) for row in rows])


@router.delete("/connections/{connection_id}", status_code=204)
async def disconnect_channel_connection(connection_id: str, request: Request) -> Response:
    config = await _get_channel_connections_config(request)
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


@router.delete("/{provider}/runtime-config", response_model=ChannelProviderResponse)
async def disconnect_channel_provider_runtime(provider: str, request: Request) -> ChannelProviderResponse:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    config = await _get_channel_connections_config(request)
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Channel connections are disabled")

    provider_config = _provider_config(config, provider)
    if not provider_config.enabled:
        raise HTTPException(status_code=400, detail="Channel provider is not enabled")

    try:
        repo = _get_repository(request, config)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        repo = None

    current_channels_config = await _get_channels_config(request)
    candidate_channels_config = dict(current_channels_config)
    candidate_channels_config.pop(provider, None)

    stopped = await _sync_runtime_channel_after_removal(provider, candidate_channels_config)
    if stopped is False:
        display_name = _PROVIDER_META[provider]["display_name"]
        raise HTTPException(status_code=400, detail=f"Failed to stop {display_name} channel. Try again.")

    # Revoke the DB connection rows before committing the store/cache so a repo
    # failure cannot leave the store and cache saying "disconnected" while the
    # DB still holds "connected" rows that a later re-configure would silently
    # reactivate.
    if repo is not None:
        await repo.disconnect_provider_connections(provider=provider)

    store = await _get_runtime_config_store(request)
    await asyncio.to_thread(store.set_provider_disconnected, provider)

    # Re-read the live cached config and drop only this provider so a concurrent
    # mutation for a different provider is not clobbered. No await may occur
    # between this read and the reassignment.
    live_channels_config = await _get_channels_config(request)
    live_channels_config.pop(provider, None)
    request.app.state.channels_config = live_channels_config

    return _provider_response(config, live_channels_config, provider, _PROVIDER_META[provider])


@router.post("/{provider}/connect", response_model=ChannelConnectResponse)
async def connect_channel_provider(provider: str, request: Request) -> ChannelConnectResponse:
    config = await _get_channel_connections_config(request)
    channels_config = await _get_channels_config(request)
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Channel connections are disabled")

    provider_config = _provider_config(config, provider)
    if provider_config.enabled and _runtime_channel_configured(provider, channels_config):
        await _ensure_runtime_channel_ready_if_available(provider, channels_config)

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


@router.post("/{provider}/runtime-config", response_model=ChannelProviderResponse)
async def configure_channel_provider_runtime(
    provider: str,
    body: ChannelRuntimeConfigRequest,
    request: Request,
) -> ChannelProviderResponse:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    config = await _get_channel_connections_config(request)
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Channel connections are disabled")

    provider_config = _provider_config(config, provider)
    if not provider_config.enabled:
        raise HTTPException(status_code=400, detail="Channel provider is not enabled")

    channels_config = await _get_channels_config(request)
    existing = channels_config.get(provider)
    runtime_config = dict(existing) if isinstance(existing, dict) else {}
    values = _required_runtime_values(provider, body.values, runtime_config)
    runtime_config["enabled"] = True

    for key in _RUNTIME_REQUIREMENTS[provider]:
        runtime_config[key] = values[key]

    if provider == "telegram":
        # The deep-link username is persisted with the runtime channel config
        # (set_provider_config below) and applied to future requests via
        # apply_runtime_connection_config; never mutate the config instance
        # cached by get_app_config().
        runtime_config["bot_username"] = values["bot_username"]

    candidate_channels_config = dict(channels_config)
    candidate_channels_config[provider] = runtime_config

    started = await _restart_runtime_channel_if_available(provider, runtime_config)
    if started is False:
        display_name = _PROVIDER_META[provider]["display_name"]
        raise HTTPException(status_code=400, detail=f"Failed to start {display_name} channel. Check the values and try again.")

    store = await _get_runtime_config_store(request)
    await asyncio.to_thread(store.set_provider_config, provider, runtime_config)

    # Re-read the live cached config and apply only this provider's change so a
    # concurrent mutation for a different provider is not clobbered. No await
    # may occur between this read and the reassignment.
    live_channels_config = await _get_channels_config(request)
    live_channels_config[provider] = runtime_config
    request.app.state.channels_config = live_channels_config

    return _provider_response(config, live_channels_config, provider, _PROVIDER_META[provider])
