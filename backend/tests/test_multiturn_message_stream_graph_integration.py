"""Graph-integration invariants for the multi-turn message stream.

Single-middleware unit tests prove each middleware's ``_apply`` in isolation.
This test sits one level up: it builds a real ``langchain.agents.create_agent``
graph with the real ``DynamicContextMiddleware`` and a checkpointer, then drives
**two user turns on the same thread** with a deterministic fake model — the
composition (middleware + ``add_messages`` reducer + persisted checkpoint state)
where message-stream corruption actually emerges.

It is a net for the *class* of bug behind #3684, not just that instance: a
middleware mutating message state across turns must not strand the newest user
message, re-answer a stale turn, duplicate ids, or explode id suffixes. The
trigger condition is memory injection enabled (a separate dateless ``<memory>``
reminder lands in history) — so memory is stubbed on, deterministically.

Why here and not e2e replay: replay disables memory, uses a single-turn golden,
and replays recorded model output by input-hash while asserting SSE *shape* — so
it cannot reproduce or detect this class. This runs at unit speed in ``make test``
(the ``backend-unit-tests`` workflow) with no gateway, SSE, fixtures, or API key.

To widen the net, add more state-touching middlewares (input sanitization,
summarization, uploads) to ``_STREAM_MIDDLEWARES`` and keep the invariants.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import Runnable
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares.dynamic_context_middleware import (
    DynamicContextMiddleware,
    is_dynamic_context_reminder,
)

_TURN_1 = "test"
_TURN_2 = "tell me the weather of next week in berlin"
_FIXED_DATE = "2026-05-08, Friday"
_MEMORY = "<memory>\nUser prefers concise answers.\n</memory>"


class _FakeModel(FakeMessagesListChatModel):
    """Deterministic model with the no-op ``bind_tools`` ``create_agent`` needs."""

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> Runnable:  # type: ignore[override]
        return self


class _RecordModelInput(AgentMiddleware):
    """Capture the message list handed to the model on each call.

    The bug is observable here: on turn 2 the model must receive the new user
    message as its latest human turn, not a re-injected stale one.
    """

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[list[Any]] = []

    def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        self.calls.append(list(request.messages))
        return handler(request)

    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        self.calls.append(list(request.messages))
        return await handler(request)


def _msg_text(msg: Any) -> str:
    """Flatten a message's content (string or list-of-blocks) to plain text."""
    content = msg.content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


def _last_human_text(messages: list[Any]) -> str:
    """Text of the last genuine (non-hidden, non-reminder) human message."""
    for msg in reversed(messages):
        if not isinstance(msg, HumanMessage):
            continue
        if msg.additional_kwargs.get("hide_from_ui") or is_dynamic_context_reminder(msg):
            continue
        return _msg_text(msg)
    return ""


def _assert_stream_well_formed(messages: list[Any], *, newest_user_text: str) -> None:
    """Structural invariants the multi-turn message stream must satisfy.

    Checked semantic-first: the primary guarantee (the newest user message is the
    latest human turn) fails before the structural id checks, so the regression
    surfaces as a meaning-level failure rather than only an id-shape artifact.
    """
    # The newest user message must be the latest human turn the model reasons about.
    assert _last_human_text(messages) == newest_user_text, "newest user message is not the latest human turn (stranded / stale re-answer)"

    # ...and it must appear exactly once (not stranded earlier + re-appended).
    occurrences = sum(1 for m in messages if isinstance(m, HumanMessage) and _msg_text(m) == newest_user_text)
    assert occurrences == 1, f"newest user message appears {occurrences} times, expected 1"

    ids = [m.id for m in messages if m.id is not None]
    assert len(ids) == len(set(ids)), f"duplicate message ids in stream: {ids}"

    # ID-swap derives one ``__user`` suffix per reminder injection. A doubled
    # ``__user__user`` means a turn was re-injected onto an already-injected
    # message — the #3684 signature.
    assert not any("__user__user" in (mid or "") for mid in ids), f"id-suffix explosion (re-injection): {ids}"


# State-touching middlewares under test, as zero-arg factories. Widen the net by
# adding more here (e.g. InputSanitizationMiddleware, SummarizationMiddleware) — the
# invariants in _assert_stream_well_formed apply to the whole composition.
_STREAM_MIDDLEWARES: tuple[type[AgentMiddleware], ...] = (DynamicContextMiddleware,)


def _run_two_turns() -> tuple[dict, _RecordModelInput]:
    recorder = _RecordModelInput()
    agent = create_agent(
        model=_FakeModel(responses=[AIMessage(content="ack-1"), AIMessage(content="ack-2")]),
        tools=[],
        # Recorder first so its wrap_model_call observes the final request;
        # the state-touching middlewares do their work in before_agent.
        middleware=[recorder, *(make() for make in _STREAM_MIDDLEWARES)],
        checkpointer=InMemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "stream-invariants-1"}}

    with (
        mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=_MEMORY),
        mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = _FIXED_DATE
        agent.invoke({"messages": [HumanMessage(content=_TURN_1, id="u1")]}, cfg)
        final = agent.invoke({"messages": [HumanMessage(content=_TURN_2, id="u2")]}, cfg)

    return final, recorder


def test_second_turn_model_receives_newest_user_message():
    """The model on turn 2 must reason about the new message, not a stale one."""
    _final, recorder = _run_two_turns()

    assert len(recorder.calls) >= 2, f"expected a model call per turn, got {len(recorder.calls)}"
    turn_2_request = recorder.calls[-1]
    _assert_stream_well_formed(turn_2_request, newest_user_text=_TURN_2)


def test_second_turn_persisted_state_is_well_formed():
    """The persisted checkpoint state after turn 2 stays ordered and de-duplicated."""
    final, _recorder = _run_two_turns()
    _assert_stream_well_formed(final["messages"], newest_user_text=_TURN_2)
