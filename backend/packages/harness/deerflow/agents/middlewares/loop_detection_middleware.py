"""循环检测中间件 - 检测并中断重复的工具调用循环

===================
设计思路说明
===================

**核心职责**：
P0安全防护：防止代理无限调用相同的工具直到递归限制杀死运行

**为什么需要这个中间件**：
1. **防止无限循环**：代理可能陷入重复调用同一工具的死循环
2. **节省资源**：避免浪费计算资源和token
3. **提升体验**：快速中断而非等待超时
4. **优雅恢复**：强制代理产生最终答案

**检测策略**：
1. 每次模型响应后，哈希工具调用（名称+参数）
2. 在滑动窗口中跟踪最近的哈希
3. 如果相同哈希出现≥warn_threshold次，注入"你正在重复—结束"系统消息（每个哈希一次）
4. 如果出现≥hard_limit次，从响应中删除所有tool_calls，强制代理产生最终文本答案

**设计决策**：
- 使用哈希检测：比字符串比较更高效
- 滑动窗口：只跟踪最近的N次调用
- 分级响应：先警告后强制停止
- 线程隔离：每个线程独立跟踪
- LRU驱逐：限制跟踪的线程数量

**架构说明**：
- 在after_model钩子中检查：模型响应后立即检测
- 使用MD5哈希：快速且冲突概率低
- 线程安全：使用锁保护共享状态
"""

import hashlib
import json
import logging
import threading
from collections import OrderedDict, defaultdict
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

# 默认值 — 可通过构造函数覆盖
_DEFAULT_WARN_THRESHOLD = 3  # 3次相同调用后注入警告
_DEFAULT_HARD_LIMIT = 5  # 5次相同调用后强制停止
_DEFAULT_WINDOW_SIZE = 20  # 跟踪最近N次工具调用
_DEFAULT_MAX_TRACKED_THREADS = 100  # LRU驱逐限制


def _hash_tool_calls(tool_calls: list[dict]) -> str:
    """计算一组工具调用的确定性哈希（名称+参数）

    为什么这样设计：
    - 顺序无关：相同的多组工具调用应始终产生相同的哈希，无论输入顺序如何
    - 确定性排序：按名称和参数排序确保排列组合产生相同的哈希
    - 使用MD5：快速且对于此用例冲突概率足够低

    Args:
        tool_calls: 工具调用列表

    Returns:
        12字符的十六进制哈希字符串
    """
    # 首先将每个工具调用规范化为最小（名称，参数）结构
    normalized: list[dict] = []
    for tc in tool_calls:
        normalized.append(
            {
                "name": tc.get("name", ""),
                "args": tc.get("args", {}),
            }
        )

    # 按名称和参数的确定性序列化排序，以便相同调用的排列产生相同的排序
    normalized.sort(
        key=lambda tc: (
            tc["name"],
            json.dumps(tc["args"], sort_keys=True, default=str),
        )
    )
    blob = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.md5(blob.encode()).hexdigest()[:12]


_WARNING_MSG = "[循环检测] 您正在重复相同的工具调用。请停止调用工具并立即产生最终答案。如果无法完成任务，请总结到目前为止完成的工作。"

_HARD_STOP_MSG = "[强制停止] 重复工具调用超过安全限制。将使用到目前为止收集的结果产生最终答案。"


class LoopDetectionMiddleware(AgentMiddleware[AgentState]):
    """检测并中断重复的工具调用循环

    设计考虑：
    - 渐进式响应：先警告后强制停止
    - 每线程跟踪：不同线程的循环独立检测
    - 滑动窗口：只考虑最近的调用历史
    - 单次警告：每个哈希只警告一次

    Args:
        warn_threshold: 注入警告消息前的相同工具调用集数量。默认：3
        hard_limit: 删除所有工具调用前的相同工具调用集数量。默认：5
        window_size: 跟踪调用的滑动窗口大小。默认：20
        max_tracked_threads: 在驱逐最少使用之前要跟踪的最大线程数。默认：100
    """

    def __init__(
        self,
        warn_threshold: int = _DEFAULT_WARN_THRESHOLD,
        hard_limit: int = _DEFAULT_HARD_LIMIT,
        window_size: int = _DEFAULT_WINDOW_SIZE,
        max_tracked_threads: int = _DEFAULT_MAX_TRACKED_THREADS,
    ):
        super().__init__()
        self.warn_threshold = warn_threshold
        self.hard_limit = hard_limit
        self.window_size = window_size
        self.max_tracked_threads = max_tracked_threads
        self._lock = threading.Lock()
        # 使用OrderedDict进行每线程跟踪以实现LRU驱逐
        self._history: OrderedDict[str, list[str]] = OrderedDict()
        self._warned: dict[str, set[str]] = defaultdict(set)

    def _get_thread_id(self, runtime: Runtime) -> str:
        """从运行时上下文中提取thread_id以进行每线程跟踪

        为什么需要这个函数：
        - 支持per-thread隔离
        - 提供默认值作为后备
        - 便于日志记录

        Args:
            runtime: 运行时上下文

        Returns:
            线程ID字符串
        """
        thread_id = runtime.context.get("thread_id") if runtime.context else None
        if thread_id:
            return thread_id
        return "default"

    def _evict_if_needed(self) -> None:
        """如果超过限制，驱逐最少使用的线程

        为什么需要LRU驱逐：
        - 限制内存使用
        - 只跟踪活跃线程
        - 自动清理不活跃线程

        必须在持有self._lock时调用
        """
        while len(self._history) > self.max_tracked_threads:
            evicted_id, _ = self._history.popitem(last=False)
            self._warned.pop(evicted_id, None)
            logger.debug("Evicted loop tracking for thread %s (LRU)", evicted_id)

    def _track_and_check(self, state: AgentState, runtime: Runtime) -> tuple[str | None, bool]:
        """跟踪工具调用并检查循环

        工作流程：
        1. 检查最后一条消息是否是AI消息
        2. 提取工具调用并计算哈希
        3. 更新线程历史
        4. 检查计数并决定是否警告或停止

        Returns:
            (warning_message_or_none, should_hard_stop)
        """
        messages = state.get("messages", [])
        if not messages:
            return None, False

        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None, False

        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return None, False

        thread_id = self._get_thread_id(runtime)
        call_hash = _hash_tool_calls(tool_calls)

        with self._lock:
            # 触摸/创建条目（移动到末尾以进行LRU）
            if thread_id in self._history:
                self._history.move_to_end(thread_id)
            else:
                self._history[thread_id] = []
                self._evict_if_needed()

            history = self._history[thread_id]
            history.append(call_hash)
            if len(history) > self.window_size:
                history[:] = history[-self.window_size :]

            count = history.count(call_hash)
            tool_names = [tc.get("name", "?") for tc in tool_calls]

            if count >= self.hard_limit:
                logger.error(
                    "Loop hard limit reached — forcing stop",
                    extra={
                        "thread_id": thread_id,
                        "call_hash": call_hash,
                        "count": count,
                        "tools": tool_names,
                    },
                )
                return _HARD_STOP_MSG, True

            if count >= self.warn_threshold:
                warned = self._warned[thread_id]
                if call_hash not in warned:
                    warned.add(call_hash)
                    logger.warning(
                        "Repetitive tool calls detected — injecting warning",
                        extra={
                            "thread_id": thread_id,
                            "call_hash": call_hash,
                            "count": count,
                            "tools": tool_names,
                        },
                    )
                    return _WARNING_MSG, False
                # 已为此哈希注入警告 — 抑制
                return None, False

        return None, False

    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        """应用循环检测逻辑并返回状态更新

        处理策略：
        - 硬停止：删除tool_calls强制文本输出
        - 警告：注入HumanMessage避免系统消息错误
        - 无操作：未检测到循环

        为什么使用HumanMessage而非SystemMessage：
        - Anthropic要求系统消息只在对话开始时
        - 中间对话注入系统消息会崩溃langchain_anthropic
        - HumanMessage与所有提供商兼容

        Args:
            state: 当前代理状态
            runtime: 运行时上下文

        Returns:
            状态更新或None
        """
        warning, hard_stop = self._track_and_check(state, runtime)

        if hard_stop:
            # 从最后一条AIMessage中删除tool_calls以强制文本输出
            messages = state.get("messages", [])
            last_msg = messages[-1]
            stripped_msg = last_msg.model_copy(
                update={
                    "tool_calls": [],
                    "content": (last_msg.content or "") + f"\n\n{_HARD_STOP_MSG}",
                }
            )
            return {"messages": [stripped_msg]}

        if warning:
            # 注入为HumanMessage而非SystemMessage以避免
            # Anthropic的"多个非连续系统消息"错误
            # Anthropic模型要求系统消息只在对话开始时；
            # 在中间对话中注入一个会崩溃langchain_anthropic的_format_messages()
            # HumanMessage适用于所有提供商。参见#1299
            return {"messages": [HumanMessage(content=warning)]}

        return None

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        """模型响应后检查循环（同步版本）"""
        return self._apply(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        """模型响应后检查循环（异步版本）"""
        return self._apply(state, runtime)

    def reset(self, thread_id: str | None = None) -> None:
        """清除跟踪状态。如果给出thread_id，只清除该线程

        为什么需要重置功能：
        - 测试清理
        - 手动重置跟踪
        - 内存管理

        Args:
            thread_id: 如果提供，只重置特定线程
        """
        with self._lock:
            if thread_id:
                self._history.pop(thread_id, None)
                self._warned.pop(thread_id, None)
            else:
                self._history.clear()
                self._warned.clear()
