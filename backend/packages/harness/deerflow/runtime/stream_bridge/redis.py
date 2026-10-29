"""Redis Streams-backed stream bridge."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from collections.abc import AsyncIterator, Mapping
from contextvars import Context
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

try:
    from redis.asyncio import Redis
    from redis.exceptions import RedisError, ResponseError
except ImportError:  # pragma: no cover - only hit when the optional extra is missing
    # ``redis`` is an optional extra (mirrors the ``postgres``/asyncpg path in
    # persistence/engine.py). This module is imported lazily from
    # ``make_stream_bridge`` only when ``stream_bridge.type == "redis"``, so the
    # hint surfaces exactly when a Redis bridge is requested without the package.
    raise ImportError(
        "stream_bridge.type is set to 'redis' but the redis package is not installed.\n"
        "Install it with:\n"
        "    cd backend && uv sync --all-packages --extra redis\n"
        "On the next `make dev` the redis extra is auto-detected from config.yaml\n"
        "(stream_bridge.type: redis) and reinstalled, so it will not be wiped again.\n"
        "Or switch to stream_bridge.type: memory in config.yaml for single-process deployment."
    ) from None

from ...utils.file_io import await_drained
from ..keyed_lock import AsyncKeyedLockTable
from .base import DEFAULT_HEARTBEAT_INTERVAL_SECONDS, END_SENTINEL, HEARTBEAT_SENTINEL, StreamBridge, StreamEvent, StreamGap, StreamItem, StreamProducerLeaseState

logger = logging.getLogger(__name__)

_KIND_EVENT = "event"
_KIND_END = "end"
_REDIS_STREAM_ID_RE = re.compile(r"[0-9]+(-[0-9]+)?")
_MAX_STREAM_ID_COMPONENT = 2**64 - 1
# Lua XADD scripts return one of these integers before any event ID.
_XADD_BLOCKED = 0
_XADD_ALREADY_ENDED = 1
_XADD_STREAM_MISSING = 2

# Batch size for ``XREAD``. Reading more than one entry per round-trip collapses
# a large ``Last-Event-ID`` replay into far fewer calls; live tailing still
# yields each event as it arrives because the consume loop returns mid-batch on
# the end marker.
_XREAD_COUNT = 64

# Maximum consecutive transient Redis errors (``ConnectionError``,
# ``TimeoutError``, etc.) tolerated during ``subscribe`` before the error
# propagates to the caller.  Brief blips are retried with exponential backoff
# capped at ``heartbeat_interval``.
_MAX_SUBSCRIBE_RETRIES = 3
_PRODUCER_LEASE_SECONDS = 30
_PRODUCER_LEASE_RENEW_INTERVAL_SECONDS = 10
_PRODUCER_LEASE_START_TIMEOUT_SECONDS = 5.0
_PRODUCER_LEASE_RELEASE_TIMEOUT_SECONDS = 5.0
_PRODUCER_LEASE_RELEASE_RETRY_SECONDS = 0.05
_PRODUCER_TRACKING_MIN_TTL_SECONDS = _PRODUCER_LEASE_SECONDS * 4
_COMPARE_DELETE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
end
return 0
"""
_COMPARE_RENEW_SCRIPT = """
if redis.call("get", KEYS[1]) ~= ARGV[1] then return 0 end
if redis.call("get", KEYS[2]) ~= ARGV[1] then return 0 end
redis.call("expire", KEYS[1], ARGV[2])
if tonumber(ARGV[3]) > 0 then redis.call("expire", KEYS[2], ARGV[3]) end
return 1
"""
_END_MARKER_CHECK_LUA = """
local function entry_is_end(fields)
  for index = 1, #fields, 2 do
    if fields[index] == "kind" and fields[index + 1] == "end" then
      return true
    end
  end
  return false
end

local function tail_is_end(stream_key)
  local entries = redis.call("xrevrange", stream_key, "+", "-", "COUNT", 1)
  return #entries > 0 and entry_is_end(entries[1][2])
end

local function has_end_marker(stream_key, legacy_scan_enabled)
  if tail_is_end(stream_key) then return true end
  if legacy_scan_enabled ~= "1" then return false end
  -- Compatibility path for retained streams written by the old buggy writer:
  -- an END may precede later entries. The first END on a normal stream also
  -- reaches this scan; operators may disable it only after legacy buffers drain.
  local entries = redis.call("xrange", stream_key, "-", "+")
  for _, entry in ipairs(entries) do
    if entry_is_end(entry[2]) then return true end
  end
  return false
end
"""
_COMPARE_XADD_SCRIPT = (
    _END_MARKER_CHECK_LUA
    + """
if redis.call("get", KEYS[1]) ~= ARGV[1] then return 0 end
if redis.call("get", KEYS[2]) ~= ARGV[1] then return 0 end
if ARGV[4] == "end" then
  if has_end_marker(KEYS[3], ARGV[7]) then return 1 end
elseif tail_is_end(KEYS[3]) then
  return 1
end
local event_id = redis.call(
  "xadd", KEYS[3], "MAXLEN", "=", ARGV[2], "*",
  "kind", ARGV[4], "event", ARGV[5], "data", ARGV[6]
)
if tonumber(ARGV[3]) > 0 then redis.call("expire", KEYS[3], ARGV[3]) end
return event_id
"""
)
_XADD_IF_NO_ACTIVE_PRODUCER_SCRIPT = (
    _END_MARKER_CHECK_LUA
    + """
if redis.call("exists", KEYS[1]) == 1 then return 0 end
if ARGV[3] == "end" and redis.call("exists", KEYS[2]) == 0 then return 2 end
if ARGV[3] == "end" then
  if has_end_marker(KEYS[2], ARGV[6]) then return 1 end
elseif tail_is_end(KEYS[2]) then
  return 1
end
local event_id = redis.call(
  "xadd", KEYS[2], "MAXLEN", "=", ARGV[1], "*",
  "kind", ARGV[3], "event", ARGV[4], "data", ARGV[5]
)
if tonumber(ARGV[2]) > 0 then redis.call("expire", KEYS[2], ARGV[2]) end
return event_id
"""
)
_CLEANUP_IF_TOKEN_SCRIPT = """
local tracked = redis.call("get", KEYS[2])
local active = redis.call("get", KEYS[3])
if tracked and tracked ~= ARGV[1] then return 0 end
if active and active ~= ARGV[1] then return 0 end
return redis.call("del", KEYS[1], KEYS[2], KEYS[3])
"""
_CLEANUP_IF_NO_ACTIVE_PRODUCER_SCRIPT = """
if redis.call("exists", KEYS[3]) == 1 then return 0 end
return redis.call("del", KEYS[1], KEYS[2])
"""
_DELETE_EXPIRED_TRACKING_SCRIPT = """
if redis.call("exists", KEYS[2]) == 1 then return 0 end
if not redis.call("get", KEYS[1]) then return 2 end
return redis.call("del", KEYS[1])
"""


@dataclass
class _ProducerLease:
    token: str
    owner_task: asyncio.Task[Any]
    renewal_task: asyncio.Task[None] | None = None
    lost: bool = False
    stopped: bool = False
    discard_tracking_requested: bool = False


class RedisStreamBridge(StreamBridge):
    """Per-run stream bridge backed by Redis Streams.

    Each run is stored in one Redis Stream and subscribers read directly with
    ``XREAD``.  This keeps the SSE bridge usable across multiple gateway
    worker processes while preserving ``Last-Event-ID`` replay semantics.
    """

    supports_cross_process = True
    producer_lease_retry_delay_seconds = _PRODUCER_LEASE_SECONDS + 1

    def __init__(
        self,
        *,
        redis_url: str,
        queue_maxsize: int = 256,
        key_prefix: str = "deerflow:stream_bridge",
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        max_connections: int | None = None,
        stream_ttl_seconds: int | None = 86400,
        producer_lease_recovery_enabled: bool = False,
        legacy_end_scan_enabled: bool = True,
        client: Redis | None = None,
    ) -> None:
        super().__init__(heartbeat_interval=heartbeat_interval)
        self._redis_url = redis_url
        self._maxsize = max(1, queue_maxsize)
        self._legacy_end_scan_enabled = legacy_end_scan_enabled
        self._key_prefix = key_prefix.rstrip(":")
        if stream_ttl_seconds is not None and stream_ttl_seconds > 0:
            self._stream_ttl_seconds = stream_ttl_seconds
        else:
            self._stream_ttl_seconds = None
        # Each live SSE subscriber holds one pooled connection blocked in
        # ``XREAD ... BLOCK`` for up to ``heartbeat_interval``. ``max_connections``
        # caps that pool; ``None`` keeps redis-py's effectively-unbounded default.
        self._redis = client if client is not None else Redis.from_url(redis_url, decode_responses=True, max_connections=max_connections)
        self._owns_client = client is None
        self.producer_lease_recovery_enabled = producer_lease_recovery_enabled
        self._producer_leases: dict[str, _ProducerLease] = {}
        self._producer_lease_locks = AsyncKeyedLockTable[str]()
        self._closing = False
        self._producer_setups = 0
        self._producer_setups_drained = asyncio.Event()
        self._producer_setups_drained.set()

    def _stream_key(self, run_id: str) -> str:
        return f"{self._key_prefix}:{run_id}"

    def _producer_tracking_key(self, run_id: str) -> str:
        return f"{self._stream_key(run_id)}:producer-tracked"

    def _producer_active_key(self, run_id: str) -> str:
        return f"{self._stream_key(run_id)}:producer-active"

    def _producer_tracking_ttl_seconds(self) -> int:
        if self._stream_ttl_seconds is None:
            return 0
        return max(
            self._stream_ttl_seconds,
            _PRODUCER_TRACKING_MIN_TTL_SECONDS,
        )

    async def _delete_if_token(self, key: str, token: str) -> bool:
        return bool(
            await self._redis.eval(
                _COMPARE_DELETE_SCRIPT,
                1,
                key,
                token,
            )
        )

    async def _rollback_producer_lease(
        self,
        run_id: str,
        token: str,
        *,
        timeout: float = _PRODUCER_LEASE_RELEASE_TIMEOUT_SECONDS,
    ) -> bool:
        keys = (
            self._producer_tracking_key(run_id),
            self._producer_active_key(run_id),
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, timeout)
        last_error: BaseException | None = None
        while True:
            remaining_seconds = deadline - loop.time()
            if remaining_seconds <= 0:
                break
            try:
                async with asyncio.timeout(remaining_seconds):
                    for key in keys:
                        await self._delete_if_token(key, token)
                    remaining = await self._redis.mget(*keys)
                return all(value is None or self._decode(value) != token for value in remaining)
            except RedisError as exc:
                last_error = exc
                await asyncio.sleep(
                    min(
                        _PRODUCER_LEASE_RELEASE_RETRY_SECONDS,
                        max(0.0, deadline - loop.time()),
                    )
                )
            except TimeoutError as exc:
                last_error = exc
                break
        logger.warning(
            "Failed to roll back Redis stream producer lease for run %s",
            run_id,
            exc_info=((type(last_error), last_error, last_error.__traceback__) if last_error is not None else False),
        )
        return False

    @staticmethod
    def _cancel_lost_producer(run_id: str, lease: _ProducerLease) -> None:
        lease.lost = True
        if lease.owner_task.done():
            return
        logger.error(
            "Redis stream producer lease expired for run %s; cancelling its owner",
            run_id,
        )
        lease.owner_task.cancel(f"Redis stream producer lease expired for run {run_id}")

    def _watch_producer_owner(
        self,
        run_id: str,
        lease: _ProducerLease,
        owner_task: asyncio.Task[Any],
    ) -> None:
        def owner_done(done_task: asyncio.Task[Any]) -> None:
            current = self._producer_leases.get(run_id)
            if current is not lease or current.owner_task is not done_task:
                return
            cleanup = asyncio.create_task(
                self._stop_producer_lease(
                    run_id,
                    discard_tracking=False,
                    expected_owner_task=done_task,
                ),
                name=f"redis-stream-producer-owner-cleanup:{run_id}",
                context=Context(),
            )
            cleanup.add_done_callback(
                lambda task: self._log_owner_cleanup_result(
                    run_id,
                    task,
                )
            )

        owner_task.add_done_callback(owner_done)

    @staticmethod
    def _log_owner_cleanup_result(
        run_id: str,
        task: asyncio.Task[None],
    ) -> None:
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.warning(
                "Failed to release Redis stream producer lease after owner exit for run %s",
                run_id,
                exc_info=True,
            )

    def _ensure_producer_can_publish(self, run_id: str) -> None:
        lease = self._producer_leases.get(run_id)
        if lease is None:
            return
        if lease.lost:
            raise RuntimeError(f"Redis stream producer lease was lost for run {run_id}")
        if lease.stopped:
            raise RuntimeError(f"Redis stream producer lease was already stopped for run {run_id}")

    async def _renew_producer_lease(self, run_id: str, lease: _ProducerLease) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _PRODUCER_LEASE_SECONDS
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                self._cancel_lost_producer(run_id, lease)
                return
            try:
                await asyncio.sleep(min(_PRODUCER_LEASE_RENEW_INTERVAL_SECONDS, remaining))
                remaining = deadline - loop.time()
                if remaining <= 0:
                    self._cancel_lost_producer(run_id, lease)
                    return
                async with asyncio.timeout(remaining):
                    if not await self._renew_owned_producer_lease(run_id, lease):
                        self._cancel_lost_producer(run_id, lease)
                        return
                deadline = loop.time() + _PRODUCER_LEASE_SECONDS
            except asyncio.CancelledError:
                raise
            except (RedisError, TimeoutError):
                if loop.time() >= deadline:
                    self._cancel_lost_producer(run_id, lease)
                    return
                logger.warning(
                    "Failed to renew Redis stream producer lease for run %s; will retry before the confirmed deadline",
                    run_id,
                    exc_info=True,
                )

    async def start_producer_lease(self, run_id: str) -> bool:
        owner_task = asyncio.current_task()
        if owner_task is None:
            raise RuntimeError("Stream producer lease requires an owning asyncio task")
        if self._closing:
            raise RuntimeError("Stream bridge is closing")

        self._producer_setups += 1
        self._producer_setups_drained.clear()
        try:
            return await self._start_producer_lease(run_id, owner_task)
        finally:
            self._producer_setups -= 1
            if self._producer_setups == 0:
                self._producer_setups_drained.set()

    async def _start_producer_lease(
        self,
        run_id: str,
        owner_task: asyncio.Task[Any],
    ) -> bool:
        async with self._producer_lease_locks.hold(run_id):
            if self._closing:
                raise RuntimeError("Stream bridge is closing")
            existing = self._producer_leases.get(run_id)
            if existing is not None:
                if existing.owner_task is owner_task and not existing.stopped:
                    return True
                raise RuntimeError(f"Run {run_id} already has a local stream producer")

            token = uuid4().hex
            active_key = self._producer_active_key(run_id)
            try:
                async with asyncio.timeout(_PRODUCER_LEASE_START_TIMEOUT_SECONDS):
                    claimed = await self._redis.set(
                        active_key,
                        token,
                        ex=_PRODUCER_LEASE_SECONDS,
                        nx=True,
                    )
                    if not claimed:
                        raise RuntimeError(f"Run {run_id} already has an active stream producer")
                    tracking_ttl = self._producer_tracking_ttl_seconds()
                    tracking_created = await self._redis.set(
                        self._producer_tracking_key(run_id),
                        token,
                        **({"ex": tracking_ttl} if tracking_ttl > 0 else {}),
                    )
                    if not tracking_created:
                        raise RuntimeError(f"Run {run_id} stream producer tracking marker disappeared")
            except asyncio.CancelledError:
                await await_drained(
                    self._rollback_producer_lease(run_id, token),
                )
                raise
            except (RedisError, TimeoutError) as exc:
                if await self._rollback_producer_lease(run_id, token):
                    logger.warning(
                        "Could not start Redis stream producer lease for run %s; the partial registration was rolled back",
                        run_id,
                        exc_info=True,
                    )
                    return False
                raise RuntimeError(f"Could not safely establish stream producer lease for run {run_id}") from exc
            except BaseException:
                await await_drained(
                    self._rollback_producer_lease(run_id, token),
                )
                raise

            lease = _ProducerLease(token=token, owner_task=owner_task)
            lease.renewal_task = asyncio.create_task(
                self._renew_producer_lease(run_id, lease),
                name=f"redis-stream-producer-lease:{run_id}",
            )
            self._producer_leases[run_id] = lease
            self._watch_producer_owner(run_id, lease, owner_task)
            return True

    async def _renew_owned_producer_lease(
        self,
        run_id: str,
        lease: _ProducerLease,
    ) -> bool:
        return bool(
            await self._redis.eval(
                _COMPARE_RENEW_SCRIPT,
                2,
                self._producer_active_key(run_id),
                self._producer_tracking_key(run_id),
                lease.token,
                _PRODUCER_LEASE_SECONDS,
                self._producer_tracking_ttl_seconds(),
            )
        )

    async def _xadd_owned(
        self,
        run_id: str,
        lease: _ProducerLease,
        fields: dict[str, str],
        *,
        maxlen: int,
    ) -> None:
        result = await self._redis.eval(
            _COMPARE_XADD_SCRIPT,
            3,
            self._producer_active_key(run_id),
            self._producer_tracking_key(run_id),
            self._stream_key(run_id),
            lease.token,
            maxlen,
            self._stream_ttl_seconds or 0,
            fields.get("kind", _KIND_EVENT),
            fields.get("event", ""),
            fields.get("data", ""),
            int(self._legacy_end_scan_enabled),
        )
        if result == _XADD_BLOCKED:
            self._cancel_lost_producer(run_id, lease)
            raise RuntimeError(f"Redis stream producer lease was lost for run {run_id}")
        if result == _XADD_ALREADY_ENDED:
            if fields.get("kind") == _KIND_END:
                return
            raise RuntimeError(f"Redis stream for run {run_id} has already ended")
        # Every remaining successful Lua reply is an XADD stream ID.
        assert isinstance(result, (str, bytes)), f"Unexpected Redis stream append result: {result!r}"

    async def _xadd_without_active_producer(
        self,
        run_id: str,
        fields: dict[str, str],
        *,
        maxlen: int,
    ) -> None:
        result = await self._redis.eval(
            _XADD_IF_NO_ACTIVE_PRODUCER_SCRIPT,
            2,
            self._producer_active_key(run_id),
            self._stream_key(run_id),
            maxlen,
            self._stream_ttl_seconds or 0,
            fields.get("kind", _KIND_EVENT),
            fields.get("event", ""),
            fields.get("data", ""),
            int(self._legacy_end_scan_enabled),
        )
        if result == _XADD_BLOCKED:
            raise RuntimeError(f"Cannot publish stream data for run {run_id} because another active producer exists")
        if result == _XADD_ALREADY_ENDED:
            if fields.get("kind") == _KIND_END:
                return
            raise RuntimeError(f"Redis stream for run {run_id} has already ended")
        if result == _XADD_STREAM_MISSING:
            if fields.get("kind") == _KIND_END:
                logger.debug("Skipping stream END for %s: retained stream no longer exists", run_id)
                return
            raise RuntimeError(f"Redis stream for run {run_id} no longer exists")
        # Every remaining successful Lua reply is an XADD stream ID.
        assert isinstance(result, (str, bytes)), f"Unexpected Redis stream append result: {result!r}"

    async def _stop_producer_lease(
        self,
        run_id: str,
        *,
        discard_tracking: bool,
        expected_owner_task: asyncio.Task[Any] | None = None,
        closing: bool = False,
    ) -> None:
        async with self._producer_lease_locks.hold(run_id):
            lease = self._producer_leases.get(run_id)
            if lease is not None and expected_owner_task is not None and lease.owner_task is not expected_owner_task:
                return
            if lease is None:
                return
            discard_tracking = discard_tracking or lease.discard_tracking_requested

            renewal_task = lease.renewal_task
            if renewal_task is not None:
                renewal_task.cancel()
                await asyncio.gather(renewal_task, return_exceptions=True)
                lease.renewal_task = None

            if discard_tracking:
                lease.discard_tracking_requested = True
                discarded = await self._rollback_producer_lease(
                    run_id,
                    lease.token,
                )
                lease.stopped = True
                if discarded:
                    self._producer_leases.pop(run_id, None)
                elif closing:
                    raise RuntimeError(f"Could not discard Redis stream producer tracking for run {run_id}")
                return

            if lease.stopped:
                if closing:
                    self._producer_leases.pop(run_id, None)
                return
            release_deadline = asyncio.get_running_loop().time() + _PRODUCER_LEASE_RELEASE_TIMEOUT_SECONDS
            try:
                async with asyncio.timeout(
                    max(
                        0.0,
                        release_deadline - asyncio.get_running_loop().time(),
                    )
                ):
                    await self._delete_if_token(
                        self._producer_active_key(run_id),
                        lease.token,
                    )
            except (RedisError, TimeoutError):
                # The key still has a short TTL; consumers remain conservative until it expires.
                logger.warning(
                    "Failed to stop Redis stream producer lease for run %s",
                    run_id,
                    exc_info=True,
                )
            finally:
                lease.stopped = True
                if closing:
                    if lease.discard_tracking_requested:
                        discarded = await self._rollback_producer_lease(
                            run_id,
                            lease.token,
                        )
                        if not discarded:
                            raise RuntimeError(f"Could not discard Redis stream producer tracking for run {run_id}")
                    self._producer_leases.pop(run_id, None)

    async def finish_producer_lease(self, run_id: str) -> None:
        await self._stop_producer_lease(
            run_id,
            discard_tracking=False,
        )

    async def abort_producer_lease(self, run_id: str) -> None:
        lease = self._producer_leases.get(run_id)
        if lease is not None:
            lease.discard_tracking_requested = True
        await self._stop_producer_lease(
            run_id,
            discard_tracking=True,
        )

    def transfer_producer_lease(
        self,
        run_id: str,
        owner_task: asyncio.Task[Any],
    ) -> None:
        lease = self._producer_leases.get(run_id)
        if lease is not None and not lease.stopped:
            lease.owner_task = owner_task
            self._watch_producer_owner(run_id, lease, owner_task)

    async def producer_lease_state(self, run_id: str) -> StreamProducerLeaseState:
        tracked, active = await self._redis.mget(
            self._producer_tracking_key(run_id),
            self._producer_active_key(run_id),
        )
        if tracked is None:
            return StreamProducerLeaseState.untracked
        if active is not None and self._decode(active) == self._decode(tracked):
            return StreamProducerLeaseState.active
        return StreamProducerLeaseState.expired

    async def cleanup_expired_producer(self, run_id: str) -> bool:
        return bool(
            await self._redis.eval(
                _DELETE_EXPIRED_TRACKING_SCRIPT,
                2,
                self._producer_tracking_key(run_id),
                self._producer_active_key(run_id),
            )
        )

    async def _xadd_retained(self, key: str, fields: dict[str, str], *, maxlen: int) -> None:
        if self._stream_ttl_seconds is None:
            await self._redis.xadd(
                key,
                fields,
                maxlen=maxlen,
                approximate=False,
            )
            return

        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.xadd(
                key,
                fields,
                maxlen=maxlen,
                approximate=False,
            )
            pipe.expire(key, self._stream_ttl_seconds)
            await pipe.execute()

    @staticmethod
    def _decode(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    @classmethod
    def _normalise_fields(cls, fields: Mapping[Any, Any]) -> dict[str, str]:
        return {cls._decode(key): cls._decode(value) for key, value in fields.items()}

    @staticmethod
    def _encode_data(data: Any) -> str:
        return json.dumps(data, default=str, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode_data(raw: str | None) -> Any:
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Redis stream bridge received non-JSON event data")
            return raw

    def _entry_from_redis(self, event_id: str, fields: Mapping[Any, Any]) -> StreamEvent:
        payload = self._normalise_fields(fields)
        kind = payload.get("kind", _KIND_EVENT)
        if kind == _KIND_END:
            return END_SENTINEL
        return StreamEvent(
            id=event_id,
            event=payload.get("event", "message"),
            data=self._decode_data(payload.get("data")),
        )

    @classmethod
    def _is_end_entry(cls, fields: Mapping[Any, Any]) -> bool:
        return cls._normalise_fields(fields).get("kind") == _KIND_END

    @staticmethod
    def _parse_stream_id(event_id: str) -> tuple[int, int] | None:
        if _REDIS_STREAM_ID_RE.fullmatch(event_id) is None:
            return None
        milliseconds, separator, sequence = event_id.partition("-")
        try:
            parts = int(milliseconds), int(sequence) if separator else 0
        except ValueError:
            return None
        # Redis stream id components are unsigned 64-bit integers.
        return parts if max(parts) <= _MAX_STREAM_ID_COMPONENT else None

    @classmethod
    def _stream_id_lt(cls, left: str, right: str) -> bool:
        left_parts = cls._parse_stream_id(left)
        right_parts = cls._parse_stream_id(right)
        return left_parts is not None and right_parts is not None and left_parts < right_parts

    @classmethod
    def _response_tail_id(cls, response: list[Any]) -> str | None:
        for _stream_name, entries in reversed(response):
            if entries:
                return cls._decode(entries[-1][0])
        return None

    async def publish(self, run_id: str, event: str, data: Any) -> None:
        self._ensure_producer_can_publish(run_id)
        lease = self._producer_leases.get(run_id)
        fields = {
            "kind": _KIND_EVENT,
            "event": event,
            "data": self._encode_data(data),
        }
        if lease is not None:
            await self._xadd_owned(
                run_id,
                lease,
                fields,
                maxlen=self._maxsize,
            )
            return
        await self._xadd_without_active_producer(
            run_id,
            fields,
            maxlen=self._maxsize,
        )

    async def publish_end(self, run_id: str) -> None:
        self._ensure_producer_can_publish(run_id)
        lease = self._producer_leases.get(run_id)
        fields = {"kind": _KIND_END}
        if lease is not None:
            await self._xadd_owned(
                run_id,
                lease,
                fields,
                maxlen=self._maxsize + 1,
            )
            return
        # Keep the configured number of data events plus the internal end marker.
        await self._xadd_without_active_producer(
            run_id,
            fields,
            maxlen=self._maxsize + 1,
        )

    async def stream_exists(self, run_id: str) -> bool:
        """Return whether Redis still has retained stream data for *run_id*."""
        return bool(await self._redis.exists(self._stream_key(run_id)))

    async def ping(self) -> bool:
        """Round-trip ``PING`` to the Redis backend for the readiness probe.

        The client connects lazily, so until something publishes nothing has
        verified that Redis is reachable; this is the only call that does.
        Redis-side failures answer ``False`` so the probe gets a verdict rather
        than a stack of client internals. Callers bound the wait themselves.
        """
        try:
            return bool(await self._redis.ping())
        except RedisError:
            logger.warning("Redis stream bridge ping failed", exc_info=True)
            return False

    async def _resolve_start_stream_id(self, key: str, last_event_id: str | None) -> str:
        if last_event_id is None:
            return "0-0"
        if self._parse_stream_id(last_event_id) is not None:
            return last_event_id
        entries = await self._redis.xrevrange(key, count=1)
        if not entries:
            return "0-0"
        event_id, fields = entries[0]
        payload = self._normalise_fields(fields)
        if payload.get("kind") == _KIND_END:
            return "0-0"
        return self._decode(event_id)

    async def _read_retained_snapshot(
        self,
        key: str,
        stream_id: str,
    ) -> tuple[list[Any], list[Any], list[Any]]:
        """Atomically read retained bounds and entries after ``stream_id``.

        A blocking ``XREAD`` cannot participate in a Redis transaction. Live
        subscribers therefore use this non-blocking atomic snapshot for
        correctness, and a separate blocking read only as a wake-up signal.
        This deliberately adds a three-command pipeline per poll (and a second
        round trip while idle) so retained-bound checks cannot race with reads.
        """
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.xrange(key, count=1)
            pipe.xrevrange(key, count=1)
            pipe.xread({key: stream_id}, count=_XREAD_COUNT)
            earliest, latest, response = await pipe.execute()
        return earliest, latest, response

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float | None = None,
    ) -> AsyncIterator[StreamItem]:
        heartbeat_interval = self._resolve_heartbeat_interval(heartbeat_interval)
        key = self._stream_key(run_id)
        stream_id = await self._resolve_start_stream_id(key, last_event_id)
        gap_detection_enabled = last_event_id is not None and self._parse_stream_id(last_event_id) is not None
        pending_initial_response: list[Any] | None = None
        block_ms = max(1, int(heartbeat_interval * 1000)) if heartbeat_interval > 0 else 1
        consecutive_errors = 0
        stream_observed = False

        while True:
            snapshot_stream_id = stream_id
            pending_initial_tail_id = None
            if pending_initial_response is not None:
                pending_initial_tail_id = self._response_tail_id(pending_initial_response)
                if pending_initial_tail_id is None:
                    pending_initial_response = None
                else:
                    # The first blocking XREAD began against a proven-empty
                    # stream. Its response is a provisional live baseline, not
                    # yet client-visible data. Validate that baseline against
                    # the retained watermark before yielding any of it.
                    snapshot_stream_id = pending_initial_tail_id

            try:
                earliest_entries, latest_entries, response = await self._read_retained_snapshot(key, snapshot_stream_id)
            except ResponseError:
                # Last-Event-ID is client-controlled and validated before XREAD.
                # If Redis still rejects the id, fail instead of resetting to
                # 0-0, which would replay the whole retained buffer on reconnect.
                logger.warning(
                    "Redis rejected stream id %r for stream bridge subscription",
                    snapshot_stream_id,
                    exc_info=True,
                )
                raise
            except RedisError:
                consecutive_errors += 1
                if consecutive_errors > _MAX_SUBSCRIBE_RETRIES:
                    raise
                delay = min(2**consecutive_errors, heartbeat_interval)
                logger.warning(
                    "Transient Redis error in stream bridge subscriber (retry %d/%d); backing off %.1fs",
                    consecutive_errors,
                    _MAX_SUBSCRIBE_RETRIES,
                    delay,
                    exc_info=True,
                )
                await asyncio.sleep(delay)
                continue
            else:
                # A non-empty snapshot is forward progress. For an empty
                # snapshot, keep any preceding wake-up failure count until the
                # blocking XREAD itself succeeds; otherwise a permanently
                # failing blocking read could retry forever because the
                # non-blocking transaction succeeds between attempts.
                if response:
                    consecutive_errors = 0

            if earliest_entries:
                stream_observed = True
            elif stream_observed or pending_initial_response is not None:
                # Cleanup/expiry can remove unread events and END while a slow
                # subscriber drains its fetched batch. An absent observed stream
                # is lost history, not an idle stream waiting for its producer.
                yield StreamGap(
                    requested_event_id=stream_id if pending_initial_response is None else None,
                    earliest_available_event_id=None,
                    latest_available_event_id=None,
                )
                return

            if earliest_entries and (gap_detection_enabled or pending_initial_tail_id is not None):
                earliest_id = self._decode(earliest_entries[0][0])
                if self._stream_id_lt(snapshot_stream_id, earliest_id):
                    latest_id = self._decode(latest_entries[0][0])
                    logger.warning(
                        "subscriber for Redis stream %s fell behind retained history at %s",
                        key,
                        snapshot_stream_id,
                    )
                    yield StreamGap(
                        requested_event_id=None if pending_initial_tail_id is not None else stream_id,
                        earliest_available_event_id=earliest_id,
                        latest_available_event_id=latest_id,
                    )
                    return

            # A syntactically valid but future Last-Event-ID cannot replay from
            # this retained stream. In particular, an already-ended run would
            # otherwise heartbeat forever because XREAD never sees its end marker.
            if latest_entries and gap_detection_enabled:
                latest_id = self._decode(latest_entries[0][0])
                if self._stream_id_lt(latest_id, stream_id):
                    earliest_id = self._decode(earliest_entries[0][0])
                    logger.warning(
                        "subscriber for Redis stream %s requested future cursor %s (latest %s)",
                        key,
                        stream_id,
                        latest_id,
                    )
                    yield StreamGap(
                        requested_event_id=stream_id,
                        earliest_available_event_id=earliest_id,
                        latest_available_event_id=latest_id,
                    )
                    return

            responses_to_process = []
            if pending_initial_response is not None:
                responses_to_process.append(pending_initial_response)
                pending_initial_response = None
            if response:
                responses_to_process.append(response)

            if not responses_to_process:
                if latest_entries and self._decode(latest_entries[0][0]) == stream_id and self._is_end_entry(latest_entries[0][1]):
                    yield END_SENTINEL
                    return

                try:
                    wake_response = await self._redis.xread(
                        {key: stream_id},
                        count=_XREAD_COUNT,
                        block=block_ms,
                    )
                except ResponseError:
                    logger.warning(
                        "Redis rejected stream id %r for stream bridge subscription",
                        stream_id,
                        exc_info=True,
                    )
                    raise
                except RedisError:
                    consecutive_errors += 1
                    if consecutive_errors > _MAX_SUBSCRIBE_RETRIES:
                        raise
                    delay = min(2**consecutive_errors, heartbeat_interval)
                    logger.warning(
                        "Transient Redis error in stream bridge subscriber (retry %d/%d); backing off %.1fs",
                        consecutive_errors,
                        _MAX_SUBSCRIBE_RETRIES,
                        delay,
                        exc_info=True,
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    consecutive_errors = 0

                if not wake_response:
                    yield HEARTBEAT_SENTINEL
                elif last_event_id is None and not gap_detection_enabled and not earliest_entries:
                    # Do not discard the first wake-up from a proven-empty
                    # stream. Holding it until the next atomic bounds check
                    # gives no-cursor subscribers the same fell-behind signal
                    # as Memory without changing malformed-cursor live tailing.
                    pending_initial_response = wake_response
                continue

            for retained_response in responses_to_process:
                for _stream_name, entries in retained_response:
                    for event_id, fields in entries:
                        event_id = self._decode(event_id)
                        stream_id = event_id
                        gap_detection_enabled = True
                        entry = self._entry_from_redis(event_id, fields)
                        if entry is END_SENTINEL:
                            yield END_SENTINEL
                            return
                        yield entry

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        lease = self._producer_leases.get(run_id)
        token = lease.token if lease is not None else None
        await self.finish_producer_lease(run_id)
        if token is None:
            await self._redis.eval(
                _CLEANUP_IF_NO_ACTIVE_PRODUCER_SCRIPT,
                3,
                self._stream_key(run_id),
                self._producer_tracking_key(run_id),
                self._producer_active_key(run_id),
            )
        else:
            await self._redis.eval(
                _CLEANUP_IF_TOKEN_SCRIPT,
                3,
                self._stream_key(run_id),
                self._producer_tracking_key(run_id),
                self._producer_active_key(run_id),
                token,
            )
        async with self._producer_lease_locks.hold(run_id):
            current = self._producer_leases.get(run_id)
            if current is lease:
                self._producer_leases.pop(run_id, None)

    async def close(self) -> None:
        self._closing = True
        await self._producer_setups_drained.wait()
        run_ids = tuple(self._producer_leases)
        failures: list[BaseException] = []
        if run_ids:
            results = await asyncio.gather(
                *(
                    self._stop_producer_lease(
                        run_id,
                        discard_tracking=False,
                        closing=True,
                    )
                    for run_id in run_ids
                ),
                return_exceptions=True,
            )
            failures = [result for result in results if isinstance(result, BaseException)]
        if not self._owns_client:
            if failures:
                raise failures[0]
            return
        close = getattr(self._redis, "aclose", None) or getattr(self._redis, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result
        if failures:
            raise failures[0]
