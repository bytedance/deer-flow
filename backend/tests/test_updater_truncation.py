"""Tests for the head500 + tail500 message truncation in format_conversation_for_update."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deermem.core.prompt import format_conversation_for_update


def test_long_message_keeps_head_and_tail_drops_middle() -> None:
    # 600 head chars + 400 middle + 600 tail = 1600 (> 1000 -> truncated).
    long_content = "H" * 600 + "M" * 400 + "T" * 600
    result = format_conversation_for_update([HumanMessage(content=long_content)])

    assert "[truncated]" in result
    # The first 500 and last 500 characters survive.
    assert "H" * 500 in result
    assert "T" * 500 in result
    # The middle block is dropped.
    assert "M" * 400 not in result


def test_message_under_threshold_is_not_truncated() -> None:
    result = format_conversation_for_update([HumanMessage(content="a short message")])
    assert "[truncated]" not in result
    assert "a short message" in result


def test_message_exactly_1000_chars_is_not_truncated() -> None:
    # The guard is strictly greater-than 1000, so 1000 chars pass through whole.
    result = format_conversation_for_update([HumanMessage(content="x" * 1000)])
    assert "[truncated]" not in result


def test_message_1001_chars_is_truncated() -> None:
    result = format_conversation_for_update([HumanMessage(content="x" * 1001)])
    assert "[truncated]" in result


def test_truncation_then_html_escape_preserves_head_marker() -> None:
    # A leading "<b>" must be HTML-escaped after truncation (block-breakout
    # defense), and the head is preserved up to the 500-char boundary.
    long_content = "<b>" + "y" * 1500
    result = format_conversation_for_update([HumanMessage(content=long_content)])
    assert "&lt;b&gt;" in result
    assert "[truncated]" in result


def test_truncation_applies_to_ai_messages_too() -> None:
    long_content = "A" * 700 + "B" * 700
    result = format_conversation_for_update([AIMessage(content=long_content)])
    assert "[truncated]" in result
    assert "A" * 500 in result
    assert "B" * 500 in result
