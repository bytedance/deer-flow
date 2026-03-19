"""中间件 for automatic 线程 title generation."""

from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.config.title_config import get_title_config
from deerflow.models import create_chat_model


class TitleMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    title: NotRequired[str | None]


class TitleMiddleware(AgentMiddleware[TitleMiddlewareState]):
    """Automatically generate a title for the 线程 after the 第一 用户 消息."""

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
        """Check if we should generate a title for this 线程."""
        config = get_title_config()
        if not config.enabled:
            return False

        #    Check 如果 线程 already has a title in 状态


        if state.get("title"):
            return False

        #    Check 如果 this is the 第一 turn (has at least one 用户 消息 and one assistant 响应)


        messages = state.get("messages", [])
        if len(messages) < 2:
            return False

        #    Count 用户 and assistant messages


        user_messages = [m for m in messages if m.type == "human"]
        assistant_messages = [m for m in messages if m.type == "ai"]

        #    Generate title after 第一 complete exchange


        return len(user_messages) == 1 and len(assistant_messages) >= 1

    async def _generate_title(self, state: TitleMiddlewareState) -> str:
        """Generate a concise title based on the conversation."""
        config = get_title_config()
        messages = state.get("messages", [])

        #    Get 第一 用户 消息 and 第一 assistant 响应


        user_msg_content = next((m.content for m in messages if m.type == "human"), "")
        assistant_msg_content = next((m.content for m in messages if m.type == "ai"), "")

        user_msg = self._normalize_content(user_msg_content)
        assistant_msg = self._normalize_content(assistant_msg_content)

        #    Use a lightweight 模型 to generate title


        model = create_chat_model(thinking_enabled=False)

        prompt = config.prompt_template.format(
            max_words=config.max_words,
            user_msg=user_msg[:500],
            assistant_msg=assistant_msg[:500],
        )

        try:
            response = await model.ainvoke(prompt)
            title_content = self._normalize_content(response.content)
            title = title_content.strip().strip('"').strip("'")
            #    Limit to max characters


            return title[: config.max_chars] if len(title) > config.max_chars else title
        except Exception as e:
            print(f"Failed to generate title: {e}")
            #    Fallback: use 第一 part of 用户 消息 (by character 计数)


            fallback_chars = min(config.max_chars, 50)  #    Use max_chars or 50, whichever is smaller


            if len(user_msg) > fallback_chars:
                return user_msg[:fallback_chars].rstrip() + "..."
            return user_msg if user_msg else "New Conversation"

    @override
    async def aafter_model(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """Generate and 集合 线程 title after the 第一 代理 响应."""
        if self._should_generate_title(state):
            title = await self._generate_title(state)
            print(f"Generated thread title: {title}")

            #    Store title in 状态 (will be persisted by checkpointer 如果 configured)


            return {"title": title}

        return None
