"""Tests for compact tool-activity formatting helpers (pure)."""

from deerflow.tui.message_format import (
    format_tool_detail,
    format_tool_result,
    summarize_tool_title,
    truncate,
)


def test_summarize_known_tool_titles():
    assert summarize_tool_title("read_file") == "Read"
    assert summarize_tool_title("write_file") == "Write"
    assert summarize_tool_title("bash") == "Bash"


def test_summarize_unknown_tool_falls_back_to_humanized_name():
    assert summarize_tool_title("my_custom_tool") == "My Custom Tool"


def test_format_tool_detail_extracts_salient_arg():
    assert format_tool_detail("read_file", {"path": "src/app.py"}) == "src/app.py"
    assert format_tool_detail("bash", {"command": "ls -la"}) == "ls -la"
    assert format_tool_detail("web_search", {"query": "deerflow tui"}) == "deerflow tui"


def test_format_tool_detail_unknown_args_compact_json():
    detail = format_tool_detail("mystery", {"a": 1, "b": 2})
    assert "a" in detail and "1" in detail


def test_format_tool_detail_empty_args_is_empty_string():
    assert format_tool_detail("bash", {}) == ""


def test_truncate_short_text_unchanged():
    assert truncate("hello", 80) == "hello"


def test_truncate_long_text_adds_marker():
    out = truncate("x" * 200, 50)
    assert len(out) <= 50 + 1  # marker char
    assert out.endswith("…")


def test_format_tool_result_collapses_whitespace_and_truncates():
    result = format_tool_result("line1\n\n   line2   \n", limit=80)
    assert "line1" in result and "line2" in result
    assert "\n" not in result


def test_format_tool_result_handles_non_string():
    assert format_tool_result({"ok": True}) != ""
