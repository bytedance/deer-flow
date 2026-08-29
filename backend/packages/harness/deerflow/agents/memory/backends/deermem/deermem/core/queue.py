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

if TYPE_CHECKING:
    from .updater import MemoryUpdater

logger = logging.getLogger(__name__)

# Keep wildcard identity distinct from the real unscoped value.
_ANY = object()


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
    agent_incarnation: str | None = None
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
    # Scope generation epoch stamped at enqueue time. Invariant:
    #
    #   A queued memory update may run only if no newer cancellation epoch
    #   covers its scope.
    #
    # ``cancel_by_agent`` / ``cancel_by_user`` assign the scope's next
    # cancellation epoch, so work snapshotted by a worker before the cancel
    # carries an older epoch and is dropped at processing time — even across
    # delete -> recreate-same-name -> fresh enqueue (#3364/#5037). Fresh
    # enqueues stamp the current epoch naturally; cancelled work cannot be
    # resurrected by newer work on the same scope.
    generation: int = 0


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
        # Per-scope cancellation epochs use ``_ANY`` as the wildcard.
        # ``None`` remains a real legacy or unscoped value.
        # Every cancel assigns the next value of one process-wide clock to its
        # scope key, so epochs stay comparable through
        # ``_generation_for_locked``'s max(): a later user-wide cancel always
        # outdates earlier exact-key work for that user (#5037 round 3).
        # Entries only appear for scopes actually cancelled — small tuples +
        # ints, bounded by distinct deleted/cleared scopes per process lifetime.
        self._generation_clock = 0
        self._scope_generations: dict[tuple[object, object], int] = {}

    def add(
        self,
        thread_id: str,
        messages: list[Any],
        agent_name: str | None = None,
        agent_incarnation: str | None = None,
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
        with self._lock:
            self._enqueue_locked(
                thread_id=thread_id,
                messages=messages,
                agent_name=agent_name,
                agent_incarnation=agent_incarnation,
                user_id=user_id,
                trace_id=trace_id,
                signals=frozenset(signals) if signals else frozenset(),
                bypass_watermark=False,
            )
            self._reset_timer()

        logger.info("Memory update queued for thread %s, queue size: %d", thread_id, len(self._items))

    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        agent_name: str | None = None,
        agent_incarnation: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
        signals: frozenset[str] | None = None,
    ) -> None:
        """Add a conversation and start processing immediately in the background."""
        with self._lock:
            self._enqueue_locked(
                thread_id=thread_id,
                messages=messages,
                agent_name=agent_name,
                agent_incarnation=agent_incarnation,
                user_id=user_id,
                trace_id=trace_id,
                signals=frozenset(signals) if signals else frozenset(),
                bypass_watermark=True,
            )
            self._schedule_timer(0)

        logger.info("Memory update queued for immediate processing on thread %s, queue size: %d", thread_id, len(self._items))

    def _enqueue_locked(
        self,
        *,
        thread_id: str,
        messages: list[Any],
        agent_name: str | None,
        agent_incarnation: str | None,
        user_id: str | None,
        trace_id: str | None,
        signals: frozenset[str],
        bypass_watermark: bool = False,
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
        context = ConversationContext(
            thread_id=thread_id,
            messages=messages,
            agent_name=agent_name,
            agent_incarnation=agent_incarnation,
            user_id=user_id,
            trace_id=trace_id,
            signals=merged_signals,
            bypass_watermark=bypass_watermark,
            generation=self._generation_for_locked(agent_name, user_id),
        )
        if existing is not None:
            self._items = [c for c in self._items if not (queue_key(c.thread_id, c.user_id, c.agent_name) == key and c.bypass_watermark == bypass_watermark)]
        self._items.append(context)
        return context

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
        stale = 0
        try:
            for context in contexts_to_process:
                # The invariant on ``ConversationContext.generation``: drop the
                # context when a newer cancellation epoch covers its scope.
                # This happens for batch items snapshotted before a
                # cancel_by_agent/cancel_by_user ran; fresh enqueues carry the
                # current epoch, so recreated-scope work is safe.
                if context.generation != self._current_generation(context.agent_name, context.user_id):
                    stale += 1
                    logger.info("Skipping stale memory update for thread %s (agent=%s user=%s)", context.thread_id, context.agent_name, context.user_id)
                    continue
                try:
                    logger.info("Updating memory for thread %s (trace_id=%s)", context.thread_id, context.trace_id)
                    update_kwargs = {
                        "messages": context.messages,
                        "thread_id": context.thread_id,
                        "agent_name": context.agent_name,
                        "signals": context.signals,
                        "user_id": context.user_id,
                        "trace_id": context.trace_id,
                        "bypass_watermark": context.bypass_watermark,
                    }
                    if context.agent_incarnation is not None:
                        update_kwargs["agent_incarnation"] = context.agent_incarnation
                    success = self._updater.update_memory(**update_kwargs)
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
            if succeeded or failed or stale:
                logger.info("Memory update batch done: %d succeeded, %d failed, %d stale", succeeded, failed, stale)
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

    # Invariant: a queued memory update may run only if no newer cancellation
    # epoch covers its scope.

    def cancel_by_agent(self, agent_name: str, *, user_id: str | None = None) -> int:
        """Drop pending updates for one agent scope; return the removed count.

        Agent deletion and scoped memory clearing call this so a debounce Timer
        can no longer fire an extraction LLM call for a scope that no longer
        exists (#3364): the extraction would re-persist state that blocks
        recreating an agent with the same name. ``user_id=None`` selects the
        legacy unscoped user. A specific ID selects that owner's entries.

        Pending removal alone cannot stop a worker that already snapshotted its
        batch into ``_process_queue`` (the cancel would see an empty ``_items``
        while the LLM calls still go out), so this also assigns the scope its
        next cancellation epoch: every context stamped before the new epoch is
        stale at processing time, while enqueues after it — including a
        recreated agent's fresh turns — carry the current epoch and run
        normally (#5037).
        """
        with self._lock:
            self._next_cancellation_epoch_locked((agent_name, user_id))
            remaining = [context for context in self._items if not (context.agent_name == agent_name and context.user_id == user_id)]
            removed = len(self._items) - len(remaining)
            self._items = remaining
        if removed:
            logger.info("Cancelled %d pending memory update(s) for agent %s (user_id=%s)", removed, agent_name, user_id)
        return removed

    def cancel_by_user(self, user_id: str | None = None) -> int:
        """Drop every pending update owned by the exact ``user_id``.

        Backs global ``clear_memory(user_id=...)``: it removes all agents'
        stored facts, so buffered extractions for any of those agents must be
        dropped too — not just the reserved default bucket (#5037 Finding 2).
        """
        with self._lock:
            self._next_cancellation_epoch_locked((_ANY, user_id))
            remaining = [context for context in self._items if context.user_id != user_id]
            removed = len(self._items) - len(remaining)
            self._items = remaining
        if removed:
            logger.info("Cancelled %d pending memory update(s) for user %s", removed, user_id)
        return removed

    def _current_generation(self, agent_name: str | None, user_id: str | None) -> int:
        """Effective generation for ``(agent_name, user_id)`` right now."""
        with self._lock:
            return self._generation_for_locked(agent_name, user_id)

    def _generation_for_locked(self, agent_name: str | None, user_id: str | None) -> int:
        """Current generation epoch for ``(agent_name, user_id)``; lock held.

        The effective epoch is the max over the exact key and any wildcard
        that covers it. Epochs come from one shared clock, so they are
        globally comparable — a later broader cancel always outdates earlier
        narrower work.
        """
        candidates = ((agent_name, user_id), (agent_name, _ANY), (_ANY, user_id), (_ANY, _ANY))
        return max(self._scope_generations.get(key, 0) for key in candidates)

    def _next_cancellation_epoch_locked(self, key: tuple[object, object]) -> None:
        """Assign the next process-wide cancellation epoch to ``key``; lock held."""
        self._generation_clock += 1
        self._scope_generations[key] = self._generation_clock

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
