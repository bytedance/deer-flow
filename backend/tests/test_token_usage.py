"""Tests for token usage tracking in DeerFlowClient."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.client import DeerFlowClient


# ---------------------------------------------------------------------------
# _serialize_message — usage_metadata passthrough
# ---------------------------------------------------------------------------


class TestSerializeMessageUsageMetadata:
    """Verify _serialize_message includes usage_metadata when present."""

    def test_ai_message_with_usage_metadata(self):
        msg = AIMessage(
            content="Hello",
            id="msg-1",
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["type"] == "ai"
        assert result["usage_metadata"] == {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }

    def test_ai_message_without_usage_metadata(self):
        msg = AIMessage(content="Hello", id="msg-2")
        result = DeerFlowClient._serialize_message(msg)
        assert result["type"] == "ai"
        assert "usage_metadata" not in result

    def test_tool_message_never_has_usage_metadata(self):
        msg = ToolMessage(content="result", tool_call_id="tc-1", name="search")
        result = DeerFlowClient._serialize_message(msg)
        assert result["type"] == "tool"
        assert "usage_metadata" not in result

    def test_human_message_never_has_usage_metadata(self):
        msg = HumanMessage(content="Hi")
        result = DeerFlowClient._serialize_message(msg)
        assert result["type"] == "human"
        assert "usage_metadata" not in result

    def test_ai_message_with_tool_calls_and_usage(self):
        msg = AIMessage(
            content="",
            id="msg-3",
            tool_calls=[{"name": "search", "args": {"q": "test"}, "id": "tc-1"}],
            usage_metadata={"input_tokens": 200, "output_tokens": 30, "total_tokens": 230},
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["type"] == "ai"
        assert result["tool_calls"] == [{"name": "search", "args": {"q": "test"}, "id": "tc-1"}]
        assert result["usage_metadata"]["input_tokens"] == 200

    def test_ai_message_with_zero_usage(self):
        """usage_metadata with zero token counts should be included."""
        msg = AIMessage(
            content="Hello",
            id="msg-4",
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["usage_metadata"] == {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }


# ---------------------------------------------------------------------------
# Cumulative usage tracking (simulated, no real agent)
# ---------------------------------------------------------------------------


class TestCumulativeUsageTracking:
    """Test cumulative usage aggregation logic."""

    def test_single_message_usage(self):
        """Single AI message usage should be the total."""
        cumulative = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        usage = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
        cumulative["input_tokens"] += usage.get("input_tokens", 0) or 0
        cumulative["output_tokens"] += usage.get("output_tokens", 0) or 0
        cumulative["total_tokens"] += usage.get("total_tokens", 0) or 0
        assert cumulative == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}

    def test_multiple_messages_usage(self):
        """Multiple AI messages should accumulate."""
        cumulative = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        messages_usage = [
            {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            {"input_tokens": 200, "output_tokens": 30, "total_tokens": 230},
            {"input_tokens": 150, "output_tokens": 80, "total_tokens": 230},
        ]
        for usage in messages_usage:
            cumulative["input_tokens"] += usage.get("input_tokens", 0) or 0
            cumulative["output_tokens"] += usage.get("output_tokens", 0) or 0
            cumulative["total_tokens"] += usage.get("total_tokens", 0) or 0
        assert cumulative == {"input_tokens": 450, "output_tokens": 160, "total_tokens": 610}

    def test_missing_usage_keys_treated_as_zero(self):
        """Missing keys in usage dict should be treated as 0."""
        cumulative = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        usage = {"input_tokens": 50}  # missing output_tokens, total_tokens
        cumulative["input_tokens"] += usage.get("input_tokens", 0) or 0
        cumulative["output_tokens"] += usage.get("output_tokens", 0) or 0
        cumulative["total_tokens"] += usage.get("total_tokens", 0) or 0
        assert cumulative == {"input_tokens": 50, "output_tokens": 0, "total_tokens": 0}

    def test_empty_usage_metadata_stays_zero(self):
        """No usage metadata should leave cumulative at zero."""
        cumulative = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        # Simulate: AI message without usage_metadata
        usage = None
        if usage:
            cumulative["input_tokens"] += usage.get("input_tokens", 0) or 0
        assert cumulative == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
