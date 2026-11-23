"""Regression tests for token budget accounting when a provider reuses
``AIMessage.id`` across distinct model calls in the same Run.

The bug: ``TokenBudgetMiddleware._apply`` keyed its ``seen`` map by
``AIMessage.id`` and counted only the *diff* since the last observation of
that ID.  When two independent model calls returned the same provider message
ID, the second call's diff was zero and its tokens were silently dropped from
the budget — the run could keep executing tools well past the cap.

The fix: ``wrap_model_call`` records a short-lived *pending observation*
(native usage snapshot + message identity) after each successful model call.
``_apply`` confirms that observation against its response anywhere in state and,
on match, accounts the call's full native usage once — independent of what the
``seen`` diff says.  The existing diff scan is preserved for retroactive
subagent-usage increments.

These tests use the real ``create_agent`` graph with scripted model responses
(no network, no paid models).  The graph and middleware are production code;
only the model is fake.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware.types import ModelResponse
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool as as_tool

from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
from deerflow.config.token_budget_config import TokenBudgetConfig

# --------------------------------------------------------------------------- #
# Shared fakes and helpers
# --------------------------------------------------------------------------- #


class _ToolCallingFakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self


def _make_runtime(thread_id="test-thread", run_id="test-run"):
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id, "run_id": run_id}
    return runtime


def _make_request(messages, runtime):
    """Build a minimal ModelRequest double for direct wrap_model_call tests."""
    request = MagicMock()
    request.messages = list(messages)
    request.runtime = runtime

    def override_fn(messages=None, **kwargs):
        new_req = MagicMock()
        new_req.messages = messages if messages is not None else request.messages
        new_req.runtime = request.runtime
        return new_req

    request.override = override_fn
    return request


def _probe_tool(executed: list[int]):
    @as_tool
    def probe(step: int) -> str:
        """Record a harmless diagnostic step."""
        executed.append(step)
        return "ok"

    return probe


def _call(step: int, *, msg_id: str, tokens: int = 600) -> AIMessage:
    return AIMessage(
        content=f"step {step}",
        id=msg_id,
        tool_calls=[{"name": "probe", "id": f"call-{step}", "args": {"step": step}}],
        usage_metadata={"input_tokens": tokens - 50, "output_tokens": 50, "total_tokens": tokens},
    )


def _model_response(message: AIMessage) -> ModelResponse:
    """Wrap a single AIMessage in a ModelResponse, as the real model handler does."""
    return ModelResponse(result=[message])


# --------------------------------------------------------------------------- #
# Core bug: reused AIMessage.id under-counts the budget
# --------------------------------------------------------------------------- #


class TestReusedMessageIDBudget:
    """Two model calls that reuse the same ``AIMessage.id`` must each count."""

    @pytest.mark.parametrize("async_mode", [False, True])
    def test_reused_id_counts_both_calls_and_caps(self, async_mode):
        """cap=1000, two 600-token calls with the same provider ID.

        Before fix: only 600 accounted, both tools run, no cap.
        After fix:  1200 accounted, only step 1 runs, ``token_capped``.
        """
        executed: list[int] = []
        probe = _probe_tool(executed)
        model = _ToolCallingFakeModel(
            responses=[
                _call(1, msg_id="provider-reused-id"),
                _call(2, msg_id="provider-reused-id"),
                AIMessage(content="done", id="answer"),
            ]
        )
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
        graph = create_agent(model=model, tools=[probe], middleware=[mw])
        ctx = {"thread_id": "budget-repro", "run_id": "budget-repro"}

        if async_mode:
            asyncio.run(
                graph.ainvoke(
                    {"messages": [HumanMessage("perform two steps")]},
                    context=ctx,
                    config={"recursion_limit": 20},
                )
            )
        else:
            graph.invoke(
                {"messages": [HumanMessage("perform two steps")]},
                context=ctx,
                config={"recursion_limit": 20},
            )

        usage = mw._cumulative_usage.get("budget-repro")
        assert usage is not None
        assert usage.total == 1200, f"expected 1200, got {usage.total}"
        assert executed == [1], f"only step 1 should execute, got {executed}"
        assert mw.consume_stop_reason("budget-repro") == "token_capped"

    def test_reused_id_same_text_same_usage_still_two_calls(self):
        """Identical content, usage *and* ID must not be deduplicated: these
        are two independent model calls that happen to look the same."""
        executed: list[int] = []
        probe = _probe_tool(executed)
        identical = _call(1, msg_id="dup-id")
        model = _ToolCallingFakeModel(responses=[identical, identical, AIMessage(content="done", id="answer")])
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
        graph = create_agent(model=model, tools=[probe], middleware=[mw])
        graph.invoke(
            {"messages": [HumanMessage("perform two steps")]},
            context={"thread_id": "t", "run_id": "r"},
            config={"recursion_limit": 20},
        )
        usage = mw._cumulative_usage.get("r")
        assert usage is not None
        assert usage.total == 1200

    def test_reused_id_different_usage_counts_each_native_amount(self):
        """When the reused-ID calls have *different* usage, each call's own
        native usage must be counted — not the diff between them."""
        executed: list[int] = []
        probe = _probe_tool(executed)
        model = _ToolCallingFakeModel(
            responses=[
                AIMessage(content="s1", id="shared", tool_calls=[{"name": "probe", "id": "c1", "args": {"step": 1}}], usage_metadata={"input_tokens": 400, "output_tokens": 0, "total_tokens": 400}),
                AIMessage(content="s2", id="shared", tool_calls=[{"name": "probe", "id": "c2", "args": {"step": 2}}], usage_metadata={"input_tokens": 800, "output_tokens": 0, "total_tokens": 800}),
                AIMessage(content="done", id="answer"),
            ]
        )
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=10000))
        graph = create_agent(model=model, tools=[probe], middleware=[mw])
        graph.invoke(
            {"messages": [HumanMessage("two steps")]},
            context={"thread_id": "t", "run_id": "r"},
            config={"recursion_limit": 20},
        )
        usage = mw._cumulative_usage.get("r")
        assert usage is not None
        assert usage.total == 1200  # 400 + 800


# --------------------------------------------------------------------------- #
# Preserved behavior: unique IDs must not be double-counted
# --------------------------------------------------------------------------- #


class TestUniqueIDBehaviorPreserved:
    """When IDs are unique, the fix must not change accounting."""

    @pytest.mark.parametrize("async_mode", [False, True])
    def test_unique_ids_behave_as_before(self, async_mode):
        executed: list[int] = []
        probe = _probe_tool(executed)
        model = _ToolCallingFakeModel(
            responses=[
                _call(1, msg_id="id-1"),
                _call(2, msg_id="id-2"),
                AIMessage(content="done", id="answer"),
            ]
        )
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
        graph = create_agent(model=model, tools=[probe], middleware=[mw])
        ctx = {"thread_id": "t", "run_id": "r"}

        if async_mode:
            asyncio.run(
                graph.ainvoke(
                    {"messages": [HumanMessage("two steps")]},
                    context=ctx,
                    config={"recursion_limit": 20},
                )
            )
        else:
            graph.invoke(
                {"messages": [HumanMessage("two steps")]},
                context=ctx,
                config={"recursion_limit": 20},
            )

        usage = mw._cumulative_usage.get("r")
        assert usage is not None
        assert usage.total == 1200
        assert executed == [1]
        assert mw.consume_stop_reason("r") == "token_capped"

    def test_repeated_after_model_does_not_grow(self):
        """Calling ``_apply`` twice on the same state must not double-count."""
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=10_000))
        runtime = _make_runtime()
        msg = AIMessage(id="m1", content="hi", usage_metadata={"input_tokens": 500, "output_tokens": 0, "total_tokens": 500})
        state = {"messages": [msg]}
        mw._apply(state, runtime)
        first = mw._cumulative_usage["test-run"].total
        mw._apply(state, runtime)
        second = mw._cumulative_usage["test-run"].total
        assert first == second == 500


# --------------------------------------------------------------------------- #
# Historical messages + new Run sharing the same ID (direct wrap_model_call)
# --------------------------------------------------------------------------- #


class TestHistoricalSameIDNewRun:
    """A historical AIMessage seeded by ``before_agent`` must not be counted
    in the new Run's budget, even when the new call reuses its ID.

    Uses ``wrap_model_call`` + ``_apply`` directly because the message reducer's
    in-place replacement makes graph-level continuation with reused IDs behave
    differently from the budget accounting we are testing here.
    """

    def test_historical_not_counted_new_call_fully_counted(self):
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=10_000))
        runtime = _make_runtime(run_id="new-run")

        # Historical message from a previous run — seeded by before_agent.
        historical = AIMessage(
            id="reused",
            content="old",
            usage_metadata={"input_tokens": 300, "output_tokens": 0, "total_tokens": 300},
        )
        mw.before_agent({"messages": [historical]}, runtime)
        assert mw._seen_messages["new-run"].get("reused") == (300, 0)

        # New model call reuses the same ID but with different usage.
        new_call = AIMessage(
            id="reused",
            content="new",
            usage_metadata={"input_tokens": 600, "output_tokens": 0, "total_tokens": 600},
        )

        # Simulate the model returning this response via wrap_model_call.
        request = _make_request([historical], runtime)
        mw.wrap_model_call(request, lambda req: _model_response(new_call))

        # after_model sees the state with the new call as the last message.
        mw._apply({"messages": [historical, new_call]}, runtime)

        usage = mw._cumulative_usage["new-run"]
        # Only the new call's 600 should be counted, not the historical 300
        # (diff) or 900 (sum).
        assert usage.total == 600

    def test_historical_same_usage_new_call_zero_diff(self):
        """Historical and new call share the same ID *and* the same usage.
        The new call must still be counted (its native usage), not zero."""
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=10_000))
        runtime = _make_runtime(run_id="r")

        historical = AIMessage(
            id="shared",
            content="old",
            usage_metadata={"input_tokens": 500, "output_tokens": 0, "total_tokens": 500},
        )
        mw.before_agent({"messages": [historical]}, runtime)

        new_call = AIMessage(
            id="shared",
            content="new",
            usage_metadata={"input_tokens": 500, "output_tokens": 0, "total_tokens": 500},
        )
        request = _make_request([historical], runtime)
        mw.wrap_model_call(request, lambda req: _model_response(new_call))
        mw._apply({"messages": [historical, new_call]}, runtime)

        assert mw._cumulative_usage["r"].total == 500


# --------------------------------------------------------------------------- #
# No native ID: reducer assigns one, must be counted once
# --------------------------------------------------------------------------- #


class TestNoNativeID:
    """A response without an ``id`` gets one from the reducer; it must be
    counted exactly once."""

    def test_no_id_counted_once_via_graph(self):
        """Model returns an AIMessage without an ``id``.  The reducer assigns
        one; the budget must count it exactly once."""
        executed: list[int] = []
        probe = _probe_tool(executed)
        no_id_call = AIMessage(
            content="step 1",
            id=None,
            tool_calls=[{"name": "probe", "id": "call-1", "args": {"step": 1}}],
            usage_metadata={"input_tokens": 500, "output_tokens": 0, "total_tokens": 500},
        )
        model = _ToolCallingFakeModel(responses=[no_id_call, AIMessage(content="done", id="answer")])
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=10_000))
        graph = create_agent(model=model, tools=[probe], middleware=[mw])
        graph.invoke(
            {"messages": [HumanMessage("do step 1")]},
            context={"thread_id": "no-id-t", "run_id": "no-id-r"},
            config={"recursion_limit": 20},
        )
        usage = mw._cumulative_usage.get("no-id-r")
        assert usage is not None
        assert usage.total == 500


# --------------------------------------------------------------------------- #
# Pending confirmation: model_copy, retroactive usage
# --------------------------------------------------------------------------- #


class TestPendingConfirmation:
    """Verify the observe/confirm mechanism handles edge cases."""

    def test_model_copy_preserving_id_counted_once(self):
        """When a middleware does ``model_copy()`` (preserving the ID) before
        ``after_model``, the new cost must still be counted once."""
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=10_000))
        runtime = _make_runtime()
        original = AIMessage(
            id="m1",
            content="hello",
            usage_metadata={"input_tokens": 500, "output_tokens": 0, "total_tokens": 500},
        )
        copied = original.model_copy()
        assert copied is not original
        assert copied.id == original.id
        mw.wrap_model_call(_make_request([], runtime), lambda request: _model_response(original))
        state = {"messages": [copied]}
        mw._apply(state, runtime)
        usage = mw._cumulative_usage["test-run"]
        assert usage.total == 500

    def test_retroactive_subagent_usage_only_increments(self):
        """Model returns 500 tokens; a retroactive subagent bump raises the
        same message's usage to 800.  Total must be 800, not 500+800."""
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=10_000))
        runtime = _make_runtime()
        msg = AIMessage(
            id="m1",
            content="hi",
            usage_metadata={"input_tokens": 500, "output_tokens": 0, "total_tokens": 500},
        )
        mw._apply({"messages": [msg]}, runtime)
        assert mw._cumulative_usage["test-run"].total == 500

        bumped = AIMessage(
            id="m1",
            content="hi",
            usage_metadata={"input_tokens": 800, "output_tokens": 0, "total_tokens": 800},
        )
        mw._apply({"messages": [bumped]}, runtime)
        assert mw._cumulative_usage["test-run"].total == 800  # 500 + 300 increment


# --------------------------------------------------------------------------- #
# Lifecycle: disabled, reset, identity
# --------------------------------------------------------------------------- #


class TestLifecycleAndIdentity:
    def test_disabled_config_no_side_effects(self):
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=False, max_tokens=1000))
        runtime = _make_runtime()
        msg = AIMessage(id="m1", content="hi", usage_metadata={"input_tokens": 500, "output_tokens": 0, "total_tokens": 500})
        result = mw._apply({"messages": [msg]}, runtime)
        assert result is None
        assert mw.wrap_model_call(_make_request([], runtime), lambda request: _model_response(msg)).result == [msg]
        assert not mw._pending_model_calls
        assert "test-run" not in mw._cumulative_usage

    def test_reset_clears_all_state(self):
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
        runtime = _make_runtime()
        msg = AIMessage(id="m1", content="hi", usage_metadata={"input_tokens": 500, "output_tokens": 0, "total_tokens": 500})
        mw._apply({"messages": [msg]}, runtime)
        assert "test-run" in mw._cumulative_usage
        mw.wrap_model_call(_make_request([], runtime), lambda request: _model_response(msg))
        assert "test-run" in mw._pending_model_calls
        mw.reset()
        for store in (mw._cumulative_usage, mw._seen_messages, mw._pending_warnings, mw._warned, mw._pending_model_calls):
            assert not store

    def test_message_and_tool_call_identity_preserved(self):
        """The fix must not mutate any AIMessage.id, tool-call ID, content,
        or provider metadata — it only changes budget accounting."""
        executed: list[int] = []
        probe = _probe_tool(executed)
        responses = [
            AIMessage(
                content="step 1",
                id="provider-x",
                tool_calls=[{"name": "probe", "id": "toolu_abc", "args": {"step": 1}}],
                usage_metadata={"input_tokens": 550, "output_tokens": 50, "total_tokens": 600},
                additional_kwargs={"provider": "anthropic"},
            ),
            AIMessage(content="final answer", id="provider-y", usage_metadata={"input_tokens": 100, "output_tokens": 0, "total_tokens": 100}),
        ]
        model = _ToolCallingFakeModel(responses=responses)
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=10_000))
        graph = create_agent(model=model, tools=[probe], middleware=[mw])
        state = graph.invoke(
            {"messages": [HumanMessage("do step 1")]},
            context={"thread_id": "id-t", "run_id": "id-r"},
            config={"recursion_limit": 20},
        )
        msgs = state["messages"]
        ai_with_tool = next(m for m in msgs if isinstance(m, AIMessage) and m.tool_calls)
        assert ai_with_tool.id == "provider-x"
        assert ai_with_tool.tool_calls[0]["id"] == "toolu_abc"
        assert ai_with_tool.additional_kwargs.get("provider") == "anthropic"


@pytest.mark.parametrize("async_mode", [False, True])
def test_nonconsecutive_reused_id_counts_all_calls_and_stops_current_response(async_mode):
    executed = []
    responses = [_call(step, msg_id=identity) for step, identity in enumerate(("a", "b", "a"), 1)]
    responses.append(AIMessage(content="done", id="answer"))
    mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1500))
    graph = create_agent(_ToolCallingFakeModel(responses=responses), tools=[_probe_tool(executed)], middleware=[mw])
    kwargs = {"context": {"run_id": "r", "thread_id": "t"}, "config": {"recursion_limit": 20}}
    state = asyncio.run(graph.ainvoke({"messages": [HumanMessage("three steps")]}, **kwargs)) if async_mode else graph.invoke({"messages": [HumanMessage("three steps")]}, **kwargs)

    assert mw._cumulative_usage["r"].total == 1800
    assert mw.consume_stop_reason("r") == "token_capped"
    assert kwargs["context"]["stop_reason"] == "token_capped"
    current = next(message for message in state["messages"] if message.id == "a")
    previous = next(message for message in state["messages"] if message.id == "b")
    assert "step 3" in current.content
    assert "TOKEN BUDGET EXCEEDED" in current.content
    assert current.tool_calls == []
    assert previous.tool_calls[0]["id"] == "call-2"
    assert executed == [1, 2]


@pytest.mark.parametrize("async_mode", [False, True])
def test_empty_history_clears_pending_but_keeps_same_run_budget(async_mode):
    mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=10_000))
    runtime = _make_runtime()
    message = _call(1, msg_id="a")
    mw._apply({"messages": [message]}, runtime)
    mw.wrap_model_call(_make_request([], runtime), lambda request: _model_response(message))
    assert "test-run" in mw._pending_model_calls
    if async_mode:
        asyncio.run(mw.abefore_agent({"messages": []}, runtime))
    else:
        mw.before_agent({"messages": []}, runtime)
    assert "test-run" not in mw._pending_model_calls
    assert mw._cumulative_usage["test-run"].total == 600


def test_pending_snapshot_and_retroactive_usage_are_counted_once():
    mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=10_000))
    runtime = _make_runtime()
    message = _call(1, msg_id="a", tokens=500)
    mw.wrap_model_call(_make_request([], runtime), lambda request: _model_response(message))
    message.usage_metadata["input_tokens"] += 300
    message.usage_metadata["total_tokens"] += 300
    assert mw._pending_model_calls["test-run"].input_tokens == 450
    for _ in range(2):
        mw._apply({"messages": [message]}, runtime)
    assert mw._cumulative_usage["test-run"].total == 800
    assert not mw._pending_model_calls


def test_historical_message_after_tool_result_is_not_rewritten_without_pending():
    mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
    runtime = _make_runtime()
    historical = _call(1, msg_id="old", tokens=1200)
    result = mw._apply({"messages": [historical, ToolMessage(content="ok", tool_call_id="call-1")]}, runtime)
    assert result is None
    assert "test-run" not in mw._cumulative_usage


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_handler_failure_discards_unconfirmed_response(async_mode, failure):
    mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
    runtime = _make_runtime()
    request = _make_request([], runtime)
    mw.wrap_model_call(request, lambda request: _model_response(_call(1, msg_id="a")))

    def broken(request):
        raise failure()

    async def abroken(request):
        raise failure()

    with pytest.raises(failure):
        if async_mode:
            asyncio.run(mw.awrap_model_call(request, abroken))
        else:
            mw.wrap_model_call(request, broken)
    assert not mw._pending_model_calls


def test_response_without_ai_discards_previous_pending():
    mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
    runtime = _make_runtime()
    request = _make_request([], runtime)
    mw.wrap_model_call(request, lambda request: _model_response(_call(1, msg_id="a")))
    mw.wrap_model_call(request, lambda request: ModelResponse(result=[]))
    assert not mw._pending_model_calls


def test_unrelated_error_fallback_does_not_confirm_historical_same_id():
    from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig

    mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
    runtime = _make_runtime()
    historical = _call(1, msg_id="a")
    mw.before_agent({"messages": [historical]}, runtime)
    mw.wrap_model_call(_make_request([historical], runtime), lambda request: _model_response(_call(2, msg_id="a")))
    fallback = LLMErrorHandlingMiddleware(app_config=AppConfig(sandbox=SandboxConfig(use="test")))._build_error_fallback_message("failed", error_type="RuntimeError", reason="other", detail="failed")
    fallback.id = "fallback"
    assert mw._apply({"messages": [historical, fallback]}, runtime) is None
    assert mw._cumulative_usage["test-run"].total == 0
    assert not mw._pending_model_calls


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("always_empty", [False, True])
def test_outer_empty_response_retry_accounts_only_the_accepted_result(monkeypatch, async_mode, always_empty):
    from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig

    empty = AIMessage(content="", id="reused", usage_metadata={"input_tokens": 600, "output_tokens": 0, "total_tokens": 600})
    accepted = AIMessage(content="accepted", id="reused", usage_metadata={"input_tokens": 600, "output_tokens": 0, "total_tokens": 600})
    model = _ToolCallingFakeModel(responses=[empty] if always_empty else [empty, accepted])
    errors = LLMErrorHandlingMiddleware(app_config=AppConfig(sandbox=SandboxConfig(use="test")))
    monkeypatch.setattr(errors, "_build_retry_delay_ms", lambda *args: 0)
    mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
    graph = create_agent(model=model, middleware=[errors, mw])
    kwargs = {"context": {"run_id": "r", "thread_id": "t"}}
    state = asyncio.run(graph.ainvoke({"messages": [HumanMessage("answer")]}, **kwargs)) if async_mode else graph.invoke({"messages": [HumanMessage("answer")]}, **kwargs)
    assert mw._cumulative_usage["r"].total == 600
    assert not mw._pending_model_calls
    assert mw.consume_stop_reason("r") is None
    if always_empty:
        assert state["messages"][-1].additional_kwargs["deerflow_error_fallback"] is True
    else:
        assert state["messages"][-1].content == "accepted"


@pytest.mark.parametrize("run_id", ["r", None])
def test_agent_cleanup_drops_pending_for_continuations_and_unidentified_runs(run_id):
    mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
    runtime = _make_runtime(run_id=run_id)
    mw.wrap_model_call(_make_request([], runtime), lambda request: _model_response(_call(1, msg_id="a")))
    assert mw._pending_model_calls
    mw.after_agent({"messages": []}, runtime)
    assert not mw._pending_model_calls


@pytest.mark.parametrize(("input_tokens", "output_tokens"), [(-100, 0), (-100, 50), (0, -100), (50, -100)])
def test_negative_provider_usage_cannot_refund_the_run_budget(input_tokens, output_tokens):
    mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=10_000))
    runtime = _make_runtime()
    previous = _call(1, msg_id="previous")
    mw._apply({"messages": [previous]}, runtime)
    unknown = AIMessage(content="provider usage", id="unknown", usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens})
    mw.wrap_model_call(_make_request([previous], runtime), lambda request: _model_response(unknown))
    for _ in range(2):
        mw._apply({"messages": [previous, unknown]}, runtime)
    assert mw._cumulative_usage["test-run"].total == 600 + max(0, input_tokens) + max(0, output_tokens)
    assert unknown.usage_metadata["input_tokens"] == input_tokens
    assert unknown.usage_metadata["output_tokens"] == output_tokens


@pytest.mark.parametrize("async_mode", [False, True])
def test_structured_output_keeps_completed_tool_pair_at_budget_stop(async_mode):
    from pydantic import BaseModel

    from deerflow.models.claude_provider import ClaudeChatModel

    class Answer(BaseModel):
        answer: str

    reply = AIMessage(content="", id="structured", tool_calls=[{"name": "Answer", "id": "schema-call", "args": {"answer": "ok"}}], usage_metadata={"input_tokens": 1200, "output_tokens": 0, "total_tokens": 1200})
    mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
    graph = create_agent(_ToolCallingFakeModel(responses=[reply]), middleware=[mw], response_format=Answer)
    kwargs = {"context": {"run_id": "r", "thread_id": "t"}}
    state = asyncio.run(graph.ainvoke({"messages": [HumanMessage("answer")]}, **kwargs)) if async_mode else graph.invoke({"messages": [HumanMessage("answer")]}, **kwargs)

    assert state["structured_response"].answer == "ok"
    assert mw._cumulative_usage["r"].total == 1200
    assert mw.consume_stop_reason("r") == "token_capped"
    message = next(message for message in state["messages"] if isinstance(message, AIMessage))
    assert message.tool_calls[0]["id"] == "schema-call"
    assert "TOKEN BUDGET EXCEEDED" in message.content
    payload = ClaudeChatModel(model="claude-sonnet-4-5", anthropic_api_key="sk-ant-offline")._get_request_payload(state["messages"] + [HumanMessage("continue")])
    uses = {block["id"] for turn in payload["messages"] if isinstance(turn["content"], list) for block in turn["content"] if block["type"] == "tool_use"}
    results = {block["tool_use_id"] for turn in payload["messages"] if isinstance(turn["content"], list) for block in turn["content"] if block["type"] == "tool_result"}
    assert uses == results == {"schema-call"}
