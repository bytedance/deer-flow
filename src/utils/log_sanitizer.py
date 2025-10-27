# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Log sanitization utilities to prevent log injection attacks.

This module provides functions to sanitize user-controlled input before
logging to prevent attackers from forging log entries through:
- Newline injection (\n)
- HTML injection (for HTML logs)
- Special character sequences that could be misinterpreted
"""

import re
from typing import Any, Optional


def sanitize_log_input(value: Any, max_length: int = 500) -> str:
    """
    Sanitize user-controlled input for safe logging.

    Replaces dangerous characters (newlines, tabs, carriage returns, etc.)
    with their escaped representations to prevent log injection attacks.

    Args:
        value: The input value to sanitize (any type)
        max_length: Maximum length of output string (truncates if exceeded)

    Returns:
        str: Sanitized string safe for logging

    Examples:
        >>> sanitize_log_input("normal text")
        'normal text'

        >>> sanitize_log_input("malicious\n[INFO] fake entry")
        'malicious\\n[INFO] fake entry'

        >>> sanitize_log_input("tab\there")
        'tab\\there'

        >>> sanitize_log_input(None)
        'None'

        >>> long_text = "a" * 1000
        >>> result = sanitize_log_input(long_text, max_length=100)
        >>> len(result) <= 100
        True
    """
    if value is None:
        return "None"

    # Convert to string
    string_value = str(value)

    # Replace dangerous characters with their escaped representations
    # Order matters: escape backslashes first to avoid double-escaping
    replacements = {
        "\\": "\\\\",  # Backslash (must be first)
        "\n": "\\n",   # Newline - prevents creating new log entries
        "\r": "\\r",   # Carriage return
        "\t": "\\t",   # Tab
        "\x00": "\\0",  # Null character
        "\x1b": "\\x1b",  # Escape character (used in ANSI sequences)
    }

    for char, replacement in replacements.items():
        string_value = string_value.replace(char, replacement)

    # Remove other control characters (ASCII 0-31 except those already handled)
    # These are rarely useful in logs and could be exploited
    string_value = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", string_value)

    # Truncate if too long (prevent log flooding)
    if len(string_value) > max_length:
        string_value = string_value[: max_length - 3] + "..."

    return string_value


def sanitize_thread_id(thread_id: Any) -> str:
    """
    Sanitize thread_id for logging.

    Thread IDs should be alphanumeric with hyphens and underscores,
    but we sanitize to be defensive.

    Args:
        thread_id: The thread ID to sanitize

    Returns:
        str: Sanitized thread ID
    """
    return sanitize_log_input(thread_id, max_length=100)


def sanitize_user_content(content: Any) -> str:
    """
    Sanitize user-provided message content for logging.

    User messages can be arbitrary length, so we truncate more aggressively.

    Args:
        content: The user content to sanitize

    Returns:
        str: Sanitized user content
    """
    return sanitize_log_input(content, max_length=200)


def sanitize_agent_name(agent_name: Any) -> str:
    """
    Sanitize agent name for logging.

    Agent names should be simple identifiers, but we sanitize to be defensive.

    Args:
        agent_name: The agent name to sanitize

    Returns:
        str: Sanitized agent name
    """
    return sanitize_log_input(agent_name, max_length=100)


def sanitize_tool_name(tool_name: Any) -> str:
    """
    Sanitize tool name for logging.

    Tool names should be simple identifiers, but we sanitize to be defensive.

    Args:
        tool_name: The tool name to sanitize

    Returns:
        str: Sanitized tool name
    """
    return sanitize_log_input(tool_name, max_length=100)


def sanitize_feedback(feedback: Any) -> str:
    """
    Sanitize user feedback for logging.

    Feedback can be arbitrary text from interrupts, so sanitize carefully.

    Args:
        feedback: The feedback to sanitize

    Returns:
        str: Sanitized feedback (truncated more aggressively)
    """
    return sanitize_log_input(feedback, max_length=150)


def create_safe_log_message(template: str, **kwargs) -> str:
    """
    Create a safe log message by sanitizing all values.

    Uses a template string with keyword arguments, sanitizing each value
    before substitution to prevent log injection.

    Args:
        template: Template string with {key} placeholders
        **kwargs: Key-value pairs to substitute

    Returns:
        str: Safe log message

    Example:
        >>> msg = create_safe_log_message(
        ...     "[{thread_id}] Processing {tool_name}",
        ...     thread_id="abc\\n[INFO]",
        ...     tool_name="my_tool"
        ... )
        >>> "[abc\\\\n[INFO]] Processing my_tool" in msg
        True
    """
    # Sanitize all values
    safe_kwargs = {
        key: sanitize_log_input(value) for key, value in kwargs.items()
    }

    # Substitute into template
    return template.format(**safe_kwargs)
