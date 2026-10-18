"""ChannelService — manages the lifecycle of all IM channels."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import socket
import uuid
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.channels.base import Channel, ChannelStopTimeout
from app.channels.leadership import ChannelLeadership, RenewOutcome
from app.channels.manager import DEFAULT_CHANNEL_MAX_CONCURRENCY, DEFAULT_CHANNEL_SHUTDOWN_GRACE_PERIOD_SECONDS, DEFAULT_GATEWAY_URL, DEFAULT_LANGGRAPH_URL, ChannelManager
from app.channels.message_bus import DEFAULT_INBOUND_QUEUE_MAXSIZE, MessageBus
from app.channels.runtime_config_store import RuntimeConfigStore, SqlChannelRuntimeConfigStore, merge_runtime_channel_configs, overlay_runtime_channel_configs, resolve_runtime_config_store, runtime_channel_disconnected
from app.channels.store import ChannelStore, SqlChannelStore, resolve_channel_store
from deerflow.config.channel_leader_lease_config import CHANNEL_LEADER_LEASE_FIELD, CHANNEL_LEADER_LEASE_KEY, ChannelLeaderLeaseConfig, channel_leader_lease_config
from deerflow.utils.file_io import await_drained

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
    "qq": "app.channels.qq:QQChannel",
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
    "qq": ["app_id", "client_secret"],
    "slack": ["bot_token", "app_token"],
    "telegram": ["bot_token"],
    "wecom": ["bot_id", "bot_secret"],
    "wechat": ["bot_token"],
}

# Providers the leader lease never arbitrates: GitHub receives webhooks pushed
# to whichever instance the load balancer picks and opens no platform
# connection of its own, so every instance keeps it.
_UNARBITRATED_PROVIDERS = frozenset({"github"})

# Ceiling for the supervisor's retry backoff when a leader cannot start its
# transport (bad credentials, platform outage).
_LEASE_START_BACKOFF_MAX_SECONDS = 300.0

_CHANNELS_LANGGRAPH_URL_ENV = "DEER_FLOW_CHANNELS_LANGGRAPH_URL"
_CHANNELS_GATEWAY_URL_ENV = "DEER_FLOW_CHANNELS_GATEWAY_URL"


def _channel_has_credentials(name: str, channel_config: dict[str, Any]) -> bool:
    cred_keys = _CHANNEL_CREDENTIAL_KEYS.get(name, [])
    return any(not isinstance(channel_config.get(key), bool) and channel_config.get(key) is not None and str(channel_config[key]).strip() for key in cred_keys)


def enabled_transport_providers(app_config: Any) -> list[str]:
    """Return the providers whose platform connection this deployment may open.

    These are the channels the leader lease arbitrates: every registered
    provider that is ``enabled`` under ``channels.*`` in config.yaml, plus every
    provider a user may connect from the web UI (``channel_connections.<p>.enabled``
    with ``channel_connections.enabled``), whose credentials arrive at runtime
    and start the transport without a restart. GitHub is excluded: it receives
    webhooks pushed to whichever instance the load balancer picks and opens no
    platform connection of its own. ``model_extra`` / ``channel_connections``
    may be absent on config doubles; both then contribute nothing.
    """
    names: set[str] = set()
    extra = getattr(app_config, "model_extra", None) or {}
    channels = extra.get("channels") if isinstance(extra, Mapping) else None
    if isinstance(channels, Mapping):
        for name, block in channels.items():
            if name in _CHANNEL_REGISTRY and isinstance(block, Mapping) and block.get("enabled", False):
                names.add(name)
    connections = getattr(app_config, "channel_connections", None)
    if connections is not None and getattr(connections, "enabled", False):
        for name in _CHANNEL_REGISTRY:
            provider = getattr(connections, name, None)
            if provider is not None and getattr(provider, "enabled", False):
                names.add(name)
    names.difference_update(_UNARBITRATED_PROVIDERS)
    return sorted(names)


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


def _runtime_config_enabled(app_config: Any) -> bool:
    connection_config = getattr(app_config, "channel_connections", None)
    return connection_config is not None and bool(getattr(connection_config, "enabled", False))


def _prepare_runtime_config(channels_config: dict[str, Any], app_config: AppConfig, *, credentials_cipher: Any | None) -> RuntimeConfigStore | None:
    """Overlay the web-UI runtime config on ``channels_config`` and return the store it came from.

    ``None`` when ``channel_connections`` is off (no runtime config applies).
    The database store first moves a pre-table ``runtime-config.json`` into
    the table (idempotent, tolerant of a peer importing concurrently), so the
    overlay already sees it. Blocks: ``from_app_config`` runs off the loop.
    """
    if not _runtime_config_enabled(app_config):
        return None
    store = resolve_runtime_config_store(app_config, cipher=credentials_cipher)
    if isinstance(store, SqlChannelRuntimeConfigStore):
        store.import_legacy_json()
    merge_runtime_channel_configs(channels_config, app_config.channel_connections, store=store)
    return store


def _make_connection_repo(connection_config: ChannelConnectionsConfig | None, *, credentials_cipher: Any | None = None):
    """Build the connection repository; ``credentials_cipher`` encrypts per-connection credentials."""
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
    return ChannelConnectionRepository(session_factory, cipher=credentials_cipher)


def _default_lease_owner_id() -> str:
    """Same shape as the RunManager worker id the Gateway passes in (``hostname:uuid``)."""
    return f"{socket.gethostname()}:{uuid.uuid4().hex}"


def _make_leadership(lease_config: ChannelLeaderLeaseConfig, *, owner_id: str | None) -> ChannelLeadership:
    """Build the lease bookkeeping over the shared application database.

    The lease needs the shared table; an active lease without a SQL database
    is a configuration the startup gate refuses, so reaching it here is an
    error rather than a silent fallback to every instance connecting.
    """
    from deerflow.persistence.channel_leases import SqlChannelLeaseRepository
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError(f"{CHANNEL_LEADER_LEASE_FIELD} is active but the application database is not available; set database.backend to sqlite or postgres")
    return ChannelLeadership(
        SqlChannelLeaseRepository(session_factory),
        owner_id=owner_id or _default_lease_owner_id(),
        lease_seconds=lease_config.lease_seconds,
        grace_seconds=lease_config.grace_seconds,
    )


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
        store: ChannelStore | None = None,
        leadership: ChannelLeadership | None = None,
        runtime_config_store: RuntimeConfigStore | None = None,
        credentials_cipher: Any | None = None,
    ) -> None:
        config = dict(channels_config or {})
        # ``channels.leader_lease`` is a settings block, not a provider: take it
        # out before the per-provider loops below and in ensure_ready_channels
        # see it. The startup gate has already validated it; a direct caller
        # (tests, embedded use) gets the same ValueError on a bad block.
        self.leader_lease: ChannelLeaderLeaseConfig = channel_leader_lease_config({CHANNEL_LEADER_LEASE_KEY: config.pop(CHANNEL_LEADER_LEASE_KEY, None)})
        inbound_queue_maxsize = _resolve_positive_int(config, "inbound_queue_maxsize", DEFAULT_INBOUND_QUEUE_MAXSIZE)
        max_concurrency = _resolve_positive_int(config, "max_concurrency", DEFAULT_CHANNEL_MAX_CONCURRENCY)
        shutdown_grace_period_seconds = _resolve_non_negative_float(config, "shutdown_grace_period_seconds", DEFAULT_CHANNEL_SHUTDOWN_GRACE_PERIOD_SECONDS)
        self.bus = MessageBus(inbound_queue_maxsize=inbound_queue_maxsize)
        # Chat-to-thread bindings: the shared ``channel_thread_bindings`` table
        # for a sqlite/postgres database, the legacy JSON file otherwise. The
        # JSON path resolves ``base_dir`` through realpath, so ``from_app_config``
        # runs this constructor off the loop.
        self.store: ChannelStore = store if store is not None else resolve_channel_store(app_config)
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
        self._stopping = False
        self._shutdown_generation = 0
        self._manager_start_lock = asyncio.Lock()
        self._readiness_locks: dict[str, asyncio.Lock] = {}
        self._config_epochs: dict[str, int] = {}
        # ``None`` unless ``channels.leader_lease`` is active for this process:
        # then only the lease holder of a provider may start its transport.
        self._leadership = leadership
        self._supervisor_task: asyncio.Task | None = None
        # One transport action (start / stop) in flight per provider, so a
        # slow platform never delays another provider's renewal.
        self._lease_actions: dict[str, asyncio.Task] = {}
        # provider -> (consecutive failed starts, monotonic time of next retry)
        self._lease_start_backoff: dict[str, tuple[int, float]] = {}
        # Web-UI runtime config (``channel_runtime_configs`` for a database).
        # Resolved on first reload when not given; the cipher decrypts it then.
        self._runtime_config_store = runtime_config_store
        self._credentials_cipher = credentials_cipher
        # provider -> runtime config version this instance has applied; the
        # lease supervisor compares it with the store to apply peers' saves.
        self._runtime_config_versions: dict[str, int] = {}

    @classmethod
    def from_app_config(
        cls,
        app_config: AppConfig | None = None,
        *,
        get_stream_bridge: Callable[[], StreamBridge | None] | None = None,
        credentials_cipher: Any | None = None,
        multi_process: bool = False,
        lease_owner_id: str | None = None,
    ) -> ChannelService:
        """Create a ChannelService from the application config.

        ``get_stream_bridge`` is threaded straight through to the
        ``ChannelManager`` (see its docstring); it is optional so direct
        callers (including most tests) that don't need follow-up-buffer
        auto-draining can omit it. ``credentials_cipher`` is the Gateway's
        ``DEER_FLOW_CREDENTIALS_KEY`` cipher for per-connection credentials;
        without it stored credentials stay unavailable. ``multi_process`` is
        the Gateway's multi-process signal, which ``channels.leader_lease:
        auto`` follows; ``lease_owner_id`` names this instance in the lease
        table (the Gateway passes its RunManager worker id).
        """
        if app_config is None:
            from deerflow.config.app_config import get_app_config

            app_config = get_app_config()
        channels_config = {}
        # extra fields are allowed by AppConfig (extra="allow")
        extra = app_config.model_extra or {}
        if "channels" in extra:
            channels_config = dict(extra["channels"] or {})
        runtime_config_store = _prepare_runtime_config(channels_config, app_config, credentials_cipher=credentials_cipher)
        connection_config = getattr(app_config, "channel_connections", None)
        connections_enabled = connection_config is not None and getattr(connection_config, "enabled", False)
        require_bound_identity = bool(connections_enabled and getattr(connection_config, "require_bound_identity", True))
        lease_config = channel_leader_lease_config(channels_config)
        leadership = _make_leadership(lease_config, owner_id=lease_owner_id) if lease_config.resolve(multi_process=multi_process) else None
        return cls(
            channels_config=channels_config,
            connection_repo=_make_connection_repo(connection_config, credentials_cipher=credentials_cipher),
            require_bound_identity=require_bound_identity,
            app_config=app_config,
            get_stream_bridge=get_stream_bridge,
            leadership=leadership,
            runtime_config_store=runtime_config_store,
            credentials_cipher=credentials_cipher,
        )

    async def start(self) -> None:
        """Start the manager and all enabled channels."""
        if self._running:
            return
        if self._stopping:
            raise RuntimeError("cannot start ChannelService while shutdown is incomplete")

        generation = self._shutdown_generation
        async with self._manager_start_lock:
            if generation != self._shutdown_generation or self._running:
                return
            if isinstance(self.store, SqlChannelStore):
                # One-time move of a pre-database ``channels/store.json`` into the
                # shared table (idempotent; a peer replica importing concurrently is
                # tolerated). It runs under the start lock, after the generation
                # check and before the manager starts, so the bindings are in the
                # table before the first message is routed (a known chat would
                # otherwise get a second thread), and a stop() that lands during
                # the import bumps the generation and invalidates this start.
                await self.store.import_legacy_json()
                if generation != self._shutdown_generation:
                    return
            await self.manager.start()
            if generation != self._shutdown_generation:
                # Keep newer starts waiting until this late start is drained.
                # stop() must remain free to invalidate an in-flight startup.
                await self.manager.stop()
                return
            self._running = True

        ready_status = await self.ensure_ready_channels(attempts=2)
        ready_count = sum(1 for ready in ready_status.values() if ready)
        if self._leadership is None:
            logger.info("ChannelService started with %d/%d ready channels", ready_count, len(ready_status))
            return
        led_elsewhere = sorted(name for name in ready_status if self._arbitrated(name) and not self._leadership.has_record(name))
        logger.info(
            "ChannelService started with %d/%d ready channels; leader lease active as %s (led by another instance: %s)",
            ready_count,
            len(ready_status),
            self._leadership.owner_id,
            ", ".join(led_elsewhere) or "none",
        )
        if self._running and generation == self._shutdown_generation:
            # Learn peers' leases before the first tick, so status and
            # notification claims are right from the start.
            await self._leadership.observe_all()
        # Re-check after the read: a stop() during it must not be followed by a supervisor.
        if self._running and generation == self._shutdown_generation:
            self._start_supervisor()

    async def ensure_ready_channels(self, *, attempts: int = 1) -> dict[str, bool]:
        """Start or restart enabled configured channels that are not ready."""
        ready_status: dict[str, bool] = {}
        for name, channel_config in self._config.items():
            if not isinstance(channel_config, dict):
                continue
            if name not in _CHANNEL_REGISTRY:
                # __init__ already popped the settings blocks (session, leader_lease),
                # so an enabled dict here is almost certainly a misspelled provider
                # key; say so instead of skipping it silently.
                if name != CHANNEL_LEADER_LEASE_KEY and channel_config.get("enabled", False):
                    logger.warning("Ignoring channels.%s: it is enabled but is not a registered provider (%s). Check the key spelling in config.yaml.", name, ", ".join(sorted(_CHANNEL_REGISTRY)))
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

        epoch = self._config_epochs.get(name, 0)
        async with self._channel_lock(name):
            if not self._running:
                return False

            if config is not None:
                if self._config_epochs.get(name, 0) == epoch:
                    self._config[name] = dict(config)
                else:
                    logger.info(
                        "Ignoring stale config snapshot for channel %s after concurrent reconfiguration",
                        name,
                    )
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

            if not await self._claim_transport(name):
                # Another instance holds the lease: its transport is the one
                # that serves this provider, so there is nothing to start here.
                return False

            max_attempts = max(1, attempts)
            for attempt in range(max_attempts):
                if not self._running:
                    return False
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
        self._shutdown_generation += 1
        self._stopping = True
        self._running = False
        # The supervisor starts and stops transports on its own; it must be
        # gone before shutdown snapshots the transports it is about to stop.
        await self._stop_supervisor()
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
            except ChannelStopTimeout as exc:
                logger.warning("Channel %s remains retained after bounded stop timeout: %s", name, exc)
                stop_errors.append(exc)
            except Exception as exc:
                logger.exception("Error stopping channel")
                stop_errors.append(exc)
            else:
                if self._channels.get(name) is channel:
                    self._channels.pop(name, None)
                logger.info("Channel stopped")

        # Hand back the leases of providers whose transport is gone, so a peer
        # connects on its next tick instead of after lease + grace. A retained
        # transport (bounded stop timed out) may still hold its socket: keep
        # its lease to expire on its own rather than invite a second connection.
        if self._leadership is not None:
            await asyncio.gather(*(self._leadership.release(name) for name in self._leadership.held_providers() if name not in self._channels))

        if stop_errors:
            raise ExceptionGroup("one or more channels failed to stop", stop_errors)

        self._stopping = False
        logger.info("ChannelService stopped")

    def _load_channel_config(self, name: str) -> dict[str, Any] | None:
        """Load the latest config for a specific channel (see :meth:`_read_channel_config`).

        Returns a snapshot without mutating shared state, or ``None`` when
        unavailable. The restart caller owns publication and cached fallback.
        """
        try:
            return self._read_channel_config(name)
        except Exception:
            logger.exception("Failed to load config snapshot for channel %s", name)
        return None

    def _read_channel_config(self, name: str) -> dict[str, Any] | None:
        """Read ``name``'s current config; blocks (call off the loop) and raises on failure.

        Uses ``get_app_config()`` which detects file changes via config
        signature, so edits to ``config.yaml`` are picked up without a process
        restart. The web-UI runtime config is re-read from its store and
        overlaid, so a reload neither drops credentials entered from the
        browser (on any instance) nor resurrects a channel disconnected from
        it. A disconnect reads as its disabled tombstone, not as absent: a
        caller that falls back to its cached config for an absent provider
        must not revive credentials a peer disconnected.
        """
        from deerflow.config.app_config import get_app_config

        app_config = get_app_config()
        extra = app_config.model_extra or {}
        channels_config = dict(extra.get("channels") or {})
        store = self._runtime_store(app_config)
        if store is not None:
            overlay_runtime_channel_configs(channels_config, app_config.channel_connections, store.load_all(), keep_disconnected=True)
        channel_config = channels_config.get(name)
        return dict(channel_config) if isinstance(channel_config, dict) else None

    def _runtime_store(self, app_config: Any) -> RuntimeConfigStore | None:
        """The runtime config store, resolved on first use (blocks); ``None`` while ``channel_connections`` is off."""
        if not _runtime_config_enabled(app_config):
            return None
        if self._runtime_config_store is None:
            self._runtime_config_store = resolve_runtime_config_store(app_config, cipher=self._credentials_cipher)
        return self._runtime_config_store

    def _channel_lock(self, name: str) -> asyncio.Lock:
        """Return the per-channel lifecycle lock ensuring serialized mutations."""
        return self._readiness_locks.setdefault(name, asyncio.Lock())

    def _bump_config_epoch(self, name: str) -> int:
        """Bump and return the configuration epoch for a channel.

        Invalidates queued readiness checks carrying an earlier config snapshot.
        """
        self._config_epochs[name] = self._config_epochs.get(name, 0) + 1
        return self._config_epochs[name]

    async def restart_channel(self, name: str, *, reload_config: bool = True) -> bool:
        """Restart a specific channel. Returns True if successful.

        Under the leader lease a restart on an instance that does not hold the
        provider's lease returns False; :meth:`leader_of` names the holder.
        """
        async with self._channel_lock(name):
            return await self._restart_channel_locked(name, reload_config=reload_config)

    async def _take_over_channel(self, name: str) -> bool:
        """Start a provider whose lease this instance just took, from its freshly loaded config.

        Unlike :meth:`restart_channel` it leaves a transport that is already
        running alone: a readiness request may have started it between the
        acquisition and this call.
        """
        async with self._channel_lock(name):
            if self._transport_running(name):
                return True
            return await self._restart_channel_locked(name, reload_config=True)

    async def _restart_channel_locked(self, name: str, *, reload_config: bool = True, accept_peer_leader: bool = False) -> bool:
        """Restart a specific channel. The caller must already hold ``_channel_lock(name)``.

        ``accept_peer_leader`` reports success when another instance holds the
        provider's lease: :meth:`configure_channel` accepted the config, and
        the transport serving the provider is the holder's.
        """
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
            loaded_config = await asyncio.to_thread(self._load_channel_config, name)
            # Publish under the lifecycle lock after await; abandoned workers stay read-only.
            if loaded_config is not None:
                self._config[name] = loaded_config
            config = self._config.get(name)
            self._bump_config_epoch(name)
        else:
            config = self._config.get(name)
        if not config or not isinstance(config, dict):
            logger.warning("No config for requested channel")
            return False

        if not config.get("enabled", False):
            logger.info("Channel %s is disabled, skipping restart", name)
            await self._release_idle_lease(name)
            return True

        if not await self._claim_transport(name):
            leader = self.leader_of(name)
            if accept_peer_leader and leader is not None:
                # The caller persists the config to the shared runtime config
                # store; the holder applies it on its next lease round.
                logger.info("Channel %s is connected by Gateway instance %s, which applies the saved configuration on its next leader lease round", name, leader)
                return True
            return False

        return await self._start_channel(name, config)

    async def configure_channel(self, name: str, config: dict[str, Any]) -> bool:
        """Apply runtime config for a channel and restart it if the service is running."""
        async with self._channel_lock(name):
            self._bump_config_epoch(name)
            try:
                self._config[name] = dict(config)
                if not self._running:
                    return True
                # The caller just supplied the authoritative config (e.g. credentials
                # entered in the browser that are never written to config.yaml) — a
                # file reload here would clobber it with the stale on-disk entry.
                return await self._restart_channel_locked(name, reload_config=False, accept_peer_leader=True)
            finally:
                self._bump_config_epoch(name)

    async def remove_channel(self, name: str) -> bool:
        """Remove runtime config for a channel and stop it if currently running."""
        async with self._channel_lock(name):
            self._bump_config_epoch(name)
            try:
                self._config.pop(name, None)
                channel = self._channels.get(name)
                if channel is None:
                    await self._release_idle_lease(name)
                    return True
                # Stop-then-drop with the shared ownership rule: a channel whose
                # stop() fails stays tracked (and returns False) instead of being
                # popped first and leaking its subscribed listener on failure.
                await self._stop_and_discard_channel(name, channel)
                if self._channels.get(name) is channel:
                    logger.warning("Removal incomplete: %s channel failed to stop and remains tracked", name)
                    return False
                await self._release_idle_lease(name)
                logger.info("Channel stopped and removed")
                return True
            finally:
                self._bump_config_epoch(name)

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
        overwrite a still-listening retained instance; all per-channel
        lifecycle mutations (``ensure_channel_ready``, ``restart_channel``,
        ``configure_channel``, ``remove_channel``) additionally serialize on
        the per-channel lock.
        """
        try:
            await channel.stop()
        except asyncio.CancelledError:
            # Keep this transport owned by the service: the Gateway deadline
            # interrupted cleanup, so detaching it here would hide resources
            # that may still be in use (mirrors ChannelService.stop()).
            raise
        except ChannelStopTimeout as exc:
            logger.warning("Channel %s remains retained after bounded stop timeout: %s", name, exc)
            return
        except Exception:
            logger.exception("Error stopping channel %s during discard", name)
            return
        if self._channels.get(name) is channel:
            self._channels.pop(name, None)

    async def _start_channel(self, name: str, config: dict[str, Any]) -> bool:
        """Instantiate and start a single channel."""
        if self._stopping or not self._running:
            logger.warning("Refusing to start %s while ChannelService is stopped or stopping", name)
            return False

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
            logger.warning("Refusing to start %s: another channel instance is still tracked under this name (previous cleanup incomplete, or the instance is still running)", name)
            return False

        # The lease fence at the mechanism itself: every start path (startup,
        # readiness, restart, runtime config, supervisor) ends here, and only
        # the holder of a provider's leader lease may open its platform
        # connection. Callers acquire first (_claim_transport); this check
        # makes no database call.
        if self._arbitrated(name) and not self._leadership.holds(name):
            logger.warning("Refusing to start %s: this Gateway instance does not hold its leader lease", name)
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

                def _default_seen_store_path() -> str:
                    # Worker thread: ``base_dir`` resolves through realpath, and a
                    # channel start runs on the Gateway event loop — including the
                    # per-request ``POST /api/channels/{name}/restart`` path.
                    return str(Path(get_paths().base_dir) / "channels" / "buzz_seen_events.json")

                config["seen_event_store_path"] = await asyncio.to_thread(_default_seen_store_path)
            if self._connection_repo is not None:
                config["connection_repo"] = self._connection_repo
            # A stop may have started while this coroutine was suspended in
            # pre-start I/O above. Fence publication again immediately before
            # the new instance becomes service-owned.
            if self._stopping or not self._running:
                logger.warning("Refusing to publish %s channel while ChannelService is stopped or stopping", name)
                return False
            channel = channel_cls(bus=self.bus, config=config)
            self._channels[name] = channel
            await channel.start()
            # A concurrent service stop may finish while channel.start() is
            # suspended, removing this instance before it subscribes. Drain
            # the late-started transport rather than leaving an orphan.
            if self._stopping or not self._running:
                await self._stop_and_discard_channel(name, channel)
                return False
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

    # -- leader lease ---------------------------------------------------------
    #
    # With ``channels.leader_lease`` active, every arbitrated provider (all but
    # GitHub) has one transport across the deployment: the instance holding
    # its ``channel_leases`` row. The manager, bus and GitHub webhooks keep
    # running on every instance. ``_supervise`` renews held leases every
    # ``renew_interval`` seconds, takes free ones, and stops a transport
    # *before* giving its lease up for lost (see ``app.channels.leadership``).
    # The same round applies web-UI runtime config saved on any instance: the
    # store's per-provider ``version`` says which providers to re-read.

    def _arbitrated(self, name: str) -> bool:
        """Whether ``name``'s transport is subject to the leader lease in this process."""
        return self._leadership is not None and name in _CHANNEL_REGISTRY and name not in _UNARBITRATED_PROVIDERS

    def _wants_transport(self, name: str) -> bool:
        config = self._config.get(name)
        return isinstance(config, dict) and bool(config.get("enabled", False))

    def _transport_running(self, name: str) -> bool:
        channel = self._channels.get(name)
        return channel is not None and bool(channel.is_running)

    async def _claim_transport(self, name: str) -> bool:
        """True when this instance may start ``name``'s transport, taking its lease if it is free."""
        if not self._arbitrated(name):
            return True
        return await self._leadership.acquire(name)

    async def _release_idle_lease(self, name: str) -> None:
        """Hand back a held lease once the provider is disabled here and its transport is gone."""
        if self._arbitrated(name) and self._leadership.has_record(name) and name not in self._channels and not self._wants_transport(name):
            await self._leadership.release(name)

    @property
    def lease_owner_id(self) -> str | None:
        """This instance's name in the lease table, or ``None`` without the leader lease."""
        return self._leadership.owner_id if self._leadership is not None else None

    def leader_of(self, name: str) -> str | None:
        """The instance holding ``name``'s lease as last seen here (``None`` without the lease or a holder)."""
        if not self._arbitrated(name):
            return None
        return self._leadership.leader_of(name)

    def notification_excluded_providers(self) -> frozenset[str] | None:
        """Providers whose scheduled-run notifications this instance must not claim.

        ``None`` without the leader lease. Otherwise the arbitrated providers
        whose lease this instance does not hold and that either are enabled
        here or were last seen held by a live peer: their holder delivers over
        its own transport, and a claim here would only park the row for the
        channel-down interval. The peer check covers a provider connected from
        the web UI on another instance, which never enters this instance's
        config until its next round applies the runtime config. Providers no
        instance runs stay claimable, so their rows still settle.
        """
        if self._leadership is None:
            return None
        lead = self._leadership
        return frozenset(name for name in _CHANNEL_REGISTRY if self._arbitrated(name) and not lead.has_record(name) and (self._wants_transport(name) or lead.peer_leads(name)))

    def _start_supervisor(self) -> None:
        if self._leadership is None or self._supervisor_task is not None:
            return
        self._supervisor_task = asyncio.create_task(self._supervise(), name="channel-leader-lease")

    async def _stop_supervisor(self) -> None:
        tasks = [task for task in (self._supervisor_task, *self._lease_actions.values()) if task is not None]
        self._supervisor_task = None
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _supervise(self) -> None:
        lead = self._leadership
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while self._running:
            # Fixed rate rather than sleep-after-round: a slow round must not
            # stretch the gap between renewals the deadline is computed from.
            # Missed ticks are skipped, not replayed as a burst.
            now = loop.time()
            next_tick = max(next_tick + lead.renew_interval, now)
            await asyncio.sleep(next_tick - now)
            if not self._running:
                return
            try:
                await self._supervise_once()
            except Exception:
                logger.exception("Channel leader lease round failed; retrying on the next tick")

    async def _supervise_once(self) -> None:
        names = set(self._leadership.held_providers())
        names.update(name for name in self._config if self._arbitrated(name) and self._wants_transport(name))
        names.update(name for name in self._channels if self._arbitrated(name))
        ordered = sorted(names)
        # Lease calls are bounded and run concurrently; transport work is
        # handed to per-provider tasks so it never delays a renewal. The
        # whole-table read keeps status and notification claims aware of
        # leases this instance has no config for.
        observed, versions, *decisions = await asyncio.gather(
            self._leadership.observe_all(),
            self._read_runtime_config_versions(),
            *(self._lease_round(name) for name in ordered),
            return_exceptions=True,
        )
        if isinstance(observed, BaseException):
            logger.error("Channel leader lease table read failed", exc_info=observed)
        if isinstance(versions, BaseException):
            logger.error("Channel runtime config versions read failed; retrying on the next tick", exc_info=versions)
        elif self._running:
            # Scheduled before the lease decisions: applying a provider's new
            # config outranks a plain start of the same provider this round,
            # while a fail-closed stop below still preempts it.
            for name, version in sorted(versions.items()):
                if self._arbitrated(name) and self._runtime_config_versions.get(name) != version:
                    self._schedule_lease_action(name, lambda name=name, version=version: self._apply_runtime_config(name, version), preempt=False)
        for name, decision in zip(ordered, decisions):
            if isinstance(decision, BaseException):
                logger.error("Channel %s leader lease round failed", name, exc_info=decision)
            elif decision is not None and self._running:
                action, preempt = decision
                self._schedule_lease_action(name, action, preempt=preempt)

    async def _lease_round(self, name: str) -> tuple[Callable[[], Awaitable[None]], bool] | None:
        """Renew or acquire ``name``'s lease and return the transport action it calls for.

        The second element is ``preempt``: a fail-closed stop cancels a start
        still in flight instead of waiting behind it.
        """
        lead = self._leadership
        if lead.has_record(name):
            outcome = await lead.renew(name, transport_running=self._transport_running(name))
            if outcome is RenewOutcome.LOST:
                return (lambda: self._stop_transport(name, release=False)), True
            if outcome is RenewOutcome.UNCONFIRMED:
                if lead.holds(name):
                    return None
                # Fail closed: a peer may take the lease once it has been
                # expired for grace_seconds, so the transport stops now, while
                # that is still at least grace_seconds away.
                logger.error("Stopping the %s transport: its leader lease renewal could not be confirmed before the local deadline", name)
                lead.forget(name)
                return (lambda: self._stop_transport(name, release=False)), True
            if not self._wants_transport(name):
                return (lambda: self._stop_transport(name, release=True)), False
            if not self._transport_running(name) and self._lease_start_due(name):
                return (lambda: self._start_led_transport(name, reload_config=False)), False
            return None
        if name in self._channels:
            # A transport left without a lease (its stop failed after the lease
            # ended): keep trying to stop it.
            return (lambda: self._stop_transport(name, release=False)), False
        if self._wants_transport(name) and await lead.acquire(name):
            # Taking over from another instance: reload the provider's config
            # so credentials saved since this instance started are used.
            return (lambda: self._start_led_transport(name, reload_config=True)), False
        return None

    async def _read_runtime_config_versions(self) -> dict[str, int]:
        store = self._runtime_config_store
        if store is None:
            return {}
        return await asyncio.wait_for(asyncio.to_thread(store.versions), timeout=self._leadership.operation_timeout)

    async def _apply_runtime_config(self, name: str, version: int) -> None:
        """Apply the runtime config of ``name`` as saved on any instance, then record ``version``.

        Acts only when the freshly read config differs from the one this
        instance runs on: a transport running here restarts with it, or stops
        and hands its lease back when the provider was disabled or
        disconnected, and a held lease whose transport is down (a start that
        failed on the old credentials) starts it now rather than on the next
        round. Without a lease here only the cached config changes, so the
        next lease round competes for the provider (or leaves it) on current
        credentials. A read that races a local reconfiguration is dropped
        unrecorded, and so is a failed one: the next round retries.
        """
        if not self._running:
            return
        epoch = self._config_epochs.get(name, 0)
        config = await asyncio.to_thread(self._read_channel_config, name)
        async with self._channel_lock(name):
            if not self._running or self._config_epochs.get(name, 0) != epoch:
                return
            current = self._config.get(name)
            if config is not None and current is None and runtime_channel_disconnected(config):
                config = None  # a disconnect this instance already applied by never loading the provider
            started = False
            if config != current:
                self._bump_config_epoch(name)
                try:
                    if config is None:
                        self._config.pop(name, None)
                    else:
                        self._config[name] = config
                    # New credentials deserve an immediate start, not the backoff earned by the old ones.
                    self._lease_start_backoff.pop(name, None)
                    channel = self._channels.get(name)
                    if channel is not None:
                        if self._wants_transport(name):
                            await self._restart_channel_locked(name, reload_config=False)
                        else:
                            await self._stop_and_discard_channel(name, channel)
                    elif self._wants_transport(name) and self._leadership.has_record(name):
                        await self._restart_channel_locked(name, reload_config=False)
                        started = True
                    if name not in self._channels:
                        await self._release_idle_lease(name)
                finally:
                    self._bump_config_epoch(name)
                logger.info("Applied runtime config version %d of channel %s", version, name)
            self._runtime_config_versions[name] = version
        if started:
            # Same retry bookkeeping as a start from the lease round.
            self._record_lease_start(name, ok=self._transport_running(name) or not self._wants_transport(name))

    def _schedule_lease_action(self, name: str, action: Callable[[], Awaitable[None]], *, preempt: bool) -> None:
        current = self._lease_actions.get(name)
        if current is not None and not current.done():
            if not preempt:
                return
            current.cancel()

        async def run() -> None:
            if current is not None:
                await asyncio.gather(current, return_exceptions=True)
            await action()

        task = asyncio.create_task(run(), name=f"channel-leader-lease-{name}")
        self._lease_actions[name] = task
        task.add_done_callback(lambda done, name=name: self._lease_action_done(name, done))

    def _lease_action_done(self, name: str, task: asyncio.Task) -> None:
        if self._lease_actions.get(name) is task:
            self._lease_actions.pop(name, None)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Channel %s leader lease action failed", name, exc_info=task.exception())

    async def _stop_transport(self, name: str, *, release: bool) -> None:
        """Stop ``name``'s transport; with ``release``, then hand its (still held) lease back."""
        async with self._channel_lock(name):
            channel = self._channels.get(name)
            if channel is not None:
                await self._stop_and_discard_channel(name, channel)
                if self._channels.get(name) is channel:
                    if release:
                        logger.warning("Keeping the %s leader lease: its transport failed to stop and may still be connected", name)
                    else:
                        logger.error("The %s transport failed to stop after its leader lease ended; another instance may connect concurrently until it stops", name)
                    return
                logger.info("Stopped the %s transport (%s)", name, "provider disabled here" if release else "leader lease ended")
            if release:
                await self._release_idle_lease(name)

    async def _start_led_transport(self, name: str, *, reload_config: bool) -> None:
        if not self._running:
            return
        if reload_config:
            await self._take_over_channel(name)
        else:
            await self.ensure_channel_ready(name)
        self._record_lease_start(name, ok=self._transport_running(name) or not self._wants_transport(name))

    def _lease_start_due(self, name: str) -> bool:
        backoff = self._lease_start_backoff.get(name)
        return backoff is None or self._leadership.now() >= backoff[1]

    def _record_lease_start(self, name: str, *, ok: bool) -> None:
        if ok:
            self._lease_start_backoff.pop(name, None)
            return
        failures = self._lease_start_backoff.get(name, (0, 0.0))[0] + 1
        delay = min(_LEASE_START_BACKOFF_MAX_SECONDS, self._leadership.renew_interval * 2 ** (failures - 1))
        self._lease_start_backoff[name] = (failures, self._leadership.now() + delay)
        logger.warning("The %s transport did not start on its leader; retrying in %.0fs (attempt %d)", name, delay, failures)

    def get_status(self) -> dict[str, Any]:
        """Return status information for all channels.

        Under the leader lease each arbitrated provider also reports
        ``leader`` (the holder's instance id, or ``None``) and ``leader_here``,
        and ``running`` covers a peer holder whose transport was running at its
        last renewal, so every instance answers the same way.
        """
        channels_status = {}
        for name in _CHANNEL_REGISTRY:
            config = self._config.get(name, {})
            enabled = isinstance(config, dict) and config.get("enabled", False)
            running = name in self._channels and self._channels[name].is_running
            channels_status[name] = {
                "enabled": enabled,
                "running": running,
            }
            if self._arbitrated(name):
                channels_status[name]["running"] = running or self._leadership.peer_transport_running(name)
                channels_status[name]["leader"] = self._leadership.leader_of(name)
                channels_status[name]["leader_here"] = self._leadership.has_record(name)
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
    credentials_cipher: Any | None = None,
    multi_process: bool = False,
    lease_owner_id: str | None = None,
) -> ChannelService:
    """Create and start the global ChannelService from app config.

    ``get_stream_bridge`` is threaded through to ``ChannelService.from_app_config``
    -> ``ChannelManager`` so fire_and_forget channels that opt into
    ``ChannelRunPolicy.buffer_followups_on_busy`` (currently GitHub) can watch
    a run's completion and auto-drain buffered follow-ups. ``app.py``'s
    lifespan passes a closure over ``app.state.stream_bridge`` here, the same
    pattern it already uses for ``ScheduledTaskService``'s ``launch_run``.
    ``multi_process`` and ``lease_owner_id`` select and name this instance's
    ``channels.leader_lease`` participation (see ``from_app_config``).
    """
    global _channel_service
    if _channel_service is not None:
        return _channel_service
    # from_app_config resolves the channel store path (realpath) and reads the
    # runtime config files; keep that disk IO off the event loop.
    # asyncio.to_thread forwards both args and kwargs to the target callable.
    service = await asyncio.to_thread(
        ChannelService.from_app_config,
        app_config,
        get_stream_bridge=get_stream_bridge,
        credentials_cipher=credentials_cipher,
        multi_process=multi_process,
        lease_owner_id=lease_owner_id,
    )
    _channel_service = service

    async def rollback_failed_start() -> None:
        global _channel_service
        await service.stop()
        if _channel_service is service:
            _channel_service = None

    try:
        await service.start()
    except BaseException:
        try:
            await await_drained(rollback_failed_start())
        except asyncio.CancelledError:
            # A repeated caller cancellation arrives only after the owned
            # rollback has drained; preserve cancellation semantics.
            raise
        except Exception:
            # Retain the singleton when cleanup itself fails so shutdown can
            # retry it instead of orphaning partially-started resources.
            logger.exception("Failed to stop ChannelService after startup failure; retaining singleton")
        raise
    return service


async def stop_channel_service() -> None:
    """Stop the global ChannelService."""
    global _channel_service
    if _channel_service is not None:
        service = _channel_service
        await service.stop()
        if _channel_service is service:
            _channel_service = None
