"""Regression tests for event-driven in-memory run-record eviction.

The ``RunManager._runs`` registry used to grow without bound: no production
path ever removed a finished record, so every ``RunRecord`` — including its
``kwargs["input"]`` copy of the full conversation payload — stayed resident
for the lifetime of the Gateway process. These tests pin the terminal-path
contract: once a run is terminal and finalization has completed, the registry
record is evicted immediately, but only after the terminal state is confirmed
in the backing RunStore (repaired from the in-memory snapshot when the
best-effort durable writes failed).
"""

import asyncio

import pytest
from langchain_core.messages import AIMessage

from deerflow.runtime import CancelOutcome
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import RunContext, run_agent


def _make_bridge():
    class _Bridge:
        async def publish(self, run_id, event, data):
            return None

        async def publish_end(self, run_id):
            return None

        async def cleanup(self, run_id, *, delay=0):
            return None

    return _Bridge()


class _OkAgent:
    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        yield {"messages": [AIMessage(content="done")]}


class _ExplodingAgent:
    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        raise RuntimeError("boom")
        yield  # pragma: no cover - keeps this a generator


async def _run_to_completion(run_manager: RunManager, record, *, agent_factory) -> None:
    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=None),
        agent_factory=agent_factory,
        graph_input={},
        config={},
    )


@pytest.mark.anyio
async def test_successful_run_evicts_record_after_finalization():
    store = MemoryRunStore()
    run_manager = RunManager(store=store)
    record = await run_manager.create("thread-1")

    await _run_to_completion(run_manager, record, agent_factory=lambda *, config: _OkAgent())
    assert record.status == RunStatus.success

    # Event-driven: once run_agent returns, finalization is complete and the
    # record is already gone from the registry — no delay window.
    assert record.run_id not in run_manager._runs
    # The durable store row survives and hydrates on demand.
    hydrated = await run_manager.get(record.run_id, raise_on_store_error=True)
    assert hydrated is not None
    assert hydrated.status == RunStatus.success
    assert await run_manager.list_by_thread("thread-1") != []


@pytest.mark.anyio
async def test_failed_run_evicts_record_after_finalization():
    store = MemoryRunStore()
    run_manager = RunManager(store=store)
    record = await run_manager.create("thread-1")

    await _run_to_completion(run_manager, record, agent_factory=lambda *, config: _ExplodingAgent())
    assert record.status == RunStatus.error

    assert record.run_id not in run_manager._runs
    hydrated = await run_manager.get(record.run_id, raise_on_store_error=True)
    assert hydrated is not None
    assert hydrated.status == RunStatus.error


@pytest.mark.anyio
async def test_fail_start_if_pending_evicts_record():
    store = MemoryRunStore()
    run_manager = RunManager(store=store)
    record = await run_manager.create("thread-1")

    marked = await run_manager.fail_start_if_pending(record.run_id, error="worker attach failed")
    assert marked is True

    assert record.run_id not in run_manager._runs
    hydrated = await run_manager.get(record.run_id, raise_on_store_error=True)
    assert hydrated is not None
    assert hydrated.status == RunStatus.error


@pytest.mark.anyio
async def test_eviction_skipped_without_store_backing():
    """No RunStore means no fallback for get()/list_by_thread() and the
    registry is the only idempotency dedup — records must be retained."""
    run_manager = RunManager()
    record = await run_manager.create("thread-1")

    await _run_to_completion(run_manager, record, agent_factory=lambda *, config: _OkAgent())
    assert record.status == RunStatus.success

    assert record.run_id in run_manager._runs
    assert await run_manager.get(record.run_id) is record


@pytest.mark.anyio
async def test_eviction_retains_record_until_terminal_state_durable():
    """When the store cannot confirm the terminal state, the record — which
    may hold the only correct snapshot — is retained for retry."""
    store = MemoryRunStore()
    run_manager = RunManager(store=store)
    record = await run_manager.create("thread-1")
    await run_manager.set_status(record.run_id, RunStatus.success)

    original_get = store.get

    async def failing_get(run_id, *, user_id=None):
        raise OSError("store unavailable")

    store.get = failing_get
    assert await run_manager._evict_run_record_if_durable(record.run_id) is False
    assert record.run_id in run_manager._runs

    store.get = original_get
    assert await run_manager._evict_run_record_if_durable(record.run_id) is True
    assert record.run_id not in run_manager._runs


@pytest.mark.anyio
async def test_eviction_repairs_stale_store_row_from_memory_snapshot():
    """A still-active durable row is repaired from the in-memory terminal
    snapshot before the record is dropped."""
    store = MemoryRunStore()
    run_manager = RunManager(store=store)
    record = await run_manager.create("thread-1")
    # Stage a terminal outcome in memory without a durable write.
    await run_manager.set_status(record.run_id, RunStatus.success, persist=False)
    row = await store.get(record.run_id)
    assert row is not None and row["status"] != RunStatus.success.value

    assert await run_manager._evict_run_record_if_durable(record.run_id) is True

    row = await store.get(record.run_id)
    assert row is not None and row["status"] == RunStatus.success.value
    assert record.run_id not in run_manager._runs


@pytest.mark.anyio
async def test_idempotent_reuse_does_not_cache_store_rows():
    """Store-only idempotency hydrations are returned uncached: an active row
    belongs to another worker and a cached active copy would outlive the
    owner's completion (fencing the thread via local_inflight forever), while
    a terminal row is served on demand by store hydration."""
    store = MemoryRunStore()
    owning = RunManager(store=store)
    admitted = await owning.create_or_reject("thread-1", idempotency_key="idem-1")
    await owning.set_status(admitted.run_id, RunStatus.running)

    reusing = RunManager(store=store)
    reused = await reusing.create_or_reject("thread-1", idempotency_key="idem-1")
    assert reused.run_id == admitted.run_id
    assert reused.idempotency_reused is True
    assert reused.run_id not in reusing._runs

    # After the owning worker finishes, the reusing worker neither holds a
    # stale active copy nor fences the thread.
    await owning.set_status(admitted.run_id, RunStatus.success)
    assert not await reusing.has_inflight("thread-1")
    terminal_reuse = await reusing.create_or_reject("thread-1", idempotency_key="idem-1")
    assert terminal_reuse.run_id == admitted.run_id
    assert terminal_reuse.idempotency_reused is True
    assert terminal_reuse.run_id not in reusing._runs

    hydrated = await reusing.get(admitted.run_id, raise_on_store_error=True)
    assert hydrated is not None
    assert hydrated.status == RunStatus.success


@pytest.mark.anyio
async def test_idempotent_reuse_of_active_local_run_returns_live_record():
    """Same-worker reuse of a live run returns the registered record itself."""
    store = MemoryRunStore()
    run_manager = RunManager(store=store)
    record = await run_manager.create_or_reject("thread-1", idempotency_key="idem-2")

    reused = await run_manager.create_or_reject("thread-1", idempotency_key="idem-2")
    assert reused is record
    assert reused.idempotency_reused is True


@pytest.mark.anyio
async def test_cancel_stays_idempotent_after_record_eviction():
    """Single-worker mode: after eviction, a durably interrupted run still
    cancels idempotently (202 semantics) instead of 409."""
    store = MemoryRunStore()
    run_manager = RunManager(store=store)
    record = await run_manager.create("thread-1")
    await run_manager.set_status(record.run_id, RunStatus.running)
    assert await run_manager.cancel(record.run_id) == CancelOutcome.cancelled

    await run_manager.evict_finished_run(record.run_id)
    assert record.run_id not in run_manager._runs

    assert await run_manager.cancel(record.run_id) == CancelOutcome.cancelled


@pytest.mark.anyio
async def test_fenced_worker_never_repairs_store_on_eviction():
    """Multi-worker regression: a worker that lost lease ownership reaches
    the eviction tail while the durable row is still active — its fenced
    local error snapshot must never be published over the peer's row."""
    store = MemoryRunStore()
    run_manager = RunManager(store=store)
    record = await run_manager.create("thread-1")
    await run_manager.set_status(record.run_id, RunStatus.running)

    # A peer takes over the lease: the durable row stays active but flips to
    # the peer's ownership.
    row = await store.get(record.run_id)
    row["owner_worker_id"] = "worker-b"
    row["lease_expires_at"] = "2999-01-01T00:00:00+00:00"

    # The stalled worker is fenced: local error rewrite only, no store write.
    assert await run_manager._mark_ownership_lost(record, reason="lease expired") is True
    assert record.status is RunStatus.error
    assert record.ownership_lost is True
    assert (await store.get(record.run_id))["status"] == RunStatus.running.value

    puts: list[dict] = []
    original_put = store.put

    async def counting_put(run_id, **payload):
        puts.append(payload)
        return await original_put(run_id, **payload)

    store.put = counting_put

    # Eviction with the row still active: no store write, record retained.
    assert await run_manager._evict_run_record_if_durable(record.run_id) is False
    assert puts == []
    assert record.run_id in run_manager._runs
    assert (await store.get(record.run_id))["status"] == RunStatus.running.value
    assert (await store.get(record.run_id))["owner_worker_id"] == "worker-b"

    # The peer terminalizes the row; the next eviction is read-only and drops
    # the fenced overlay.
    row["status"] = RunStatus.success.value
    assert await run_manager._evict_run_record_if_durable(record.run_id) is True
    assert puts == []
    assert record.run_id not in run_manager._runs


@pytest.mark.anyio
async def test_fenced_worker_evicts_overlay_when_row_missing():
    """A fenced record whose store row disappeared (no peer will ever
    terminalize it) drops its overlay instead of lingering in the registry."""
    store = MemoryRunStore()
    run_manager = RunManager(store=store)
    record = await run_manager.create("thread-1")
    await run_manager.set_status(record.run_id, RunStatus.running)
    assert await run_manager._mark_ownership_lost(record, reason="lease expired") is True

    await store.delete(record.run_id)

    assert await run_manager._evict_run_record_if_durable(record.run_id) is True
    assert record.run_id not in run_manager._runs


@pytest.mark.anyio
async def test_eviction_repairs_completion_data_when_status_only_durable():
    """The completion write is best-effort: when only the terminal status
    reached the store, eviction repairs the completion snapshot before
    dropping the record that holds the only copy."""
    store = MemoryRunStore()
    run_manager = RunManager(store=store)
    record = await run_manager.create("thread-1")
    await run_manager.set_status(record.run_id, RunStatus.success)
    record.total_tokens = 123
    record.message_count = 4
    record.last_ai_message = "done"
    row = await store.get(record.run_id)
    assert row["status"] == RunStatus.success.value
    assert row.get("total_tokens", 0) == 0

    assert await run_manager._evict_run_record_if_durable(record.run_id) is True

    row = await store.get(record.run_id)
    assert row["total_tokens"] == 123
    assert row["message_count"] == 4
    assert row["last_ai_message"] == "done"
    assert record.run_id not in run_manager._runs
    hydrated = await run_manager.get(record.run_id, raise_on_store_error=True)
    assert hydrated.total_tokens == 123


@pytest.mark.anyio
async def test_shutdown_drains_runs_before_eviction_retries():
    """A cancellation-resistant eviction retry must not consume the run-drain
    budget: runs are drained first, retries only afterwards."""
    store = MemoryRunStore()
    run_manager = RunManager(store=store)
    done = await run_manager.create("thread-1")
    await run_manager.set_status(done.run_id, RunStatus.success, persist=False)
    live = await run_manager.create("thread-2")
    await run_manager.set_status(live.run_id, RunStatus.running)

    async def failing_put(run_id, **payload):
        raise OSError("store unavailable")

    resist_cancellation = asyncio.Event()

    async def resistant_retry(run_id):
        while not resist_cancellation.is_set():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                if resist_cancellation.is_set():
                    raise

    store.put = failing_put
    run_manager._retry_eviction_until_durable = resistant_retry  # type: ignore[method-assign]
    await run_manager.evict_finished_run(done.run_id)
    retry = run_manager._eviction_retry_tasks[done.run_id]
    assert not retry.done()
    await asyncio.sleep(0)  # start the retry so cancellation hits a running task

    async def slow_run():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)  # bounded cleanup after cancellation
            raise

    live.task = asyncio.create_task(slow_run())
    await asyncio.sleep(0)  # park the run in its sleep before shutdown signals it

    await run_manager.shutdown(timeout=1.0)

    # The run drained within the budget despite the resistant retry.
    assert live.task.done()
    assert not retry.done()  # still resistant, but fenced and re-cancelled
    resist_cancellation.set()
    retry.cancel()
    await asyncio.gather(retry, return_exceptions=True)
    assert run_manager._eviction_retry_tasks == {}


@pytest.mark.anyio
async def test_eviction_retry_lifecycle_is_deduplicated_and_shutdown_fenced():
    """Retry tasks are deduplicated per run, cancelled at shutdown, and the
    shutdown fence prevents a finalizing worker from spawning new ones."""
    store = MemoryRunStore()
    run_manager = RunManager(store=store)
    record = await run_manager.create("thread-1")
    await run_manager.set_status(record.run_id, RunStatus.success, persist=False)

    async def failing_put(run_id, **payload):
        raise OSError("store unavailable")

    store.put = failing_put
    await run_manager.evict_finished_run(record.run_id)
    retry = run_manager._eviction_retry_tasks[record.run_id]
    await run_manager.evict_finished_run(record.run_id)
    assert run_manager._eviction_retry_tasks[record.run_id] is retry

    await run_manager.shutdown(timeout=1)
    assert run_manager._eviction_retry_tasks == {}
    assert retry.cancelled()

    # Fenced: durability stays unconfirmed, but no new retry is spawned.
    await run_manager.evict_finished_run(record.run_id)
    assert run_manager._eviction_retry_tasks == {}
    assert record.run_id in run_manager._runs
