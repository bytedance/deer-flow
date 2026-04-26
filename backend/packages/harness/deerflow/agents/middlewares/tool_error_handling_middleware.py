"""
工具错误处理中间件 - 将工具异常转换为错误ToolMessage

===================
设计思路说明
===================

**核心职责**：
捕获工具执行异常并转换为错误ToolMessage，使运行可以继续：
1. **异常捕获**：捕获工具执行中的所有异常
2. **错误转换**：将异常转换为ToolMessage格式
3. **消息限制**：限制错误消息长度，避免超长
4. **流程保留**：保留LangGraph控制流信号

**为什么需要这个中间件**：
1. **优雅降级**：工具失败不应中断整个对话
2. **错误恢复**：允许代理尝试其他工具
3. **用户友好**：提供清晰的错误信息
4. **调试便利**：记录完整的异常信息

**设计决策**：
- 捕获所有异常：除了GraphBubbleUp
- 保留控制流：不中断/暂停/恢复信号
- 错误消息格式：标准化错误响应
- 消息长度限制：防止超长错误消息

**为什么保留GraphBubbleUp**：
- **控制流信号**：用于中断/暂停/恢复
- **系统级操作**：不应被错误处理捕获
- **预期行为**：代理需要看到这些信号
"""

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)

_MISSING_TOOL_CALL_ID = "missing_tool_call_id"


class ToolErrorHandlingMiddleware(AgentMiddleware[AgentState]):
    """将工具异常转换为错误ToolMessage，使运行可以继续

    **为什么需要错误处理**：
    - **连续性**：工具失败不应终止整个对话
    - **恢复能力**：允许代理尝试替代方案
    - **透明度**：向用户显示清晰的错误信息
    - **可调试性**：记录完整异常供调试

    **工作原理**：
    捕获工具执行异常，将其转换为带有status="error"
    的ToolMessage，使代理循环可以优雅地继续。

    **错误消息格式**：
    "Error: Tool '{tool_name}' failed with {exception_type}: {detail}.
     Continue with available context, or choose an alternative tool."

    **为什么这样设计错误消息**：
    - **清晰标识**：明确说明是工具错误
    - **类型信息**：包含异常类型便于调试
    - **恢复指导**：建议代理如何继续
    - **长度限制**：防止超长消息

    **特殊处理**：
    - GraphBubbleUp异常被重新抛出以保留LangGraph控制流
    - 其他所有异常被转换为错误消息
    """

    def _build_error_message(self, request: ToolCallRequest, exc: Exception) -> ToolMessage:
        tool_name = str(request.tool_call.get("name") or "unknown_tool")
        tool_call_id = str(request.tool_call.get("id") or _MISSING_TOOL_CALL_ID)
        detail = str(exc).strip() or exc.__class__.__name__
        if len(detail) > 500:
            detail = detail[:497] + "..."

        content = f"Error: Tool '{tool_name}' failed with {exc.__class__.__name__}: {detail}. Continue with available context, or choose an alternative tool."
        return ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        try:
            return handler(request)
        except GraphBubbleUp:
            # Preserve LangGraph control-flow signals (interrupt/pause/resume).
            raise
        except Exception as exc:
            logger.exception("Tool execution failed (sync): name=%s id=%s", request.tool_call.get("name"), request.tool_call.get("id"))
            return self._build_error_message(request, exc)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        try:
            return await handler(request)
        except GraphBubbleUp:
            # Preserve LangGraph control-flow signals (interrupt/pause/resume).
            raise
        except Exception as exc:
            logger.exception("Tool execution failed (async): name=%s id=%s", request.tool_call.get("name"), request.tool_call.get("id"))
            return self._build_error_message(request, exc)


def _build_runtime_middlewares(
    *,
    include_uploads: bool,
    include_dangling_tool_call_patch: bool,
    lazy_init: bool = True,
) -> list[AgentMiddleware]:
    """Build shared base middlewares for agent execution."""
    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from deerflow.sandbox.middleware import SandboxMiddleware

    middlewares: list[AgentMiddleware] = [
        ThreadDataMiddleware(lazy_init=lazy_init),
        SandboxMiddleware(lazy_init=lazy_init),
    ]

    if include_uploads:
        from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware

        middlewares.insert(1, UploadsMiddleware())

    if include_dangling_tool_call_patch:
        from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

        middlewares.append(DanglingToolCallMiddleware())

    # Guardrail middleware (if configured)
    from deerflow.config.guardrails_config import get_guardrails_config

    guardrails_config = get_guardrails_config()
    if guardrails_config.enabled and guardrails_config.provider:
        import inspect

        from deerflow.guardrails.middleware import GuardrailMiddleware
        from deerflow.reflection import resolve_variable

        provider_cls = resolve_variable(guardrails_config.provider.use)
        provider_kwargs = dict(guardrails_config.provider.config) if guardrails_config.provider.config else {}
        # Pass framework hint if the provider accepts it (e.g. for config discovery).
        # Built-in providers like AllowlistProvider don't need it, so only inject
        # when the constructor accepts 'framework' or '**kwargs'.
        if "framework" not in provider_kwargs:
            try:
                sig = inspect.signature(provider_cls.__init__)
                if "framework" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    provider_kwargs["framework"] = "deerflow"
            except (ValueError, TypeError):
                pass
        provider = provider_cls(**provider_kwargs)
        middlewares.append(GuardrailMiddleware(provider, fail_closed=guardrails_config.fail_closed, passport=guardrails_config.passport))

    from deerflow.agents.middlewares.sandbox_audit_middleware import SandboxAuditMiddleware

    middlewares.append(SandboxAuditMiddleware())
    middlewares.append(ToolErrorHandlingMiddleware())
    return middlewares


def build_lead_runtime_middlewares(*, lazy_init: bool = True) -> list[AgentMiddleware]:
    """Middlewares shared by lead agent runtime before lead-only middlewares."""
    return _build_runtime_middlewares(
        include_uploads=True,
        include_dangling_tool_call_patch=True,
        lazy_init=lazy_init,
    )


def build_subagent_runtime_middlewares(*, lazy_init: bool = True) -> list[AgentMiddleware]:
    """Middlewares shared by subagent runtime before subagent-only middlewares."""
    return _build_runtime_middlewares(
        include_uploads=False,
        include_dangling_tool_call_patch=False,
        lazy_init=lazy_init,
    )
