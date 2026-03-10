"""Tests for BudgetEnforcementMiddleware and task_tool salvage logic."""

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.middlewares.budget_enforcement_middleware import (
    BudgetEnforcementMiddleware,
)
from src.tools.builtins.task_tool import _salvage_partial_output


def _make_state(thread_id: str = "test-thread") -> dict:
    """Build a minimal AgentState."""
    return {
        "messages": [HumanMessage(content="hello"), AIMessage(content="hi")],
        "thread_data": {"workspace_path": thread_id},
    }


class TestBudgetEnforcementMiddleware:
    def test_thresholds_computed_from_max_turns(self):
        """Thresholds use max_turns // 8 (each model call ≈ 8 graph steps)."""
        mw = BudgetEnforcementMiddleware(max_turns=500)
        # effective_calls = 500 // 8 = 62
        assert mw.warn_at == 40   # int(62 * 0.65)
        assert mw.urgent_at == 52  # int(62 * 0.85)
        assert mw.force_at == 58   # int(62 * 0.95)

    def test_no_warning_on_first_call(self):
        mw = BudgetEnforcementMiddleware(max_turns=500)
        state = _make_state()
        result = mw._apply(state)
        assert result is None  # 1 call, way below warn_at=32

    def test_warn_after_n_calls(self):
        mw = BudgetEnforcementMiddleware(max_turns=500)
        state = _make_state()
        # Call _apply until we hit warn_at
        for _ in range(mw.warn_at - 1):
            result = mw._apply(state)
            assert result is None
        # This call should trigger warn
        result = mw._apply(state)
        assert result is not None
        assert "BUDGET WARNING" in result["messages"][0].content

    def test_urgent_after_more_calls(self):
        mw = BudgetEnforcementMiddleware(max_turns=500)
        state = _make_state()
        # Call until urgent_at
        for _ in range(mw.urgent_at - 1):
            mw._apply(state)
        result = mw._apply(state)
        assert result is not None
        assert "BUDGET CRITICAL" in result["messages"][0].content

    def test_force_after_many_calls(self):
        mw = BudgetEnforcementMiddleware(max_turns=500)
        state = _make_state()
        for _ in range(mw.force_at - 1):
            mw._apply(state)
        result = mw._apply(state)
        assert result is not None
        assert "BUDGET EXHAUSTED" in result["messages"][0].content

    def test_warnings_not_repeated(self):
        mw = BudgetEnforcementMiddleware(max_turns=500)
        state = _make_state()
        for _ in range(mw.warn_at):
            mw._apply(state)
        # Next call: already warned
        result = mw._apply(state)
        assert result is None

    def test_after_model_strips_tool_calls_at_force(self):
        mw = BudgetEnforcementMiddleware(max_turns=500)
        state = _make_state()
        # Advance counter past force threshold
        for _ in range(mw.force_at):
            mw._apply(state)
        # Now add an AI message with tool calls
        state["messages"].append(
            AIMessage(
                content="Let me read another file",
                tool_calls=[{"name": "read_file", "args": {"path": "/foo"}, "id": "tc1"}],
            )
        )
        result = mw._apply_after_model(state)
        assert result is not None
        stripped = result["messages"][0]
        assert stripped.tool_calls == []
        assert "BUDGET EXHAUSTED" in stripped.content

    def test_after_model_no_strip_below_force(self):
        mw = BudgetEnforcementMiddleware(max_turns=500)
        state = _make_state()
        mw._apply(state)  # 1 call, way below force
        state["messages"].append(
            AIMessage(
                content="Reading",
                tool_calls=[{"name": "read_file", "args": {"path": "/foo"}, "id": "tc1"}],
            )
        )
        result = mw._apply_after_model(state)
        assert result is None

    def test_custom_fractions(self):
        mw = BudgetEnforcementMiddleware(max_turns=80, warn_fraction=0.5, urgent_fraction=0.75, force_fraction=0.9)
        # effective_calls = max(80 // 8, 10) = 10
        assert mw.warn_at == 5    # int(10 * 0.5)
        assert mw.urgent_at == 7  # int(10 * 0.75)
        assert mw.force_at == 9   # int(10 * 0.9)

    def test_reset_clears_counter_and_warnings(self):
        mw = BudgetEnforcementMiddleware(max_turns=500)
        state = _make_state()
        for _ in range(mw.warn_at):
            mw._apply(state)
        mw.reset("test-thread")
        # After reset, counter is 0 — next call should not warn
        result = mw._apply(state)
        assert result is None

    def test_per_thread_isolation(self):
        mw = BudgetEnforcementMiddleware(max_turns=500)
        state_a = _make_state(thread_id="thread-a")
        state_b = _make_state(thread_id="thread-b")
        # Advance thread-a past warn
        for _ in range(mw.warn_at):
            mw._apply(state_a)
        # thread-b should still be at 0
        result = mw._apply(state_b)
        assert result is None  # 1 call on thread-b


class TestSalvagePartialOutput:
    def test_salvage_text_only_message(self):
        """Should find the last AI message without tool calls."""
        from unittest.mock import MagicMock

        result = MagicMock()
        result.ai_messages = [
            {"content": "Reading file...", "tool_calls": [{"name": "read_file", "args": {}}]},
            {"content": "Found the pattern in auth.py. The flow is X → Y → Z.", "tool_calls": []},
            {"content": "Let me check one more...", "tool_calls": [{"name": "read_file", "args": {}}]},
        ]
        salvaged = _salvage_partial_output(result)
        assert salvaged is not None
        assert "Found the pattern" in salvaged

    def test_salvage_no_text_only_falls_back_to_composite(self):
        """If all messages have tool calls, build composite from reasoning snippets."""
        from unittest.mock import MagicMock

        result = MagicMock()
        result.ai_messages = [
            {"content": "The auth module uses JWT tokens with a 24-hour expiry window.", "tool_calls": [{"name": "read_file", "args": {}}]},
            {"content": "Found that the middleware chain has 13 components in total.", "tool_calls": [{"name": "bash", "args": {}}]},
        ]
        salvaged = _salvage_partial_output(result)
        assert "JWT tokens" in salvaged
        assert "middleware chain" in salvaged
        assert "---" in salvaged  # composite separator

    def test_salvage_empty_messages(self):
        from unittest.mock import MagicMock

        result = MagicMock()
        result.ai_messages = []
        assert _salvage_partial_output(result) is None

    def test_salvage_list_content(self):
        """Handle list-type content (multimodal messages)."""
        from unittest.mock import MagicMock

        result = MagicMock()
        result.ai_messages = [
            {"content": [{"type": "text", "text": "Analysis complete."}, {"type": "text", "text": "Found 3 issues."}], "tool_calls": []},
        ]
        salvaged = _salvage_partial_output(result)
        assert "Analysis complete" in salvaged
        assert "Found 3 issues" in salvaged

    def test_salvage_truncates_long_content(self):
        from unittest.mock import MagicMock

        result = MagicMock()
        result.ai_messages = [
            {"content": "x" * 20000, "tool_calls": []},
        ]
        salvaged = _salvage_partial_output(result)
        assert len(salvaged) == 8000
