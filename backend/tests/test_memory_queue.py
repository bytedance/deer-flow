import threading
import time
from unittest.mock import MagicMock, call, patch

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.queue import ConversationContext, MemoryUpdateQueue


def _queue(updater: MagicMock | None = None) -> MemoryUpdateQueue:
    """A MemoryUpdateQueue with DI config + a (mock) updater; timer disabled."""
    return MemoryUpdateQueue(DeerMemConfig(), updater or MagicMock())


def test_queue_add_preserves_existing_correction_flag_for_same_thread() -> None:
    queue = _queue()
    with patch.object(queue, "_reset_timer"):
        queue.add(thread_id="thread-1", messages=["first"], correction_detected=True)
        queue.add(thread_id="thread-1", messages=["second"], correction_detected=False)

    assert len(queue._queue) == 1
    assert queue._queue[0].messages == ["second"]
    assert queue._queue[0].correction_detected is True


def test_process_queue_forwards_correction_flag_to_updater() -> None:
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["conversation"], agent_name="lead_agent", correction_detected=True)]

    queue._process_queue()

    mock_updater.update_memory.assert_called_once_with(
        messages=["conversation"],
        thread_id="thread-1",
        agent_name="lead_agent",
        correction_detected=True,
        reinforcement_detected=False,
        user_id=None,
        trace_id=None,
    )


def test_queue_add_preserves_existing_reinforcement_flag_for_same_thread() -> None:
    queue = _queue()
    with patch.object(queue, "_reset_timer"):
        queue.add(thread_id="thread-1", messages=["first"], reinforcement_detected=True)
        queue.add(thread_id="thread-1", messages=["second"], reinforcement_detected=False)

    assert len(queue._queue) == 1
    assert queue._queue[0].messages == ["second"]
    assert queue._queue[0].reinforcement_detected is True


def test_process_queue_forwards_reinforcement_flag_to_updater() -> None:
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["conversation"], agent_name="lead_agent", reinforcement_detected=True)]

    queue._process_queue()

    mock_updater.update_memory.assert_called_once_with(
        messages=["conversation"],
        thread_id="thread-1",
        agent_name="lead_agent",
        correction_detected=False,
        reinforcement_detected=True,
        user_id=None,
        trace_id=None,
    )


def test_flush_nowait_cancels_existing_timer_and_starts_immediate_timer() -> None:
    queue = _queue()
    existing_timer = MagicMock()
    queue._timer = existing_timer
    created_timer = MagicMock()

    with patch("deerflow.agents.memory.backends.deermem.deermem.core.queue.threading.Timer", return_value=created_timer) as timer_cls:
        queue.flush_nowait()

    existing_timer.cancel.assert_called_once_with()
    timer_cls.assert_called_once_with(0, queue._process_queue)
    assert created_timer.daemon is True
    created_timer.start.assert_called_once_with()
    assert queue._timer is created_timer


def test_add_nowait_cancels_existing_timer_and_starts_immediate_timer() -> None:
    queue = _queue()
    existing_timer = MagicMock()
    queue._timer = existing_timer
    created_timer = MagicMock()

    with patch("deerflow.agents.memory.backends.deermem.deermem.core.queue.threading.Timer", return_value=created_timer) as timer_cls:
        queue.add_nowait(thread_id="thread-1", messages=["conversation"], agent_name="lead-agent")

    existing_timer.cancel.assert_called_once_with()
    timer_cls.assert_called_once_with(0, queue._process_queue)
    assert queue.pending_count == 1
    assert queue._queue[0].agent_name == "lead-agent"
    assert created_timer.daemon is True
    created_timer.start.assert_called_once_with()


def test_process_queue_defers_reprocess_when_already_processing() -> None:
    """When a timer fires while a worker is active, ``_process_queue`` must set the
    deferred-rerun flag instead of spinning up a tight 0-delay Timer chain.

    The old behavior re-scheduled a 0-delay Timer on every re-entry while busy,
    burning a fresh thread each time. The fix defers a single re-run via
    ``_reprocess_pending`` that the finishing worker honors once.
    """
    queue = _queue()
    queue._processing = True

    with patch("deerflow.agents.memory.backends.deermem.deermem.core.queue.threading.Timer") as timer_cls:
        queue._process_queue()

    timer_cls.assert_not_called()
    assert queue._reprocess_pending is True


def test_finishing_worker_reschedules_once_when_reprocess_pending() -> None:
    """A worker that finishes with ``_reprocess_pending`` set and work still queued
    schedules exactly one follow-up run (not a per-arrival timer spin)."""
    mock_updater = MagicMock()
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["first"], agent_name="lead_agent")]
    queue._reprocess_pending = True
    created_timer = MagicMock()

    def _enqueue_more_while_processing(**_kwargs) -> bool:
        # Simulate a new update arriving mid-processing so the finally block sees
        # remaining work and reschedules exactly once.
        queue._queue.append(ConversationContext(thread_id="thread-2", messages=["second"], agent_name="lead_agent"))
        return True

    mock_updater.update_memory.side_effect = _enqueue_more_while_processing

    with patch("deerflow.agents.memory.backends.deermem.deermem.core.queue.threading.Timer", return_value=created_timer) as timer_cls:
        queue._process_queue()

    timer_cls.assert_called_once_with(0, queue._process_queue)
    assert created_timer.daemon is True
    created_timer.start.assert_called_once_with()
    assert queue._reprocess_pending is False


def test_finishing_worker_does_not_reschedule_when_no_work_remains() -> None:
    """The deferred re-run is cleared even when nothing is left to process, so a
    stray flag never leaves a dangling ``_reprocess_pending``."""
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["only"], agent_name="lead_agent")]
    queue._reprocess_pending = True

    with patch("deerflow.agents.memory.backends.deermem.deermem.core.queue.threading.Timer") as timer_cls:
        queue._process_queue()

    timer_cls.assert_not_called()
    assert queue._reprocess_pending is False


def test_flush_nowait_is_non_blocking() -> None:
    queue = _queue()
    started = threading.Event()
    finished = threading.Event()

    def _slow_process_queue() -> None:
        started.set()
        time.sleep(0.2)
        finished.set()

    queue._process_queue = _slow_process_queue

    start = time.perf_counter()
    queue.flush_nowait()
    elapsed = time.perf_counter() - start

    assert started.wait(0.1) is True
    assert elapsed < 0.1
    assert finished.is_set() is False
    assert finished.wait(1.0) is True


def test_queue_keeps_updates_for_different_agents_in_same_thread() -> None:
    queue = _queue()
    with patch.object(queue, "_reset_timer"):
        queue.add(thread_id="thread-1", messages=["agent-a"], agent_name="agent-a")
        queue.add(thread_id="thread-1", messages=["agent-b"], agent_name="agent-b")

    assert queue.pending_count == 2
    assert [context.agent_name for context in queue._queue] == ["agent-a", "agent-b"]


def test_queue_still_coalesces_updates_for_same_agent_in_same_thread() -> None:
    queue = _queue()
    with patch.object(queue, "_reset_timer"):
        queue.add(thread_id="thread-1", messages=["first"], agent_name="agent-a", correction_detected=True)
        queue.add(thread_id="thread-1", messages=["second"], agent_name="agent-a", correction_detected=False)

    assert queue.pending_count == 1
    assert queue._queue[0].agent_name == "agent-a"
    assert queue._queue[0].messages == ["second"]
    assert queue._queue[0].correction_detected is True


def test_process_queue_updates_different_agents_in_same_thread_separately() -> None:
    queue = _queue()
    with patch.object(queue, "_reset_timer"):
        queue.add(thread_id="thread-1", messages=["agent-a"], agent_name="agent-a")
        queue.add(thread_id="thread-1", messages=["agent-b"], agent_name="agent-b")

    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue._updater = mock_updater

    with patch("deerflow.agents.memory.backends.deermem.deermem.core.queue.time.sleep"):
        queue.flush()

    assert mock_updater.update_memory.call_count == 2
    mock_updater.update_memory.assert_has_calls(
        [
            call(messages=["agent-a"], thread_id="thread-1", agent_name="agent-a", correction_detected=False, reinforcement_detected=False, user_id=None, trace_id=None),
            call(messages=["agent-b"], thread_id="thread-1", agent_name="agent-b", correction_detected=False, reinforcement_detected=False, user_id=None, trace_id=None),
        ]
    )


def test_process_queue_forwards_trace_id_to_updater() -> None:
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["conversation"], agent_name="lead_agent", trace_id="trace-memory-1")]

    queue._process_queue()

    mock_updater.update_memory.assert_called_once_with(
        messages=["conversation"],
        thread_id="thread-1",
        agent_name="lead_agent",
        correction_detected=False,
        reinforcement_detected=False,
        user_id=None,
        trace_id="trace-memory-1",
    )


# ---------------------------------------------------------------------------
# shutdown_flush / flush_sync (graceful-shutdown drain) — review carry-overs.
# The queue is a daemon-timer + in-memory buffer, so anything pending at
# process exit is lost. flush_sync drains it within a hard timeout, joining an
# in-flight worker first so contexts a debounce Timer already pulled out of the
# queue are not lost either.
# ---------------------------------------------------------------------------

_QUEUE_MODULE = "deerflow.agents.memory.backends.deermem.deermem.core.queue"


def test_flush_sync_noop_on_empty_queue() -> None:
    """flush_sync short-circuits and returns True when there is nothing to drain."""
    queue = _queue()
    assert queue.pending_count == 0
    assert queue.flush_sync(timeout=5.0) is True


def test_flush_sync_drains_pending_queue_and_returns_true() -> None:
    """flush_sync runs the synchronous flush() and waits for it to finish."""
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["conversation"], agent_name="lead_agent")]

    with (
        patch(_QUEUE_MODULE + ".MemoryUpdater", create=True),
        patch(_QUEUE_MODULE + ".time.sleep"),
    ):
        completed = queue.flush_sync(timeout=5.0)

    assert completed is True
    assert queue.pending_count == 0
    mock_updater.update_memory.assert_called_once_with(
        messages=["conversation"],
        thread_id="thread-1",
        agent_name="lead_agent",
        correction_detected=False,
        reinforcement_detected=False,
        user_id=None,
        trace_id=None,
    )


def test_flush_sync_returns_false_when_flush_exceeds_timeout() -> None:
    """flush_sync does not block past ``timeout``; a slow flush returns False."""
    queue = _queue()
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["conversation"], agent_name="lead_agent")]
    release = threading.Event()

    def _slow_flush() -> None:
        # Block until the test releases us (well past the flush_sync timeout).
        release.wait(timeout=5.0)

    with patch.object(queue, "flush", side_effect=_slow_flush):
        completed = queue.flush_sync(timeout=0.1)

    assert completed is False
    # The queue was not drained because flush() never returned.
    assert queue.pending_count == 1
    # Release the daemon thread so it does not linger past the test.
    release.set()


def _run_inflight_worker(queue: MemoryUpdateQueue, release: threading.Event) -> threading.Thread:
    """Start a thread that mimics _process_queue's "pulled contexts, mid-LLM" state.

    It claims ``_processing`` / ``_processing_thread`` (so the queue looks idle
    by ``pending_count`` but a worker is in flight), blocks on ``release``,
    then clears the flags on the way out.
    """

    def _inflight() -> None:
        with queue._lock:
            queue._processing = True
            queue._processing_thread = threading.current_thread()
        release.wait(timeout=5.0)
        with queue._lock:
            queue._processing = False
            queue._processing_thread = None

    thread = threading.Thread(target=_inflight, name="fake-inflight-worker", daemon=True)
    thread.start()
    # Wait until the fake worker has claimed _processing.
    while not queue.is_processing:
        time.sleep(0.005)
    return thread


def test_flush_sync_waits_for_inflight_worker_and_returns_false_if_unfinished() -> None:
    """flush_sync must not report success while an in-flight _process_queue is
    still mid-LLM-call — the contexts it already pulled out would be lost on
    exit. It joins the in-flight worker (bounded) and returns False when the
    worker does not finish within the budget (review comment #1)."""
    queue = _queue()
    release = threading.Event()
    inflight = _run_inflight_worker(queue, release)

    try:
        completed = queue.flush_sync(timeout=0.2)
    finally:
        release.set()
        inflight.join(timeout=5.0)

    assert completed is False


def test_flush_sync_returns_true_when_inflight_worker_finishes_in_budget() -> None:
    """When the in-flight worker finishes within the budget, flush_sync joins it
    and reports success (review comment #1, positive case)."""
    queue = _queue()
    release = threading.Event()
    inflight = _run_inflight_worker(queue, release)

    # Let the in-flight worker finish well within the budget.
    release.set()

    completed = queue.flush_sync(timeout=5.0)
    inflight.join(timeout=5.0)

    assert completed is True
    assert queue.is_processing is False
    assert queue._processing_thread is None


def test_flush_sync_returns_false_when_flush_raises() -> None:
    """flush_sync reports failure (not success) when flush() raises, so the
    caller never logs a contradictory 'completed' next to the exception
    (review comment #2)."""
    queue = _queue()
    queue._queue = [ConversationContext(thread_id="thread-1", messages=["conversation"], agent_name="lead_agent")]

    with patch.object(queue, "flush", side_effect=RuntimeError("boom")):
        completed = queue.flush_sync(timeout=5.0)

    assert completed is False


def test_flush_sync_skips_inter_item_delay_on_drain_path() -> None:
    """On the shutdown-drain path the per-item rate-limit sleep is skipped so
    the bounded timeout covers as many items as possible (review comment #5)."""
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    queue = _queue(mock_updater)
    queue._queue = [ConversationContext(thread_id=f"thread-{i}", messages=["conversation"], agent_name="lead_agent") for i in range(3)]

    with patch(_QUEUE_MODULE + ".time.sleep") as mock_sleep:
        completed = queue.flush_sync(timeout=5.0)

    assert completed is True
    assert queue.pending_count == 0
    # No inter-item rate-limit sleep on the drain path.
    mock_sleep.assert_not_called()
    assert mock_updater.update_memory.call_count == 3
