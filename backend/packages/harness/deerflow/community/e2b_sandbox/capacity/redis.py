"""Atomic Redis Hash ledger for deployment-wide E2B capacity."""

from __future__ import annotations

import enum
import logging

from deerflow.community.aio_sandbox.ownership.factory import resolve_ownership_redis_url
from deerflow.config.sandbox_config import SandboxOwnershipConfig

logger = logging.getLogger(__name__)

_SOCKET_TIMEOUT_SECONDS = 5.0

_LEDGER_SCRIPT = """
local function now_ms()
    local current = redis.call('TIME')
    return tonumber(current[1]) * 1000 + math.floor(tonumber(current[2]) / 1000)
end

-- Number of 'meta:*' fields initialize() writes. Live entries ('r:'/'s:') are
-- counted as HLEN minus this, so the two must move together: adding a meta
-- field without updating this constant makes the ledger over-count usage and
-- reject one reservation early. test_ledger_meta_field_count_matches_constant
-- pins it against initialize()'s actual output.
local META_FIELD_COUNT = 3

local function initialize(hard_limit)
    redis.call('HSET', KEYS[1],
        'meta:state', 'initializing',
        'meta:hard_limit', hard_limit,
        'meta:revision', '0')
end

local function mark_present(sandbox_id)
    local field = 's:' .. sandbox_id
    if redis.call('HGET', KEYS[1], field) == '1' then
        return false
    end
    redis.call('HSET', KEYS[1], field, '1')
    return true
end

local operation = ARGV[1]
local hard_limit = ARGV[2]
local state = redis.call('HGET', KEYS[1], 'meta:state')
local stored_limit = redis.call('HGET', KEYS[1], 'meta:hard_limit')
if state ~= false and stored_limit ~= hard_limit then
    return redis.error_reply(
        'E2B capacity ledger configuration mismatch: configured hard_limit='
        .. hard_limit .. ', ledger hard_limit=' .. (stored_limit or '')
    )
end

if operation == 'revision' then
    return tonumber(redis.call('HGET', KEYS[1], 'meta:revision') or '0')
end

if operation == 'reserve' then
    if state ~= 'ready' then
        return 'NOT_READY'
    end
    local field = 'r:' .. ARGV[3]
    if redis.call('HEXISTS', KEYS[1], field) == 1 then
        return 'GRANTED'
    end
    if redis.call('HLEN', KEYS[1]) - META_FIELD_COUNT >= tonumber(hard_limit) then
        return 'FULL'
    end
    redis.call('HSET', KEYS[1], field, tostring(now_ms()))
    redis.call('HINCRBY', KEYS[1], 'meta:revision', 1)
    return 'GRANTED'
end

if operation == 'release' then
    if state ~= false and redis.call('HDEL', KEYS[1], 's:' .. ARGV[3]) == 1 then
        redis.call('HINCRBY', KEYS[1], 'meta:revision', 1)
    end
    return 'OK'
end

if state == false then
    if operation == 'reconcile' and tonumber(ARGV[3]) ~= 0 then
        return 'STALE'
    end
    initialize(hard_limit)
    state = 'initializing'
end

if operation == 'track' then
    local changed = false
    if ARGV[3] ~= '' and redis.call('HDEL', KEYS[1], 'r:' .. ARGV[3]) == 1 then
        changed = true
    end
    if mark_present(ARGV[4]) then
        changed = true
    end
    if changed then
        redis.call('HINCRBY', KEYS[1], 'meta:revision', 1)
    end
    return 'OK'
end

if operation ~= 'reconcile' then
    return redis.error_reply('unknown E2B capacity operation: ' .. operation)
end

local expected_revision = tonumber(ARGV[3])
local revision = tonumber(redis.call('HGET', KEYS[1], 'meta:revision') or '0')
if revision ~= expected_revision then
    return 'STALE'
end

local complete = ARGV[4] == '1'
local remote_ids = {}
local changed = false
for index = 6, #ARGV, 2 do
    local sandbox_id = ARGV[index]
    local token = ARGV[index + 1]
    remote_ids[sandbox_id] = true
    if token ~= '' and redis.call('HDEL', KEYS[1], 'r:' .. token) == 1 then
        changed = true
    end
    if mark_present(sandbox_id) then
        changed = true
    end
end

if complete then
    local stale_before_ms = now_ms() - tonumber(ARGV[5])
    for _, field in ipairs(redis.call('HKEYS', KEYS[1])) do
        local prefix = string.sub(field, 1, 2)
        local identifier = string.sub(field, 3)
        if prefix == 's:' and remote_ids[identifier] ~= true then
            local missing_since_ms = tonumber(string.match(redis.call('HGET', KEYS[1], field) or '', '^m:(%d+)$'))
            if missing_since_ms == nil then
                redis.call('HSET', KEYS[1], field, 'm:' .. now_ms())
                changed = true
            elseif missing_since_ms <= stale_before_ms then
                redis.call('HDEL', KEYS[1], field)
                changed = true
            end
        elseif prefix == 'r:' then
            local created_ms = tonumber(redis.call('HGET', KEYS[1], field))
            if created_ms ~= nil and created_ms <= stale_before_ms then
                redis.call('HDEL', KEYS[1], field)
                changed = true
            end
        end
    end
    if state ~= 'ready' then
        redis.call('HSET', KEYS[1], 'meta:state', 'ready')
        changed = true
    end
end

if changed then
    redis.call('HINCRBY', KEYS[1], 'meta:revision', 1)
end
return 'APPLIED'
"""


class CapacityBackendError(RuntimeError):
    """Redis could not return a definitive capacity decision."""


class ReserveStatus(enum.StrEnum):
    GRANTED = "GRANTED"
    FULL = "FULL"
    NOT_READY = "NOT_READY"


def _text(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


class RedisE2BCapacityStore:
    """One capacity scope stored in one Redis Hash."""

    def __init__(
        self,
        *,
        redis_url: str,
        hard_limit: int,
        key_prefix: str = "deerflow:sandbox:owner",
    ) -> None:
        if hard_limit < 1:
            raise ValueError("hard_limit must be at least 1")
        try:
            from redis import Redis
            from redis.exceptions import RedisError
        except ImportError:  # pragma: no cover - optional extra
            raise ImportError("Redis E2B capacity requires: cd backend && uv sync --extra redis") from None

        self._hard_limit = hard_limit
        self._key = f"{key_prefix.rstrip(':')}:e2b-capacity"
        self._redis_error = RedisError
        self._redis = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=_SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
        )
        self._script = self._redis.register_script(_LEDGER_SCRIPT)

    @property
    def key(self) -> str:
        return self._key

    def _run(self, operation: str, *args: object) -> object:
        try:
            return self._script(keys=[self._key], args=[operation, self._hard_limit, *args])
        except self._redis_error as error:
            raise CapacityBackendError(f"failed to {operation} E2B capacity in Redis: {error}") from error

    def revision(self) -> int:
        return int(self._run("revision"))

    def reserve(self, token: str) -> ReserveStatus:
        if not token:
            raise ValueError("token must not be empty")
        try:
            return ReserveStatus(_text(self._run("reserve", token)))
        except ValueError as error:
            raise CapacityBackendError("unexpected E2B capacity reserve result") from error

    def track(
        self,
        sandbox_id: str,
        *,
        reservation_token: str | None = None,
    ) -> None:
        if not sandbox_id:
            raise ValueError("sandbox_id must not be empty")
        self._run("track", reservation_token or "", sandbox_id)

    def release(self, sandbox_id: str) -> None:
        if sandbox_id:
            self._run("release", sandbox_id)

    def reconcile(
        self,
        *,
        expected_revision: int,
        remote_sandboxes: dict[str, str | None],
        complete: bool,
        reservation_max_age_ms: int,
    ) -> bool:
        remote_args = [item for sandbox_id, token in remote_sandboxes.items() for item in (sandbox_id, token or "")]
        status = _text(
            self._run(
                "reconcile",
                expected_revision,
                "1" if complete else "0",
                reservation_max_age_ms,
                *remote_args,
            )
        )
        if status not in {"APPLIED", "STALE"}:
            raise CapacityBackendError(f"unexpected E2B capacity reconciliation result: {status}")
        return status == "APPLIED"

    def close(self) -> None:
        try:
            self._redis.close()
        except Exception as error:  # pragma: no cover - teardown best effort
            logger.warning("Error closing E2B capacity Redis client: %s", error)


def make_e2b_capacity_store(
    ownership: SandboxOwnershipConfig,
    *,
    hard_limit: int,
) -> RedisE2BCapacityStore | None:
    """Enable the shared ledger only with Redis ownership."""
    if ownership.type == "memory":
        return None
    if ownership.type != "redis":
        raise ValueError(f"Unknown sandbox ownership type: {ownership.type!r}")
    logger.info("E2B deployment capacity: redis (key_prefix=%s, hard_limit=%d)", ownership.key_prefix, hard_limit)
    return RedisE2BCapacityStore(
        redis_url=resolve_ownership_redis_url(ownership),
        hard_limit=hard_limit,
        key_prefix=ownership.key_prefix,
    )
