"""Domain memory update queue with debounce mechanism."""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from deerflow.config.domain_memory_config import get_domain_memory_config

logger = logging.getLogger(__name__)


@dataclass
class DomainConversationContext:
    """Context for a conversation to be processed for domain memory extraction."""

    thread_id: str
    messages: list[Any]
    tenant_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    user_id: str | None = None


class DomainMemoryUpdateQueue:
    """Queue for domain memory updates with debounce mechanism.

    This queue collects conversation contexts and processes them after
    a configurable debounce period. Multiple conversations received within
    the debounce window are batched together.
    """

    def __init__(self):
        """Initialize the domain memory update queue."""
        self._queue: list[DomainConversationContext] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._processing = False

    def add(
        self,
        thread_id: str,
        messages: list[Any],
        tenant_id: str,
        user_id: str | None = None,
    ) -> None:
        """Add a conversation to the domain memory update queue.

        Args:
            thread_id: The thread ID.
            messages: The conversation messages.
            tenant_id: The tenant ID for fact storage.
            user_id: The user ID captured at enqueue time.
        """
        config = get_domain_memory_config()
        if not config.enabled:
            return

        with self._lock:
            existing_context = next(
                (context for context in self._queue if context.thread_id == thread_id),
                None,
            )
            context = DomainConversationContext(
                thread_id=thread_id,
                messages=messages,
                tenant_id=tenant_id,
                user_id=user_id,
            )

            self._queue = [c for c in self._queue if c.thread_id != thread_id]
            self._queue.append(context)
            self._reset_timer()

        logger.info("Domain memory update queued for thread %s, queue size: %d", thread_id, len(self._queue))

    def _reset_timer(self) -> None:
        """Reset the debounce timer."""
        config = get_domain_memory_config()
        self._schedule_timer(config.debounce_seconds)

        logger.debug("Domain memory update timer set for %ss", config.debounce_seconds)

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
        """Process all queued domain conversation contexts."""
        from deerflow.agents.memory.updater import extract_domain_facts

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

        logger.info("Processing %d queued domain memory updates", len(contexts_to_process))

        try:
            for context in contexts_to_process:
                try:
                    logger.info("Extracting domain facts for thread %s", context.thread_id)
                    facts = extract_domain_facts(
                        messages=context.messages,
                        tenant_id=context.tenant_id,
                    )
                    if facts:
                        logger.info("Extracted %d domain facts for thread %s", len(facts), context.thread_id)
                    else:
                        logger.debug("No domain facts extracted for thread %s", context.thread_id)
                except Exception as e:
                    logger.error("Error extracting domain facts for thread %s: %s", context.thread_id, e)

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
_domain_memory_queue: DomainMemoryUpdateQueue | None = None
_domain_queue_lock = threading.Lock()


def get_domain_memory_queue() -> DomainMemoryUpdateQueue:
    """Get the global domain memory update queue singleton."""
    global _domain_memory_queue
    with _domain_queue_lock:
        if _domain_memory_queue is None:
            _domain_memory_queue = DomainMemoryUpdateQueue()
        return _domain_memory_queue


def reset_domain_memory_queue() -> None:
    """Reset the global domain memory queue."""
    global _domain_memory_queue
    with _domain_queue_lock:
        if _domain_memory_queue is not None:
            _domain_memory_queue.clear()
        _domain_memory_queue = None
