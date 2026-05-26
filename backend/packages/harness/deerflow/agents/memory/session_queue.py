"""Session memory update queue with debounce mechanism."""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from deerflow.config.session_memory_config import get_session_memory_config

logger = logging.getLogger(__name__)


@dataclass
class SessionConversationContext:
    """Context for a conversation to be processed for session memory update."""

    thread_id: str
    messages: list[Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    user_id: str | None = None
    correction_detected: bool = False
    reinforcement_detected: bool = False


class SessionMemoryUpdateQueue:
    """Queue for session memory updates with debounce mechanism.

    This queue collects conversation contexts and processes them after
    a configurable debounce period. Multiple conversations received within
    the debounce window are batched together.
    """

    def __init__(self):
        """Initialize the session memory update queue."""
        self._queue: list[SessionConversationContext] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._processing = False

    def add(
        self,
        thread_id: str,
        messages: list[Any],
        user_id: str | None = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
    ) -> None:
        """Add a conversation to the session memory update queue.

        Args:
            thread_id: The thread ID.
            messages: The conversation messages.
            user_id: The user ID captured at enqueue time.
            correction_detected: Whether recent turns include an explicit correction signal.
            reinforcement_detected: Whether recent turns include a positive reinforcement signal.
        """
        config = get_session_memory_config()
        if not config.enabled:
            return

        with self._lock:
            self._enqueue_locked(
                thread_id=thread_id,
                messages=messages,
                user_id=user_id,
                correction_detected=correction_detected,
                reinforcement_detected=reinforcement_detected,
            )
            self._reset_timer()

        logger.info("Session memory update queued for thread %s, queue size: %d", thread_id, len(self._queue))

    def _enqueue_locked(
        self,
        *,
        thread_id: str,
        messages: list[Any],
        user_id: str | None,
        correction_detected: bool,
        reinforcement_detected: bool,
    ) -> None:
        existing_context = next(
            (context for context in self._queue if context.thread_id == thread_id),
            None,
        )
        merged_correction_detected = correction_detected or (existing_context.correction_detected if existing_context is not None else False)
        merged_reinforcement_detected = reinforcement_detected or (existing_context.reinforcement_detected if existing_context is not None else False)
        context = SessionConversationContext(
            thread_id=thread_id,
            messages=messages,
            user_id=user_id,
            correction_detected=merged_correction_detected,
            reinforcement_detected=merged_reinforcement_detected,
        )

        self._queue = [c for c in self._queue if c.thread_id != thread_id]
        self._queue.append(context)

    def _reset_timer(self) -> None:
        """Reset the debounce timer."""
        config = get_session_memory_config()
        self._schedule_timer(config.debounce_seconds)

        logger.debug("Session memory update timer set for %ss", config.debounce_seconds)

    def _schedule_timer(self, delay_seconds: float) -> None:
        """Schedule queue processing after the provided delay."""
        if self._timer is not None:
            self._timer.cancel()

        self._timer = threading.Timer(
            delay_seconds,
            self._process_queue,
        )
        self._timer.daemon = True
        self._timer.start()

    def _process_queue(self) -> None:
        """Process all queued session conversation contexts."""
        from deerflow.agents.memory.updater import update_session_from_conversation

        with self._lock:
            if self._processing:
                self._schedule_timer(0)
                return

            if not self._queue:
                return

            self._processing = True
            contexts_to_process = self._queue.copy()
            self._queue.clear()
            self._timer = None

        logger.info("Processing %d queued session memory updates", len(contexts_to_process))

        try:
            for context in contexts_to_process:
                try:
                    logger.info("Updating session memory for thread %s", context.thread_id)
                    success = update_session_from_conversation(
                        messages=context.messages,
                        thread_id=context.thread_id,
                        correction_detected=context.correction_detected,
                        reinforcement_detected=context.reinforcement_detected,
                        user_id=context.user_id,
                    )
                    if success:
                        logger.info("Session memory updated successfully for thread %s", context.thread_id)
                    else:
                        logger.warning("Session memory update skipped/failed for thread %s", context.thread_id)
                except Exception as e:
                    logger.error("Error updating session memory for thread %s: %s", context.thread_id, e)

                if len(contexts_to_process) > 1:
                    time.sleep(0.5)

        finally:
            with self._lock:
                self._processing = False

    def flush(self) -> None:
        """Force immediate processing of the queue."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

        self._process_queue()

    def clear(self) -> None:
        """Clear the queue without processing."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._queue.clear()
            self._processing = False

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


# Global singleton instance
_session_memory_queue: SessionMemoryUpdateQueue | None = None
_session_queue_lock = threading.Lock()


def get_session_memory_queue() -> SessionMemoryUpdateQueue:
    """Get the global session memory update queue singleton."""
    global _session_memory_queue
    with _session_queue_lock:
        if _session_memory_queue is None:
            _session_memory_queue = SessionMemoryUpdateQueue()
        return _session_memory_queue


def reset_session_memory_queue() -> None:
    """Reset the global session memory queue."""
    global _session_memory_queue
    with _session_queue_lock:
        if _session_memory_queue is not None:
            _session_memory_queue.clear()
        _session_memory_queue = None
