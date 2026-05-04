"""Tests for SkillReviewMiddleware and SkillReviewer."""

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio

from deerflow.agents.middlewares.skill_review_middleware import SkillReviewMiddleware
from deerflow.agents.skill_review.reviewer import SkillReviewer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime(thread_id="test-thread"):
    """Build a minimal Runtime mock with context."""
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id}
    return runtime


def _make_state(tool_call_rounds=0, messages=None):
    """Build a minimal AgentState dict.

    If *messages* is provided, use it directly. Otherwise create a conversation
    with the specified number of tool-call rounds (AI messages containing tool_calls).
    """
    from langchain_core.messages import AIMessage, HumanMessage

    if messages is not None:
        return {"messages": messages}

    msgs = [HumanMessage(content="hello")]
    for i in range(tool_call_rounds):
        msgs.append(AIMessage(content="", tool_calls=[{"name": "bash", "id": f"call_{i}", "args": {"command": "ls"}}]))
    return {"messages": msgs}


def _tool_call(name="bash", args=None):
    return {"name": name, "id": f"call_{name}", "args": args or {"command": "ls"}}


def _make_config(enabled=True, interval=10):
    """Build a minimal AppConfig-like object."""
    return SimpleNamespace(
        skill_evolution=SimpleNamespace(
            enabled=enabled,
            moderation_model_name=None,
            creation_nudge_interval=interval,
        ),
        models=[SimpleNamespace(name="test-model")],
    )


async def _run_middleware(mw, state, runtime):
    """Helper to run aafter_agent in an async context."""
    return await mw.aafter_agent(state, runtime)


class _SyncThread:
    """Patches threading.Thread to run the target synchronously in the calling thread.

    This avoids race conditions in tests where assertions run before the daemon
    thread has executed. Replace ``threading.Thread`` with this class via patch.
    """

    def __init__(self, target=None, args=(), kwargs=None, daemon=False, name=None, **_):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)

    def join(self, timeout=None):
        pass  # Already completed in start()


# ---------------------------------------------------------------------------
# SkillReviewer tests
# ---------------------------------------------------------------------------


class TestSkillReviewer:
    def test_model_name_from_config(self):
        config = _make_config()
        config.skill_evolution.moderation_model_name = "mod-model"
        reviewer = SkillReviewer(config)
        assert reviewer._get_model_name() == "mod-model"

    def test_model_name_from_constructor(self):
        config = _make_config()
        config.skill_evolution.moderation_model_name = None
        reviewer = SkillReviewer(config, model_name="my-model")
        assert reviewer._get_model_name() == "my-model"

    def test_model_name_fallback_to_first_configured(self):
        config = _make_config()
        config.skill_evolution.moderation_model_name = None
        reviewer = SkillReviewer(config)
        assert reviewer._get_model_name() == "test-model"

    def test_model_name_none_when_no_models(self):
        config = _make_config()
        config.skill_evolution.moderation_model_name = None
        config.models = []
        reviewer = SkillReviewer(config)
        assert reviewer._get_model_name() is None

    def test_review_best_effort_catches_exceptions(self):
        """review() should never raise — all exceptions are caught and logged."""
        config = _make_config()
        reviewer = SkillReviewer(config)

        with patch.object(reviewer, "_create_review_agent", side_effect=RuntimeError("boom")):
            # Should not raise
            anyio.run(reviewer.review, "thread-1", [])

    def test_review_invokes_agent(self):
        """review() should invoke the created agent with proper args."""
        config = _make_config()
        reviewer = SkillReviewer(config)

        mock_agent = AsyncMock()
        mock_agent.ainvoke.return_value = {"messages": []}

        with patch.object(reviewer, "_create_review_agent", return_value=mock_agent):
            anyio.run(reviewer.review, "thread-1", [MagicMock()])

        mock_agent.ainvoke.assert_awaited_once()
        call_kwargs = mock_agent.ainvoke.call_args
        assert call_kwargs[1]["config"]["configurable"]["thread_id"] == "thread-1"

    def test_review_logs_skill_changes(self):
        config = _make_config()
        reviewer = SkillReviewer(config)

        tool_msg = MagicMock()
        tool_msg.type = "tool"
        tool_msg.content = "Created custom skill 'my-skill'"

        mock_agent = AsyncMock()
        mock_agent.ainvoke.return_value = {"messages": [tool_msg]}

        with patch.object(reviewer, "_create_review_agent", return_value=mock_agent):
            with patch("deerflow.agents.skill_review.reviewer.logger") as mock_logger:
                anyio.run(reviewer.review, "thread-1", [])
                mock_logger.info.assert_called()


# ---------------------------------------------------------------------------
# SkillReviewMiddleware tests
# ---------------------------------------------------------------------------


class TestSkillReviewMiddleware:
    def test_skip_when_skill_evolution_disabled(self):
        """Middleware returns None when skill_evolution is not enabled."""
        config = _make_config(enabled=False)
        mw = SkillReviewMiddleware(config=config)
        state = _make_state(tool_call_rounds=1)
        runtime = _make_runtime()

        result = anyio.run(_run_middleware, mw, state, runtime)
        assert result is None

    def test_skip_when_no_thread_id(self):
        """Middleware returns None when thread_id is missing."""
        config = _make_config(enabled=True)
        mw = SkillReviewMiddleware(config=config)
        state = _make_state(tool_call_rounds=1)

        runtime = MagicMock()
        runtime.context = None

        with patch("deerflow.agents.middlewares.skill_review_middleware.get_config", return_value={"configurable": {}}):
            result = anyio.run(_run_middleware, mw, state, runtime)
        assert result is None

    def test_skip_when_no_tool_call_rounds(self):
        """Middleware returns None when there are no tool-call rounds."""
        config = _make_config(enabled=True)
        mw = SkillReviewMiddleware(config=config)
        state = _make_state(tool_call_rounds=0)
        runtime = _make_runtime()

        result = anyio.run(_run_middleware, mw, state, runtime)
        assert result is None

    def test_counter_increment_by_rounds(self):
        """Counter increments by the number of tool-call rounds (AI messages with tool_calls)."""
        config = _make_config(enabled=True, interval=100)
        mw = SkillReviewMiddleware(config=config)
        runtime = _make_runtime("thread-A")

        # 3 tool-call rounds
        state = _make_state(tool_call_rounds=3)
        anyio.run(_run_middleware, mw, state, runtime)

        assert mw._iters["thread-A"] == 3

    def test_delta_counting_across_turns(self):
        """Counter only counts new rounds since last check, not total across turns."""
        from langchain_core.messages import AIMessage

        config = _make_config(enabled=True, interval=100)
        mw = SkillReviewMiddleware(config=config)
        runtime = _make_runtime("thread-A")

        # Turn 1: 2 tool-call rounds
        state1 = _make_state(tool_call_rounds=2)
        anyio.run(_run_middleware, mw, state1, runtime)
        assert mw._iters["thread-A"] == 2

        # Turn 2: same 2 rounds seen again + 1 new = total 3, delta = 1
        msgs = state1["messages"] + [AIMessage(content="", tool_calls=[{"name": "bash", "id": "call_new", "args": {"command": "ls"}}])]
        state2 = {"messages": msgs}
        anyio.run(_run_middleware, mw, state2, runtime)
        assert mw._iters["thread-A"] == 3  # 2 + 1

    def test_threshold_triggers_review(self):
        """Review is triggered when counter reaches the threshold."""
        config = _make_config(enabled=True, interval=3)
        mw = SkillReviewMiddleware(config=config)
        runtime = _make_runtime("thread-B")

        mock_reviewer = AsyncMock()
        mw._reviewer = mock_reviewer

        # First call: 2 tool-call rounds → counter = 2 (below threshold)
        state1 = _make_state(tool_call_rounds=2)
        anyio.run(_run_middleware, mw, state1, runtime)
        assert mw._iters["thread-B"] == 2

        # Second call: 1 more round → counter would be 3 ≥ threshold → triggers review, resets
        from langchain_core.messages import AIMessage

        msgs = state1["messages"] + [AIMessage(content="", tool_calls=[{"name": "bash", "id": "call_new", "args": {"command": "ls"}}])]
        state2 = {"messages": msgs}

        # Patch threading.Thread to execute synchronously so the assertion is deterministic
        with patch.object(threading, "Thread", _SyncThread):
            anyio.run(_run_middleware, mw, state2, runtime)

        assert mw._iters["thread-B"] == 0  # Reset after trigger
        mock_reviewer.review.assert_called_once()

    def test_counter_resets_after_trigger(self):
        """Counter resets to 0 after threshold is reached."""
        config = _make_config(enabled=True, interval=2)
        mw = SkillReviewMiddleware(config=config)
        runtime = _make_runtime("thread-C")

        mock_reviewer = AsyncMock()
        mw._reviewer = mock_reviewer

        state = _make_state(tool_call_rounds=2)

        with patch.object(threading, "Thread", _SyncThread):
            anyio.run(_run_middleware, mw, state, runtime)

        assert mw._iters["thread-C"] == 0

    def test_per_thread_isolation(self):
        """Counters are independent per thread."""
        config = _make_config(enabled=True, interval=10)
        mw = SkillReviewMiddleware(config=config)

        runtime_a = _make_runtime("thread-A")
        runtime_b = _make_runtime("thread-B")

        state = _make_state(tool_call_rounds=1)

        anyio.run(_run_middleware, mw, state, runtime_a)
        anyio.run(_run_middleware, mw, state, runtime_b)

        assert mw._iters["thread-A"] == 1
        assert mw._iters["thread-B"] == 1

    def test_lru_eviction(self):
        """Old threads are evicted when tracking exceeds the limit."""
        config = _make_config(enabled=True, interval=100)
        mw = SkillReviewMiddleware(config=config)

        # Fill up to the limit
        for i in range(100):
            runtime = _make_runtime(f"thread-{i}")
            state = _make_state(tool_call_rounds=1)
            anyio.run(_run_middleware, mw, state, runtime)

        assert len(mw._iters) == 100

        # Add one more — should evict the oldest
        runtime = _make_runtime("thread-new")
        state = _make_state(tool_call_rounds=1)
        anyio.run(_run_middleware, mw, state, runtime)

        assert len(mw._iters) <= 100
        assert "thread-0" not in mw._iters  # Oldest evicted
        assert "thread-new" in mw._iters

    def test_background_thread_launch_failure_does_not_propagate(self):
        """If thread launch fails, the middleware still returns None."""
        config = _make_config(enabled=True, interval=1)
        mw = SkillReviewMiddleware(config=config)
        runtime = _make_runtime("thread-D")

        mock_reviewer = AsyncMock()
        mw._reviewer = mock_reviewer

        state = _make_state(tool_call_rounds=1)

        with patch("deerflow.agents.middlewares.skill_review_middleware.threading.Thread", side_effect=RuntimeError("no threads")):
            result = anyio.run(_run_middleware, mw, state, runtime)

        assert result is None

    def test_count_tool_call_rounds(self):
        """_count_tool_call_rounds counts AI messages containing tool_calls."""
        from langchain_core.messages import AIMessage, HumanMessage

        config = _make_config(enabled=True, interval=100)
        mw = SkillReviewMiddleware(config=config)

        # 2 AI messages with tool_calls = 2 rounds
        state = {
            "messages": [
                HumanMessage(content="hi"),
                AIMessage(content="", tool_calls=[_tool_call("bash")]),
                AIMessage(content="done", tool_calls=[]),  # No tool_calls = not a round
                AIMessage(content="", tool_calls=[_tool_call("read_file")]),
            ]
        }
        assert mw._count_tool_call_rounds(state) == 2

    def test_awrap_tool_call_resets_counter_on_skill_manage(self):
        """awrap_tool_call resets counter when skill_manage tool is called."""
        config = _make_config(enabled=True, interval=100)
        mw = SkillReviewMiddleware(config=config)
        runtime = _make_runtime("thread-X")

        # Set up a counter
        state = _make_state(tool_call_rounds=2)
        anyio.run(_run_middleware, mw, state, runtime)
        assert mw._iters["thread-X"] == 2

        # Simulate skill_manage tool call
        request = MagicMock()
        request.tool_call = {"name": "skill_manage", "id": "call_1", "args": {}}
        request.runtime = runtime

        handler = AsyncMock(return_value=MagicMock())
        anyio.run(mw.awrap_tool_call, request, handler)

        # Counter should be reset
        assert "thread-X" not in mw._iters

    def test_awrap_tool_call_no_reset_for_other_tools(self):
        """awrap_tool_call does not reset counter for non-skill_manage tools."""
        config = _make_config(enabled=True, interval=100)
        mw = SkillReviewMiddleware(config=config)
        runtime = _make_runtime("thread-Y")

        # Set up a counter
        state = _make_state(tool_call_rounds=2)
        anyio.run(_run_middleware, mw, state, runtime)
        assert mw._iters["thread-Y"] == 2

        # Simulate bash tool call
        request = MagicMock()
        request.tool_call = {"name": "bash", "id": "call_1", "args": {}}
        request.runtime = runtime

        handler = AsyncMock(return_value=MagicMock())
        anyio.run(mw.awrap_tool_call, request, handler)

        # Counter should remain
        assert mw._iters["thread-Y"] == 2

    def test_lazy_config_resolution(self):
        """Middleware resolves config lazily if not provided at construction."""
        mw = SkillReviewMiddleware()

        with patch("deerflow.agents.middlewares.skill_review_middleware.get_app_config", return_value=_make_config()):
            mw._ensure_config()
            assert mw._config is not None
            assert mw._reviewer is not None
