"""澄清中间件 - 拦截澄清请求并向用户展示

===================
设计思路说明
===================

**核心职责**：
拦截ask_clarification工具调用，中断执行并向用户展示澄清问题：
1. 检测ask_clarification工具调用
2. 提取澄清问题和元数据
3. 格式化为用户友好的消息
4. 中断执行并展示问题
5. 等待用户响应后继续

**为什么需要这个中间件**：
1. **用户交互**：代理需要在执行前向用户确认某些信息
2. **执行控制**：暂停代理执行，等待用户输入
3. **消息格式化**：将工具参数转换为易读的展示格式
4. **状态管理**：确保中断后可以正确恢复

**设计决策**：
- 使用Command中断：通过goto=END暂停执行
- 工具消息记录：将格式化的问题作为ToolMessage添加到历史
- 不添加额外AIMessage：前端直接检测和展示ask_clarification消息
- 类型图标：使用emoji增强可读性

**架构说明**：
- 实现AgentMiddleware接口
- 拦截wrap_tool_call/awrap_tool_call
- 非ask_clarification调用正常传递
- 同步和异步版本都支持
"""

import logging
from collections.abc import Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)


class ClarificationMiddlewareState(AgentState):
    """与ThreadState模式兼容

    为什么需要这个类：
    - 提供类型提示
    - 确保与ThreadState兼容
    - 便于未来扩展
    """

    pass


class ClarificationMiddleware(AgentMiddleware[ClarificationMiddlewareState]):
    """拦截ask_clarification工具调用并中断执行以向用户展示问题

    当模型调用ask_clarification工具时，此中间件：
    1. 在执行前拦截工具调用
    2. 提取澄清问题和元数据
    3. 格式化为用户友好的消息
    4. 返回中断执行并展示问题的Command
    5. 在继续前等待用户响应

    这替代了基于工具的方法，其中澄清会继续对话流程

    设计优势：
    - 更好的用户体验：问题格式化展示
    - 明确的中断：用户知道需要响应
    - 消息历史保留：澄清记录在对话中
    - 类型支持：不同类型的澄清有不同图标
    """

    state_schema = ClarificationMiddlewareState

    def _is_chinese(self, text: str) -> bool:
        """检查文本是否包含中文字符

        为什么需要这个函数：
        - 支持多语言界面
        - 自动检测用户语言
        - 未来可能用于格式化调整

        Args:
            text: 要检查的文本

        Returns:
            如果文本包含中文字符则返回True
        """
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _format_clarification_message(self, args: dict) -> str:
        """将澄清参数格式化为用户友好的消息

        设计考虑：
        - 类型图标：不同澄清类型使用不同emoji
        - 上下文优先：如果有上下文，先展示背景
        - 选项编号：清晰列出可选项
        - 自然格式：多行显示，易于阅读

        Args:
            args: 包含澄清详情的工具调用参数

        Returns:
            格式化的消息字符串
        """
        question = args.get("question", "")
        clarification_type = args.get("clarification_type", "missing_info")
        context = args.get("context")
        options = args.get("options", [])

        # 类型特定图标
        type_icons = {
            "missing_info": "❓",
            "ambiguous_requirement": "🤔",
            "approach_choice": "🔀",
            "risk_confirmation": "⚠️",
            "suggestion": "💡",
        }

        icon = type_icons.get(clarification_type, "❓")

        # 自然构建消息
        message_parts = []

        # 将图标和问题放在一起以获得更自然的流程
        if context:
            # 如果有上下文，先将其作为背景展示
            message_parts.append(f"{icon} {context}")
            message_parts.append(f"\n{question}")
        else:
            # 只有问题带图标
            message_parts.append(f"{icon} {question}")

        # 以更清晰的格式添加选项
        if options and len(options) > 0:
            message_parts.append("")  # 空行用于间距
            for i, option in enumerate(options, 1):
                message_parts.append(f"  {i}. {option}")

        return "\n".join(message_parts)

    def _handle_clarification(self, request: ToolCallRequest) -> Command:
        """处理澄清请求并返回中断执行的命令

        工作流程：
        1. 提取澄清参数
        2. 格式化澄清消息
        3. 创建ToolMessage记录
        4. 返回中断Command

        Args:
            request: 工具调用请求

        Returns:
            中断执行并带有格式化澄清消息的Command
        """
        # 提取澄清参数
        args = request.tool_call.get("args", {})
        question = args.get("question", "")

        logger.info("Intercepted clarification request")
        logger.debug("Clarification question: %s", question)

        # 格式化澄清消息
        formatted_message = self._format_clarification_message(args)

        # 获取工具调用ID
        tool_call_id = request.tool_call.get("id", "")

        # 创建带有格式化问题的ToolMessage
        # 这将被添加到消息历史中
        tool_message = ToolMessage(
            content=formatted_message,
            tool_call_id=tool_call_id,
            name="ask_clarification",
        )

        # 返回一个Command：
        # 1. 添加格式化的工具消息
        # 2. 通过转到__end__中断执行
        # 注意：我们不在这里添加额外的AIMessage - 前端将直接
        # 检测和展示ask_clarification工具消息
        return Command(
            update={"messages": [tool_message]},
            goto=END,
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """拦截ask_clarification工具调用并中断执行（同步版本）

        设计考虑：
        - 只拦截ask_clarification：其他工具正常执行
        - 早期返回：避免不必要的处理
        - 传递handler：非拦截调用正常传递

        Args:
            request: 工具调用请求
            handler: 原始工具执行处理程序

        Returns:
            中断执行并带有格式化澄清消息的Command
        """
        # 检查这是否是ask_clarification工具调用
        if request.tool_call.get("name") != "ask_clarification":
            # 不是澄清调用，正常执行
            return handler(request)

        return self._handle_clarification(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """拦截ask_clarification工具调用并中断执行（异步版本）

        Args:
            request: 工具调用请求
            handler: 原始工具执行处理程序（异步）

        Returns:
            中断执行并带有格式化澄清消息的Command
        """
        # 检查这是否是ask_clarification工具调用
        if request.tool_call.get("name") != "ask_clarification":
            # 不是澄清调用，正常执行
            return await handler(request)

        return self._handle_clarification(request)
