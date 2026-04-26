"""悬空工具调用修复中间件

===================
设计思路说明
===================

**核心职责**：
修复消息历史中的悬空工具调用，确保LLM接收格式正确的对话：
1. 检测AIMessage中的工具调用但没有对应ToolMessage的情况
2. 为悬空调用插入合成的ToolMessage（带错误指示）
3. 确保正确的消息顺序

**为什么需要这个中间件**：
1. **用户中断**：用户可能在工具执行前取消请求
2. **请求取消**：网络问题或其他原因导致请求中断
3. **格式要求**：LLM要求工具调用必须有对应的响应消息
4. **错误恢复**：自动修复格式错误，避免LLM报错

**设计决策**：
- 使用wrap_model_call：确保补丁插入在正确位置
- 错误指示：使用明确的错误消息标记中断的工具调用
- 最小侵入：只修复必要的问题，不改变其他消息
- 日志警告：记录修复操作便于调试

**架构说明**：
- 在模型调用前检查消息历史
- 为每个悬空调用插入合成ToolMessage
- 保持消息顺序：ToolMessage紧跟对应的AIMessage
"""

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)


class DanglingToolCallMiddleware(AgentMiddleware[AgentState]):
    """在模型调用前为悬空工具调用插入占位符ToolMessage

    扫描消息历史中的AIMessage，其tool_calls缺少对应的ToolMessage，
    并在有问题的AIMessage之后立即注入合成的错误响应，以便LLM接收
    格式良好的对话。

    设计考虑：
    - 早期检测：在模型调用前检查和修复
    - 精确定位：在正确位置插入补丁（紧接悬空AIMessage之后）
    - 错误标记：使用status="error"标记中断的工具调用
    - 性能优化：只在实际需要时才重建消息列表
    """

    def _build_patched_messages(self, messages: list) -> list | None:
        """返回在正确位置插入补丁的新消息列表

        对于每个带有悬空tool_calls（没有对应ToolMessage）的AIMessage，
        在该AIMessage之后立即插入合成的ToolMessage。
        如果不需要补丁则返回None。

        算法说明：
        1. 收集所有现有ToolMessage的ID
        2. 检查是否有任何悬空调用
        3. 如果需要，构建新列表并插入补丁
        4. 避免重复修补同一个调用

        Args:
            messages: 原始消息列表

        Returns:
            修补后的消息列表，如果不需要补丁则返回None
        """
        # 收集所有现有ToolMessage的ID
        existing_tool_msg_ids: set[str] = set()
        for msg in messages:
            if isinstance(msg, ToolMessage):
                existing_tool_msg_ids.add(msg.tool_call_id)

        # 检查是否需要任何修补
        needs_patch = False
        for msg in messages:
            if getattr(msg, "type", None) != "ai":
                continue
            for tc in getattr(msg, "tool_calls", None) or []:
                tc_id = tc.get("id")
                if tc_id and tc_id not in existing_tool_msg_ids:
                    needs_patch = True
                    break
            if needs_patch:
                break

        if not needs_patch:
            return None

        # 在每个悬空AIMessage之后立即插入补丁构建新列表
        patched: list = []
        patched_ids: set[str] = set()
        patch_count = 0
        for msg in messages:
            patched.append(msg)
            if getattr(msg, "type", None) != "ai":
                continue
            for tc in getattr(msg, "tool_calls", None) or []:
                tc_id = tc.get("id")
                if tc_id and tc_id not in existing_tool_msg_ids and tc_id not in patched_ids:
                    # 插入合成的ToolMessage
                    patched.append(
                        ToolMessage(
                            content="[Tool call was interrupted and did not return a result.]",
                            tool_call_id=tc_id,
                            name=tc.get("name", "unknown"),
                            status="error",
                        )
                    )
                    patched_ids.add(tc_id)
                    patch_count += 1

        logger.warning(f"Injecting {patch_count} placeholder ToolMessage(s) for dangling tool calls")
        return patched

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        """同步版本：在模型调用前检查并修补悬空工具调用

        Args:
            request: 模型请求
            handler: 原始模型调用处理程序

        Returns:
            模型调用结果
        """
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        """异步版本：在模型调用前检查并修补悬空工具调用

        Args:
            request: 模型请求
            handler: 原始模型调用处理程序（异步）

        Returns:
            模型调用结果
        """
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return await handler(request)
