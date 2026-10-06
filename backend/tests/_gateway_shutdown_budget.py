"""Shutdown work every deployment's stop grace period must cover.

The chart's ``terminationGracePeriodSeconds`` and both compose files'
``stop_grace_period`` must outlast the Gateway's lifespan shutdown: channel
stop, the in-flight run drain and the memory queue flush. These numbers are read
from the Gateway rather than copied into the tests, so raising a drain budget
fails the grace-period tests instead of silently outgrowing the deployments.
"""

from __future__ import annotations

from app.gateway.deps import _RUN_DRAIN_TIMEOUT_SECONDS
from deerflow.config.memory_config import MemoryConfig


def channel_stop_seconds() -> float:
    """Bound on channel-service stop (``app.gateway.app._SHUTDOWN_HOOK_TIMEOUT_SECONDS``)."""
    from app.gateway.app import _SHUTDOWN_HOOK_TIMEOUT_SECONDS  # imports the FastAPI app; keep it lazy

    return float(_SHUTDOWN_HOOK_TIMEOUT_SECONDS)


def run_drain_seconds() -> float:
    """Bound on draining in-flight runs before the checkpointer is torn down."""
    return float(_RUN_DRAIN_TIMEOUT_SECONDS)


def memory_flush_seconds() -> float:
    """Default ``memory.shutdown_flush_timeout_seconds``."""
    return float(MemoryConfig.model_fields["shutdown_flush_timeout_seconds"].default)


def lifespan_shutdown_seconds() -> float:
    """Channel stop + in-flight run drain + memory queue flush."""
    return channel_stop_seconds() + run_drain_seconds() + memory_flush_seconds()
