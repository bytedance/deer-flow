from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool as as_tool
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
from deerflow.config.token_budget_config import TokenBudgetConfig


def _make_runtime(thread_id="test-thread", run_id="test-run"):
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id, "run_id": run_id}
    return runtime


def _make_request(messages, runtime):
    request = MagicMock()
    request.messages = list(messages)
    request.runtime = runtime

    def override_fn(messages=None, **kwags):
        new_req = MagicMock()
        new_req.messages = messages if messages is not None else request.messages
        new_req.runtime = request.runtime
        return new_req

    request.override = override_fn
    return request


def _capture_handler():
    captured: list = []

    def handler(req):
        captured.append(req)
        return MagicMock()

    return captured, handler


def _make_state_with_usage(total: int, input_tk: int = 0, output_tk: int = 0, tool_calls=None, content=""):
    """Build a state dict with a single AIMessage containing usage."""
    if input_tk == 0 and output_tk == 0:
        input_tk = total
    msg = AIMessage(id="test-msg", content=content, tool_calls=tool_calls or [], usage_metadata={"input_tokens": input_tk, "output_tokens": output_tk, "total_tokens": total})
    return {"messages": [msg]}


class TestTokenBudgetTracking:
    def test_no_usage_metadata_returns_none(self):
        config = TokenBudgetConfig(max_tokens=1000, enabled=True)
        mw = TokenBudgetMiddleware.from_config(config)

        state = {"messages": [AIMessage(content="hello", tool_calls=[])]}
        result = mw._apply(state, _make_runtime())
        assert result is None

    def test_below_threshold_returns_none(self):
        config = TokenBudgetConfig(max_tokens=100000, warn_threshold=0.8, enabled=True)
        mw = TokenBudgetMiddleware.from_config(config)

        state = _make_state_with_usage(total=50000)
        result = mw._apply(state, _make_runtime())
        assert result is None

    def test_warning_threshold_injects_warning_and_returns_none(self):
        config = TokenBudgetConfig(max_tokens=100000, warn_threshold=0.8, enabled=True)
        mw = TokenBudgetMiddleware.from_config(config)

        # history with multiple AIMessages that add up to 85000 tokens (>80%)
        msg1 = AIMessage(id="msg1", content="1", usage_metadata={"total_tokens": 45000, "input_tokens": 45000, "output_tokens": 0})
        msg2 = ToolMessage(content="ok", tool_call_id="call1")
        msg3 = AIMessage(id="msg3", content="3", usage_metadata={"total_tokens": 45000, "input_tokens": 45000, "output_tokens": 0})

        state = {"messages": [msg1, msg2, msg3]}
        result = mw._apply(state, _make_runtime())

        # should queue warning but not mutate state (return None)
        assert result is None
        assert len(mw._pending_warnings["test-run"]) == 1
        assert "TOKEN BUDGET WARNING" in mw._pending_warnings["test-run"][0]


class TestTokenBudgetLifecycle:
    @pytest.mark.parametrize("context", [None, {}, {"run_id": None}, {"run_id": ""}, {"run_id": 0}, {"run_id": []}])
    @pytest.mark.parametrize("async_hooks", [False, True])
    @pytest.mark.asyncio
    async def test_missing_or_invalid_run_id_clears_invocation_state(self, context, async_hooks):
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
        runtime = _make_runtime()
        runtime.context = context
        state = _make_state_with_usage(total=850)
        if async_hooks:
            await mw.abefore_agent({"messages": []}, runtime)
            await mw.aafter_model(state, runtime)
        else:
            mw.before_agent({"messages": []}, runtime)
            mw.after_model(state, runtime)

        # Missing identities are invocation-local, never shared under None or "".
        key = mw._get_run_id(runtime)
        assert key.startswith("__invocation__:")
        assert mw._cumulative_usage[key].total == 850
        assert mw._warned[key]
        assert mw._pending_warnings[key]
        assert mw._seen_messages[key]

        if async_hooks:
            await mw.aafter_agent(state, runtime)
        else:
            mw.after_agent(state, runtime)
        for values in (mw._cumulative_usage, mw._warned, mw._pending_warnings, mw._seen_messages):
            assert key not in values

        # Reusing even the same runtime object starts a fresh invocation budget.
        mw.before_agent(state, runtime)
        follow_up = _make_state_with_usage(total=200)
        follow_up["messages"][0].id = "next-msg"
        assert mw.after_model(follow_up, runtime) is None
        next_key = mw._get_run_id(runtime)
        assert next_key != key
        assert mw._cumulative_usage[next_key].total == 200
        assert not mw._warned.get(next_key)

    def test_active_invocation_keeps_its_key_when_the_anchor_map_is_full(self):
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
        mw._fallback_run_ids.maxsize = 3
        active = SimpleNamespace(context={}, control=object())
        key = mw._get_run_id(active)

        for _ in range(5):
            mw._get_run_id(SimpleNamespace(context={}, control=object()))
            assert mw._get_run_id(active) == key

    @pytest.mark.asyncio
    async def test_valid_run_id_preserves_usage_warnings_and_stop_reason(self):
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=1000))
        runtime = _make_runtime(run_id="goal-run")
        mw.after_model(_make_state_with_usage(total=850), runtime)
        state = _make_state_with_usage(total=1100)
        assert mw.after_model(state, runtime) is not None
        await mw.aafter_agent(state, runtime)

        assert "goal-run" not in mw._seen_messages
        assert mw._cumulative_usage["goal-run"].total == 1100
        assert mw._warned["goal-run"]
        assert len(mw._pending_warnings["goal-run"]) == 1
        assert mw.consume_stop_reason("goal-run") == "token_capped"

        # Continuations may get another Runtime object with the same run identity.
        continuation = _make_runtime(run_id="goal-run")
        await mw.abefore_agent(state, continuation)
        await mw.aafter_model(state, continuation)
        assert mw._cumulative_usage["goal-run"].total == 1100
        assert len(mw._pending_warnings["goal-run"]) == 1


class TestTokenBudgetWarning:
    def test_warn_injected_at_next_model_call(self):
        config = TokenBudgetConfig(max_tokens=100000, warn_threshold=0.8, enabled=True)
        mw = TokenBudgetMiddleware.from_config(config)
        runtime = _make_runtime()

        # trigger warning queue
        mw._apply(_make_state_with_usage(total=85000), runtime)

        ai_msg = AIMessage(content="", tool_calls=[{"name": "test", "args": {}, "id": "1"}])
        tool_msg = ToolMessage(content="ok", tool_call_id="1")

        request = _make_request([ai_msg, tool_msg], runtime)

        captured, handler = _capture_handler()
        mw.wrap_model_call(request, handler)

        sent = captured[0].messages

        assert sent[0] is ai_msg
        assert sent[1] is tool_msg
        assert isinstance(sent[2], HumanMessage)
        assert sent[2].name == "budget_warning"
        assert "TOKEN BUDGET WARNING" in sent[2].content

    def test_warn_only_once_per_run(self):
        config = TokenBudgetConfig(max_tokens=100000, warn_threshold=0.8, enabled=True)
        mw = TokenBudgetMiddleware.from_config(config)
        runtime = _make_runtime()

        mw._apply(_make_state_with_usage(total=85000), runtime)

        assert len(mw._pending_warnings["test-run"]) == 1

        # call 2: still above threshold, but already warning -> no second enqueue
        mw._apply(_make_state_with_usage(total=90000), runtime)
        assert len(mw._pending_warnings["test-run"]) == 1


class TestTokenBudgetHardStop:
    def test_hard_stop_strip_tool_calls(self):
        config = TokenBudgetConfig(max_tokens=100000, hard_stop_threshold=1.0, enabled=True)
        mw = TokenBudgetMiddleware.from_config(config)

        tool_calls = [{"name": "bash", "args": {"command": "ls"}, "id": "call_1"}]
        state = _make_state_with_usage(total=105000, tool_calls=tool_calls, content="Thinking")

        res = mw._apply(state, _make_runtime())

        assert res is not None
        msgs = res["messages"]
        assert len(msgs) == 1

        # tool calls must be stripped
        assert msgs[0].tool_calls == []
        # content must have the warning appended
        assert "Thinking" in msgs[0].content
        assert "TOKEN BUDGET EXCEEDED" in msgs[0].content

    def test_hard_stop_stamps_token_capped_stop_reason_consumed_once(self):
        """#3875 Phase 2: a hard-stop stamps ``token_capped`` on a per-run
        accessor the executor reads post-run. It pops on read so a second read
        (e.g. a retry over the same executor) does not double-report, and a
        non-capped run yields ``None``."""
        config = TokenBudgetConfig(max_tokens=100000, hard_stop_threshold=1.0, enabled=True)
        mw = TokenBudgetMiddleware.from_config(config)

        runtime = _make_runtime(run_id="capped-run")
        tool_calls = [{"name": "bash", "args": {"command": "ls"}, "id": "call_1"}]
        state = _make_state_with_usage(total=105000, tool_calls=tool_calls, content="partial answer")
        mw._apply(state, runtime)

        # First read pops the reason.
        assert mw.consume_stop_reason("capped-run") == "token_capped"
        # Second read is None — the reason is per-run and consumed once.
        assert mw.consume_stop_reason("capped-run") is None
        # A run that never hit the cap has no stop reason.
        assert mw.consume_stop_reason("uncapped-run") is None

    def test_stop_reason_round_trips_an_explicit_none_run_id(self):
        """A subagent whose parent run has no run_id runs with ``run_id=None``;
        ``SubagentExecutor`` reads the reason back with that same ``None``."""
        mw = TokenBudgetMiddleware.from_config(TokenBudgetConfig(max_tokens=1000, enabled=True))
        runtime = _make_runtime(run_id=None)
        tool_calls = [{"name": "bash", "args": {"command": "ls"}, "id": "call_1"}]
        assert mw._apply(_make_state_with_usage(total=1500, tool_calls=tool_calls), runtime) is not None

        assert mw.consume_stop_reason(None) == "token_capped"
        assert mw.consume_stop_reason(None) is None

    def test_below_threshold_does_not_stamp_stop_reason(self):
        """A run that only crosses the warn threshold (not the hard stop) keeps
        running and must not stamp ``token_capped`` — the run is not capped."""
        config = TokenBudgetConfig(max_tokens=100000, warn_threshold=0.7, hard_stop_threshold=1.0, enabled=True)
        mw = TokenBudgetMiddleware.from_config(config)

        runtime = _make_runtime(run_id="warn-run")
        # 80k of 100k -> crosses warn (0.7) but not hard stop (1.0).
        state = _make_state_with_usage(total=80000)
        mw._apply(state, runtime)

        assert mw.consume_stop_reason("warn-run") is None


class TestIndependentDimensions:
    def test_input_tokens_trigger_limit(self):
        config = TokenBudgetConfig(max_tokens=100000, max_input_tokens=10000, warn_threshold=0.8, enabled=True)
        mw = TokenBudgetMiddleware.from_config(config)

        # total is safe (10k < 100k) but input is over limit (9k >= 8k)
        state = _make_state_with_usage(total=10000, input_tk=9000, output_tk=1000)
        mw._apply(state, _make_runtime())

        warnings = mw._pending_warnings["test-run"]
        assert len(warnings) == 1
        assert "input token" in warnings[0]

    def test_output_tokens_trigger_limit(self):
        config = TokenBudgetConfig(max_tokens=100_000, max_output_tokens=5_000, hard_stop_threshold=1.0, enabled=True)
        mw = TokenBudgetMiddleware.from_config(config)

        # Total is safe (10k < 100k) but output is over hard limit (6k >= 5k)
        state = _make_state_with_usage(total=10_000, input_tk=4000, output_tk=6000)
        result = mw._apply(state, _make_runtime())

        assert result is not None
        assert "output token" in result["messages"][0].content


class _ToolCallingFakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self


class _RecordingToolCallingFakeModel(_ToolCallingFakeModel):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        object.__setattr__(self, "requests", [])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.requests.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class TestTokenBudgetAgentGraph:
    def test_goal_continuation_shares_the_run_budget(self):
        """A hidden goal continuation re-enters the graph under the same run_id; it must not get a fresh budget."""
        executed: list[str] = []

        @as_tool
        def bash(command: str) -> str:
            """Run a fake shell command."""
            executed.append(command)
            return "ok"

        def call(command: str, tokens: int = 4000) -> AIMessage:
            return AIMessage(
                content="",
                id=f"ai-{command}",
                tool_calls=[{"name": "bash", "id": f"call-{command}", "args": {"command": command}}],
                usage_metadata={"input_tokens": tokens, "output_tokens": 0, "total_tokens": tokens},
            )

        model = _ToolCallingFakeModel(
            responses=[
                call("a"),
                call("b"),
                AIMessage(content="first answer", id="ai-answer-1", usage_metadata={"input_tokens": 1000, "output_tokens": 0, "total_tokens": 1000}),
                call("c"),
                call("d"),
                AIMessage(content="second answer", id="ai-answer-2", usage_metadata={"input_tokens": 1000, "output_tokens": 0, "total_tokens": 1000}),
            ]
        )
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=10_000))
        graph = create_agent(model=model, tools=[bash], middleware=[mw], checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "goal-thread"}}

        # User turn: 9k of 10k.
        graph.invoke({"messages": [HumanMessage("research")]}, config=config, context={"thread_id": "goal-thread", "run_id": "run-1"})
        assert executed == ["a", "b"]

        # Goal continuation in the same run: the next 4k call crosses the cap.
        result = graph.invoke({"messages": [HumanMessage("keep going")]}, config=config, context={"thread_id": "goal-thread", "run_id": "run-1"})
        assert executed == ["a", "b"]
        assert "TOKEN BUDGET EXCEEDED" in result["messages"][-1].content

        # A later user run still starts with a fresh budget.
        graph.invoke({"messages": [HumanMessage("next question")]}, config=config, context={"thread_id": "goal-thread", "run_id": "run-2"})
        assert executed == ["a", "b", "d"]

    @pytest.mark.parametrize("context", [{"thread_id": "no-run-id"}, {"thread_id": "no-run-id", "run_id": None}])
    def test_invocation_without_run_id_keeps_one_budget_across_graph_nodes(self, context):
        """LangGraph hands each node its own Runtime, so an invocation without a run_id can't be keyed by id(runtime)."""
        executed: list[str] = []

        @as_tool
        def bash(command: str) -> str:
            """Run a fake shell command."""
            executed.append(command)
            return "ok"

        def call(command: str, tokens: int) -> AIMessage:
            return AIMessage(
                content="",
                id=f"ai-{command}",
                tool_calls=[{"name": "bash", "id": f"call-{command}", "args": {"command": command}}],
                usage_metadata={"input_tokens": tokens, "output_tokens": 0, "total_tokens": tokens},
            )

        def answer(text: str) -> AIMessage:
            return AIMessage(content=text, id=f"ai-{text}", usage_metadata={"input_tokens": 500, "output_tokens": 0, "total_tokens": 500})

        model = _RecordingToolCallingFakeModel(responses=[call("a", 4000), call("b", 4500), answer("first answer"), call("c", 4000), call("d", 4500), answer("second answer")])
        mw = TokenBudgetMiddleware(TokenBudgetConfig(enabled=True, max_tokens=10_000, warn_threshold=0.8))
        graph = create_agent(model=model, tools=[bash], middleware=[mw], checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "no-run-id"}}

        # 8.5k of 10k after "b": the warning reaches the next model request.
        graph.invoke({"messages": [HumanMessage("research")]}, config=config, context=dict(context))
        assert [getattr(message, "name", None) for message in model.requests[2]][-1] == "budget_warning"

        # The next invocation has its own 10k; the first one's 9k doesn't count.
        result = graph.invoke({"messages": [HumanMessage("next question")]}, config=config, context=dict(context))
        assert executed == ["a", "b", "c", "d"]
        assert result["messages"][-1].content == "second answer"
        for values in (mw._cumulative_usage, mw._warned, mw._pending_warnings, mw._seen_messages, mw._fallback_run_ids):
            assert not values
