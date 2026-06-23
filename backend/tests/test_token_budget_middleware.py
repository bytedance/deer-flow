from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

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
