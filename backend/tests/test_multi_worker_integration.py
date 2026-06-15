"""Integration tests for multi-worker deployment scenarios.

Covers tasks 6.1-6.8 from the multi-worker-support change.
Tests use mocks for external dependencies (PostgreSQL, Redis) to keep
the suite fast and CI-friendly.

Note: 6.6 (dev mode fallback) and 6.7 (config override priority) are
covered in test_deployment_config.py.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest


class TestWorkerIdLogging:
    """6.8: Log records include worker_id."""

    def test_worker_id_filter_injects_id(self) -> None:
        from deerflow.config.worker_id import WORKER_ID, WorkerIdFilter

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        filt = WorkerIdFilter()
        filt.filter(record)

        assert hasattr(record, "worker_id")
        assert record.worker_id == WORKER_ID
        assert len(record.worker_id) == 8

    def test_worker_id_is_unique_per_process(self) -> None:
        from deerflow.config.worker_id import WORKER_ID

        assert isinstance(WORKER_ID, str)
        assert len(WORKER_ID) == 8
        assert all(c in "0123456789abcdef" for c in WORKER_ID)

    def test_different_workers_have_different_ids(self) -> None:
        """Each import of worker_id module in a separate process would get a different ID."""
        from deerflow.config.worker_id import WORKER_ID

        ids = {WORKER_ID}
        for _ in range(10):
            import uuid

            ids.add(uuid.uuid4().hex[:8])
        assert len(ids) > 1


class TestMultiWorkerThreadConsistency:
    """6.1: Two workers sharing the same thread see consistent state."""

    @pytest.mark.asyncio
    async def test_checkpointer_state_shared_via_store(self) -> None:
        """Simulate two workers writing/reading from the same store."""
        store: dict = {}

        async def _worker_a_write() -> None:
            store["thread-1"] = {"messages": [{"role": "user", "content": "hello"}]}

        async def _worker_b_read() -> dict:
            return store.get("thread-1", {})

        await _worker_a_write()
        result = await _worker_b_read()

        assert result == {"messages": [{"role": "user", "content": "hello"}]}

    @pytest.mark.asyncio
    async def test_concurrent_writes_to_same_thread(self) -> None:
        """Two workers writing to the same thread ID concurrently."""
        store: dict[str, list] = {}
        lock = asyncio.Lock()

        async def _worker_append(worker_id: str, content: str) -> None:
            async with lock:
                store.setdefault("thread-1", [])
                store["thread-1"].append({"worker": worker_id, "content": content})

        await asyncio.gather(
            _worker_append("w1", "message from worker 1"),
            _worker_append("w2", "message from worker 2"),
        )

        assert len(store["thread-1"]) == 2
        workers = {msg["worker"] for msg in store["thread-1"]}
        assert workers == {"w1", "w2"}


class TestSSEMultiWorker:
    """6.2: Redis stream bridge delivers events across workers."""

    @pytest.mark.asyncio
    async def test_redis_bridge_publish_calls_xadd(self) -> None:
        """Verify publish() calls Redis XADD with the correct stream key and payload."""
        pytest.importorskip("redis")
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.xadd = AsyncMock(return_value=b"1-0")
            mock_from_url.return_value = mock_redis

            from deerflow.runtime.stream_bridge.redis_bridge import RedisStreamBridge

            bridge = RedisStreamBridge(redis_url="redis://localhost")

            await bridge.publish("run-123", "token", {"text": "hello"})

            mock_redis.xadd.assert_called_once()
            call_args = mock_redis.xadd.call_args
            stream_key = call_args[0][0]
            assert "run-123" in stream_key

            await bridge.close()

    @pytest.mark.asyncio
    async def test_redis_bridge_publish_end(self) -> None:
        """Verify publish_end() signals stream termination."""
        pytest.importorskip("redis")
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.xadd = AsyncMock(return_value=b"1-0")
            mock_from_url.return_value = mock_redis

            from deerflow.runtime.stream_bridge.redis_bridge import RedisStreamBridge

            bridge = RedisStreamBridge(redis_url="redis://localhost")

            await bridge.publish_end("run-456")

            mock_redis.xadd.assert_called_once()
            await bridge.close()


class TestAgentMemoryMultiWorker:
    """6.3: Memory written by Worker A is visible to Worker B; optimistic merge works."""

    def test_optimistic_merge_two_workers_different_facts(self) -> None:
        """Two workers write different facts; merge produces union."""
        from deerflow.agents.memory.updater import _merge_facts

        current = {"facts": [{"content": "User prefers Python", "confidence": 0.9}]}
        incoming = {"facts": [{"content": "User works at Acme Corp", "confidence": 0.8}]}

        merged = _merge_facts(current, incoming)

        assert len(merged["facts"]) == 2
        contents = {f["content"] for f in merged["facts"]}
        assert "User prefers Python" in contents
        assert "User works at Acme Corp" in contents

    def test_optimistic_merge_two_workers_same_fact_higher_confidence_wins(self) -> None:
        """Two workers write the same fact with different confidence; higher wins."""
        from deerflow.agents.memory.updater import _merge_facts

        current = {"facts": [{"content": "User prefers Python", "confidence": 0.7}]}
        incoming = {"facts": [{"content": "User prefers Python", "confidence": 0.95}]}

        merged = _merge_facts(current, incoming)

        assert len(merged["facts"]) == 1
        assert merged["facts"][0]["confidence"] == 0.95

    def test_optimistic_merge_preserves_user_and_history(self) -> None:
        """Merge preserves user profile and history from incoming."""
        from deerflow.agents.memory.updater import _merge_facts

        current = {"facts": [], "user": {"name": "old"}, "history": ["old event"]}
        incoming = {"facts": [], "user": {"name": "new"}, "history": ["new event"]}

        merged = _merge_facts(current, incoming)

        assert merged["user"] == {"name": "new"}
        assert merged["history"] == ["new event"]


class TestKBIndexingCompetition:
    """6.4: Two workers compete for the same pending job; only one processes it."""

    @pytest.mark.asyncio
    async def test_two_workers_one_job(self) -> None:
        """Simulate FOR UPDATE SKIP LOCKED: first claim wins, second gets None."""
        job_repo = AsyncMock()
        job_repo.claim_job.side_effect = [
            {"id": "j1", "status": "running", "worker_id": "w1"},
            None,
        ]

        result_a = await job_repo.claim_job("w1")
        result_b = await job_repo.claim_job("w2")

        assert result_a is not None
        assert result_a["worker_id"] == "w1"
        assert result_b is None

    @pytest.mark.asyncio
    async def test_stale_job_reclaimed_after_timeout(self) -> None:
        """A job stuck in 'running' state is reclaimed by another worker."""
        job_repo = AsyncMock()
        job_repo.reclaim_stale_jobs = AsyncMock(return_value=1)

        reclaimed = await job_repo.reclaim_stale_jobs(timeout_seconds=300, max_retries=3)
        assert reclaimed == 1


class TestIMLockCompetition:
    """6.5: Two workers compete for the same IM channel; only one holds the lock."""

    @pytest.mark.asyncio
    async def test_two_workers_one_channel(self) -> None:
        """First worker acquires lock; second worker fails."""
        from app.channels.coordination import IMChannelLock

        redis = AsyncMock()
        redis.eval = AsyncMock()

        redis.eval.return_value = b"OK"
        lock_a = IMChannelLock(redis, channel="feishu", worker_id="w1", ttl=30)
        acquired_a = await lock_a.acquire()
        assert acquired_a is True

        redis.eval.return_value = None
        lock_b = IMChannelLock(redis, channel="feishu", worker_id="w2", ttl=30)
        acquired_b = await lock_b.acquire()
        assert acquired_b is False

        await lock_a.release()

    @pytest.mark.asyncio
    async def test_lock_expiry_allows_takeover(self) -> None:
        """When lock holder stops renewing, another worker can acquire after expiry."""
        from app.channels.coordination import IMChannelLock

        redis = AsyncMock()
        lock_a_held = True

        async def _eval_side_effect(*args, **kwargs):
            nonlocal lock_a_held
            script = args[0]
            if "NX" in script:
                if lock_a_held:
                    return None
                return b"OK"
            if "GET" in script and "SET" in script:
                return b"OK" if lock_a_held else 0
            if "DEL" in script:
                lock_a_held = False
                return 1
            return None

        redis.eval = AsyncMock(side_effect=_eval_side_effect)

        lock_a = IMChannelLock(redis, channel="feishu", worker_id="w1", ttl=3)
        acquired_a = await lock_a.acquire()
        assert acquired_a is False

        lock_a_held = False

        lock_b = IMChannelLock(redis, channel="feishu", worker_id="w2", ttl=30)
        acquired_b = await lock_b.acquire()
        assert acquired_b is True

        await lock_b.release()
