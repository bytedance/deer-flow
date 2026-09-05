"""Memory update queue with debounce mechanism.

The queue collects conversation contexts and processes them after a
configurable debounce period; multiple contexts for the same
``(thread_id, user_id, agent_name)`` key are coalesced into one update.

The queue is a process-local in-memory list plus a debounce
:class:`~threading.Timer`. Items still pending at process exit are lost
(best-effort :meth:`MemoryUpdateQueue.flush_sync` drain softens this for
graceful shutdown). Memory updates are best-effort: a failed or lost update is
re-fed on the next conversation turn (the middleware passes the full
conversation each cycle, and the updater's watermark does not advance on
failure), so an in-memory queue covers the realistic graceful-deploy case
without a persistence layer.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..config import DeerMemConfig
from .storage import is_stale_clear_generation

if TYPE_CHECKING:
    from .updater import MemoryUpdater

logger = logging.getLogger(__name__)


class QueueFull(Exception):
    """Raised when a non-signal update is rejected under backpressure.

    Signal-bearing updates (any detected signal) are always admitted so that
    important memories are never shed; only non-signal updates are rejected
    once ``queue_max_depth`` is reached. Callers may catch this to degrade
    (e.g. fall back to a synchronous write on the emergency path).
    """


def queue_key(
    thread_id: str,
    user_id: str | None,
    agent_name: str | None,
) -> tuple[str, str | None, str | None]:
    """Return the debounce identity for a memory update target."""
    return (thread_id, user_id, agent_name)


@dataclass
class ConversationContext:
    """Context for a conversation to be processed for memory update."""

    thread_id: str
    messages: list[Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    agent_name: str | None = None
    user_id: str | None = None
    trace_id: str | None = None
    signals: frozenset[str] = field(default_factory=frozenset)
    # Emergency (summarization) flushes bypass the updater's index watermark:
    # the subset they carry is a one-shot "extract before removal" snapshot whose
    # own length would otherwise regress the conversation watermark. Such contexts
    # also coexist with (do not replace) a pending normal update for the same key
    # so a flush cannot drop a pending normal update's un-extracted tail. See
    # ``_enqueue_locked``'s match-key + backpressure handling.
    bypass_watermark: bool = False
    # Scope clear-generation captured when this conversation became pending
    # work. Commit must use this token, not a later snapshot: a clear that
    # lands during debounce would otherwise look current and restore facts.
    # Same-key merges keep the earlier value unless a newer clear is already
    # visible; then the queue consumes the pre-clear snapshot and starts a
    # fresh fence. An incoming peek older than the queued context is refused
    # so that snapshot cannot inherit the newer fence. A missing token and
    # emergency (bypass) snapshots are never refreshed.
    clear_generation: tuple[int, int] | None = None


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
        self._items: list[ConversationContext] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._processing = False
        # Thread currently running ``_process_queue`` (None when idle). ``flush_sync``
        # joins an in-flight worker instead of reporting a false-positive "completed"
        # while contexts it already pulled out of the queue are still being processed
        # (and would be lost on exit). See ``flush_sync`` step (1).
        self._processing_thread: threading.Thread | None = None
        self._reprocess_pending = False

    def add(
        self,
        thread_id: str,
        messages: list[Any],
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
        signals: frozenset[str] | None = None,
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
            signals: Signal classes detected in the conversation (correction /
                reinforcement / preference / ...), used as extraction hints. Any
                signal is admitted under backpressure.
        """
        # Peek before the queue lock: every conversation turn enqueues here, and
        # the file-backed peek is uncached manifest I/O. Holding ``_lock`` across
        # that read would serialize all memory admits behind disk. A token that
        # misses a clear landing afterwards is still dropped by the pre-LLM and
        # commit-time checks.
        captured_clear_generation = self._capture_clear_generation(agent_name, user_id)
        with self._lock:
            self._enqueue_locked(
                thread_id=thread_id,
                messages=messages,
                agent_name=agent_name,
                user_id=user_id,
                trace_id=trace_id,
                signals=frozenset(signals) if signals else frozenset(),
                bypass_watermark=False,
                captured_clear_generation=captured_clear_generation,
            )
            self._reset_timer()

        logger.info("Memory update queued for thread %s, queue size: %d", thread_id, len(self._items))

    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
        signals: frozenset[str] | None = None,
    ) -> None:
        """Add a conversation and start processing immediately in the background."""
        captured_clear_generation = self._capture_clear_generation(agent_name, user_id)
        with self._lock:
            self._enqueue_locked(
                thread_id=thread_id,
                messages=messages,
                agent_name=agent_name,
                user_id=user_id,
                trace_id=trace_id,
                signals=frozenset(signals) if signals else frozenset(),
                bypass_watermark=True,
                captured_clear_generation=captured_clear_generation,
            )
            self._schedule_timer(0)

        logger.info("Memory update queued for immediate processing on thread %s, queue size: %d", thread_id, len(self._items))

    def _enqueue_locked(
        self,
        *,
        thread_id: str,
        messages: list[Any],
        agent_name: str | None,
        user_id: str | None,
        trace_id: str | None,
        signals: frozenset[str],
        bypass_watermark: bool = False,
        captured_clear_generation: tuple[int, int],
    ) -> ConversationContext:
        key = queue_key(thread_id, user_id, agent_name)
        # Emergency (bypass) and normal updates coexist: the match key includes
        # ``bypass_watermark`` so a summarization flush (bypass=True) never
        # replaces a pending normal update for the same (thread, user, agent) --
        # replacing it would drop the normal update's un-extracted tail, which
        # the next turn may not re-feed if the user stops. Both are processed
        # independently instead.
        existing = next(
            (c for c in self._items if queue_key(c.thread_id, c.user_id, c.agent_name) == key and c.bypass_watermark == bypass_watermark),
            None,
        )
        # Backpressure: once depth reaches the cap, reject NEW non-signal normal
        # items. Same-key updates merge (do not grow depth); signal-bearing items
        # and emergency (bypass) flushes are always admitted. Signals capture
        # important memories, and the emergency path captures messages about to
        # be removed by summarization -- neither can be re-fed next turn, so
        # shedding them under load would lose data rather than merely defer it.
        max_depth = self._config.queue_max_depth
        if max_depth > 0 and not bypass_watermark and not signals and existing is None and len(self._items) >= max_depth:
            raise QueueFull(f"memory update queue is full (depth {len(self._items)} >= {max_depth}); non-signal update for thread {thread_id} rejected")

        # Merge by signal union: a signal seen on any update for this key stays.
        merged_signals = signals | (existing.signals if existing is not None else frozenset())
        # First enqueue binds the pre-lock peek. A later same-key merge keeps
        # that token when the generation is unchanged, missing, or this is an
        # emergency snapshot. Re-reading after a clear and blindly refreshing
        # would restore pre-clear facts; a visible newer clear instead consumes
        # the pre-clear snapshot and starts a fresh fence so post-clear turns
        # are extracted on this flush. A late add whose peek is older than the
        # queued context must not replace messages: that would inherit the
        # newer fence and restore the pre-clear snapshot.
        if existing is None:
            enqueued_clear_generation = captured_clear_generation
        elif existing.clear_generation is not None and is_stale_clear_generation(captured_clear_generation, existing.clear_generation):
            incoming = ConversationContext(
                thread_id=thread_id,
                messages=messages,
                agent_name=agent_name,
                user_id=user_id,
                trace_id=trace_id,
                signals=signals,
                bypass_watermark=bypass_watermark,
                clear_generation=captured_clear_generation,
            )
            if not self._consume_pre_clear_feed(incoming):
                existing.clear_generation = captured_clear_generation
            return existing
        elif existing.bypass_watermark or existing.clear_generation is None:
            enqueued_clear_generation = existing.clear_generation
        elif is_stale_clear_generation(existing.clear_generation, captured_clear_generation) and self._consume_pre_clear_feed(existing):
            enqueued_clear_generation = captured_clear_generation
        else:
            enqueued_clear_generation = existing.clear_generation
        context = ConversationContext(
            thread_id=thread_id,
            messages=messages,
            agent_name=agent_name,
            user_id=user_id,
            trace_id=trace_id,
            signals=merged_signals,
            bypass_watermark=bypass_watermark,
            clear_generation=enqueued_clear_generation,
        )
        if existing is not None:
            self._items = [c for c in self._items if not (queue_key(c.thread_id, c.user_id, c.agent_name) == key and c.bypass_watermark == bypass_watermark)]
        self._items.append(context)
        return context

    def _capture_clear_generation(self, agent_name: str | None, user_id: str | None) -> tuple[int, int]:
        """Read the current scope fence without loading fact files.

        Callers must invoke this before acquiring ``self._lock``. Missing or
        invalid updater peeks default to ``(0, 0)`` so a later clear still
        looks newer and the write is dropped.
        """
        peek = getattr(self._updater, "peek_clear_generation", None)
        if not callable(peek):
            return (0, 0)
        try:
            value = peek(agent_name, user_id=user_id)
        except Exception:
            logger.warning("Failed to capture clear generation at enqueue; defaulting to (0, 0)", exc_info=True)
            return (0, 0)
        if not isinstance(value, tuple) or len(value) != 2:
            return (0, 0)
        user_gen, agent_gen = value
        if isinstance(user_gen, bool) or isinstance(agent_gen, bool) or not isinstance(user_gen, int) or not isinstance(agent_gen, int) or user_gen < 0 or agent_gen < 0:
            return (0, 0)
        return user_gen, agent_gen

    def _consume_pre_clear_feed(self, existing: ConversationContext) -> bool:
        """Mark the stale job's snapshot consumed so it cannot restore after a clear.

        Returns False when the updater cannot advance the watermark. The caller
        must then keep the earlier fence rather than refresh the token.
        """
        mark = getattr(self._updater, "mark_feed_consumed", None)
        if not callable(mark):
            return False
        try:
            mark(
                existing.messages,
                thread_id=existing.thread_id,
                user_id=existing.user_id,
                agent_name=existing.agent_name,
                bypass_watermark=existing.bypass_watermark,
            )
        except Exception:
            logger.warning("Failed to consume the pre-clear snapshot after a newer clear; keeping the stale fence", exc_info=True)
            return False
        return True

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

            if not self._items:
                return

            self._processing = True
            self._processing_thread = threading.current_thread()
            contexts_to_process = self._items
            self._items = []
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
                        signals=context.signals,
                        user_id=context.user_id,
                        trace_id=context.trace_id,
                        bypass_watermark=context.bypass_watermark,
                        expected_clear_generation=context.clear_generation,
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
                # Reschedule inside the lock: ``_schedule_timer`` read-cancels-
                # reassigns ``self._timer`` non-atomically, and a concurrent
                # ``add``'s ``_reset_timer`` (also under the lock) touches the
                # same field. Holding the lock makes the reschedule atomic w.r.t.
                # ``add``. ``_schedule_timer`` only calls ``Timer.start()`` (no
                # synchronous lock acquisition), so this cannot deadlock.
                if self._reprocess_pending:
                    self._reprocess_pending = False
                    if self._items:
                        # New work arrived mid-processing: re-run immediately.
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
        # that exit will kill - losing the contexts it already pulled out.
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

    def cancel_by_agent(
        self,
        agent_name: str | None = None,
        *,
        user_id: str | None = None,
        all_agents: bool = False,
    ) -> int:
        """Drop pending contexts for a scope without processing them.

        Matches ``(agent_name, user_id)`` against items still sitting in
        ``_items``. Dropped snapshots still advance the conversation watermark
        so a later turn cannot restore those pre-clear messages against a
        newer generation. Contexts already pulled out by an in-flight
        :meth:`_process_queue` worker are deliberately left alone -- interrupting
        mid-LLM-call belongs to the durable clear-generation fence, not this
        in-memory debounce queue.

        Args:
            agent_name: Canonical agent bucket to cancel. Ignored when
                ``all_agents`` is True.
            user_id: When set, only that user's pending contexts are eligible.
                When omitted, only the legacy ``user_id is None`` root is
                cancelled (mirrors storage), whether ``all_agents`` is set or not.
            all_agents: When True, ignore ``agent_name`` and cancel every agent
                bucket in the matched user scope (used by ``clear_memory`` with
                ``agent_name=None``).

        Returns:
            Number of pending contexts removed.
        """
        with self._lock:
            before = len(self._items)

            def _keep(context: ConversationContext) -> bool:
                # Scope matches storage: user_id=None is the legacy no-user root
                # only (None == None), never "every user".
                if not all_agents and context.agent_name != agent_name:
                    return True
                return context.user_id != user_id

            dropped = [context for context in self._items if not _keep(context)]
            self._items = [context for context in self._items if _keep(context)]
            removed = before - len(self._items)
            if removed and not self._items and self._timer is not None:
                self._timer.cancel()
                self._timer = None
            # Consume under the lock so a concurrent add cannot re-feed the
            # dropped snapshot before the watermark advances.
            for context in dropped:
                self._consume_pre_clear_feed(context)
            return removed

    def clear(self) -> None:
        """Clear the queue without processing.

        This is useful for testing.
        """
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._items = []
            self._processing = False
            self._processing_thread = None
            self._reprocess_pending = False

    @property
    def pending_count(self) -> int:
        """Get the number of pending updates."""
        with self._lock:
            return len(self._items)

    @property
    def is_processing(self) -> bool:
        """Check if the queue is currently being processed."""
        with self._lock:
            return self._processing
