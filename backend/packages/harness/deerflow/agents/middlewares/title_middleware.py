"""
自动标题生成中间件 - 在首次对话后自动生成线程标题

===================
设计思路说明
===================

**核心职责**：
在首次用户消息后自动为线程生成标题：
1. **检测时机**：在首次完整对话后触发
2. **LLM生成**：使用LLM理解对话内容生成标题
3. **状态更新**：将标题写入thread_state
4. **降级策略**：LLM失败时使用用户消息前几个词

**为什么需要这个中间件**：
1. **用户体验**：让用户更容易识别和管理对话
2. **自动化**：无需手动命名每个对话
3. **智能理解**：利用LLM理解对话意图
4. **一致性**：统一的标题格式和风格

**设计决策**：
- 在after_agent中触发：代理执行完成后检查
- 只生成一次：检查state中是否已有title
- 首次对话后：确保有足够的上下文
- Fallback策略：LLM失败时使用用户消息

**为什么在首次对话后生成**：
- **上下文充足**：用户意图+代理响应提供足够信息
- **时机合适**：对话刚结束，用户体验流畅
- **只生成一次**：避免重复计算和成本
"""

import logging
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.config.title_config import get_title_config
from deerflow.models import create_chat_model

logger = logging.getLogger(__name__)


class TitleMiddlewareState(AgentState):
    """与ThreadState模式兼容

    **为什么需要这个类**：
    - **类型提示**：提供title字段的类型
    - **模式兼容**：确保与ThreadState兼容
    - **可选字段**：标题可能尚未生成
    """

    title: NotRequired[str | None]


class TitleMiddleware(AgentMiddleware[TitleMiddlewareState]):
    """在首次用户消息后自动为线程生成标题

    **为什么需要这个中间件**：
    - **自动化**：无需手动命名对话
    - **智能理解**：LLM理解对话意图生成标题
    - **可识别性**：用户更容易在列表中识别对话
    - **一致性**：统一的标题格式

    **工作流程**：
    1. 检查是否已生成标题
    2. 检查是否为首次完整对话
    3. 构建标题生成提示词
    4. 调用LLM生成标题
    5. 更新状态中的title字段

    **设计考虑**：
    - **只生成一次**：检查state中是否已有title
    - **时机选择**：首次对话后确保有足够上下文
    - **降级策略**：LLM失败时使用用户消息
    - **配置驱动**：可通过配置禁用或调整
    """

    state_schema = TitleMiddlewareState

    def _normalize_content(self, content: object) -> str:
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts = [self._normalize_content(item) for item in content]
            return "\n".join(part for part in parts if part)

        if isinstance(content, dict):
            text_value = content.get("text")
            if isinstance(text_value, str):
                return text_value

            nested_content = content.get("content")
            if nested_content is not None:
                return self._normalize_content(nested_content)

        return ""

    def _should_generate_title(self, state: TitleMiddlewareState) -> bool:
        """Check if we should generate a title for this thread."""
        config = get_title_config()
        if not config.enabled:
            return False

        # Check if thread already has a title in state
        if state.get("title"):
            return False

        # Check if this is the first turn (has at least one user message and one assistant response)
        messages = state.get("messages", [])
        if len(messages) < 2:
            return False

        # Count user and assistant messages
        user_messages = [m for m in messages if m.type == "human"]
        assistant_messages = [m for m in messages if m.type == "ai"]

        # Generate title after first complete exchange
        return len(user_messages) == 1 and len(assistant_messages) >= 1

    def _build_title_prompt(self, state: TitleMiddlewareState) -> tuple[str, str]:
        """Extract user/assistant messages and build the title prompt.

        Returns (prompt_string, user_msg) so callers can use user_msg as fallback.
        """
        config = get_title_config()
        messages = state.get("messages", [])

        user_msg_content = next((m.content for m in messages if m.type == "human"), "")
        assistant_msg_content = next((m.content for m in messages if m.type == "ai"), "")

        user_msg = self._normalize_content(user_msg_content)
        assistant_msg = self._normalize_content(assistant_msg_content)

        prompt = config.prompt_template.format(
            max_words=config.max_words,
            user_msg=user_msg[:500],
            assistant_msg=assistant_msg[:500],
        )
        return prompt, user_msg

    def _parse_title(self, content: object) -> str:
        """Normalize model output into a clean title string."""
        config = get_title_config()
        title_content = self._normalize_content(content)
        title = title_content.strip().strip('"').strip("'")
        return title[: config.max_chars] if len(title) > config.max_chars else title

    def _fallback_title(self, user_msg: str) -> str:
        config = get_title_config()
        fallback_chars = min(config.max_chars, 50)
        if len(user_msg) > fallback_chars:
            return user_msg[:fallback_chars].rstrip() + "..."
        return user_msg if user_msg else "New Conversation"

    def _generate_title_result(self, state: TitleMiddlewareState) -> dict | None:
        """Synchronously generate a title. Returns state update or None."""
        if not self._should_generate_title(state):
            return None

        prompt, user_msg = self._build_title_prompt(state)
        config = get_title_config()
        model = create_chat_model(name=config.model_name, thinking_enabled=False)

        try:
            response = model.invoke(prompt)
            title = self._parse_title(response.content)
            if not title:
                title = self._fallback_title(user_msg)
        except Exception:
            logger.exception("Failed to generate title (sync)")
            title = self._fallback_title(user_msg)

        return {"title": title}

    async def _agenerate_title_result(self, state: TitleMiddlewareState) -> dict | None:
        """Asynchronously generate a title. Returns state update or None."""
        if not self._should_generate_title(state):
            return None

        prompt, user_msg = self._build_title_prompt(state)
        config = get_title_config()
        model = create_chat_model(name=config.model_name, thinking_enabled=False)

        try:
            response = await model.ainvoke(prompt)
            title = self._parse_title(response.content)
            if not title:
                title = self._fallback_title(user_msg)
        except Exception:
            logger.exception("Failed to generate title (async)")
            title = self._fallback_title(user_msg)

        return {"title": title}

    @override
    def after_model(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        return self._generate_title_result(state)

    @override
    async def aafter_model(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        return await self._agenerate_title_result(state)
