"""End-to-end graph integration test for SafetyFinishReasonMiddleware.

Unit tests prove ``_apply`` does the right thing on a synthetic state.
This test does one level up: builds a real ``langchain.agents.create_agent``
graph with the SafetyFinishReasonMiddleware in place, feeds it a fake model
that returns ``finish_reason='content_filter'`` + tool_calls, and asserts:

  1. The tool node is **not** invoked (the dangerous truncated tool call
     is suppressed).
  2. The final AIMessage in graph state has ``tool_calls == []``.
  3. The observability ``safety_termination`` record is attached.
  4. The user-facing explanation is appended to the message content.

This is the closest we can get to the issue's failure mode without a live
Moonshot key, and it proves the middleware actually gates LangChain's
tool router — not just rewrites state in isolation.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware

_TOOL_INVOCATIONS: list[dict[str, Any]] = []


@tool
def write_file(path: str, content: str) -> str:
    """Pretend to write *content* to *path*. Records the call for assertion."""
    _TOOL_INVOCATIONS.append({"path": path, "content": content})
    return f"wrote {len(content)} bytes to {path}"


class _ContentFilteredModel(BaseChatModel):
    """Fake chat model that mimics OpenAI/Moonshot's content_filter response.

    First call returns finish_reason='content_filter' + a tool_call whose
    arguments are visibly truncated. Second call (if reached) returns a
    normal text completion so the agent can terminate cleanly.
    """

    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-content-filtered"

    def bind_tools(self, tools, **kwargs):
        # create_agent binds tools onto the model; we don't actually need
        # to bind anything since responses are hard-coded, but the method
        # must not raise.
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            message = AIMessage(
                content="Here is the report:\n# Weekly Politics\n- Meeting time: 2026-05-12—",
                tool_calls=[
                    {
                        "id": "call_truncated_1",
                        "name": "write_file",
                        "args": {
                            "path": "/mnt/user-data/outputs/report.md",
                            "content": "# Weekly Politics\n- Meeting time: 2026-05-12—",
                        },
                    }
                ],
                response_metadata={"finish_reason": "content_filter", "model_name": "fake-kimi"},
            )
        else:
            message = AIMessage(content="ack", response_metadata={"finish_reason": "stop"})
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _InspectMiddleware(AgentMiddleware):
    """Captures the messages list at every model entry so we can assert
    no synthetic tool result was injected back into the conversation."""

    def __init__(self) -> None:
        super().__init__()
        self.observed: list[list[Any]] = []

    def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        self.observed.append(list(request.messages))
        return handler(request)


def test_content_filter_with_tool_calls_does_not_invoke_tool_node():
    _TOOL_INVOCATIONS.clear()
    inspector = _InspectMiddleware()

    agent = create_agent(
        model=_ContentFilteredModel(),
        tools=[write_file],
        # Inspector first so its after_model is registered; Safety last in
        # the list so it executes first under LIFO (matches production wiring).
        middleware=[inspector, SafetyFinishReasonMiddleware()],
    )

    result = agent.invoke({"messages": [HumanMessage(content="write me a report")]})

    # Critical assertion: the dangerous truncated tool call must NOT have
    # been executed. This is the entire point of the middleware.
    assert _TOOL_INVOCATIONS == [], f"write_file was invoked despite content_filter: {_TOOL_INVOCATIONS}"

    # Final AIMessage has no tool calls left.
    final_ai = next(m for m in reversed(result["messages"]) if isinstance(m, AIMessage))
    assert final_ai.tool_calls == []

    # Observability stamp is present.
    record = final_ai.additional_kwargs.get("safety_termination")
    assert record is not None
    assert record["detector"] == "openai_compatible_content_filter"
    assert record["reason_field"] == "finish_reason"
    assert record["reason_value"] == "content_filter"
    assert record["suppressed_tool_call_count"] == 1
    assert record["suppressed_tool_call_names"] == ["write_file"]

    # User-facing explanation is appended.
    assert "safety-related signal" in final_ai.content
    # Original partial text preserved (we don't throw away what the user
    # already saw in the stream — see middleware docstring).
    assert "Weekly Politics" in final_ai.content

    # finish_reason on response_metadata is preserved (so SSE / converters
    # downstream still see the real provider reason).
    assert final_ai.response_metadata.get("finish_reason") == "content_filter"


@pytest.mark.anyio
async def test_safety_termination_event_reaches_astream_events():
    """Exercise the middleware's real async graph hook and callback context."""

    _TOOL_INVOCATIONS.clear()
    agent = create_agent(
        model=_ContentFilteredModel(),
        tools=[write_file],
        middleware=[SafetyFinishReasonMiddleware()],
        context_schema=dict,
    )

    events = [
        event
        async for event in agent.astream_events(
            {"messages": [HumanMessage(content="write me a report")]},
            version="v2",
            context={"thread_id": "safety-stream-thread"},
        )
        if event["event"] == "on_custom_event"
    ]

    assert len(events) == 1
    assert events[0]["name"] == "safety_termination"
    assert events[0]["data"] == {
        "type": "safety_termination",
        "detector": "openai_compatible_content_filter",
        "reason_field": "finish_reason",
        "reason_value": "content_filter",
        "suppressed_tool_call_count": 1,
        "suppressed_tool_call_names": ["write_file"],
        "thread_id": "safety-stream-thread",
    }
    assert _TOOL_INVOCATIONS == []


def test_content_filter_without_tool_calls_passes_through_unchanged():
    """No tool calls => issue scope says don't intervene; the partial
    response should be delivered as-is so the user sees what they got."""
    _TOOL_INVOCATIONS.clear()

    class _NoToolModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "fake-no-tool"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            msg = AIMessage(
                content="Partial answer truncated by safety filter",
                response_metadata={"finish_reason": "content_filter"},
            )
            return ChatResult(generations=[ChatGeneration(message=msg)])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    agent = create_agent(
        model=_NoToolModel(),
        tools=[write_file],
        middleware=[SafetyFinishReasonMiddleware()],
    )
    result = agent.invoke({"messages": [HumanMessage(content="hi")]})
    final_ai = next(m for m in reversed(result["messages"]) if isinstance(m, AIMessage))

    # Content untouched.
    assert final_ai.content == "Partial answer truncated by safety filter"
    # No safety_termination stamp because we didn't intervene.
    assert "safety_termination" not in final_ai.additional_kwargs
    # tool node never ran (there were no tool calls in the first place).
    assert _TOOL_INVOCATIONS == []


def test_content_filter_empty_no_tool_calls_is_backfilled_not_persisted_empty():
    """#4393: a content_filter response with empty content and no tool calls
    must not survive in graph state as an empty AIMessage — strict
    OpenAI-compatible providers reject an empty assistant message on the next
    request, poisoning the whole thread. The middleware backfills a
    user-facing explanation so the persisted message is non-empty."""
    _TOOL_INVOCATIONS.clear()

    class _EmptyContentFilterModel(BaseChatModel):
        """Mimics Kimi/Moonshot refusing a sensitive question: an empty
        assistant message flagged finish_reason='content_filter'."""

        @property
        def _llm_type(self) -> str:
            return "fake-empty-content-filter"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            msg = AIMessage(content="", response_metadata={"finish_reason": "content_filter"})
            return ChatResult(generations=[ChatGeneration(message=msg)])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    agent = create_agent(
        model=_EmptyContentFilterModel(),
        tools=[write_file],
        middleware=[SafetyFinishReasonMiddleware()],
    )
    result = agent.invoke({"messages": [HumanMessage(content="a sensitive question")]})
    final_ai = next(m for m in reversed(result["messages"]) if isinstance(m, AIMessage))

    # The poison condition: the persisted assistant message must not be empty.
    assert isinstance(final_ai.content, str)
    assert final_ai.content.strip(), "empty assistant message would be rejected by strict providers on the next turn"
    assert "safety-related signal" in final_ai.content
    assert "returned no content" in final_ai.content

    # Observability stamp present with zero suppressed tool calls.
    record = final_ai.additional_kwargs.get("safety_termination")
    assert record is not None
    assert record["suppressed_tool_call_count"] == 0

    # Real provider reason preserved for downstream SSE / converters.
    assert final_ai.response_metadata.get("finish_reason") == "content_filter"
    assert _TOOL_INVOCATIONS == []


def test_normal_tool_call_round_trip_is_not_affected():
    """Regression: a healthy finish_reason='tool_calls' response must still
    execute the tool. The middleware must not over-fire."""
    _TOOL_INVOCATIONS.clear()

    class _HealthyToolModel(BaseChatModel):
        call_count: int = 0

        @property
        def _llm_type(self) -> str:
            return "fake-healthy"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.call_count += 1
            if self.call_count == 1:
                msg = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_ok",
                            "name": "write_file",
                            "args": {"path": "/tmp/ok", "content": "complete content"},
                        }
                    ],
                    response_metadata={"finish_reason": "tool_calls"},
                )
            else:
                msg = AIMessage(content="done", response_metadata={"finish_reason": "stop"})
            return ChatResult(generations=[ChatGeneration(message=msg)])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    agent = create_agent(
        model=_HealthyToolModel(),
        tools=[write_file],
        middleware=[SafetyFinishReasonMiddleware()],
    )
    agent.invoke({"messages": [HumanMessage(content="write")]})

    assert _TOOL_INVOCATIONS == [{"path": "/tmp/ok", "content": "complete content"}]
