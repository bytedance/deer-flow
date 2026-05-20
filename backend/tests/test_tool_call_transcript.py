"""Regression tests for tool-call transcript validation and normalization.

Covers the failure modes described in Issue #3029:
  - missing tool result
  - non-adjacent tool result
  - multiple tool results after one AI tool-call turn
  - multiple AI tool-call turns — each result stays with its own AI turn
  - orphan ToolMessage
  - middleware inserts non-tool messages between AIMessage(tool_calls) and ToolMessages
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage

from deerflow.agents.middlewares.tool_call_transcript import (
    Violation,
    ValidationResult,
    normalize_tool_call_transcript,
    validate_tool_call_transcript,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ai(tool_calls: list[dict] | None = None, **kw) -> AIMessage:
    return AIMessage(content="", tool_calls=tool_calls or [], **kw)


def _tc(name: str = "bash", tc_id: str = "call_1") -> dict:
    return {"name": name, "id": tc_id, "args": {}}


def _tool(tc_id: str, name: str = "test_tool", content: str = "result") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=tc_id, name=name)


# ===========================================================================
# Validation tests
# ===========================================================================


class TestValidateToolCallTranscript:
    """Tests for validate_tool_call_transcript (pure detection, no repair)."""

    def test_empty_messages_is_valid(self):
        r = validate_tool_call_transcript([])
        assert r.is_valid
        assert r.violations == []

    def test_no_ai_messages_is_valid(self):
        r = validate_tool_call_transcript([HumanMessage(content="hi")])
        assert r.is_valid

    def test_ai_without_tool_calls_is_valid(self):
        r = validate_tool_call_transcript([AIMessage(content="hello")])
        assert r.is_valid

    def test_all_tool_calls_responded_is_valid(self):
        msgs = [
            _ai([_tc("bash", "c1")]),
            _tool("c1", "bash"),
        ]
        r = validate_tool_call_transcript(msgs)
        assert r.is_valid

    def test_missing_tool_result(self):
        msgs = [_ai([_tc("bash", "c1")])]
        r = validate_tool_call_transcript(msgs)
        assert not r.is_valid
        kinds = {v.kind for v in r.violations}
        assert "missing_tool_result" in kinds

    def test_non_adjacent_tool_result(self):
        msgs = [
            _ai([_tc("bash", "c1")]),
            HumanMessage(content="interruption"),
            _tool("c1", "bash"),
        ]
        r = validate_tool_call_transcript(msgs)
        assert not r.is_valid
        kinds = {v.kind for v in r.violations}
        assert "non_adjacent_tool_result" in kinds

    def test_non_tool_between_ai_and_tool(self):
        msgs = [
            _ai([_tc("bash", "c1")]),
            HumanMessage(content="interruption"),
            _tool("c1", "bash"),
        ]
        r = validate_tool_call_transcript(msgs)
        assert not r.is_valid
        kinds = {v.kind for v in r.violations}
        assert "non_tool_between_ai_and_tool" in kinds

    def test_orphan_tool_message(self):
        msgs = [
            HumanMessage(content="hi"),
            _tool("orphan_id", "orphan"),
        ]
        r = validate_tool_call_transcript(msgs)
        assert not r.is_valid
        kinds = {v.kind for v in r.violations}
        assert "orphan_tool_message" in kinds

    def test_multiple_tool_calls_all_responded_is_valid(self):
        msgs = [
            _ai([_tc("bash", "c1"), _tc("read", "c2")]),
            _tool("c1", "bash"),
            _tool("c2", "read"),
        ]
        r = validate_tool_call_transcript(msgs)
        assert r.is_valid

    def test_multiple_ai_turns_each_valid(self):
        msgs = [
            _ai([_tc("bash", "c1")]),
            _tool("c1", "bash"),
            HumanMessage(content="next"),
            _ai([_tc("read", "c2")]),
            _tool("c2", "read"),
        ]
        r = validate_tool_call_transcript(msgs)
        assert r.is_valid

    def test_multiple_ai_turns_one_missing_result(self):
        msgs = [
            _ai([_tc("bash", "c1")]),
            _tool("c1", "bash"),
            HumanMessage(content="next"),
            _ai([_tc("read", "c2")]),
        ]
        r = validate_tool_call_transcript(msgs)
        assert not r.is_valid
        kinds = {v.kind for v in r.violations}
        assert "missing_tool_result" in kinds

    def test_middleware_inserts_system_message_between_ai_and_tool(self):
        """Simulates middleware injecting a SystemMessage between tool call and result."""
        msgs = [
            _ai([_tc("bash", "c1")]),
            SystemMessage(content="middleware note"),
            _tool("c1", "bash"),
        ]
        r = validate_tool_call_transcript(msgs)
        assert not r.is_valid
        kinds = {v.kind for v in r.violations}
        assert "non_tool_between_ai_and_tool" in kinds


# ===========================================================================
# Normalization tests
# ===========================================================================


class TestNormalizeToolCallTranscript:
    """Tests for normalize_tool_call_transcript (repair)."""

    def test_valid_transcript_unchanged(self):
        msgs = [
            _ai([_tc("bash", "c1")]),
            _tool("c1", "bash"),
        ]
        result = normalize_tool_call_transcript(msgs)
        # Should return same object when nothing to fix.
        assert result is msgs

    def test_empty_returns_empty(self):
        result = normalize_tool_call_transcript([])
        assert result == []

    def test_no_ai_returns_same(self):
        msgs = [HumanMessage(content="hi")]
        result = normalize_tool_call_transcript(msgs)
        assert result is msgs

    def test_missing_tool_result_inserts_synthetic(self):
        msgs = [_ai([_tc("bash", "c1")])]
        result = normalize_tool_call_transcript(msgs)
        assert len(result) == 2
        assert isinstance(result[1], ToolMessage)
        assert result[1].tool_call_id == "c1"
        assert result[1].status == "error"

    def test_missing_tool_result_custom_content(self):
        msgs = [_ai([_tc("bash", "c1")])]
        result = normalize_tool_call_transcript(msgs, synthetic_content="custom error")
        assert result[1].content == "custom error"

    def test_non_adjacent_tool_result_moved(self):
        msgs = [
            _ai([_tc("bash", "c1")]),
            HumanMessage(content="interruption"),
            _tool("c1", "bash"),
        ]
        result = normalize_tool_call_transcript(msgs)
        # ToolMessage should be right after AIMessage, before HumanMessage.
        assert isinstance(result[0], AIMessage)
        assert isinstance(result[1], ToolMessage)
        assert result[1].tool_call_id == "c1"
        assert isinstance(result[2], HumanMessage)

    def test_multiple_tool_results_grouped_after_one_ai_turn(self):
        msgs = [
            _ai([_tc("bash", "c1"), _tc("read", "c2")]),
            HumanMessage(content="interruption"),
            _tool("c2", "read"),
            _tool("c1", "bash"),
        ]
        result = normalize_tool_call_transcript(msgs)
        # Both ToolMessages right after AIMessage, then HumanMessage.
        assert isinstance(result[0], AIMessage)
        assert isinstance(result[1], ToolMessage)
        assert isinstance(result[2], ToolMessage)
        assert {result[1].tool_call_id, result[2].tool_call_id} == {"c1", "c2"}
        assert isinstance(result[3], HumanMessage)

    def test_multiple_ai_turns_each_result_stays_with_own_turn(self):
        msgs = [
            _ai([_tc("bash", "c1")]),
            HumanMessage(content="interruption"),
            _ai([_tc("read", "c2")]),
            _tool("c1", "bash"),
            _tool("c2", "read"),
        ]
        result = normalize_tool_call_transcript(msgs)
        # Turn 1: AI + ToolMessage for c1
        assert isinstance(result[0], AIMessage)
        assert isinstance(result[1], ToolMessage)
        assert result[1].tool_call_id == "c1"
        # Then HumanMessage
        assert isinstance(result[2], HumanMessage)
        # Turn 2: AI + ToolMessage for c2
        assert isinstance(result[3], AIMessage)
        assert isinstance(result[4], ToolMessage)
        assert result[4].tool_call_id == "c2"

    def test_orphan_tool_message_preserved(self):
        orphan = _tool("orphan_id", "orphan")
        msgs = [
            _ai([_tc("bash", "c1")]),
            orphan,
            HumanMessage(content="interruption"),
            _tool("c1", "bash"),
        ]
        result = normalize_tool_call_transcript(msgs)
        # c1 tool message should be right after AI.
        assert isinstance(result[0], AIMessage)
        assert isinstance(result[1], ToolMessage)
        assert result[1].tool_call_id == "c1"
        # Orphan should still be present.
        assert orphan in result

    def test_middleware_inserts_non_tool_between_ai_and_tool(self):
        """Simulates middleware inserting SystemMessage between tool call and result."""
        msgs = [
            _ai([_tc("bash", "c1")]),
            SystemMessage(content="middleware note"),
            _tool("c1", "bash"),
        ]
        result = normalize_tool_call_transcript(msgs)
        assert isinstance(result[0], AIMessage)
        assert isinstance(result[1], ToolMessage)
        assert result[1].tool_call_id == "c1"
        assert isinstance(result[2], SystemMessage)

    def test_mixed_responded_and_missing(self):
        msgs = [
            _ai([_tc("bash", "c1"), _tc("read", "c2")]),
            _tool("c1", "bash"),
            # c2 is missing
        ]
        result = normalize_tool_call_transcript(msgs)
        tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 2
        synthetic = [m for m in tool_msgs if getattr(m, "status", None) == "error"]
        assert len(synthetic) == 1
        assert synthetic[0].tool_call_id == "c2"

    def test_multiple_missing_results(self):
        msgs = [
            _ai([_tc("bash", "c1")]),
            HumanMessage(content="next"),
            _ai([_tc("read", "c2"), _tc("write", "c3")]),
        ]
        result = normalize_tool_call_transcript(msgs)
        # First AI: synthetic for c1
        # HumanMessage
        # Second AI: synthetics for c2, c3
        assert isinstance(result[0], AIMessage)
        assert isinstance(result[1], ToolMessage)
        assert result[1].tool_call_id == "c1"
        assert isinstance(result[2], HumanMessage)
        assert isinstance(result[3], AIMessage)
        assert isinstance(result[4], ToolMessage)
        assert result[4].tool_call_id == "c2"
        assert isinstance(result[5], ToolMessage)
        assert result[5].tool_call_id == "c3"

    def test_no_mutation_of_input(self):
        original = [
            _ai([_tc("bash", "c1")]),
            HumanMessage(content="interruption"),
            _tool("c1", "bash"),
        ]
        import copy
        snapshot = copy.deepcopy(original)
        normalize_tool_call_transcript(original)
        assert original == snapshot


# ===========================================================================
# Round-trip: validate → normalize → validate
# ===========================================================================


class TestRoundTrip:
    """Verify that normalizing an invalid transcript makes it valid."""

    @pytest.mark.parametrize(
        "msgs",
        [
            # missing result
            [_ai([_tc("bash", "c1")])],
            # non-adjacent
            [_ai([_tc("bash", "c1")]), HumanMessage(content="x"), _tool("c1")],
            # middleware injection
            [_ai([_tc("bash", "c1")]), SystemMessage(content="note"), _tool("c1")],
            # multiple missing
            [_ai([_tc("bash", "c1")]), _ai([_tc("read", "c2")])],
        ],
        ids=["missing", "non-adjacent", "middleware-injection", "multiple-missing"],
    )
    def test_normalize_fixes_violations(self, msgs):
        r1 = validate_tool_call_transcript(msgs)
        assert not r1.is_valid, f"Expected invalid, got valid: {r1.violations}"

        fixed = normalize_tool_call_transcript(msgs)
        r2 = validate_tool_call_transcript(fixed)
        assert r2.is_valid, f"Still invalid after normalization: {r2.violations}"

    def test_already_valid_stays_valid(self):
        msgs = [
            _ai([_tc("bash", "c1")]),
            _tool("c1", "bash"),
            HumanMessage(content="next"),
        ]
        r = validate_tool_call_transcript(msgs)
        assert r.is_valid
        fixed = normalize_tool_call_transcript(msgs)
        assert fixed is msgs  # no-op returns same object
        r2 = validate_tool_call_transcript(fixed)
        assert r2.is_valid
