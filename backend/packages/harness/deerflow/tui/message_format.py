"""Compact, human-friendly formatting for tool activity in the TUI.

Pure helpers: given a tool name + args (or a tool result), produce short,
readable strings for the transcript instead of dumping raw JSON. No Textual
dependency.
"""

from __future__ import annotations

import json
from typing import Any

# Friendly titles for built-in tools. Anything not listed falls back to a
# humanized version of the raw name.
_TOOL_TITLES: dict[str, str] = {
    "read_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "str_replace": "Edit",
    "bash": "Bash",
    "shell": "Shell",
    "command": "Run",
    "web_search": "Search",
    "web_fetch": "Fetch",
    "todo_write": "Todo",
    "task": "Subagent",
    "ls": "List",
    "glob": "Find",
    "grep": "Search",
}

# Per-tool: which arg holds the single most salient value to show inline.
_DETAIL_KEYS: dict[str, tuple[str, ...]] = {
    "read_file": ("path", "file_path", "filename"),
    "write_file": ("path", "file_path", "filename"),
    "edit_file": ("path", "file_path", "filename"),
    "bash": ("command", "cmd"),
    "shell": ("command", "cmd"),
    "command": ("command", "cmd"),
    "web_search": ("query", "q"),
    "grep": ("pattern", "query"),
    "glob": ("pattern",),
    "web_fetch": ("url",),
}

# Generic arg keys to try when a tool isn't in _DETAIL_KEYS.
_GENERIC_DETAIL_KEYS = ("path", "file_path", "command", "query", "url", "pattern", "name")

DEFAULT_DETAIL_LIMIT = 80
DEFAULT_RESULT_LIMIT = 160


def truncate(text: str, limit: int) -> str:
    """Truncate ``text`` to ``limit`` chars, appending an ellipsis marker."""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def summarize_tool_title(tool_name: str) -> str:
    if not tool_name or not tool_name.strip():
        return "Tool"
    if tool_name in _TOOL_TITLES:
        return _TOOL_TITLES[tool_name]
    return _humanize(tool_name)


def format_tool_detail(tool_name: str, args: Any, limit: int = DEFAULT_DETAIL_LIMIT) -> str:
    """Return a short inline detail for a tool call (e.g. the path or command)."""
    if not isinstance(args, dict) or not args:
        return ""

    keys = _DETAIL_KEYS.get(tool_name, ()) + _GENERIC_DETAIL_KEYS
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return truncate(_one_line(value), limit)

    # Fallback: compact JSON of the args.
    try:
        compact = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        compact = str(args)
    return truncate(compact, limit)


def format_tool_result(result: Any, limit: int = DEFAULT_RESULT_LIMIT) -> str:
    """Return a one-line, truncated preview of a tool result."""
    if result is None:
        return ""
    if not isinstance(result, str):
        try:
            result = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            result = str(result)
    return truncate(_one_line(result), limit)


def _one_line(text: str) -> str:
    """Collapse all runs of whitespace (incl. newlines) into single spaces."""
    return " ".join(text.split())


def _humanize(name: str) -> str:
    cleaned = name.replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return name
    return " ".join(word[:1].upper() + word[1:] for word in cleaned.split())
