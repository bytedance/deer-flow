"""Tests for the per-source context-usage snapshot middleware."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from deerflow_extension_api import ContentKind, provenance_kwargs
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from deerflow.agents.middlewares.context_usage_middleware import (
    CONTEXT_USAGE_KEY,
    ContextUsageMiddleware,
    ContextUsageSnapshot,
)
from deerflow.tools.mcp_metadata import tag_mcp_tool


class _CountingCounter:
    """Deterministic stand-in for ``count_tokens_approximately``.

    Counts one token per content character and one per tool-name character, and
    records how often the (expensive) tool-schema path ran.
    """

    def __init__(self) -> None:
        self.tool_count_calls = 0

    def __call__(self, messages, *, tools=None) -> int:
        total = sum(len(message.content) for message in messages if isinstance(message.content, str))
        if tools:
            self.tool_count_calls += 1
            total += sum(len(getattr(item, "name", "") or "") for item in tools)
        return total


class _RaisingCounter:
    def __call__(self, messages, *, tools=None) -> int:
        raise RuntimeError("counter unavailable")


@tool
def builtin_tool(query: str) -> str:
    """A built-in tool."""
    return query


@tool
def mcp_tool(query: str) -> str:
    """An MCP tool."""
    return query


def _mcp_tool():
    return tag_mcp_tool(mcp_tool)


def _runtime(thread_id: str | None = "thread-1"):
    return SimpleNamespace(context={"thread_id": thread_id} if thread_id else {})


def _request(messages, *, system: str | None = "S" * 40, tools=(), runtime=None) -> ModelRequest:
    return ModelRequest(
        model=SimpleNamespace(),
        messages=list(messages),
        system_message=SystemMessage(content=system) if system is not None else None,
        tools=list(tools),
        state={"messages": list(messages)},
        runtime=runtime or _runtime(),
    )


def _run(middleware: ContextUsageMiddleware, request: ModelRequest, messages=None) -> tuple[ModelResponse, ModelResponse]:
    """Drive one model call through the middleware's wrap hook.

    Returns the fake model's response and the response the middleware
    returned, so tests can assert that the original stayed untouched.
    """
    response = ModelResponse(result=list(messages if messages is not None else [AIMessage(content="final", id="ai-1")]))
    returned = middleware.wrap_model_call(request, lambda _request: response)
    assert isinstance(returned, ModelResponse)
    return response, returned


def _snapshot(middleware: ContextUsageMiddleware, request: ModelRequest) -> dict:
    _, returned = _run(middleware, request)
    payload = returned.result[-1].additional_kwargs.get(CONTEXT_USAGE_KEY)
    assert payload is not None
    return payload


def _middleware(counter=None, *, context_window=1000) -> ContextUsageMiddleware:
    return ContextUsageMiddleware(model_name="test-model", context_window=context_window, token_counter=counter or _CountingCounter())


def _provenance_message(kind: ContentKind, content: str, message_type=HumanMessage):
    return message_type(content=content, additional_kwargs=provenance_kwargs(kind, "test_producer"))


def test_snapshot_partitions_every_source_exactly_once() -> None:
    messages = [
        HumanMessage(content="u" * 10),
        AIMessage(content="a" * 20),
        ToolMessage(content="t" * 30, tool_call_id="call-1"),
        _provenance_message(ContentKind.SKILL_BODY, "s" * 50),
        _provenance_message(ContentKind.MEMORY, "m" * 60),
        _provenance_message(ContentKind.DURABLE_CONTEXT, "d" * 70),
        _provenance_message(ContentKind.MIDDLEWARE_INJECTION, "i" * 80, SystemMessage),
    ]

    payload = _snapshot(_middleware(), _request(messages, tools=[builtin_tool, _mcp_tool()]))

    assert payload["system_prompt_tokens"] == 40
    assert payload["builtin_tools_tokens"] == len(builtin_tool.name)
    assert payload["mcp_tools_tokens"] == len(mcp_tool.name)
    assert payload["conversation_tokens"] == 30
    assert payload["tool_result_tokens"] == 30
    assert payload["skill_body_tokens"] == 50
    assert payload["memory_tokens"] == 60
    assert payload["task_state_tokens"] == 70
    assert payload["other_injection_tokens"] == 80
    assert payload["total_tokens"] == 40 + 12 + 8 + 30 + 30 + 50 + 60 + 70 + 80
    assert payload["model_name"] == "test-model"
    assert payload["context_window"] == 1000
    # Only counts are persisted; window-relative figures are derived on read.
    assert "percentage" not in payload


def test_snapshot_without_context_window_still_counts_and_has_no_percentage() -> None:
    payload = _snapshot(_middleware(context_window=None), _request([HumanMessage(content="hi")]))

    assert payload["conversation_tokens"] == 2
    assert payload["total_tokens"] == 42
    assert payload["context_window"] is None


def test_image_payload_follows_the_message_type() -> None:
    messages = [
        _provenance_message(ContentKind.IMAGE_PAYLOAD, "h" * 10, HumanMessage),
        ToolMessage(content="t" * 20, tool_call_id="call-1", additional_kwargs=provenance_kwargs(ContentKind.IMAGE_PAYLOAD, "test_producer")),
    ]

    payload = _snapshot(_middleware(), _request(messages))

    assert payload["conversation_tokens"] == 10
    assert payload["tool_result_tokens"] == 20


def test_unstamped_system_message_counts_as_injection() -> None:
    payload = _snapshot(_middleware(), _request([SystemMessage(content="x" * 12)]))

    assert payload["other_injection_tokens"] == 12
    assert payload["conversation_tokens"] == 0


def test_static_system_prompt_and_tool_schemas_are_counted_once_per_assembly() -> None:
    counter = _CountingCounter()
    middleware = _middleware(counter)
    request = _request([HumanMessage(content="hi")], tools=[builtin_tool, _mcp_tool()])

    _run(middleware, request)
    _run(middleware, request)

    assert counter.tool_count_calls == 2  # one built-in group, one MCP group


def test_tool_set_change_invalidates_the_static_cache() -> None:
    counter = _CountingCounter()
    middleware = _middleware(counter)

    _run(middleware, _request([], tools=[builtin_tool]))
    _run(middleware, _request([], tools=[builtin_tool, _mcp_tool()]))

    assert counter.tool_count_calls == 3


def test_counting_failure_does_not_break_the_model_call() -> None:
    middleware = ContextUsageMiddleware(model_name="test-model", context_window=1000, token_counter=_RaisingCounter())
    handler_calls: list[ModelRequest] = []
    response = ModelResponse(result=[AIMessage(content="ok", id="ai-1")])

    returned = middleware.wrap_model_call(_request([HumanMessage(content="hi")]), lambda request: handler_calls.append(request) or response)

    assert returned is response
    assert len(handler_calls) == 1
    assert CONTEXT_USAGE_KEY not in response.result[0].additional_kwargs


def test_wrap_model_call_stamps_the_last_ai_message_without_mutating_it() -> None:
    middleware = _middleware()
    original = AIMessage(content="final", id="ai-1")

    response, returned = _run(middleware, _request([HumanMessage(content="hi")]), [original])

    stamped = returned.result[-1]
    assert returned is not response
    assert stamped is not original
    assert stamped.id == "ai-1"
    assert CONTEXT_USAGE_KEY not in original.additional_kwargs
    assert stamped.additional_kwargs[CONTEXT_USAGE_KEY]["conversation_tokens"] == 2
    assert stamped.additional_kwargs[CONTEXT_USAGE_KEY]["total_tokens"] == 42


def test_wrap_model_call_leaves_a_response_without_an_ai_message_untouched() -> None:
    middleware = _middleware()
    tool_message = ToolMessage(content="result", tool_call_id="call-1")

    response, returned = _run(middleware, _request([HumanMessage(content="hi")]), [tool_message])

    assert returned is response
    assert CONTEXT_USAGE_KEY not in tool_message.additional_kwargs


def test_stamp_lands_on_the_ai_message_before_a_structured_output_tool_message() -> None:
    middleware = _middleware()
    ai_message = AIMessage(content="", id="ai-1")
    tool_message = ToolMessage(content='{"answer": 1}', tool_call_id="call-1")

    _, returned = _run(middleware, _request([HumanMessage(content="hi")]), [ai_message, tool_message])

    assert CONTEXT_USAGE_KEY in returned.result[0].additional_kwargs
    assert returned.result[1] is tool_message
    assert CONTEXT_USAGE_KEY not in tool_message.additional_kwargs


def test_each_model_call_stamps_only_its_own_response() -> None:
    middleware = _middleware()

    _, first = _run(middleware, _request([HumanMessage(content="one")], runtime=_runtime("thread-a")))
    _, second = _run(middleware, _request([HumanMessage(content="two-two")], runtime=_runtime("thread-b")))

    assert first.result[-1].additional_kwargs[CONTEXT_USAGE_KEY]["conversation_tokens"] == 3
    assert second.result[-1].additional_kwargs[CONTEXT_USAGE_KEY]["conversation_tokens"] == 7


def test_the_stamp_adds_no_stream_step() -> None:
    """A graph node per model call would add a ``values`` SSE event and drift the
    replay golden, so the stamp must ride the model node's own response."""
    baseline = create_agent(FakeListChatModel(responses=["done"]))
    instrumented = create_agent(FakeListChatModel(responses=["done"]), middleware=[_middleware()])

    def steps(graph) -> int:
        return sum(1 for _ in graph.stream({"messages": [HumanMessage(content="hi")]}, stream_mode="values"))

    assert steps(instrumented) == steps(baseline)


def test_snapshot_runs_before_system_message_coalescing() -> None:
    """The injected SystemMessage keeps its own bucket instead of the prompt's."""
    from deerflow.agents.middlewares.system_message_coalescing_middleware import SystemMessageCoalescingMiddleware

    injected = "INJECTED"

    class _InjectSystemMiddleware(AgentMiddleware):
        def wrap_model_call(self, request, handler):
            return handler(
                request.override(
                    messages=[
                        *request.messages,
                        SystemMessage(content=injected, additional_kwargs=provenance_kwargs(ContentKind.MIDDLEWARE_INJECTION, "test_injection")),
                    ]
                )
            )

    middleware = _middleware(_CountingCounter())
    graph = create_agent(
        FakeListChatModel(responses=["done"]),
        system_prompt="STATIC",
        middleware=[_InjectSystemMiddleware(), middleware, SystemMessageCoalescingMiddleware()],
    )

    result = graph.invoke({"messages": [HumanMessage(content="hi")]})
    payload = result["messages"][-1].additional_kwargs[CONTEXT_USAGE_KEY]

    assert payload["system_prompt_tokens"] == len("STATIC")
    assert payload["other_injection_tokens"] == len(injected)


def test_snapshot_survives_token_usage_attribution_in_the_same_step() -> None:
    """TokenUsageMiddleware's after_model node rewrites the same AIMessage.

    It runs after the model node stamped the response; if it did not merge the
    existing kwargs the snapshot would be silently dropped in every real
    lead-agent run.
    """
    from deerflow.agents.middlewares.token_usage_middleware import TOKEN_USAGE_ATTRIBUTION_KEY, TokenUsageMiddleware

    middleware = _middleware(_CountingCounter())
    graph = create_agent(
        FakeListChatModel(responses=["done"]),
        middleware=[TokenUsageMiddleware(), middleware],
    )

    result = graph.invoke({"messages": [HumanMessage(content="hi")]})
    kwargs = result["messages"][-1].additional_kwargs

    assert TOKEN_USAGE_ATTRIBUTION_KEY in kwargs
    assert kwargs[CONTEXT_USAGE_KEY]["total_tokens"] == 2


def test_snapshot_rejects_malformed_persisted_values() -> None:
    valid = ContextUsageSnapshot(system_prompt_tokens=3, conversation_tokens=4).to_dict()
    assert ContextUsageSnapshot.from_dict(valid) is not None

    assert ContextUsageSnapshot.from_dict(None) is None
    assert ContextUsageSnapshot.from_dict("nope") is None
    assert ContextUsageSnapshot.from_dict({**valid, "conversation_tokens": -1}) is None
    assert ContextUsageSnapshot.from_dict({**valid, "conversation_tokens": True}) is None
    assert ContextUsageSnapshot.from_dict({**valid, "memory_tokens": "10"}) is None
    assert ContextUsageSnapshot.from_dict({**valid, "model_name": 7}) is None
    assert ContextUsageSnapshot.from_dict({**valid, "context_window": 0}) is None
    assert ContextUsageSnapshot.from_dict({**valid, "captured_at": 1}) is None


def test_snapshot_total_is_derived_from_the_parts() -> None:
    raw = ContextUsageSnapshot(system_prompt_tokens=3, conversation_tokens=4).to_dict()
    raw["total_tokens"] = 9999

    restored = ContextUsageSnapshot.from_dict(raw)

    assert restored is not None
    assert restored.total_tokens == 7
    assert restored.to_dict()["total_tokens"] == 7


def test_payload_derives_percentage_and_remaining_from_the_window() -> None:
    snapshot = ContextUsageSnapshot(system_prompt_tokens=300, conversation_tokens=200, context_window=1000)

    payload = snapshot.to_payload()

    assert payload["total_tokens"] == 500
    assert payload["percentage"] == 50.0
    assert payload["remaining_tokens"] == 500


def test_payload_keeps_sub_tenth_precision_for_the_formatter() -> None:
    """Rounding to display precision here would turn a real share into 0%."""

    payload = ContextUsageSnapshot(conversation_tokens=1, context_window=10_000).to_payload()

    assert payload["percentage"] == 0.01


def test_payload_clamps_a_full_window_and_leaves_unknown_capacity_open() -> None:
    over = ContextUsageSnapshot(conversation_tokens=1200, context_window=1000).to_payload()
    unknown = ContextUsageSnapshot(conversation_tokens=1200).to_payload()

    assert over["percentage"] == 120.0
    assert over["remaining_tokens"] == 0
    assert unknown["percentage"] is None
    assert unknown["remaining_tokens"] is None


@pytest.mark.parametrize(
    ("kind", "field"),
    [
        (ContentKind.SKILL_BODY, "skill_body_tokens"),
        (ContentKind.MEMORY, "memory_tokens"),
        (ContentKind.DURABLE_CONTEXT, "task_state_tokens"),
        (ContentKind.MIDDLEWARE_INJECTION, "other_injection_tokens"),
    ],
)
def test_each_provenance_kind_maps_to_its_bucket(kind: ContentKind, field: str) -> None:
    payload = _snapshot(_middleware(), _request([_provenance_message(kind, "z" * 9)], system=None))

    assert payload[field] == 9
    assert payload["total_tokens"] == 9
