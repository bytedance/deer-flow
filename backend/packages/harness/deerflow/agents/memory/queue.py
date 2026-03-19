"""内存 更新 queue with debounce mechanism."""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from deerflow.config.memory_config import get_memory_config


@dataclass
class ConversationContext:
    """Context for a conversation to be processed for 内存 更新."""

    thread_id: str
    messages: list[Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    agent_name: str | None = None


class MemoryUpdateQueue:
    """Queue for 内存 updates with debounce mechanism.

    This queue collects conversation contexts and processes them after
    a configurable debounce period. Multiple conversations received within
    the debounce window are batched together.
    """

    def __init__(self):
        """Initialize the 内存 更新 queue."""
        self._queue: list[ConversationContext] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._processing = False

    def add(self, thread_id: str, messages: list[Any], agent_name: str | None = None) -> None:
        """Add a conversation to the 更新 queue.

        Args:
            thread_id: The 线程 ID.
            messages: The conversation messages.
            agent_name: If provided, 内存 is stored per-代理. If None, uses global 内存.
        """
        config = get_memory_config()
        if not config.enabled:
            return

        context = ConversationContext(
            thread_id=thread_id,
            messages=messages,
            agent_name=agent_name,
        )

        with self._lock:
            #    Check 如果 this 线程 already has a 待处理 更新


            #    If so, replace it with the newer one


            self._queue = [c for c in self._queue if c.thread_id != thread_id]
            self._queue.append(context)

            #    Reset or 开始 the debounce timer


            self._reset_timer()

        print(f"Memory update queued for thread {thread_id}, queue size: {len(self._queue)}")

    def _reset_timer(self) -> None:
        """Reset the debounce timer."""
        config = get_memory_config()

        #    Cancel existing timer 如果 any


        if self._timer is not None:
            self._timer.cancel()

        #    Start 新建 timer


        self._timer = threading.Timer(
            config.debounce_seconds,
            self._process_queue,
        )
        self._timer.daemon = True
        self._timer.start()

        print(f"Memory update timer set for {config.debounce_seconds}s")

    def _process_queue(self) -> None:
        """Process all queued conversation contexts."""
        #    Import here to avoid circular dependency


        from deerflow.agents.memory.updater import MemoryUpdater

        with self._lock:
            if self._processing:
                #    Already processing, reschedule


                self._reset_timer()
                return

            if not self._queue:
                return

            self._processing = True
            contexts_to_process = self._queue.copy()
            self._queue.clear()
            self._timer = None

        print(f"Processing {len(contexts_to_process)} queued memory updates")

        try:
            updater = MemoryUpdater()

            for context in contexts_to_process:
                try:
                    print(f"Updating memory for thread {context.thread_id}")
                    success = updater.update_memory(
                        messages=context.messages,
                        thread_id=context.thread_id,
                        agent_name=context.agent_name,
                    )
                    if success:
                        print(f"Memory updated successfully for thread {context.thread_id}")
                    else:
                        print(f"Memory update skipped/failed for thread {context.thread_id}")
                except Exception as e:
                    print(f"Error updating memory for thread {context.thread_id}: {e}")

                #    Small delay between updates to avoid rate limiting


                if len(contexts_to_process) > 1:
                    time.sleep(0.5)

        finally:
            with self._lock:
                self._processing = False

    def flush(self) -> None:
        """Force immediate processing of the queue.

        This is useful for testing or graceful shutdown.
        """
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

        self._process_queue()

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

    @property
    def pending_count(self) -> int:
        """Get the 数字 of 待处理 updates."""
        with self._lock:
            return len(self._queue)

    @property
    def is_processing(self) -> bool:
        """Check if the queue is currently being processed."""
        with self._lock:
            return self._processing


#    Global singleton instance


_memory_queue: MemoryUpdateQueue | None = None
_queue_lock = threading.Lock()


def get_memory_queue() -> MemoryUpdateQueue:
    """Get the global 内存 更新 queue singleton.

    Returns:
        The 内存 更新 queue instance.
    """
    global _memory_queue
    with _queue_lock:
        if _memory_queue is None:
            _memory_queue = MemoryUpdateQueue()
        return _memory_queue


def reset_memory_queue() -> None:
    """Reset the global 内存 queue.

    This is useful for testing.
    """
    global _memory_queue
    with _queue_lock:
        if _memory_queue is not None:
            _memory_queue.clear()
        _memory_queue = None
