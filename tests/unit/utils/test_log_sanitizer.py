# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Unit tests for log sanitization utilities.

This test file verifies that the log sanitizer properly prevents log injection attacks
by escaping dangerous characters in user-controlled input before logging.
"""

import pytest

from src.utils.log_sanitizer import (
    create_safe_log_message,
    sanitize_agent_name,
    sanitize_feedback,
    sanitize_log_input,
    sanitize_thread_id,
    sanitize_tool_name,
    sanitize_user_content,
)


class TestSanitizeLogInput:
    """Test the main sanitize_log_input function."""

    def test_sanitize_normal_text(self):
        """Test that normal text is preserved."""
        text = "normal text"
        result = sanitize_log_input(text)
        assert result == "normal text"

    def test_sanitize_newline_injection(self):
        """Test prevention of newline injection attack."""
        malicious = "abc\n[INFO] Forged log entry"
        result = sanitize_log_input(malicious)
        assert "\n" not in result
        assert "[INFO]" in result  # The attack text is preserved but escaped
        assert "\\n" in result  # Newline is escaped

    def test_sanitize_carriage_return(self):
        """Test prevention of carriage return injection."""
        malicious = "text\r[WARN] Forged entry"
        result = sanitize_log_input(malicious)
        assert "\r" not in result
        assert "\\r" in result

    def test_sanitize_tab_character(self):
        """Test prevention of tab character injection."""
        malicious = "text\t[ERROR] Forged"
        result = sanitize_log_input(malicious)
        assert "\t" not in result
        assert "\\t" in result

    def test_sanitize_null_character(self):
        """Test prevention of null character injection."""
        malicious = "text\x00[CRITICAL]"
        result = sanitize_log_input(malicious)
        assert "\x00" not in result

    def test_sanitize_backslash(self):
        """Test that backslashes are properly escaped."""
        text = "path\\to\\file"
        result = sanitize_log_input(text)
        assert result == "path\\\\to\\\\file"

    def test_sanitize_escape_character(self):
        """Test prevention of ANSI escape sequence injection."""
        malicious = "text\x1b[31mRED TEXT\x1b[0m"
        result = sanitize_log_input(malicious)
        assert "\x1b" not in result
        assert "\\x1b" in result

    def test_sanitize_max_length_truncation(self):
        """Test that long strings are truncated."""
        long_text = "a" * 1000
        result = sanitize_log_input(long_text, max_length=100)
        assert len(result) <= 100
        assert result.endswith("...")

    def test_sanitize_none_value(self):
        """Test that None is handled properly."""
        result = sanitize_log_input(None)
        assert result == "None"

    def test_sanitize_numeric_value(self):
        """Test that numeric values are converted to strings."""
        result = sanitize_log_input(12345)
        assert result == "12345"

    def test_sanitize_complex_injection_attack(self):
        """Test complex multi-character injection attack."""
        malicious = 'thread-123\n[WARNING] Unauthorized\r[ERROR] System failure\t[CRITICAL] Shutdown'
        result = sanitize_log_input(malicious)
        # All dangerous characters should be escaped
        assert "\n" not in result
        assert "\r" not in result
        assert "\t" not in result
        # But the text should still be there (escaped)
        assert "WARNING" in result
        assert "ERROR" in result


class TestSanitizeThreadId:
    """Test sanitization of thread IDs."""

    def test_thread_id_normal(self):
        """Test normal thread ID."""
        thread_id = "thread-123-abc"
        result = sanitize_thread_id(thread_id)
        assert result == "thread-123-abc"

    def test_thread_id_with_newline(self):
        """Test thread ID with newline injection."""
        malicious = "thread-1\n[INFO] Forged"
        result = sanitize_thread_id(malicious)
        assert "\n" not in result
        assert "\\n" in result

    def test_thread_id_max_length(self):
        """Test that thread ID truncation respects max length."""
        long_id = "x" * 200
        result = sanitize_thread_id(long_id)
        assert len(result) <= 100


class TestSanitizeUserContent:
    """Test sanitization of user-provided message content."""

    def test_user_content_normal(self):
        """Test normal user content."""
        content = "What is the weather today?"
        result = sanitize_user_content(content)
        assert result == "What is the weather today?"

    def test_user_content_with_newline(self):
        """Test user content with newline."""
        malicious = "My question\n[ADMIN] Delete user"
        result = sanitize_user_content(malicious)
        assert "\n" not in result
        assert "\\n" in result

    def test_user_content_max_length(self):
        """Test that user content is truncated more aggressively."""
        long_content = "x" * 500
        result = sanitize_user_content(long_content)
        assert len(result) <= 200


class TestSanitizeToolName:
    """Test sanitization of tool names."""

    def test_tool_name_normal(self):
        """Test normal tool name."""
        tool = "web_search"
        result = sanitize_tool_name(tool)
        assert result == "web_search"

    def test_tool_name_injection(self):
        """Test tool name with injection attempt."""
        malicious = "search\n[WARN] Forged"
        result = sanitize_tool_name(malicious)
        assert "\n" not in result


class TestSanitizeFeedback:
    """Test sanitization of user feedback."""

    def test_feedback_normal(self):
        """Test normal feedback."""
        feedback = "[accepted]"
        result = sanitize_feedback(feedback)
        assert result == "[accepted]"

    def test_feedback_injection(self):
        """Test feedback with injection attempt."""
        malicious = "[approved]\n[CRITICAL] System down"
        result = sanitize_feedback(malicious)
        assert "\n" not in result
        assert "\\n" in result

    def test_feedback_max_length(self):
        """Test that feedback is truncated."""
        long_feedback = "x" * 500
        result = sanitize_feedback(long_feedback)
        assert len(result) <= 150


class TestCreateSafeLogMessage:
    """Test the create_safe_log_message helper function."""

    def test_safe_message_normal(self):
        """Test normal message creation."""
        msg = create_safe_log_message(
            "[{thread_id}] Processing {tool_name}",
            thread_id="thread-1",
            tool_name="search",
        )
        assert "[thread-1] Processing search" == msg

    def test_safe_message_with_injection(self):
        """Test message creation with injected values."""
        msg = create_safe_log_message(
            "[{thread_id}] Tool: {tool_name}",
            thread_id="id\n[INFO] Forged",
            tool_name="search\r[ERROR]",
        )
        # The dangerous characters should be escaped
        assert "\n" not in msg
        assert "\r" not in msg
        assert "\\n" in msg
        assert "\\r" in msg

    def test_safe_message_multiple_values(self):
        """Test message with multiple values."""
        msg = create_safe_log_message(
            "[{id}] User: {user} Tool: {tool}",
            id="123",
            user="admin\t[WARN]",
            tool="delete\x1b[31m",
        )
        assert "\t" not in msg
        assert "\x1b" not in msg


class TestLogInjectionAttackPrevention:
    """Integration tests for log injection prevention."""

    def test_classic_log_injection_newline(self):
        """Test the classic log injection attack using newlines."""
        attacker_input = 'abc\n[WARNING] Unauthorized access detected'
        result = sanitize_log_input(attacker_input)
        # The output should not contain an actual newline that would create a new log entry
        assert result.count("\n") == 0
        # But the escaped version should be in there
        assert "\\n" in result

    def test_carriage_return_log_injection(self):
        """Test log injection via carriage return."""
        attacker_input = "request_id\r\n[ERROR] CRITICAL FAILURE"
        result = sanitize_log_input(attacker_input)
        assert "\r" not in result
        assert "\n" not in result

    def test_html_injection_prevention(self):
        """Test prevention of HTML injection in logs."""
        # While HTML tags themselves aren't dangerous in log files,
        # escaping control characters helps prevent parsing attacks
        malicious_html = "user\x1b[32m<script>alert('xss')</script>"
        result = sanitize_log_input(malicious_html)
        assert "\x1b" not in result
        # HTML is preserved but with escaped control chars
        assert "<script>" in result

    def test_multiple_injection_techniques(self):
        """Test prevention of multiple injection techniques combined."""
        attack = 'id_1\n\r\t[CRITICAL]\x1b[31m RED TEXT'
        result = sanitize_log_input(attack)
        # No actual control characters should exist
        assert "\n" not in result
        assert "\r" not in result
        assert "\t" not in result
        assert "\x1b" not in result
        # But escaped versions should exist
        assert "\\n" in result
        assert "\\r" in result
        assert "\\t" in result
        assert "\\x1b" in result
