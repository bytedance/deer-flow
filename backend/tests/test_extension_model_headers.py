"""Extension-contributed transport headers on the final model request."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from deerflow_extension_api import (
    AgentBuildContext,
    AgentScope,
    ModelHeadersProvider,
    ModelRequestView,
    ReadOnlyDict,
)
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from deerflow.extensions.registry import ExtensionRegistry
from deerflow.extensions.stack import compose_with_extensions

#: Every request the fake provider received (module level: pydantic models
#: treat class attributes as fields).
CALLS: list[dict[str, Any]] = []


class RecordingChatModel(BaseChatModel):
    """Records the kwargs that reached the provider (``extra_headers`` included)."""

    @property
    def _llm_type(self) -> str:
        return "recording"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        CALLS.append(dict(kwargs))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])


def _reply_graph(middlewares: list[Any] | None = None):
    return create_agent(RecordingChatModel(), tools=[], middleware=list(middlewares or []))


def _compose(providers, *, extra: list[Any] | None = None, scope: AgentScope = AgentScope.LEAD):
    registry = ExtensionRegistry()
    with registry.attributed_to("test-extension"):
        for provider in providers:
            registry.model_headers(provider)
    loaded = registry.build()
    base = [*(extra or [])]
    return compose_with_extensions(base, scope, AgentBuildContext(scope=scope), loaded)


class StaticProvider:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers
        self.views: list[ModelRequestView] = []

    def provide_model_headers(self, view: ModelRequestView):
        self.views.append(view)
        return dict(self.headers)


# --- Contract surface -------------------------------------------------------


def test_provider_default_is_noop():
    class Bare:
        pass

    assert ModelHeadersProvider.provide_model_headers(Bare(), ModelRequestView()) is None


def test_view_properties_and_read_only_state():
    view = ModelRequestView(
        model_name="m",
        messages=("a", "b"),
        system_message=object(),
        tools=({"name": "search"},),
        state=ReadOnlyDict({"messages": ["a"], "nested": {"k": [1, 2]}}),
    )
    assert view.message_count == 2
    assert view.system_present is True
    assert view.tool_names == ("search",)
    assert ModelRequestView().system_present is False
    assert ModelRequestView().message_count == 0
    assert view.state["messages"] == ("a",)
    assert view.state["nested"] == {"k": (1, 2)}
    with pytest.raises(TypeError):
        view.state["messages"] = ()  # type: ignore[index]


def test_registry_registers_builds_and_rolls_back_providers():
    registry = ExtensionRegistry()
    provider = StaticProvider({"X-Test": "1"})
    mark = registry.mark()
    with registry.attributed_to("first"):
        registry.model_headers(provider)
    loaded = registry.build()
    assert loaded.has_model_headers is True
    assert loaded.model_headers == (("first", provider),)
    registry.rollback_to(mark)
    assert registry.build().has_model_headers is False
    with registry.attributed_to("again"):
        registry.model_headers(provider)
    registry.discard("again")
    assert registry.build().model_headers == ()


# --- Host behaviour ---------------------------------------------------------


def test_headers_reach_the_provider_and_leave_the_body_untouched():
    provider = StaticProvider({"X-Agent-Hint": "payload"})
    agent = _reply_graph(_compose([provider]))
    agent.invoke({"messages": [("user", "hi")]})
    call = CALLS[-1]
    assert call["extra_headers"] == {"X-Agent-Hint": "payload"}
    view = provider.views[-1]
    assert view.message_count == 1
    assert view.system_present is False
    assert view.state["messages"] == ("a",) or view.state["messages"]


def test_provider_sees_the_final_request_after_inner_transforms():
    class AppendNote(AgentMiddleware):
        name = "test_append_note"

        def wrap_model_call(self, request, handler):
            return handler(request.override(messages=[*request.messages, AIMessage(content="note")]))

        async def awrap_model_call(self, request, handler):
            return await handler(request.override(messages=[*request.messages, AIMessage(content="note")]))

    provider = StaticProvider({"X-Seen": "yes"})
    agent = _reply_graph(_compose([provider], extra=[AppendNote()]))
    agent.invoke({"messages": [("user", "hi")]})
    # The outer middleware appends one message before the header provider runs.
    assert provider.views[-1].message_count == 2


def test_existing_headers_are_preserved_and_providers_win():
    class PreexistingHeader(AgentMiddleware):
        name = "test_preexisting_header"

        def wrap_model_call(self, request, handler):
            request.model_settings["extra_headers"] = {"X-Keep": "1", "X-Agent-Hint": "old"}
            return handler(request)

        async def awrap_model_call(self, request, handler):
            request.model_settings["extra_headers"] = {"X-Keep": "1", "X-Agent-Hint": "old"}
            return await handler(request)

    provider = StaticProvider({"X-Agent-Hint": "new"})
    agent = _reply_graph(_compose([provider], extra=[PreexistingHeader()]))
    agent.invoke({"messages": [("user", "hi")]})
    assert CALLS[-1]["extra_headers"] == {"X-Keep": "1", "X-Agent-Hint": "new"}


def test_later_providers_override_earlier_ones():
    first = StaticProvider({"X-Order": "first", "X-First": "1"})
    second = StaticProvider({"X-Order": "second"})
    agent = _reply_graph(_compose([first, second]))
    agent.invoke({"messages": [("user", "hi")]})
    assert CALLS[-1]["extra_headers"] == {"X-Order": "second", "X-First": "1"}


def test_failing_or_malformed_provider_never_fails_the_model_call():
    class Boom:
        def provide_model_headers(self, view):
            raise RuntimeError("boom")

    class Malformed:
        def provide_model_headers(self, view):
            return {"X-Ok": "yes", "X-Bad": 3, 4: "no"}

    good = StaticProvider({"X-Good": "1"})
    agent = _reply_graph(_compose([Boom(), Malformed(), good]))
    result = agent.invoke({"messages": [("user", "hi")]})
    assert result["messages"][-1].content == "ok"
    assert CALLS[-1]["extra_headers"] == {"X-Ok": "yes", "X-Good": "1"}


def test_provider_returning_none_adds_no_headers():
    provider = StaticProvider({})
    provider.provide_model_headers = lambda view: None  # type: ignore[method-assign]
    agent = _reply_graph(_compose([provider]))
    agent.invoke({"messages": [("user", "hi")]})
    assert "extra_headers" not in CALLS[-1]


def test_async_path_applies_headers_too():
    provider = StaticProvider({"X-Async": "1"})
    agent = _reply_graph(_compose([provider]))
    asyncio.run(agent.ainvoke({"messages": [("user", "hi")]}))
    assert CALLS[-1]["extra_headers"] == {"X-Async": "1"}


def test_subagent_scope_gets_the_same_middleware():
    provider = StaticProvider({"X-Sub": "1"})
    middleware = _compose([provider], scope=AgentScope.SUBAGENT)
    assert any(type(item).__name__ == "ModelHeadersMiddleware" for item in middleware)
    agent = _reply_graph(middleware)
    agent.invoke({"messages": [("user", "hi")]})
    assert CALLS[-1]["extra_headers"] == {"X-Sub": "1"}


def test_no_provider_leaves_the_stack_unchanged():
    registry = ExtensionRegistry()
    loaded = registry.build()
    base = [object(), object()]
    result = compose_with_extensions(base, AgentScope.LEAD, None, loaded)
    assert result == base
    assert not any(type(item).__name__ == "ModelHeadersMiddleware" for item in result)


def test_header_middleware_is_innermost_before_clarification():
    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

    provider = StaticProvider({"X-Position": "1"})
    registry = ExtensionRegistry()
    with registry.attributed_to("test-extension"):
        registry.model_headers(provider)
    loaded = registry.build()
    result = compose_with_extensions([ClarificationMiddleware()], AgentScope.LEAD, AgentBuildContext(scope=AgentScope.LEAD), loaded)
    names = [type(item).__name__ for item in result]
    assert names[-1] == "ClarificationMiddleware"
    assert names[-2] == "ModelHeadersMiddleware"
