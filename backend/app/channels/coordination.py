"""Redis-based distributed lock for IM channel coordination.

Prevents multiple workers from consuming the same IM channel simultaneously.
Each channel gets a lock key ``deerflow:im_lock:{channel}`` with the worker_id
as value. Lua scripts ensure atomicity and ownership verification.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_ACQUIRE_SCRIPT = """
return redis.call("SET", KEYS[1], ARGV[1], "NX", "EX", ARGV[2])
"""

_RENEW_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
"""


class IMChannelLock:
    """Distributed lock for a single IM channel, backed by Redis.

    Uses Lua scripts for atomic acquire/renew/release with ownership checks.
    """

    def __init__(
        self,
        redis_client: Any,
        channel: str,
        worker_id: str,
        ttl: int = 30,
    ) -> None:
        self._redis = redis_client
        self._channel = channel
        self._worker_id = worker_id
        self._key = f"deerflow:im_lock:{channel}"
        self._ttl = ttl
        self._renew_task: asyncio.Task[None] | None = None
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    async def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if successful."""
        result = await self._redis.eval(_ACQUIRE_SCRIPT, 1, self._key, self._worker_id, str(self._ttl))
        if result == b"OK" or result == "OK" or result == 1 or result is True:
            self._held = True
            self._start_renewal()
            logger.info("IMChannelLock acquired for channel=%s worker=%s", self._channel, self._worker_id)
            return True
        return False

    async def renew(self) -> bool:
        """Renew the lock TTL. Only succeeds if we still own the lock."""
        result = await self._redis.eval(_RENEW_SCRIPT, 1, self._key, self._worker_id, str(self._ttl))
        if result == b"OK" or result == "OK" or result == 1 or result is True:
            return True
        self._held = False
        return False

    async def release(self) -> bool:
        """Release the lock. Only succeeds if we still own it."""
        self._stop_renewal()
        result = await self._redis.eval(_RELEASE_SCRIPT, 1, self._key, self._worker_id)
        was_held = self._held
        self._held = False
        if result == 1 or result == b"OK" or result == "OK" or result is True:
            logger.info("IMChannelLock released for channel=%s worker=%s", self._channel, self._worker_id)
            return True
        if was_held:
            logger.warning("IMChannelLock release failed (lost ownership?) for channel=%s worker=%s", self._channel, self._worker_id)
        return False

    def _start_renewal(self) -> None:
        """Start the periodic renewal task."""
        if self._renew_task is not None:
            return
        self._renew_task = asyncio.create_task(self._renewal_loop(), name=f"im-lock-renew-{self._channel}")

    def _stop_renewal(self) -> None:
        """Cancel the renewal task."""
        if self._renew_task is not None:
            self._renew_task.cancel()
            self._renew_task = None

    async def _renewal_loop(self) -> None:
        """Renew the lock every TTL/3 seconds until it's lost or released."""
        interval = max(self._ttl // 3, 1)
        try:
            while self._held:
                await asyncio.sleep(interval)
                if not self._held:
                    break
                ok = await self.renew()
                if not ok:
                    logger.warning("IMChannelLock renewal failed for channel=%s — lock lost", self._channel)
                    break
        except asyncio.CancelledError:
            return


async def webhook_dedup(redis_client: Any, channel: str, message_id: str, ttl: int = 300) -> bool:
    """Return True if this webhook message is new (not a duplicate).

    Uses ``SET NX EX`` to atomically check-and-set a dedup key.
    Returns False if the message was already seen within the TTL window.
    """
    key = f"deerflow:webhook_dedup:{channel}:{message_id}"
    result = await redis_client.set(key, "1", nx=True, ex=ttl)
    return result is not None and result is not False
