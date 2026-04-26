"""
Token使用统计中间件 - 记录LLM token使用情况

===================
设计思路说明
===================

**核心职责**：
从模型响应的usage_metadata中记录token使用情况：
1. **输入token**：记录提示词消耗的token数
2. **输出token**：记录模型响应消耗的token数
3. **总token数**：记录总的token消耗
4. **日志记录**：将统计信息写入日志

**为什么需要这个中间件**：
1. **成本监控**：跟踪LLM API调用成本
2. **性能分析**：分析token使用模式
3. **预算控制**：防止超出预期成本
4. **优化依据**：为优化提供数据支持

**设计决策**：
- 非侵入式：只记录不修改状态
- 标准日志：使用logger.info记录
- 元数据读取：从usage_metadata获取
- 同步/异步：同时支持两种路径

**为什么只记录不修改**：
- **可观测性**：纯粹用于监控和分析
- **无副作用**：不影响代理执行
- **性能**：不增加额外处理开销
"""

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class TokenUsageMiddleware(AgentMiddleware):
    """从模型响应的usage_metadata记录token使用

    **为什么需要这个中间件**：
    - **成本追踪**：监控每次LLM调用的成本
    - **性能分析**：分析token使用模式
    - **预算控制**：防止超出预期成本
    - **优化依据**：为提示词优化提供数据

    **工作原理**：
    在模型响应后（after_model），从最后一条消息的
    usage_metadata中提取token统计信息并记录到日志。

    **记录内容**：
    - input_tokens: 输入提示词的token数
    - output_tokens: 模型响应的token数
    - total_tokens: 总token消耗

    **为什么使用logger.info**：
    - **标准级别**：info级别适合常规操作记录
    - **可配置**：可以根据日志配置调整
    - **结构化**：便于日志解析和分析
    """

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._log_usage(state)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._log_usage(state)

    def _log_usage(self, state: AgentState) -> None:
        messages = state.get("messages", [])
        if not messages:
            return None
        last = messages[-1]
        usage = getattr(last, "usage_metadata", None)
        if usage:
            logger.info(
                "LLM token usage: input=%s output=%s total=%s",
                usage.get("input_tokens", "?"),
                usage.get("output_tokens", "?"),
                usage.get("total_tokens", "?"),
            )
        return None
