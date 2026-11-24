"""Scripted model shared by execution-boundary approval tests."""

from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class StateAwareToolModel(FakeMessagesListChatModel):
    calls: list[dict[str, Any]]

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        message = AIMessage(content="final answer") if any(isinstance(message, ToolMessage) for message in messages) else AIMessage(content="", tool_calls=self.calls)
        return ChatResult(generations=[ChatGeneration(message=message)])
