"""Memory update queue with debounce mechanism."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..config import DeerMemConfig

if TYPE_CHECKING:
    from .updater import MemoryUpdater

logger = logging.getLogger(__name__)


@dataclass
class ConversationContext:
    """Context for a conversation to be processed for memory update."""

    thread_id: str
    messages: list[Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    agent_name: str | None = None
    user_id: str | None = None
    trace_id: str | None = None
    correction_detected: bool = False
    reinforcement_detected: bool = False


class MemoryUpdateQueue:
    """Queue for memory updates with debounce mechanism.

    This queue collects conversation contexts and processes them after
    a configurable debounce period. Multiple conversations received within
    the debounce window are batched together.
    """

    def __init__(self, config: DeerMemConfig, updater: MemoryUpdater):
        """Initialize the memory update queue with injected config + updater."""
        self._config = config
        self._updater = updater
        self._queue: list[ConversationContext] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._processing = False
        # Thread currently running ``_process_queue`` (None when idle). ``flush_sync``
        # joins an in-flight worker instead of reporting a false-positive "completed"
        # while contexts it already pulled out of the queue are still being processed
        # (and would be lost on exit). See ``flush_sync`` step (1).
        self._processing_thread: threading.Thread | None = None
        self._reprocess_pending = False

    @staticmethod
    def _queue_key(
        thread_id: str,
        user_id: str | None,
        agent_name: str | None,
    ) -> tuple[str, str | None, str | None]:
        """Return the debounce identity for a memory update target."""
        return (thread_id, user_id, agent_name)

    def add(
        self,
        thread_id: str,
        messages: list[Any],
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
    ) -> None:
        """Add a conversation to the update queue.

        Args:
            thread_id: The thread ID.
            messages: The conversation messages.
            agent_name: If provided, memory is stored per-agent. If None, uses global memory.
            user_id: The user ID captured at enqueue time. Stored in ConversationContext so it
                survives the threading.Timer boundary (ContextVar does not propagate across
                raw threads).
            trace_id: Request trace id captured at enqueue time so the
                later Timer thread can attach it to memory LLM tracing metadata.
            correction_detected: Whether recent turns include an explicit correction signal.
            reinforcement_detected: Whether recent turns include a positive reinforcement signal.
        """
        with self._lock:
            self._enqueue_locked(
                thread_id=thread_id,
                messages=messages,
                agent_name=agent_name,
                user_id=user_id,
                trace_id=trace_id,
                correction_detected=correction_detected,
                reinforcement_detected=reinforcement_detected,
            )
            self._reset_timer()

        logger.info("Memory update queued for thread %s, queue size: %d", thread_id, len(self._queue))

    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
    ) -> None:
        """Add a conversation and start processing immediately in the background."""
        with self._lock:
            self._enqueue_locked(
                thread_id=thread_id,
                messages=messages,
                agent_name=agent_name,
                user_id=user_id,
                trace_id=trace_id,
                correction_detected=correction_detected,
                reinforcement_detected=reinforcement_detected,
            )
            self._schedule_timer(0)

        logger.info("Memory update queued for immediate processing on thread %s, queue size: %d", thread_id, len(self._queue))

    def _enqueue_locked(
        self,
        *,
        thread_id: str,
        messages: list[Any],
        agent_name: str | None,
        user_id: str | None,
        trace_id: str | None,
        correction_detected: bool,
        reinforcement_detected: bool,
    ) -> None:
        queue_key = self._queue_key(thread_id, user_id, agent_name)
        existing_context = next(
            (context for context in self._queue if self._queue_key(context.thread_id, context.user_id, context.agent_name) == queue_key),
            None,
        )
        merged_correction_detected = correction_detected or (existing_context.correction_detected if existing_context is not None else False)
        merged_reinforcement_detected = reinforcement_detected or (existing_context.reinforcement_detected if existing_context is not None else False)
        context = ConversationContext(
            thread_id=thread_id,
            messages=messages,
            agent_name=agent_name,
            user_id=user_id,
            trace_id=trace_id,
            correction_detected=merged_correction_detected,
            reinforcement_detected=merged_reinforcement_detected,
        )

        self._queue = [context for context in self._queue if self._queue_key(context.thread_id, context.user_id, context.agent_name) != queue_key]
        self._queue.append(context)

    def _reset_timer(self) -> None:
        """Reset the debounce timer."""
        config = self._config
        self._schedule_timer(config.debounce_seconds)

        logger.debug("Memory update timer set for %ss", config.debounce_seconds)

    def _schedule_timer(self, delay_seconds: float) -> None:
        """Schedule queue processing after the provided delay."""
        # Cancel existing timer if any
        if self._timer is not None:
            self._timer.cancel()

        self._timer = threading.Timer(
            delay_seconds,
            self._process_queue,
        )
        self._timer.daemon = True
        self._timer.start()

    def _process_queue(self, *, skip_inter_item_delay: bool = False) -> None:
        """Process all queued conversation contexts.

        Args:
            skip_inter_item_delay: When set, skip the inter-item rate-limit
                ``time.sleep``. Intended for the shutdown-drain path
                (:meth:`flush_sync`), which races a bounded timeout and should
                not waste budget sleeping between items.
        """
        with self._lock:
            if self._processing:
                # Another worker is already draining the queue. Instead of
                # spawning a tight timer spin (repeatedly re-scheduling a
                # 0-delay Timer thread while busy), defer a single re-run: the
                # active worker checks this flag in its finally block and
                # reschedules once if work remains.
                self._reprocess_pending = True
                return

            if not self._queue:
                return

            self._processing = True
            self._processing_thread = threading.current_thread()
            contexts_to_process = self._queue.copy()
            self._queue.clear()
            self._timer = None

        logger.info("Processing %d queued memory updates", len(contexts_to_process))

        succeeded = 0
        failed = 0
        try:
            for context in contexts_to_process:
                try:
                    logger.info("Updating memory for thread %s (trace_id=%s)", context.thread_id, context.trace_id)
                    success = self._updater.update_memory(
                        messages=context.messages,
                        thread_id=context.thread_id,
                        agent_name=context.agent_name,
                        correction_detected=context.correction_detected,
                        reinforcement_detected=context.reinforcement_detected,
                        user_id=context.user_id,
                        trace_id=context.trace_id,
                    )
                    if success:
                        succeeded += 1
                        logger.info("Memory updated successfully for thread %s (trace_id=%s)", context.thread_id, context.trace_id)
                    else:
                        failed += 1
                        logger.warning("Memory update skipped/failed for thread %s (trace_id=%s)", context.thread_id, context.trace_id)
                except Exception as e:
                    failed += 1
                    logger.error("Error updating memory for thread %s (trace_id=%s): %s", context.thread_id, context.trace_id, e)

                # Small delay between updates to avoid rate limiting.
                # Skipped on the shutdown-drain path, which races a bounded
                # timeout and should spend that budget on LLM calls, not on
                # sleeping between items.
                if not skip_inter_item_delay and len(contexts_to_process) > 1:
                    time.sleep(0.5)
        finally:
            # Summary count disambiguates "drained" (queue emptied) from "saved"
            # (every extraction persisted): per-item ``update_memory`` failures are
            # swallowed above, so without this an operator debugging missing
            # memories would see only the happy-path "Processing N" line.
            if succeeded or failed:
                logger.info("Memory update batch done: %d succeeded, %d failed", succeeded, failed)
            with self._lock:
                self._processing = False
                self._processing_thread = None
                if self._reprocess_pending:
                    self._reprocess_pending = False
                    if self._queue:
                        self._schedule_timer(0)

    def flush(self, *, skip_inter_item_delay: bool = False) -> None:
        """Force immediate processing of the queue.

        This is useful for testing or graceful shutdown.

        Args:
            skip_inter_item_delay: Forwarded to :meth:`_process_queue`; skip the
                inter-item rate-limit sleep. Intended for the shutdown-drain
                path (:meth:`flush_sync`).
        """
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

        self._process_queue(skip_inter_item_delay=skip_inter_item_delay)

    def flush_sync(self, timeout: float) -> bool:
        """Best-effort synchronous flush bounded by ``timeout`` seconds.

        Unlike :meth:`flush_nowait` (which only schedules a daemon timer that
        is killed on process exit), this runs :meth:`flush` on a daemon thread
        and waits up to ``timeout`` seconds for it to finish. Intended for
        graceful shutdown: without it, any updates enqueued since the last
        timer fire are lost on restart / rolling deploy / SIGTERM, because the
        queue is pure in-memory and the debounce Timer is a daemon thread.

        The drain accounts for two races a naive ``flush()`` would miss:

        - **In-flight worker.** If the debounce Timer already fired, an
          ``_process_queue`` worker is mid-LLM-call holding contexts it already
          pulled out of the queue (``_processing=True``, queue empty). ``flush``
          alone would see ``_processing=True``, no-op, and report success while
          that worker is still running and likely killed on exit. So we join
          the in-flight worker first (bounded by the remaining budget).
        - **Failed flush.** ``flush`` makes a synchronous LLM call that can
          raise; success is tracked on the happy path only, so the return value
          matches the docstring's "completed".

        Note: steps (1) and (3) share the same ``deadline`` budget. A slow
        in-flight worker can consume most/all of it, leaving step (3) to no-op;
        ``timeout`` must therefore cover both a slow in-flight worker *and* the
        remaining queue (best-effort: any tail not drained in budget is dropped,
        same failure direction as no flush, scoped to the tail).

        Returns ``True`` only if the drain genuinely finished (queue empty, no
        worker still running, flush did not raise) within ``timeout``.
        """
        deadline = time.monotonic() + timeout

        # (1) Wait for an in-flight _process_queue first (bounded). Otherwise
        # flush() would see _processing=True, no-op, and we would report
        # success while that worker is still mid-LLM-call on a daemon thread
        # that exit will kill — losing the contexts it already pulled out.
        with self._lock:
            in_flight = self._processing_thread
        if in_flight is not None:
            in_flight.join(timeout=max(0.0, deadline - time.monotonic()))

        # (2) Genuine idle: nothing pending and no worker still running.
        if self.pending_count == 0 and not self.is_processing:
            return True

        # (3) Drain the queue on a daemon thread so the timeout is a real hard
        # stop: flush() makes a synchronous LLM call that cannot be
        # interrupted, so we wait on Event.wait, not on Thread.join.
        success = False
        done = threading.Event()

        def _run() -> None:
            nonlocal success
            try:
                self.flush(skip_inter_item_delay=True)
                success = True
            except Exception:
                logger.exception("Memory queue flush failed during shutdown drain")
            finally:
                done.set()

        worker = threading.Thread(target=_run, name="memory-shutdown-flush", daemon=True)
        worker.start()
        finished = done.wait(timeout=max(0.0, deadline - time.monotonic()))
        if not finished:
            return False
        # flush() returned; only report success if no worker raced back in.
        return bool(success) and not self.is_processing

    def flush_nowait(self) -> None:
        """Start queue processing immediately in a background thread."""
        with self._lock:
            # Daemon thread: queued messages may be lost if the process exits
            # before _process_queue completes. Acceptable for best-effort memory updates.
            self._schedule_timer(0)

    def clear(self) -> None:
        """Clear the queue without processing.

        This is useful for testing.
        """
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._queue.clear()
            self._processing = False
            self._processing_thread = None
            self._reprocess_pending = False

    @property
    def pending_count(self) -> int:
        """Get the number of pending updates."""
        with self._lock:
            return len(self._queue)

    @property
    def is_processing(self) -> bool:
        """Check if the queue is currently being processed."""
        with self._lock:
            return self._processing
