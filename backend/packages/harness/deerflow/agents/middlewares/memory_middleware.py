"""记忆中间件 - 在代理执行后将对话排队以进行记忆更新

===================
设计思路说明
===================

**核心职责**：
在每次代理执行后将对话排队进行记忆更新：
1. 过滤消息：只保留用户输入和最终助手响应
2. 排队更新：使用防抖批量处理多个更新
3. 异步处理：记忆更新通过LLM摘要异步进行

**为什么需要这个中间件**：
1. **自动记忆**：无需手动操作，对话自动记录到长期记忆
2. **智能过滤**：只保存有意义的对话，忽略工具调用细节
3. **性能优化**：防抖机制减少LLM调用次数
4. **会话隔离**：上传文件信息不持久化到长期记忆

**设计决策**：
- 在after_agent中排队：代理执行完成后触发
- 过滤工具消息：只保留用户输入和最终响应
- 移除上传块：上传文件是会话作用域的
- 使用队列：防抖批量处理更新

**架构说明**：
- MemoryQueue：管理待处理的记忆更新
- 防抖机制：短时间内的多次更新合并为一次
- LLM处理：使用LLM从对话中提取和更新记忆
- Per-agent支持：不同代理可以有独立的记忆
"""

import logging
import re
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

from deerflow.agents.memory.queue import get_memory_queue
from deerflow.config.memory_config import get_memory_config

logger = logging.getLogger(__name__)


class MemoryMiddlewareState(AgentState):
    """与ThreadState模式兼容

    为什么需要这个类：
    - 提供类型提示
    - 确保与ThreadState兼容
    """
    pass


def _filter_messages_for_memory(messages: list[Any]) -> list[Any]:
    """过滤消息以只保留用户输入和最终助手响应

    过滤规则：
    - 删除工具消息（中间工具调用结果）
    - 删除带有tool_calls的AI消息（中间步骤，非最终响应）
    - 删除人类消息中由UploadsMiddleware注入的<uploaded_files>块
      （文件路径是会话作用域的，绝不能持久化到长期记忆）
      用户的实际问题被保留；只有内容完全是上传块（去除后没有剩余）的轮次
      及其配对的助手响应被一起删除
    - 只保留人类消息（去除临时上传块）和没有tool_calls的AI消息（最终助手响应），
      除非配对的人类轮次仅是上传且没有真实用户文本

    为什么这样过滤：
    - 工具调用是临时的，不应影响长期记忆
    - 上传文件只在当前会话有效
    - 只需要记录用户意图和代理响应

    Args:
        messages: 所有对话消息的列表

    Returns:
        只包含用户输入和最终助手响应的过滤列表
    """
    _UPLOAD_BLOCK_RE = re.compile(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", re.IGNORECASE)

    filtered = []
    skip_next_ai = False
    for msg in messages:
        msg_type = getattr(msg, "type", None)

        if msg_type == "human":
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            content_str = str(content)
            if "<uploaded_files>" in content_str:
                # 删除临时上传块；保留用户的真实问题
                stripped = _UPLOAD_BLOCK_RE.sub("", content_str).strip()
                if not stripped:
                    # 没有剩余 — 整个轮次是上传记录；
                    # 跳过它和配对的助手响应
                    skip_next_ai = True
                    continue
                # 使用清理后的内容重建消息，以便用户的问题
                # 仍可用于记忆摘要
                from copy import copy

                clean_msg = copy(msg)
                clean_msg.content = stripped
                filtered.append(clean_msg)
                skip_next_ai = False
            else:
                filtered.append(msg)
                skip_next_ai = False
        elif msg_type == "ai":
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                if skip_next_ai:
                    skip_next_ai = False
                    continue
                filtered.append(msg)
        # 跳过工具消息和带有tool_calls的AI消息

    return filtered


class MemoryMiddleware(AgentMiddleware[MemoryMiddlewareState]):
    """在代理执行后将对话排队进行记忆更新的中间件

    工作流程：
    1. 每次代理执行后，将对话排队进行记忆更新
    2. 只包含用户输入和最终助手响应（忽略工具调用）
    3. 队列使用防抖批量处理多个更新
    4. 记忆通过LLM摘要异步更新

    设计优势：
    - 自动化：无需手动操作
    - 智能过滤：只记录有意义的对话
    - 性能优化：防抖减少LLM调用
    - 非阻塞：异步处理不影响主流程
    """

    state_schema = MemoryMiddlewareState

    def __init__(self, agent_name: str | None = None):
        """初始化MemoryMiddleware

        Args:
            agent_name: 如果提供，记忆存储为per-agent。如果为None，使用全局记忆
        """
        super().__init__()
        self._agent_name = agent_name

    @override
    def after_agent(self, state: MemoryMiddlewareState, runtime: Runtime) -> dict | None:
        """代理完成后将对话排队进行记忆更新

        处理步骤：
        1. 检查记忆配置是否启用
        2. 提取thread_id
        3. 过滤消息
        4. 验证有意义的对话
        5. 添加到更新队列

        Args:
            state: 当前代理状态
            runtime: 运行时上下文

        Returns:
            None（此中间件不需要状态更改）
        """
        config = get_memory_config()
        if not config.enabled:
            return None

        # 首先从运行时上下文获取thread_id，然后回退到LangGraph的configurable元数据
        thread_id = runtime.context.get("thread_id") if runtime.context else None
        if thread_id is None:
            config_data = get_config()
            thread_id = config_data.get("configurable", {}).get("thread_id")
        if not thread_id:
            logger.debug("No thread_id in context, skipping memory update")
            return None

        # 从状态获取消息
        messages = state.get("messages", [])
        if not messages:
            logger.debug("No messages in state, skipping memory update")
            return None

        # 过滤以只保留用户输入和最终助手响应
        filtered_messages = _filter_messages_for_memory(messages)

        # 只在有意义的对话时排队
        # 至少需要一个用户消息和一个助手响应
        user_messages = [m for m in filtered_messages if getattr(m, "type", None) == "human"]
        assistant_messages = [m for m in filtered_messages if getattr(m, "type", None) == "ai"]

        if not user_messages or not assistant_messages:
            return None

        # 将过滤后的对话排队进行记忆更新
        queue = get_memory_queue()
        queue.add(thread_id=thread_id, messages=filtered_messages, agent_name=self._agent_name)

        return None
