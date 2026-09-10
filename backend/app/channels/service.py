"""ChannelService — manages the lifecycle of all IM channels."""

from __future__ import annotations

import asyncio
import logging
import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.channels.base import Channel
from app.channels.manager import DEFAULT_CHANNEL_MAX_CONCURRENCY, DEFAULT_CHANNEL_SHUTDOWN_GRACE_PERIOD_SECONDS, DEFAULT_GATEWAY_URL, DEFAULT_LANGGRAPH_URL, ChannelManager
from app.channels.message_bus import DEFAULT_INBOUND_QUEUE_MAXSIZE, MessageBus
from app.channels.runtime_config_store import merge_runtime_channel_configs
from app.channels.store import ChannelStore

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig
    from deerflow.config.channel_connections_config import ChannelConnectionsConfig
    from deerflow.runtime import StreamBridge

# Channel name → import path for lazy loading
_CHANNEL_REGISTRY: dict[str, str] = {
    "buzz": "app.channels.buzz:BuzzChannel",
    "dingtalk": "app.channels.dingtalk:DingTalkChannel",
    "discord": "app.channels.discord:DiscordChannel",
    "feishu": "app.channels.feishu:FeishuChannel",
    "github": "app.channels.github:GitHubChannel",
    "slack": "app.channels.slack:SlackChannel",
    "telegram": "app.channels.telegram:TelegramChannel",
    "wechat": "app.channels.wechat:WechatChannel",
    "wecom": "app.channels.wecom:WeComChannel",
}

# Keys that indicate a user has configured credentials for a channel.
_CHANNEL_CREDENTIAL_KEYS: dict[str, list[str]] = {
    "buzz": ["private_key"],
    "dingtalk": ["client_id", "client_secret"],
    "discord": ["bot_token"],
    "feishu": ["app_id", "app_secret"],
    "slack": ["bot_token", "app_token"],
    "telegram": ["bot_token"],
    "wecom": ["bot_id", "bot_secret"],
    "wechat": ["bot_token"],
}

_CHANNELS_LANGGRAPH_URL_ENV = "DEER_FLOW_CHANNELS_LANGGRAPH_URL"
_CHANNELS_GATEWAY_URL_ENV = "DEER_FLOW_CHANNELS_GATEWAY_URL"


def _channel_has_credentials(name: str, channel_config: dict[str, Any]) -> bool:
    cred_keys = _CHANNEL_CREDENTIAL_KEYS.get(name, [])
    return any(not isinstance(channel_config.get(key), bool) and channel_config.get(key) is not None and str(channel_config[key]).strip() for key in cred_keys)


def _resolve_service_url(config: dict[str, Any], config_key: str, env_key: str, default: str) -> str:
    value = config.pop(config_key, None)
    if isinstance(value, str) and value.strip():
        return value
    env_value = os.getenv(env_key, "").strip()
    if env_value:
        return env_value
    return default


def _resolve_positive_int(config: dict[str, Any], config_key: str, default: int) -> int:
    value = config.pop(config_key, None)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        logger.warning("Invalid channels.%s=%r; using default %d", config_key, value, default)
        return default
    return value


def _resolve_non_negative_float(config: dict[str, Any], config_key: str, default: float) -> float:
    value = config.pop(config_key, None)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        logger.warning("Invalid channels.%s=%r; using default %.1f", config_key, value, default)
        return default
    return float(value)


def _merge_channel_connection_runtime_config(channels_config: dict[str, Any], app_config: AppConfig) -> None:
    connection_config = getattr(app_config, "channel_connections", None)
    merge_runtime_channel_configs(channels_config, connection_config)


def _make_connection_repo(connection_config: ChannelConnectionsConfig | None):
    if connection_config is None or not getattr(connection_config, "enabled", False):
        return None

    try:
        from deerflow.persistence.channel_connections import ChannelConnectionRepository
        from deerflow.persistence.engine import get_session_factory
    except Exception:
        logger.exception("Failed to import channel connection repository")
        return None

    session_factory = get_session_factory()
    if session_factory is None:
        logger.warning("Channel connections are enabled but database persistence is not available")
        return None
    return ChannelConnectionRepository(session_factory)


class ChannelService:
    """Manages the lifecycle of all configured IM channels.

    Reads configuration from ``config.yaml`` under the ``channels`` key,
    instantiates enabled channels, and starts the ChannelManager dispatcher.
    """

    def __init__(
        self,
        channels_config: dict[str, Any] | None = None,
        *,
        connection_repo: Any | None = None,
        require_bound_identity: bool = False,
        app_config: AppConfig | None = None,
        get_stream_bridge: Callable[[], StreamBridge | None] | None = None,
    ) -> None:
        config = dict(channels_config or {})
        inbound_queue_maxsize = _resolve_positive_int(config, "inbound_queue_maxsize", DEFAULT_INBOUND_QUEUE_MAXSIZE)
        max_concurrency = _resolve_positive_int(config, "max_concurrency", DEFAULT_CHANNEL_MAX_CONCURRENCY)
        shutdown_grace_period_seconds = _resolve_non_negative_float(config, "shutdown_grace_period_seconds", DEFAULT_CHANNEL_SHUTDOWN_GRACE_PERIOD_SECONDS)
        self.bus = MessageBus(inbound_queue_maxsize=inbound_queue_maxsize)
        self.store = ChannelStore()
        self._connection_repo = connection_repo
        self._get_stream_bridge = get_stream_bridge
        langgraph_url = _resolve_service_url(config, "langgraph_url", _CHANNELS_LANGGRAPH_URL_ENV, DEFAULT_LANGGRAPH_URL)
        gateway_url = _resolve_service_url(config, "gateway_url", _CHANNELS_GATEWAY_URL_ENV, DEFAULT_GATEWAY_URL)
        default_session = config.pop("session", None)
        channel_sessions = {name: channel_config.get("session") for name, channel_config in config.items() if isinstance(channel_config, dict)}
        from app.channels.dedupe_store import make_inbound_dedupe_store

        self.manager = ChannelManager(
            bus=self.bus,
            store=self.store,
            max_concurrency=max_concurrency,
            shutdown_grace_period_seconds=shutdown_grace_period_seconds,
            langgraph_url=langgraph_url,
            gateway_url=gateway_url,
            default_session=default_session if isinstance(default_session, dict) else None,
            channel_sessions=channel_sessions,
            connection_repo=connection_repo,
            require_bound_identity=require_bound_identity,
            inbound_dedupe_store=make_inbound_dedupe_store(app_config),
            get_stream_bridge=get_stream_bridge,
        )
        self._channels: dict[str, Any] = {}  # name -> Channel instance
        self._config = config
        self._running = False
        self._readiness_locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def from_app_config(
        cls,
        app_config: AppConfig | None = None,
        *,
        get_stream_bridge: Callable[[], StreamBridge | None] | None = None,
    ) -> ChannelService:
        """Create a ChannelService from the application config.

        ``get_stream_bridge`` is threaded straight through to the
        ``ChannelManager`` (see its docstring); it is optional so direct
        callers (including most tests) that don't need follow-up-buffer
        auto-draining can omit it.
        """
        if app_config is None:
            from deerflow.config.app_config import get_app_config

            app_config = get_app_config()
        channels_config = {}
        # extra fields are allowed by AppConfig (extra="allow")
        extra = app_config.model_extra or {}
        if "channels" in extra:
            channels_config = dict(extra["channels"] or {})
        _merge_channel_connection_runtime_config(channels_config, app_config)
        connection_config = getattr(app_config, "channel_connections", None)
        connections_enabled = connection_config is not None and getattr(connection_config, "enabled", False)
        require_bound_identity = bool(connections_enabled and getattr(connection_config, "require_bound_identity", True))
        return cls(
            channels_config=channels_config,
            connection_repo=_make_connection_repo(connection_config),
            require_bound_identity=require_bound_identity,
            app_config=app_config,
            get_stream_bridge=get_stream_bridge,
        )

    async def start(self) -> None:
        """Start the manager and all enabled channels."""
        if self._running:
            return

        await self.manager.start()
        self._running = True

        ready_status = await self.ensure_ready_channels(attempts=2)
        ready_count = sum(1 for ready in ready_status.values() if ready)
        logger.info("ChannelService started with %d/%d ready channels", ready_count, len(ready_status))

    async def ensure_ready_channels(self, *, attempts: int = 1) -> dict[str, bool]:
        """Start or restart enabled configured channels that are not ready."""
        ready_status: dict[str, bool] = {}
        for name, channel_config in self._config.items():
            if not isinstance(channel_config, dict):
                continue
            if not channel_config.get("enabled", False):
                if _channel_has_credentials(name, channel_config):
                    logger.warning(
                        "A configured channel has credentials configured but is disabled. Set enabled: true under its channels entry in config.yaml to activate it.",
                    )
                else:
                    logger.info("A configured channel is disabled, skipping")
                continue

            ready_status[name] = await self.ensure_channel_ready(name, attempts=attempts)
        return ready_status

    async def ensure_channel_ready(
        self,
        name: str,
        config: dict[str, Any] | None = None,
        *,
        attempts: int = 1,
    ) -> bool:
        """Ensure a single enabled channel is running using its current config."""
        if not self._running:
            logger.warning("ChannelService is not running; cannot ensure channel readiness")
            return False

        if config is not None:
            self._config[name] = dict(config)

        # Serialize per channel: readiness is polled from request handlers, so
        # concurrent calls must not stop/start the same channel worker twice.
        lock = self._readiness_locks.setdefault(name, asyncio.Lock())
        async with lock:
            channel_config = self._config.get(name)
            if not channel_config or not isinstance(channel_config, dict):
                logger.warning("No config for requested channel")
                return False
            if not channel_config.get("enabled", False):
                return False

            channel = self._channels.get(name)
            if channel is not None and channel.is_running:
                return True

            if channel is not None:
                # Ownership-preserving cleanup: the instance is retained when
                # its stop() fails or is cancelled, and this round must NOT
                # start a replacement over it — _start_channel would overwrite
                # the tracked entry and orphan the still-subscribed listener
                # one hop later (the gap this closes from the review on 5227).
                await self._stop_and_discard_channel(name, channel)
                if self._channels.get(name) is channel:
                    logger.warning("Readiness retry deferred: previous %s channel failed to stop and remains tracked", name)
                    return False

            max_attempts = max(1, attempts)
            for attempt in range(max_attempts):
                if attempt > 0:
                    logger.info("Retrying channel startup after readiness check")
                if await self._start_channel(name, channel_config):
                    return True
                # A failed attempt whose cleanup retained the instance ends
                # the loop for this round: the next attempt would be refused
                # by _start_channel's retained-instance guard anyway, and the
                # still-tracked channel must not be replaced one hop later.
                if self._channels.get(name) is not None:
                    logger.warning("Readiness retries deferred: %s channel failed to clean up after a failed start and remains tracked", name)
                    return False
            return False

    async def stop(self) -> None:
        """Drain accepted messages while channels can still deliver replies."""
        self._running = False
        # Reject new provider work first. Existing workers keep draining during
        # manager.stop(), and channel transports remain alive until that drain
        # completes so an already-sent "Working on it..." can still receive its
        # final update.
        await self.manager.stop()
        stop_errors: list[Exception] = []
        for name, channel in list(self._channels.items()):
            try:
                await channel.stop()
            except asyncio.CancelledError:
                # Keep this and the remaining transports owned by the service.
                # The Gateway deadline interrupted shutdown, so detaching them
                # would hide resources that may still be in use.
                raise
            except Exception as exc:
                logger.exception("Error stopping channel")
                stop_errors.append(exc)
            else:
                if self._channels.get(name) is channel:
                    self._channels.pop(name, None)
                logger.info("Channel stopped")

        if stop_errors:
            raise ExceptionGroup("one or more channels failed to stop", stop_errors)

        logger.info("ChannelService stopped")

    def _load_channel_config(self, name: str) -> dict[str, Any] | None:
        """Load the latest config for a specific channel from disk.

        Uses ``get_app_config()`` which detects file changes via config
        signature, so edits to ``config.yaml`` are picked up without a process
        restart.
        The UI runtime-config overlay applied at startup is re-applied here
        so a file-driven reload neither drops credentials entered from the
        browser nor resurrects a channel disconnected from it.
        Falls back to the cached ``self._config`` when config loading fails.
        """
        try:
            from deerflow.config.app_config import get_app_config

            app_config = get_app_config()
            extra = app_config.model_extra or {}
            channels_config = dict(extra.get("channels") or {})
            _merge_channel_connection_runtime_config(channels_config, app_config)
            channel_config = channels_config.get(name)
            if isinstance(channel_config, dict):
                # Update the cached config so get_status() stays consistent.
                self._config[name] = channel_config
                return channel_config
        except Exception:
            logger.exception("Failed to reload config for channel %s, using cached version", name)
        return self._config.get(name)

    async def restart_channel(self, name: str, *, reload_config: bool = True) -> bool:
        """Restart a specific channel. Returns True if successful."""
        if name in self._channels:
            channel = self._channels[name]
            # Same ownership rule as readiness retries: retain an instance
            # whose stop() fails, and decline the restart rather than
            # overwriting a still-tracked (still-listening) channel.
            await self._stop_and_discard_channel(name, channel)
            if self._channels.get(name) is channel:
                logger.warning("Restart deferred: %s channel failed to stop and remains tracked", name)
                return False

        if reload_config:
            # Reading config.yaml and the runtime store is disk IO; keep it
            # off the event loop.
            config = await asyncio.to_thread(self._load_channel_config, name)
        else:
            config = self._config.get(name)
        if not config or not isinstance(config, dict):
            logger.warning("No config for requested channel")
            return False

        if not config.get("enabled", False):
            logger.info("Channel %s is disabled, skipping restart", name)
            return True

        return await self._start_channel(name, config)

    async def configure_channel(self, name: str, config: dict[str, Any]) -> bool:
        """Apply runtime config for a channel and restart it if the service is running."""
        self._config[name] = dict(config)
        if not self._running:
            return True
        # The caller just supplied the authoritative config (e.g. credentials
        # entered in the browser that are never written to config.yaml) — a
        # file reload here would clobber it with the stale on-disk entry.
        return await self.restart_channel(name, reload_config=False)

    async def remove_channel(self, name: str) -> bool:
        """Remove runtime config for a channel and stop it if currently running."""
        self._config.pop(name, None)
        channel = self._channels.get(name)
        if channel is None:
            return True
        # Stop-then-drop with the shared ownership rule: a channel whose
        # stop() fails stays tracked (and returns False) instead of being
        # popped first and leaking its subscribed listener on failure.
        await self._stop_and_discard_channel(name, channel)
        if self._channels.get(name) is channel:
            logger.warning("Removal incomplete: %s channel failed to stop and remains tracked", name)
            return False
        logger.info("Channel stopped and removed")
        return True

    async def _stop_and_discard_channel(self, name: str, channel: Channel) -> None:
        """Stop a channel and drop it only once its ``stop()`` has completed.

        This is the single ownership-preserving cleanup every discard path
        routes through (failed startup, readiness retry, restart, removal).
        ``start()`` subscribes the outbound listener before the transport is
        up, so an instance that never reached ``is_running`` — or a running
        one being torn down — must be ``stop()``-ed before it is discarded:
        otherwise the bus keeps a strong reference to the dead listener and
        every future outbound for this channel name fans out to it, while
        repeated attempts accumulate more stale listeners the service can no
        longer clean up (the instances are untracked by then). Discord's
        fail-fast ``is_running`` makes this reachable for a client thread that
        dies immediately (invalid token); the same hygiene applies to any
        channel that subscribes before its transport is confirmed.

        Ownership mirrors ``ChannelService.stop()``: the instance is dropped
        only after its ``stop()`` actually completes. A cancellation arriving
        mid-cleanup (or a ``stop()`` that raises) leaves it tracked, so a
        retried readiness attempt stops it again before replacing it and
        service shutdown can still reach it — untracking first would orphan
        resources nobody can clean up anymore. Callers check for retention
        (``self._channels.get(name) is channel``) and defer starting or
        removing a replacement for that round, so startup cannot silently
        overwrite a still-listening retained instance; ``ensure_channel_ready``
        additionally serializes on the per-channel readiness lock.
        """
        try:
            await channel.stop()
        except asyncio.CancelledError:
            # Keep this transport owned by the service: the Gateway deadline
            # interrupted cleanup, so detaching it here would hide resources
            # that may still be in use (mirrors ChannelService.stop()).
            raise
        except Exception:
            logger.exception("Error stopping channel %s during discard", name)
            return
        if self._channels.get(name) is channel:
            self._channels.pop(name, None)

    async def _start_channel(self, name: str, config: dict[str, Any]) -> bool:
        """Instantiate and start a single channel."""
        import_path = _CHANNEL_REGISTRY.get(name)
        if not import_path:
            logger.warning("Unknown channel type")
            return False

        # Never install a fresh instance over a retained one: a channel whose
        # failed cleanup kept it tracked still holds a subscribed outbound
        # listener, and overwriting the entry here is the one remaining way to
        # orphan it (nothing would be able to stop it afterwards). Callers
        # decline the operation when they see the name still tracked; this
        # guard makes the invariant hold at the mechanism itself.
        retained = self._channels.get(name)
        if retained is not None:
            logger.warning("Refusing to start %s: previous channel instance is still tracked after failed cleanup", name)
            return False

        try:
            from deerflow.reflection import resolve_class

            channel_cls = resolve_class(import_path, base_class=None)
        except Exception:
            logger.exception("Failed to import channel class")
            return False

        channel: Channel | None = None
        try:
            config = dict(config)
            config["channel_store"] = self.store
            if name == "buzz" and "seen_event_store_path" not in config:
                # Durable processed-event ids for the Buzz connector's replay
                # guard. Wired here (like channel_store) rather than defaulted
                # inside the connector so that directly constructed channels
                # (tests, tooling) stay free of filesystem side effects.
                from deerflow.config.paths import get_paths

                config["seen_event_store_path"] = str(Path(get_paths().base_dir) / "channels" / "buzz_seen_events.json")
            if self._connection_repo is not None:
                config["connection_repo"] = self._connection_repo
            channel = channel_cls(bus=self.bus, config=config)
            self._channels[name] = channel
            await channel.start()
            if not channel.is_running:
                logger.error("Channel did not enter a running state after start()")
                await self._stop_and_discard_channel(name, channel)
                return False
            logger.info("Channel started")
            return True
        except Exception:
            logger.exception("Failed to start channel")
            if channel is not None:
                await self._stop_and_discard_channel(name, channel)
            else:
                self._channels.pop(name, None)
            return False

    def get_status(self) -> dict[str, Any]:
        """Return status information for all channels."""
        channels_status = {}
        for name in _CHANNEL_REGISTRY:
            config = self._config.get(name, {})
            enabled = isinstance(config, dict) and config.get("enabled", False)
            running = name in self._channels and self._channels[name].is_running
            channels_status[name] = {
                "enabled": enabled,
                "running": running,
            }
        return {
            "service_running": self._running,
            "channels": channels_status,
        }

    def get_channel(self, name: str) -> Channel | None:
        """Return a running channel instance by name when available."""
        return self._channels.get(name)

    def is_channel_enabled(self, name: str) -> bool:
        """Return whether ``channels.<name>.enabled`` is truthy in the live config.

        Tracks the runtime-authoritative ``_config`` dict, which
        :meth:`configure_channel` updates when the UI flips the
        enabled flag — so callers that read this between requests get
        the current effective setting without re-reading config.yaml.
        Used by the GitHub webhook router as a fan-out kill-switch:
        ``channels.github.enabled: false`` skips dispatch even though
        the webhook route itself remains mounted (which is governed by
        ``GITHUB_WEBHOOK_SECRET``, not this flag).
        """
        config = self._config.get(name)
        if not isinstance(config, dict):
            return False
        return bool(config.get("enabled", False))

    def get_channel_config(self, name: str) -> dict[str, Any] | None:
        """Return a shallow copy of the live ``channels.<name>`` block, or None.

        Mirrors :meth:`is_channel_enabled` in tracking the runtime-
        authoritative ``_config`` dict, so callers see the same effective
        configuration the manager sees — including any updates pushed via
        :meth:`configure_channel` from the UI. Returns ``None`` when no
        config exists for ``name`` (rather than an empty dict) so callers
        can distinguish "not configured" from "configured with defaults".
        The shallow copy keeps callers from accidentally mutating live
        config state.
        """
        config = self._config.get(name)
        if not isinstance(config, dict):
            return None
        return dict(config)


# -- singleton access -------------------------------------------------------

_channel_service: ChannelService | None = None


def get_channel_service() -> ChannelService | None:
    """Get the singleton ChannelService instance (if started)."""
    return _channel_service


async def start_channel_service(
    app_config: AppConfig | None = None,
    *,
    get_stream_bridge: Callable[[], StreamBridge | None] | None = None,
) -> ChannelService:
    """Create and start the global ChannelService from app config.

    ``get_stream_bridge`` is threaded through to ``ChannelService.from_app_config``
    -> ``ChannelManager`` so fire_and_forget channels that opt into
    ``ChannelRunPolicy.buffer_followups_on_busy`` (currently GitHub) can watch
    a run's completion and auto-drain buffered follow-ups. ``app.py``'s
    lifespan passes a closure over ``app.state.stream_bridge`` here, the same
    pattern it already uses for ``ScheduledTaskService``'s ``launch_run``.
    """
    global _channel_service
    if _channel_service is not None:
        return _channel_service
    # from_app_config reads the JSON channel store and runtime config files;
    # keep that disk IO off the event loop. asyncio.to_thread forwards both
    # args and kwargs to the target callable.
    _channel_service = await asyncio.to_thread(ChannelService.from_app_config, app_config, get_stream_bridge=get_stream_bridge)
    await _channel_service.start()
    return _channel_service


async def stop_channel_service() -> None:
    """Stop the global ChannelService."""
    global _channel_service
    if _channel_service is not None:
        service = _channel_service
        await service.stop()
        if _channel_service is service:
            _channel_service = None
