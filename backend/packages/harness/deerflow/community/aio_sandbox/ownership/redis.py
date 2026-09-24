"""Redis-backed ownership store for multi-instance gateways (#4206).

Ownership is a single key per sandbox whose value encodes both the owner and the
lease state — ``own:<owner_id>`` (responsible for this container) or
``del:<owner_id>`` (tearing it down) — with a TTL the owning instance refreshes.

The state prefix is what makes the destroy window safe without a lock: a
takeover is refused against a ``del:`` lease, so a container cannot be
re-acquired between a destroy path's claim and its container stop.

The sync client is deliberate: this store is driven from provider construction
and from background threads, never from the event loop (see ``base`` for the
contract). ``redis.asyncio`` would be the wrong client here.

Every mutation goes through a Lua script so the read and the write cannot be
interleaved by a peer. ``SET NX`` alone is not enough: it fails on a key we
already own, and a GET-then-SET fallback in Python reopens the race the script
closes.
"""

from __future__ import annotations

import logging

from .base import OwnershipBackendError, RenewOutcome, SandboxOwnershipStore

try:
    from redis import Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - only hit when the optional extra is missing
    # ``redis`` is an optional extra (mirrors the stream_bridge redis path). This
    # module is imported lazily from ``make_sandbox_ownership_store`` only when
    # ``sandbox.ownership.type == "redis"``, so this hint surfaces exactly when a
    # redis ownership store is requested without the package.
    raise ImportError(
        "sandbox.ownership.type is set to 'redis' but the redis package is not installed.\n"
        "Install it with:\n"
        "    cd backend && uv sync --all-packages --extra redis\n"
        "On the next `make dev` the redis extra is auto-detected from config.yaml\n"
        "(sandbox.ownership.type: redis) and reinstalled, so it will not be wiped again.\n"
        "Or switch to sandbox.ownership.type: memory in config.yaml for single-instance deployment."
    ) from None

logger = logging.getLogger(__name__)

_OWN = "own:"
_DEL = "del:"

# Bound every store round-trip so a stalled Redis cannot wedge a caller. This
# matters most for the teardown heartbeat: its exit — and the final lease
# release that exit performs — must stay finite, otherwise a refresh blocked on
# a black-holed connection could hold a destroy path (and its deferred release)
# open indefinitely. Without a socket timeout redis-py blocks forever.
_STORE_SOCKET_TIMEOUT_SECONDS = 5.0

# Acquire-path takeover. Overwrites a live peer's normal lease on purpose — a
# thread's turn has routed here — but refuses a teardown in progress, which is
# what stops us handing out a container a peer is about to stop.
_TAKE_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current ~= false and string.sub(current, 1, 4) == 'del:' then
    return 0
end
redis.call('SET', KEYS[1], 'own:' .. ARGV[1], 'PX', ARGV[2])
return 1
"""

# Adopt/reap gate: only if unowned or already ours (in either state).
# ARGV[3] selects the state written: '1' marks a teardown in progress.
#
# A non-destroy claim never unwinds our *own* teardown: a stop is already in
# flight and cannot be recalled, so downgrading the marker to `own:` would let a
# `take()` hand out a container that is about to die. No caller does this today
# (the `for_destroy=false` callers run against an absent or unowned key), but the
# contract has to forbid it rather than rely on that staying true.
_CLAIM_SCRIPT = """
local current = redis.call('GET', KEYS[1])
local mine_own = 'own:' .. ARGV[1]
local mine_del = 'del:' .. ARGV[1]
if ARGV[3] == '0' and current == mine_del then
    return 0
end
if current == false or current == mine_own or current == mine_del then
    local value = mine_own
    if ARGV[3] == '1' then
        value = mine_del
    end
    redis.call('SET', KEYS[1], value, 'PX', ARGV[2])
    return 1
end
return 0
"""

# Three-way so the caller can tell an absent lease (safe to re-establish) from a
# peer's (re-taking it is the #4206 kill). Collapsing them is what let a Redis
# restart drop every live sandbox fleet-wide.
#    1 = renewed, -1 = lapsed/absent, 0 = held by a peer or being torn down
_RENEW_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current == false then
    return -1
end
if current == 'own:' .. ARGV[1] then
    redis.call('PEXPIRE', KEYS[1], ARGV[2])
    return 1
end
return 0
"""

# Drop only our own lease, in either state, so a peer's is never cleared.
_RELEASE_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current == 'own:' .. ARGV[1] or current == 'del:' .. ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisOwnershipStore(SandboxOwnershipStore):
    """Ownership leases shared across gateway instances via Redis."""

    supports_cross_process = True

    def __init__(
        self,
        *,
        owner_id: str,
        redis_url: str,
        ttl_seconds: float,
        key_prefix: str = "deerflow:sandbox:owner",
        client: Redis | None = None,
    ) -> None:
        self._owner_id = owner_id
        self._ttl_ms = max(1, int(float(ttl_seconds) * 1000))
        self._key_prefix = key_prefix.rstrip(":")
        # Redis.from_url is lazy, so an unreachable Redis does not block provider
        # construction; the first claim raises instead. socket_timeout bounds
        # every round-trip (see _STORE_SOCKET_TIMEOUT_SECONDS) so no store call —
        # in particular a teardown-heartbeat refresh — can block unbounded.
        self._redis = (
            client
            if client is not None
            else Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=_STORE_SOCKET_TIMEOUT_SECONDS,
                socket_connect_timeout=_STORE_SOCKET_TIMEOUT_SECONDS,
            )
        )
        self._owns_client = client is None
        self._take = self._redis.register_script(_TAKE_SCRIPT)
        self._claim = self._redis.register_script(_CLAIM_SCRIPT)
        self._renew = self._redis.register_script(_RENEW_SCRIPT)
        self._release = self._redis.register_script(_RELEASE_SCRIPT)

    @property
    def owner_id(self) -> str:
        return self._owner_id

    def _key(self, sandbox_id: str) -> str:
        return f"{self._key_prefix}:{sandbox_id}"

    def take(self, sandbox_id: str) -> bool:
        try:
            result = self._take(keys=[self._key(sandbox_id)], args=[self._owner_id, self._ttl_ms])
        except RedisError as e:
            raise OwnershipBackendError(f"failed to publish sandbox ownership for {sandbox_id}: {e}") from e
        return bool(result)

    def claim(self, sandbox_id: str, *, for_destroy: bool = False) -> bool:
        try:
            result = self._claim(keys=[self._key(sandbox_id)], args=[self._owner_id, self._ttl_ms, "1" if for_destroy else "0"])
        except RedisError as e:
            raise OwnershipBackendError(f"failed to claim sandbox ownership for {sandbox_id}: {e}") from e
        return bool(result)

    def renew(self, sandbox_id: str) -> RenewOutcome:
        try:
            result = int(self._renew(keys=[self._key(sandbox_id)], args=[self._owner_id, self._ttl_ms]))
        except RedisError as e:
            raise OwnershipBackendError(f"failed to renew sandbox ownership for {sandbox_id}: {e}") from e
        if result == 1:
            return RenewOutcome.RENEWED
        if result == -1:
            return RenewOutcome.LAPSED
        return RenewOutcome.LOST

    def release(self, sandbox_id: str) -> None:
        try:
            self._release(keys=[self._key(sandbox_id)], args=[self._owner_id])
        except RedisError as e:
            raise OwnershipBackendError(f"failed to release sandbox ownership for {sandbox_id}: {e}") from e

    def owner(self, sandbox_id: str) -> str | None:
        try:
            value = self._redis.get(self._key(sandbox_id))
        except RedisError as e:
            raise OwnershipBackendError(f"failed to read sandbox ownership for {sandbox_id}: {e}") from e
        if value is None:
            return None
        # An injected client may not set decode_responses.
        text = value.decode("utf-8") if isinstance(value, bytes) else value
        if text.startswith(_OWN) or text.startswith(_DEL):
            return text[4:]
        return text

    def close(self) -> None:
        if not self._owns_client:
            return
        try:
            self._redis.close()
        except Exception as e:  # pragma: no cover - teardown best effort
            logger.warning("Error closing sandbox ownership redis client: %s", e)
