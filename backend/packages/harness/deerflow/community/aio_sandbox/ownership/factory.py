"""Resolve the configured sandbox ownership store.

Mirrors ``stream_bridge``'s ``make_stream_bridge``: dispatch on ``config.type``,
lazy per-branch imports so a memory-only install never imports ``redis``, and an
env-var escape hatch so a container deployment can flip the backend without
editing config.yaml.
"""

from __future__ import annotations

import logging
import os
import socket
import uuid

from deerflow.config.sandbox_config import SandboxOwnershipConfig
from deerflow.config.stream_bridge_config import StreamBridgeConfig

from .base import SandboxOwnershipStore

logger = logging.getLogger(__name__)

_ENV_OWNERSHIP_REDIS_URL = "DEER_FLOW_SANDBOX_OWNERSHIP_REDIS_URL"
_ENV_STREAM_BRIDGE_REDIS_URL = "DEER_FLOW_STREAM_BRIDGE_REDIS_URL"


def generate_owner_id() -> str:
    """Return a unique id for this provider instance: ``hostname:hex``.

    Per-instance, not per-host: two gateway workers on one host must be able to
    tell their leases apart.
    """
    return f"{socket.gethostname()}:{uuid.uuid4().hex}"


def resolve_ownership_config(config: SandboxOwnershipConfig | None, *, stream_bridge: StreamBridgeConfig | None = None) -> SandboxOwnershipConfig:
    """Fill in an omitted ownership section.

    A deployment that already points the stream bridge at Redis is by definition
    multi-instance, so it gets a redis ownership store rather than silently
    falling back to memory (which cannot see peers and would leave #4206 open).

    Both of the stream bridge's own redis triggers are honoured, and in its
    order (``stream_bridge/async_provider.py::_resolve_config``): the config.yaml
    section first, then the env var. Reading only the env var would miss the
    config.yaml-native way of pointing the bridge at Redis — i.e. exactly the
    multi-instance deployments this inference exists for.
    """
    if config is not None:
        return config

    if stream_bridge is not None and stream_bridge.type == "redis":
        redis_url = stream_bridge.redis_url or os.getenv(_ENV_OWNERSHIP_REDIS_URL) or os.getenv(_ENV_STREAM_BRIDGE_REDIS_URL)
        logger.info("Sandbox ownership: redis inferred from stream_bridge.type (multi-instance deployment)")
        return SandboxOwnershipConfig(type="redis", redis_url=redis_url)

    redis_url = os.getenv(_ENV_OWNERSHIP_REDIS_URL) or os.getenv(_ENV_STREAM_BRIDGE_REDIS_URL)
    if redis_url:
        logger.info("Sandbox ownership: redis inferred from environment (multi-instance deployment)")
        return SandboxOwnershipConfig(type="redis", redis_url=redis_url)
    return SandboxOwnershipConfig()


def _resolve_redis_url(config: SandboxOwnershipConfig) -> str:
    return config.redis_url or os.getenv(_ENV_OWNERSHIP_REDIS_URL) or os.getenv(_ENV_STREAM_BRIDGE_REDIS_URL) or os.getenv("REDIS_URL") or "redis://localhost:6379/0"


def compute_lease_ttl(config: SandboxOwnershipConfig) -> float:
    """Lease TTL in seconds.

    Derived from the renewal interval, never from ``sandbox.idle_timeout``:
    coupling liveness to the idle reaper is what let ownership lapse under
    ``idle_timeout: 0``, where the idle checker never starts.
    """
    return config.renewal_interval_seconds * config.ttl_multiplier


def make_sandbox_ownership_store(config: SandboxOwnershipConfig | None, *, owner_id: str | None = None) -> SandboxOwnershipStore:
    """Build the ownership store for *config*.

    Caller owns the returned store and must ``close()`` it.
    """
    # Trust an already-resolved config; only fill in an omitted section. The
    # provider resolves once (with the stream_bridge inference this factory
    # cannot do) and passes that in, so re-resolving here would be a no-op.
    resolved = config if config is not None else resolve_ownership_config(None)
    effective_owner_id = owner_id or generate_owner_id()
    ttl = compute_lease_ttl(resolved)

    if resolved.type == "memory":
        from .memory import MemoryOwnershipStore

        logger.info("Sandbox ownership store: memory (single-instance; ttl=%.1fs)", ttl)
        return MemoryOwnershipStore(owner_id=effective_owner_id, ttl_seconds=ttl)

    if resolved.type == "redis":
        from .redis import RedisOwnershipStore

        redis_url = _resolve_redis_url(resolved)
        logger.info("Sandbox ownership store: redis (ttl=%.1fs, renewal=%.1fs)", ttl, resolved.renewal_interval_seconds)
        return RedisOwnershipStore(
            owner_id=effective_owner_id,
            redis_url=redis_url,
            ttl_seconds=ttl,
            key_prefix=resolved.key_prefix,
        )

    raise ValueError(f"Unknown sandbox ownership type: {resolved.type!r}")
