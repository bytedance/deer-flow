"""带防抖机制的记忆更新队列

===================
设计思路说明
===================

**为什么需要记忆更新队列**：
1. **性能优化**：避免频繁的LLM调用，通过批量处理降低成本
2. **防抖机制**：在短时间内多次更新时，只处理最后一次
3. **异步处理**：不阻塞主流程，在后台处理记忆更新
4. **线程安全**：使用锁保护共享状态

**核心设计模式**：
- 单例模式：全局唯一的队列实例
- 防抖模式：延迟处理，合并多次更新
- 生产者-消费者模式：添加更新和处理更新分离

**为什么使用防抖机制**：
- **成本控制**：减少LLM API调用次数
- **效率提升**：批量处理比单次处理更高效
- **用户体验**：不阻塞对话响应

**设计权衡**：
- **实时性 vs 成本**：延迟处理降低成本但牺牲实时性
- **批量大小**：防抖窗口越长，批量越大，但延迟越高
- **线程安全**：使用锁保护，确保并发安全
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from deerflow.config.memory_config import get_memory_config

logger = logging.getLogger(__name__)


@dataclass
class ConversationContext:
    """等待记忆更新处理的对话上下文

    **为什么需要这个数据类**：
    - **数据封装**：将对话相关数据打包在一起
    - **类型安全**：使用dataclass提供类型提示
    - **不可变性**：时间戳自动生成，避免手动设置

    **字段说明**：
        thread_id: 对话线程ID
        messages: 对话消息列表
        timestamp: 上下文创建时间（UTC）
        agent_name: 可选的代理名称，用于per-agent记忆
    """

    thread_id: str
    messages: list[Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    agent_name: str | None = None


class MemoryUpdateQueue:
    """带防抖机制的记忆更新队列

    **为什么需要这个类**：
    - **批量处理**：收集多个对话上下文，批量更新记忆
    - **防抖优化**：在防抖窗口内的多次更新会被合并
    - **成本节约**：减少LLM API调用次数
    - **异步执行**：不阻塞主对话流程

    **工作原理**：
    1. 对话上下文添加到队列
    2. 重置/启动防抖定时器
    3. 定时器到期后批量处理队列
    4. 同一线程的新上下文替换旧的

    **为什么使用线程锁**：
    - 保护共享状态（队列、定时器）
    - 确保并发安全
    - 防止竞态条件
    """

    def __init__(self):
        """初始化记忆更新队列

        **为什么使用这些字段**：
        - _queue: 存储待处理的对话上下文
        - _lock: 保护共享状态的线程锁
        - _timer: 防抖定时器
        - _processing: 处理状态标志，防止重入
        """
        self._queue: list[ConversationContext] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._processing = False

    def add(self, thread_id: str, messages: list[Any], agent_name: str | None = None) -> None:
        """添加对话到更新队列

        **为什么需要这个方法**：
        - **队列管理**：将对话上下文添加到处理队列
        - **去重优化**：同一线程的新上下文替换旧的
        - **防抖重置**：重新启动防抖定时器

        **参数说明**：
            thread_id: 对话线程ID
            messages: 对话消息列表
            agent_name: 如果提供，存储per-agent记忆；如果为None，使用全局记忆
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
            # Check if this thread already has a pending update
            # If so, replace it with the newer one
            self._queue = [c for c in self._queue if c.thread_id != thread_id]
            self._queue.append(context)

            # Reset or start the debounce timer
            self._reset_timer()

        logger.info("Memory update queued for thread %s, queue size: %d", thread_id, len(self._queue))

    def _reset_timer(self) -> None:
        """Reset the debounce timer."""
        config = get_memory_config()

        # Cancel existing timer if any
        if self._timer is not None:
            self._timer.cancel()

        # Start new timer
        self._timer = threading.Timer(
            config.debounce_seconds,
            self._process_queue,
        )
        self._timer.daemon = True
        self._timer.start()

        logger.debug("Memory update timer set for %ss", config.debounce_seconds)

    def _process_queue(self) -> None:
        """Process all queued conversation contexts."""
        # Import here to avoid circular dependency
        from deerflow.agents.memory.updater import MemoryUpdater

        with self._lock:
            if self._processing:
                # Already processing, reschedule
                self._reset_timer()
                return

            if not self._queue:
                return

            self._processing = True
            contexts_to_process = self._queue.copy()
            self._queue.clear()
            self._timer = None

        logger.info("Processing %d queued memory updates", len(contexts_to_process))

        try:
            updater = MemoryUpdater()

            for context in contexts_to_process:
                try:
                    logger.info("Updating memory for thread %s", context.thread_id)
                    success = updater.update_memory(
                        messages=context.messages,
                        thread_id=context.thread_id,
                        agent_name=context.agent_name,
                    )
                    if success:
                        logger.info("Memory updated successfully for thread %s", context.thread_id)
                    else:
                        logger.warning("Memory update skipped/failed for thread %s", context.thread_id)
                except Exception as e:
                    logger.error("Error updating memory for thread %s: %s", context.thread_id, e)

                # Small delay between updates to avoid rate limiting
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
        """Get the number of pending updates."""
        with self._lock:
            return len(self._queue)

    @property
    def is_processing(self) -> bool:
        """Check if the queue is currently being processed."""
        with self._lock:
            return self._processing


# Global singleton instance
_memory_queue: MemoryUpdateQueue | None = None
_queue_lock = threading.Lock()


def get_memory_queue() -> MemoryUpdateQueue:
    """Get the global memory update queue singleton.

    Returns:
        The memory update queue instance.
    """
    global _memory_queue
    with _queue_lock:
        if _memory_queue is None:
            _memory_queue = MemoryUpdateQueue()
        return _memory_queue


def reset_memory_queue() -> None:
    """Reset the global memory queue.

    This is useful for testing.
    """
    global _memory_queue
    with _queue_lock:
        if _memory_queue is not None:
            _memory_queue.clear()
        _memory_queue = None
