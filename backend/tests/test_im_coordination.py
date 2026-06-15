"""Tests for IMChannelLock and webhook dedup."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.channels.coordination import IMChannelLock, webhook_dedup


def _make_redis(*, acquire_ok: bool = True) -> AsyncMock:
    """Create a mock Redis client that simulates SET NX EX behavior."""
    redis = AsyncMock()
    redis.eval = AsyncMock()
    if acquire_ok:
        redis.eval.return_value = b"OK"
    else:
        redis.eval.return_value = None
    return redis


class TestIMChannelLock:
    @pytest.mark.asyncio
    async def test_acquire_success(self) -> None:
        redis = _make_redis(acquire_ok=True)
        lock = IMChannelLock(redis, channel="feishu", worker_id="w1", ttl=30)
        result = await lock.acquire()
        assert result is True
        assert lock.held is True
        redis.eval.assert_called_once()
        await lock.release()

    @pytest.mark.asyncio
    async def test_acquire_failure(self) -> None:
        redis = _make_redis(acquire_ok=False)
        lock = IMChannelLock(redis, channel="feishu", worker_id="w1", ttl=30)
        result = await lock.acquire()
        assert result is False
        assert lock.held is False

    @pytest.mark.asyncio
    async def test_release_ownership_check(self) -> None:
        """Release should only succeed if we still own the lock."""
        redis = AsyncMock()
        redis.eval = AsyncMock(side_effect=[b"OK", 1])
        lock = IMChannelLock(redis, channel="feishu", worker_id="w1", ttl=30)
        await lock.acquire()
        assert lock.held is True
        released = await lock.release()
        assert released is True
        assert lock.held is False

    @pytest.mark.asyncio
    async def test_renew_ownership_check(self) -> None:
        """Renew should fail if another worker took the lock."""
        redis = AsyncMock()
        call_count = 0

        async def _eval_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return b"OK"
            return 0

        redis.eval = AsyncMock(side_effect=_eval_side_effect)
        lock = IMChannelLock(redis, channel="feishu", worker_id="w1", ttl=30)
        await lock.acquire()
        renewed = await lock.renew()
        assert renewed is False
        assert lock.held is False
        await lock.release()

    @pytest.mark.asyncio
    async def test_renewal_loop_stops_on_lost_lock(self) -> None:
        """When renewal fails, the renewal loop should stop."""
        redis = AsyncMock()
        call_count = 0

        async def _eval_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return b"OK"
            return 0

        redis.eval = AsyncMock(side_effect=_eval_side_effect)
        lock = IMChannelLock(redis, channel="feishu", worker_id="w1", ttl=3)
        await lock.acquire()
        assert lock.held is True
        await asyncio.sleep(2)
        assert lock.held is False
        await lock.release()


class TestWebhookDedup:
    @pytest.mark.asyncio
    async def test_first_message_returns_true(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        result = await webhook_dedup(redis, "feishu", "msg-123")
        assert result is True

    @pytest.mark.asyncio
    async def test_duplicate_message_returns_false(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=None)
        result = await webhook_dedup(redis, "feishu", "msg-123")
        assert result is False

    @pytest.mark.asyncio
    async def test_dedup_key_includes_channel_and_message(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        await webhook_dedup(redis, "slack", "abc")
        call_args = redis.set.call_args
        assert call_args[0][0] == "deerflow:webhook_dedup:slack:abc"
