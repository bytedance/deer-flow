"""Shared types and lazy Redis factory for E2B deployment capacity."""

from __future__ import annotations

import enum
import logging
from typing import TYPE_CHECKING

from deerflow.community.aio_sandbox.ownership.factory import resolve_ownership_redis_url
from deerflow.config.sandbox_config import SandboxOwnershipConfig

if TYPE_CHECKING:
    from .redis import RedisE2BCapacityStore

logger = logging.getLogger(__name__)


class CapacityBackendError(RuntimeError):
    """Redis could not return a definitive capacity decision."""


class ReserveStatus(enum.Enum):
    GRANTED = "granted"
    FULL = "full"
    NOT_READY = "not_ready"


def make_e2b_capacity_store(
    ownership: SandboxOwnershipConfig,
    *,
    hard_limit: int,
) -> RedisE2BCapacityStore | None:
    """Use Redis only when the deployment already enables Redis ownership."""
    if ownership.type == "memory":
        return None
    if ownership.type != "redis":
        raise ValueError(f"Unknown sandbox ownership type: {ownership.type!r}")

    from .redis import RedisE2BCapacityStore

    logger.info(
        "E2B deployment capacity: redis (key_prefix=%s, hard_limit=%d)",
        ownership.key_prefix,
        hard_limit,
    )
    return RedisE2BCapacityStore(
        redis_url=resolve_ownership_redis_url(ownership),
        hard_limit=hard_limit,
        key_prefix=ownership.key_prefix,
    )
