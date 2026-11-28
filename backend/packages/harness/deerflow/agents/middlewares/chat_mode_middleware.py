"""Keep Chat tool results, model history and completed turns text-only."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ExtendedModelResponse, ModelCallResult, ModelRequest
from langchain_core.messages import AIMessage, ToolMessage, convert_to_messages
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command, Overwrite

from deerflow.agents.chat_mode import chat_message


def _chat_command(command: Command) -> Command:
    if not isinstance(command.update, dict):
        return command
    update = {key: value for key, value in command.update.items() if key not in ("artifacts", "uploaded_files", "tool_artifacts", "sandbox", "viewed_images", "thread_data")}
    messages = update.get("messages")
    replace_history = isinstance(messages, Overwrite)
    if replace_history:
        messages = messages.value
    if messages is not None:
        # The reducer also accepts serialized messages and (role, content) pairs.
        role_pair = isinstance(messages, tuple) and len(messages) == 2 and isinstance(messages[0], str)
        batch = messages if isinstance(messages, (list, tuple)) and not role_pair else [messages]
        projected = [chat_message(msg, mark_mode=True) for msg in convert_to_messages(batch)]
        update["messages"] = Overwrite(projected) if replace_history else projected
    return replace(command, update=update)


def _tool_result(result: ToolMessage | Command) -> ToolMessage | Command:
    if isinstance(result, Command):
        return _chat_command(result)
    return chat_message(result, mark_mode=True)


def _model_result(response: ModelCallResult) -> ModelCallResult:
    if isinstance(response, AIMessage):
        return chat_message(response, mark_mode=True)
    if isinstance(response, ExtendedModelResponse):
        return replace(response, model_response=_model_result(response.model_response), command=_chat_command(response.command) if response.command else None)
    return replace(response, result=[chat_message(message, mark_mode=True) for message in response.result])


def _model_input(request: ModelRequest) -> ModelRequest:
    return request.override(messages=[chat_message(message) for message in request.messages])


class ChatModeMiddleware(AgentMiddleware):
    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]) -> ToolMessage | Command:
        return _tool_result(handler(request))

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]) -> ToolMessage | Command:
        return _tool_result(await handler(request))

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelCallResult]) -> ModelCallResult:
        return _model_result(handler(_model_input(request)))

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelCallResult]]) -> ModelCallResult:
        return _model_result(await handler(_model_input(request)))
