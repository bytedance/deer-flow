"""延迟工具过滤器中间件

===================
设计思路说明
===================

**核心职责**：
从模型绑定中过滤延迟工具的schema：
1. 检测哪些工具已注册为延迟工具
2. 从request.tools中移除这些工具的schema
3. 确保LLM只看到活动工具的schema

**为什么需要这个中间件**：
1. **Token节省**：延迟工具的schema不发送给LLM，节省上下文
2. **按需发现**：代理通过tool_search工具在运行时发现延迟工具
3. **执行保留**：ToolNode仍持有所有工具（包括延迟）用于执行路由
4. **动态加载**：支持大量可选工具而不消耗初始上下文

**设计决策**：
- 在模型调用前过滤：使用wrap_model_call拦截
- 只过滤schema：工具执行能力不受影响
- 保留注册信息：DeferredToolRegistry仍然跟踪所有延迟工具
- 性能优化：只在有延迟工具时才执行过滤

**架构说明**：
- DeferredToolRegistry：注册和跟踪延迟工具
- tool_search工具：代理在运行时查询可用工具
- ToolNode：执行所有工具（包括延迟的）
- 此中间件：确保延迟工具schema不发送给LLM
"""

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse

logger = logging.getLogger(__name__)


class DeferredToolFilterMiddleware(AgentMiddleware[AgentState]):
    """在模型绑定前从request.tools中删除延迟工具

    ToolNode仍然持有所有工具（包括延迟）用于执行路由，
    但LLM只看到活动工具schema — 延迟工具通过tool_search在运行时发现

    设计优势：
    - 上下文节省：不向LLM发送大量可选工具的schema
    - 按需发现：代理只在需要时查询特定工具
    - 无缝执行：延迟工具的执行流程与活动工具相同
    - 可扩展性：支持数百个可选工具而不影响初始上下文

    工作流程：
    1. 从DeferredToolRegistry获取延迟工具列表
    2. 从request.tools中过滤掉延迟工具
    3. 将过滤后的工具列表传递给模型
    4. 代理可以通过tool_search查询延迟工具
    """

    def _filter_tools(self, request: ModelRequest) -> ModelRequest:
        """从模型绑定中过滤延迟工具

        算法说明：
        1. 获取DeferredToolRegistry
        2. 收集延迟工具的名称
        3. 过滤掉这些工具
        4. 返回修改后的请求

        Args:
            request: 模型请求

        Returns:
            工具列表已过滤的模型请求
        """
        from deerflow.tools.builtins.tool_search import get_deferred_registry

        registry = get_deferred_registry()
        if not registry:
            return request

        # 收集延迟工具名称
        deferred_names = {e.name for e in registry.entries}
        # 过滤掉延迟工具
        active_tools = [t for t in request.tools if getattr(t, "name", None) not in deferred_names]

        if len(active_tools) < len(request.tools):
            logger.debug(f"Filtered {len(request.tools) - len(active_tools)} deferred tool schema(s) from model binding")

        return request.override(tools=active_tools)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        """同步版本：在模型调用前过滤延迟工具

        Args:
            request: 模型请求
            handler: 原始模型调用处理程序

        Returns:
            模型调用结果
        """
        return handler(self._filter_tools(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        """异步版本：在模型调用前过滤延迟工具

        Args:
            request: 模型请求
            handler: 原始模型调用处理程序（异步）

        Returns:
            模型调用结果
        """
        return await handler(self._filter_tools(request))
