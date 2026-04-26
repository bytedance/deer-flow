"""子代理限制中间件 - 强制执行每次模型响应的最大并发子代理调用数

===================
设计思路说明
===================

**核心职责**：
截断单个模型响应中多余的'task'工具调用：
1. **限制并发**：确保不超过max_concurrent限制
2. **可靠执行**：比基于提示词的限制更可靠
3. **静默截断**：多余调用被丢弃，不会产生错误

**为什么需要这个中间件**：
1. **资源控制**：防止同时启动太多子代理
2. **成本控制**：限制并发LLM调用数量
3. **系统稳定性**：避免过载系统资源
4. **可靠性**：强制执行比依赖提示词更可靠

**设计决策**：
- **硬限制**：截断超出限制的调用
- **保留优先**：保留前面的调用，截断后面的
- **范围限制**：限制在[2, 4]范围内
- **同步/异步**：同时支持两种执行路径

**为什么截断而非报错**：
- **优雅降级**：部分执行比完全不执行好
- **用户体验**：不会因为超出限制而失败
- **简单高效**：不需要复杂的重试逻辑
"""

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.subagents.executor import MAX_CONCURRENT_SUBAGENTS

logger = logging.getLogger(__name__)

# Valid range for max_concurrent_subagents
MIN_SUBAGENT_LIMIT = 2
MAX_SUBAGENT_LIMIT = 4


def _clamp_subagent_limit(value: int) -> int:
    """Clamp subagent limit to valid range [2, 4]."""
    return max(MIN_SUBAGENT_LIMIT, min(MAX_SUBAGENT_LIMIT, value))


class SubagentLimitMiddleware(AgentMiddleware[AgentState]):
    """Truncates excess 'task' tool calls from a single model response.

    When an LLM generates more than max_concurrent parallel task tool calls
    in one response, this middleware keeps only the first max_concurrent and
    discards the rest. This is more reliable than prompt-based limits.

    Args:
        max_concurrent: Maximum number of concurrent subagent calls allowed.
            Defaults to MAX_CONCURRENT_SUBAGENTS (3). Clamped to [2, 4].
    """

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_SUBAGENTS):
        super().__init__()
        self.max_concurrent = _clamp_subagent_limit(max_concurrent)

    def _truncate_task_calls(self, state: AgentState) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None

        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return None

        # Count task tool calls
        task_indices = [i for i, tc in enumerate(tool_calls) if tc.get("name") == "task"]
        if len(task_indices) <= self.max_concurrent:
            return None

        # Build set of indices to drop (excess task calls beyond the limit)
        indices_to_drop = set(task_indices[self.max_concurrent :])
        truncated_tool_calls = [tc for i, tc in enumerate(tool_calls) if i not in indices_to_drop]

        dropped_count = len(indices_to_drop)
        logger.warning(f"Truncated {dropped_count} excess task tool call(s) from model response (limit: {self.max_concurrent})")

        # Replace the AIMessage with truncated tool_calls (same id triggers replacement)
        updated_msg = last_msg.model_copy(update={"tool_calls": truncated_tool_calls})
        return {"messages": [updated_msg]}

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._truncate_task_calls(state)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._truncate_task_calls(state)
