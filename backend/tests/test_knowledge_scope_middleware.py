from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.knowledge_scope_middleware import (
    KnowledgeScopeMiddleware,
)
from deerflow.knowledge_scope import KNOWLEDGE_SCOPE_KEY, KNOWLEDGE_SCOPE_RUNTIME_KEY
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY


@tool
def knowledge_search(query: str) -> str:
    """Search."""
    return query


@tool
def other_tool(query: str) -> str:
    """Other."""
    return query


class _ModelRequest:
    def __init__(self, messages, *, tools=(), runtime=None):
        self.messages = list(messages)
        self.tools = list(tools)
        self.runtime = runtime

    def override(self, **kwargs):
        return _ModelRequest(
            kwargs.get("messages", self.messages),
            tools=kwargs.get("tools", self.tools),
            runtime=self.runtime,
        )


def _scope(mode: str = "selected") -> dict:
    if mode != "selected":
        return {"version": 1, "mode": mode}
    return {
        "version": 1,
        "mode": "selected",
        "dataset_ids": ["dataset-a"],
        "display": {
            "datasets": [{"id": "dataset-a", "name": "Agriculture"}],
        },
    }


def test_before_agent_projects_only_current_message_execution_scope() -> None:
    historical = HumanMessage(
        content="old",
        id="old",
        additional_kwargs={KNOWLEDGE_SCOPE_KEY: _scope("all")},
    )
    current = HumanMessage(
        content="new",
        id="new",
        additional_kwargs={KNOWLEDGE_SCOPE_KEY: _scope()},
    )
    runtime = Runtime(context={CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset({"old"})})

    KnowledgeScopeMiddleware().before_agent(
        {"messages": [historical, current]},
        runtime,
    )

    assert runtime.context[KNOWLEDGE_SCOPE_RUNTIME_KEY] == {
        "version": 1,
        "mode": "selected",
        "dataset_ids": ["dataset-a"],
    }


def test_before_agent_uses_server_admitted_runtime_scope_for_recovery() -> None:
    runtime = Runtime(
        context={
            CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset({"source"}),
            KNOWLEDGE_SCOPE_RUNTIME_KEY: _scope("disabled"),
        }
    )
    source = HumanMessage(
        content="source",
        id="source",
        additional_kwargs={KNOWLEDGE_SCOPE_KEY: _scope("selected")},
    )

    KnowledgeScopeMiddleware().before_agent({"messages": [source]}, runtime)

    assert runtime.context[KNOWLEDGE_SCOPE_RUNTIME_KEY] == {
        "version": 1,
        "mode": "disabled",
    }


@pytest.mark.parametrize("method_name", ["wrap_model_call", "awrap_model_call"])
@pytest.mark.anyio
async def test_model_paths_strip_every_historical_scope_and_hide_disabled_tool(
    method_name: str,
) -> None:
    runtime = Runtime(context={KNOWLEDGE_SCOPE_RUNTIME_KEY: _scope("disabled")})
    messages = [
        HumanMessage(
            content="old",
            additional_kwargs={KNOWLEDGE_SCOPE_KEY: _scope("all"), "keep": True},
        ),
        AIMessage(
            content="answer",
            additional_kwargs={KNOWLEDGE_SCOPE_KEY: _scope(), "keep": True},
        ),
    ]
    request = _ModelRequest(
        messages,
        tools=[knowledge_search, other_tool],
        runtime=runtime,
    )
    captured = []
    middleware = KnowledgeScopeMiddleware()

    if method_name == "wrap_model_call":
        middleware.wrap_model_call(
            request,
            lambda value: captured.append(value) or "ok",
        )
    else:

        async def handler(value):
            captured.append(value)
            return "ok"

        await middleware.awrap_model_call(request, handler)

    assert [item.name for item in captured[0].tools] == ["other_tool"]
    assert all(KNOWLEDGE_SCOPE_KEY not in message.additional_kwargs for message in captured[0].messages)
    assert all(message.additional_kwargs["keep"] for message in captured[0].messages)
    assert KNOWLEDGE_SCOPE_KEY in request.messages[0].additional_kwargs


def test_disabled_execution_guard_blocks_knowledge_tool() -> None:
    runtime = Runtime(context={KNOWLEDGE_SCOPE_RUNTIME_KEY: _scope("disabled")})
    request = SimpleNamespace(
        tool_call={"name": "knowledge_search", "id": "call-1"},
        runtime=runtime,
    )

    result = KnowledgeScopeMiddleware().wrap_tool_call(
        request,
        lambda _request: pytest.fail("disabled call must not execute"),
    )

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.tool_call_id == "call-1"
    assert "disabled" in str(result.content).lower()


def test_legacy_message_without_scope_keeps_tools_and_runtime_unset() -> None:
    runtime = Runtime(context={CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()})
    middleware = KnowledgeScopeMiddleware()
    middleware.before_agent(
        {"messages": [HumanMessage(content="legacy", id="new")]},
        runtime,
    )
    request = _ModelRequest(
        [HumanMessage(content="legacy")],
        tools=[knowledge_search],
        runtime=runtime,
    )
    captured = []

    middleware.wrap_model_call(
        request,
        lambda value: captured.append(value) or "ok",
    )

    assert KNOWLEDGE_SCOPE_RUNTIME_KEY not in runtime.context
    assert [item.name for item in captured[0].tools] == ["knowledge_search"]
