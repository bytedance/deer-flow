"""Redis-backed deployment-wide E2B capacity.

One Redis Hash stores one ownership namespace. Sandbox fields represent confirmed
remote VMs and reservation fields represent creates that have not returned an
E2B sandbox id yet. Lua keeps every admission transition atomic across Gateway
processes.
"""

from __future__ import annotations

import logging

from . import (
    CapacityBackendError,
    ReserveStatus,
)

try:
    from redis import Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - optional extra
    raise ImportError("Redis-backed E2B capacity requires the redis package.\nInstall it with:\n    cd backend && uv sync --all-packages --extra redis") from None

logger = logging.getLogger(__name__)

_SOCKET_TIMEOUT_SECONDS = 5.0

_LUA_COMMON = """
local function now_ms()
    local current = redis.call('TIME')
    return (tonumber(current[1]) * 1000)
        + math.floor(tonumber(current[2]) / 1000)
end

local function config_matches(expected_hard)
    return redis.call('HGET', KEYS[1], 'meta:hard_limit') == expected_hard
end

local function config_mismatch(expected_hard)
    local hard = redis.call('HGET', KEYS[1], 'meta:hard_limit') or ''
    return redis.error_reply(
        'E2B capacity ledger configuration mismatch: configured hard_limit='
        .. expected_hard .. ', ledger hard_limit=' .. hard
    )
end

local function initialize(hard_limit)
    redis.call(
        'HSET',
        KEYS[1],
        'meta:state', 'initializing',
        'meta:hard_limit', hard_limit,
        'meta:revision', '0'
    )
end
"""

_REVISION_SCRIPT = (
    _LUA_COMMON
    + """
local hard_limit = ARGV[1]
local state = redis.call('HGET', KEYS[1], 'meta:state')
if state ~= false and not config_matches(hard_limit) then
    return config_mismatch(hard_limit)
end
return tonumber(redis.call('HGET', KEYS[1], 'meta:revision') or '0')
"""
)

_MUTATE_SCRIPT = (
    _LUA_COMMON
    + """
local operation = ARGV[1]
local hard_limit = ARGV[2]
local state = redis.call('HGET', KEYS[1], 'meta:state')

if operation == 'reserve' then
    if state == false then
        return 'NOT_READY'
    end
    if not config_matches(hard_limit) then
        return config_mismatch(hard_limit)
    end
    if state ~= 'ready' then
        return 'NOT_READY'
    end

    local token = ARGV[3]
    local field = 'r:' .. token
    if redis.call('HEXISTS', KEYS[1], field) == 1 then
        return 'GRANTED'
    end
    -- A ready ledger has exactly the three meta fields from initialize().
    if redis.call('HLEN', KEYS[1]) - 3 >= tonumber(hard_limit) then
        return 'FULL'
    end
    redis.call('HSET', KEYS[1], field, tostring(now_ms()))
    redis.call('HINCRBY', KEYS[1], 'meta:revision', 1)
    return 'GRANTED'
end

if operation == 'release' and state == false then
    return 'OK'
end
if state == false then
    initialize(hard_limit)
elseif not config_matches(hard_limit) then
    return config_mismatch(hard_limit)
end

if operation == 'upsert' then
    local token = ARGV[3]
    local sandbox_id = ARGV[4]
    local changed = false
    if token ~= '' and redis.call('HDEL', KEYS[1], 'r:' .. token) == 1 then
        changed = true
    end
    if redis.call('HSETNX', KEYS[1], 's:' .. sandbox_id, '1') == 1 then
        changed = true
    end
    if changed then
        redis.call('HINCRBY', KEYS[1], 'meta:revision', 1)
    end
    return 'OK'
end

if operation == 'release' then
    if redis.call('HDEL', KEYS[1], 's:' .. ARGV[3]) == 1 then
        redis.call('HINCRBY', KEYS[1], 'meta:revision', 1)
    end
    return 'OK'
end

return redis.error_reply('unknown E2B capacity operation: ' .. operation)
"""
)

_RECONCILE_SCRIPT = (
    _LUA_COMMON
    + """
local hard_limit = ARGV[1]
local expected_revision = tonumber(ARGV[2])
local complete = ARGV[3] == '1'
local stale_before_ms = tonumber(ARGV[4])
local state = redis.call('HGET', KEYS[1], 'meta:state')

if state == false then
    if expected_revision ~= 0 then
        return 'STALE'
    end
    initialize(hard_limit)
    state = 'initializing'
elseif not config_matches(hard_limit) then
    return config_mismatch(hard_limit)
end

local revision = tonumber(
    redis.call('HGET', KEYS[1], 'meta:revision') or '0'
)
if revision ~= expected_revision then
    return 'STALE'
end

local remote_ids = {}
local changed = false
for index = 5, #ARGV, 2 do
    local sandbox_id = ARGV[index]
    local token = ARGV[index + 1]
    remote_ids[sandbox_id] = true
    if token ~= '' then
        if redis.call('HDEL', KEYS[1], 'r:' .. token) == 1 then
            changed = true
        end
    end
    if redis.call('HSETNX', KEYS[1], 's:' .. sandbox_id, '1') == 1 then
        changed = true
    end
end

if complete then
    for _, field in ipairs(redis.call('HKEYS', KEYS[1])) do
        local prefix = string.sub(field, 1, 2)
        local identifier = string.sub(field, 3)
        if prefix == 's:' and remote_ids[identifier] ~= true then
            redis.call('HDEL', KEYS[1], field)
            changed = true
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
)


def _text(value: object) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


class RedisE2BCapacityStore:
    """Atomic Redis Hash ledger for one E2B deployment capacity scope."""

    def __init__(
        self,
        *,
        redis_url: str,
        hard_limit: int,
        key_prefix: str = "deerflow:sandbox:owner",
    ) -> None:
        if hard_limit < 1:
            raise ValueError("hard_limit must be at least 1")

        self._hard_limit = hard_limit
        self._key = f"{key_prefix.rstrip(':')}:e2b-capacity"
        self._redis = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=_SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
        )
        self._revision_script = self._redis.register_script(_REVISION_SCRIPT)
        self._mutate_script = self._redis.register_script(_MUTATE_SCRIPT)
        self._reconcile_script = self._redis.register_script(_RECONCILE_SCRIPT)

    @property
    def key(self) -> str:
        return self._key

    def _execute(self, script, *, args: list[object], operation: str) -> object:
        try:
            return script(keys=[self._key], args=args)
        except RedisError as error:
            raise CapacityBackendError(f"failed to {operation} E2B capacity in Redis: {error}") from error

    def revision(self) -> int:
        raw = self._execute(
            self._revision_script,
            args=[self._hard_limit],
            operation="read",
        )
        return int(raw)

    def reserve(self, token: str) -> ReserveStatus:
        if not token:
            raise ValueError("token must not be empty")
        raw = self._execute(
            self._mutate_script,
            args=["reserve", self._hard_limit, token],
            operation="reserve",
        )
        try:
            return ReserveStatus[_text(raw)]
        except KeyError as error:
            raise CapacityBackendError(f"unexpected E2B capacity reserve result: {_text(raw)}") from error

    def track(
        self,
        sandbox_id: str,
        *,
        reservation_token: str | None = None,
    ) -> None:
        if not sandbox_id:
            raise ValueError("sandbox_id must not be empty")
        self._execute(
            self._mutate_script,
            args=[
                "upsert",
                self._hard_limit,
                reservation_token or "",
                sandbox_id,
            ],
            operation="track",
        )

    def release(self, sandbox_id: str) -> None:
        if not sandbox_id:
            return
        self._execute(
            self._mutate_script,
            args=["release", self._hard_limit, sandbox_id],
            operation="release",
        )

    def reconcile(
        self,
        *,
        expected_revision: int,
        remote_sandboxes: dict[str, str | None],
        complete: bool,
        stale_reservation_before_ms: int,
    ) -> bool:
        remote_args = [value for sandbox_id, reservation_token in remote_sandboxes.items() for value in (sandbox_id, reservation_token or "")]
        raw = self._execute(
            self._reconcile_script,
            args=[
                self._hard_limit,
                expected_revision,
                "1" if complete else "0",
                stale_reservation_before_ms,
                *remote_args,
            ],
            operation="reconcile",
        )
        status = _text(raw)
        if status == "APPLIED":
            return True
        if status == "STALE":
            return False
        raise CapacityBackendError(f"unexpected E2B capacity reconciliation result: {status}")

    def close(self) -> None:
        try:
            self._redis.close()
        except Exception as error:  # pragma: no cover - teardown best effort
            logger.warning("Error closing E2B capacity Redis client: %s", error)
