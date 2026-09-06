"""Enforce per-message knowledge scope at model and tool boundaries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from deerflow.knowledge_scope import (
    KNOWLEDGE_SCOPE_KEY,
    KNOWLEDGE_SCOPE_RUNTIME_KEY,
    canonicalize_knowledge_scope,
    execution_scope,
    strip_message_knowledge_scope,
)
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY

_KNOWLEDGE_SEARCH_TOOL_NAME = "knowledge_search"


def _runtime_context(value: object) -> dict[str, Any] | None:
    context = getattr(value, "context", None)
    return context if isinstance(context, dict) else None


def _scope_from_runtime(value: object) -> dict[str, Any] | None:
    context = _runtime_context(value)
    if context is None or KNOWLEDGE_SCOPE_RUNTIME_KEY not in context:
        return None
    return execution_scope(canonicalize_knowledge_scope(context[KNOWLEDGE_SCOPE_RUNTIME_KEY]))


class KnowledgeScopeMiddleware(AgentMiddleware[AgentState]):
    """Project execution scope, redact message snapshots, and enforce disabled."""

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> None:
        context = _runtime_context(runtime)
        if context is None:
            return

        admitted = _scope_from_runtime(runtime)
        if admitted is not None:
            context[KNOWLEDGE_SCOPE_RUNTIME_KEY] = admitted
            return

        messages = list((state or {}).get("messages") or [])
        raw_boundary = context.get(CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY)
        if isinstance(raw_boundary, (set, frozenset, list, tuple)):
            pre_existing_ids = {str(message_id) for message_id in raw_boundary if message_id}
            candidates = [message for message in messages if str(getattr(message, "id", "") or "") not in pre_existing_ids]
        else:
            # Standalone harness callers do not always expose a checkpoint
            # boundary. Only the terminal input message is eligible; never
            # search backwards through arbitrary history for a scope.
            candidates = messages[-1:]

        scoped = []
        for message in candidates:
            additional_kwargs = getattr(message, "additional_kwargs", None)
            if isinstance(additional_kwargs, Mapping) and KNOWLEDGE_SCOPE_KEY in additional_kwargs:
                if not isinstance(message, HumanMessage):
                    raise ValueError("knowledge_scope is allowed only on a current HumanMessage")
                scoped.append(additional_kwargs[KNOWLEDGE_SCOPE_KEY])
        if len(scoped) > 1:
            raise ValueError("only one current HumanMessage may carry knowledge_scope")
        if scoped:
            context[KNOWLEDGE_SCOPE_RUNTIME_KEY] = execution_scope(canonicalize_knowledge_scope(scoped[0]))

    @staticmethod
    def _prepare_model_request(request: ModelRequest) -> ModelRequest:
        messages = [strip_message_knowledge_scope(message) for message in request.messages]
        tools = list(request.tools)
        scope = _scope_from_runtime(request.runtime)
        if scope is not None and scope["mode"] == "disabled":
            tools = [tool for tool in tools if getattr(tool, "name", None) != _KNOWLEDGE_SEARCH_TOOL_NAME]
        if messages == list(request.messages) and tools == list(request.tools):
            return request
        return request.override(messages=messages, tools=tools)

    @staticmethod
    def _disabled_tool_message(request: ToolCallRequest) -> ToolMessage | None:
        if str(request.tool_call.get("name") or "") != _KNOWLEDGE_SEARCH_TOOL_NAME:
            return None
        scope = _scope_from_runtime(getattr(request, "runtime", None))
        if scope is None or scope["mode"] != "disabled":
            return None
        return ToolMessage(
            content="Error: Knowledge search is disabled for this turn.",
            tool_call_id=str(request.tool_call.get("id") or "missing_tool_call_id"),
            name=_KNOWLEDGE_SEARCH_TOOL_NAME,
            status="error",
        )

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._prepare_model_request(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._prepare_model_request(request))

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        blocked = self._disabled_tool_message(request)
        return blocked if blocked is not None else handler(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        blocked = self._disabled_tool_message(request)
        return blocked if blocked is not None else await handler(request)
