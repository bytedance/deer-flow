"""Unit tests for tool output truncation functions.

These functions truncate long tool outputs to prevent context window overflow.
- _truncate_bash_output: middle-truncation (head + tail), for bash tool
- _truncate_read_file_output: head-truncation, for read_file tool
"""

from deerflow.sandbox.tools import _truncate_bash_output, _truncate_read_file_output

# ---------------------------------------------------------------------------
# _truncate_bash_output
# ---------------------------------------------------------------------------


class TestTruncateBashOutput:
    def test_short_output_returned_unchanged(self):
        output = "hello world"
        assert _truncate_bash_output(output, 20000) == output

    def test_output_equal_to_limit_returned_unchanged(self):
        output = "A" * 20000
        assert _truncate_bash_output(output, 20000) == output

    def test_long_output_is_truncated(self):
        output = "A" * 30000
        result = _truncate_bash_output(output, 20000)
        assert len(result) < len(output)

    def test_result_never_exceeds_max_chars(self):
        output = "A" * 30000
        max_chars = 20000
        result = _truncate_bash_output(output, max_chars)
        assert len(result) <= max_chars

    def test_head_is_preserved(self):
        head = "HEAD_CONTENT"
        output = head + "M" * 30000
        result = _truncate_bash_output(output, 20000)
        assert result.startswith(head)

    def test_tail_is_preserved(self):
        tail = "TAIL_CONTENT"
        output = "M" * 30000 + tail
        result = _truncate_bash_output(output, 20000)
        assert result.endswith(tail)

    def test_middle_truncation_marker_present(self):
        output = "A" * 30000
        result = _truncate_bash_output(output, 20000)
        assert "[middle truncated:" in result
        assert "chars skipped" in result

    def test_skipped_chars_count_is_correct(self):
        # kept = max_chars - _MARKER_MAX_LEN (80) = 19920; skipped = 25000 - 19920 = 5080
        output = "A" * 25000
        result = _truncate_bash_output(output, 20000)
        skipped = 25000 - (20000 - 80)
        assert f"{skipped} chars skipped" in result

    def test_max_chars_zero_returns_empty(self):
        output = "A" * 100000
        assert _truncate_bash_output(output, 0) == ""

    def test_50_50_split(self):
        # head and tail should each be roughly max_chars // 2
        output = "H" * 20000 + "M" * 10000 + "T" * 20000
        result = _truncate_bash_output(output, 20000)
        assert result[:100] == "H" * 100
        assert result[-100:] == "T" * 100

    def test_small_max_chars_does_not_crash(self):
        output = "A" * 1000
        result = _truncate_bash_output(output, 10)
        assert len(result) <= 10

    def test_result_never_exceeds_max_chars_various_sizes(self):
        output = "X" * 50000
        for max_chars in [100, 1000, 5000, 20000, 49999]:
            result = _truncate_bash_output(output, max_chars)
            assert len(result) <= max_chars, f"failed for max_chars={max_chars}"


# ---------------------------------------------------------------------------
# _truncate_read_file_output
# ---------------------------------------------------------------------------


class TestTruncateReadFileOutput:
    def test_short_output_returned_unchanged(self):
        output = "def foo():\n    pass\n"
        assert _truncate_read_file_output(output, 50000) == output

    def test_output_equal_to_limit_returned_unchanged(self):
        output = "X" * 50000
        assert _truncate_read_file_output(output, 50000) == output

    def test_long_output_is_truncated(self):
        output = "X" * 60000
        result = _truncate_read_file_output(output, 50000)
        assert len(result) < len(output)

    def test_result_never_exceeds_max_chars(self):
        output = "X" * 60000
        max_chars = 50000
        result = _truncate_read_file_output(output, max_chars)
        assert len(result) <= max_chars

    def test_head_is_preserved(self):
        head = "import os\nimport sys\n"
        output = head + "X" * 60000
        result = _truncate_read_file_output(output, 50000)
        assert result.startswith(head)

    def test_truncation_marker_present(self):
        output = "X" * 60000
        result = _truncate_read_file_output(output, 50000)
        assert "[truncated:" in result
        assert "showing first" in result

    def test_total_chars_reported_correctly(self):
        output = "X" * 60000
        result = _truncate_read_file_output(output, 50000)
        assert "of 60000 chars" in result

    def test_start_line_hint_present(self):
        output = "X" * 60000
        result = _truncate_read_file_output(output, 50000)
        assert "start_line" in result
        assert "end_line" in result

    def test_max_chars_zero_returns_empty(self):
        output = "X" * 100000
        assert _truncate_read_file_output(output, 0) == ""

    def test_tail_is_not_preserved(self):
        # head-truncation: tail should be cut off
        output = "H" * 50000 + "TAIL_SHOULD_NOT_APPEAR"
        result = _truncate_read_file_output(output, 50000)
        assert "TAIL_SHOULD_NOT_APPEAR" not in result

    def test_small_max_chars_does_not_crash(self):
        output = "X" * 1000
        result = _truncate_read_file_output(output, 10)
        assert len(result) <= 10

    def test_result_never_exceeds_max_chars_various_sizes(self):
        output = "X" * 50000
        for max_chars in [100, 1000, 5000, 20000, 49999]:
            result = _truncate_read_file_output(output, max_chars)
            assert len(result) <= max_chars, f"failed for max_chars={max_chars}"
