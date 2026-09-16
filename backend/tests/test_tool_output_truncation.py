"""Unit tests for tool output truncation functions.

These functions truncate long tool outputs to prevent context window overflow.
- _truncate_bash_output: middle-truncation (head + tail), for bash tool
- _truncate_read_file_output: head-truncation, for read_file tool
- _truncate_ls_output: head-truncation, for ls tool
"""

import re

from deerflow.sandbox.tools import _truncate_bash_output, _truncate_ls_output, _truncate_read_file_output


def _head_and_marker(result: str) -> tuple[str, str]:
    """Split a truncated read_file result into shown head and trailing marker."""
    idx = result.rfind("\n... [truncated:")
    assert idx != -1, "truncation marker missing"
    return result[:idx], result[idx:]


def _line_containing(output: str, char_index: int) -> int:
    """Return the 0-based line index holding ``output[char_index]``.

    Computed from line spans independently of the truncation marker, so the
    tests verify the marker's reported line rather than restating its formula.
    """
    assert 0 <= char_index < len(output)
    starts = [0]
    for line in output.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    candidate = 0
    for i, start in enumerate(starts):
        if start <= char_index:
            candidate = i
    return candidate


# ---------------------------------------------------------------------------
# _truncate_bash_output
# ---------------------------------------------------------------------------


class TestTruncateBashOutput:
    def test_short_output_returned_unchanged(self):
        output = "hello world"
        assert _truncate_bash_output(output, 20000) == output

    def test_trailing_exit_marker_survives_truncation(self):
        """PR review: a failing command's pass-shaped text must not lose the
        authoritative exit marker to truncation — evidence consumers parse it."""
        output = "1 passed\n" + "M" * 30000 + "\nExit Code: 1"
        result = _truncate_bash_output(output, 20000)
        assert result.endswith("\nExit Code: 1")
        assert len(result) <= 20000

    def test_trailing_exit_marker_survives_a_tiny_budget(self):
        output = "x" * 5000 + "\nExit Code: 124"
        result = _truncate_bash_output(output, 100)
        assert result.endswith("\nExit Code: 124")
        assert len(result) <= 100

    def test_command_exited_with_code_form_is_preserved(self):
        output = "M" * 5000 + "\nCommand exited with code 3"
        result = _truncate_bash_output(output, 1000)
        assert result.endswith("Command exited with code 3")

    def test_signed_signal_exit_marker_is_preserved(self):
        """Signal-killed processes report signed codes (Exit Code: -9)."""
        output = "5 passed\n" + "M" * 5000 + "\nExit Code: -9"
        result = _truncate_bash_output(output, 100)
        assert result.endswith("\nExit Code: -9")
        assert len(result) <= 100

    def test_marker_preserved_when_limit_is_below_marker_length(self):
        """PR review: a configured limit smaller than the exit marker must
        not silently discard failure status — the floor keeps it."""
        result = _truncate_bash_output("1 passed\nExit Code: 1", 10)
        assert result.endswith("\nExit Code: 1")
        assert len(result) <= 32  # the marker-preserving floor

    def test_small_limit_without_marker_uses_the_floor(self):
        result = _truncate_bash_output("x" * 500, 10)
        assert len(result) <= 32

    def test_output_without_marker_truncates_as_before(self):
        output = "A" * 30000
        result = _truncate_bash_output(output, 20000)
        assert len(result) <= 20000
        assert not result.endswith("Exit Code: 1")

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
        output = "A" * 25000
        result = _truncate_bash_output(output, 20000)
        # Extract the reported skipped count and verify it equals len(output) - kept.
        # (kept = max_chars - marker_max_len, where marker_max_len is computed from
        # the worst-case marker string — so the exact value is implementation-defined,
        # but it must equal len(output) minus the chars actually preserved.)
        import re

        m = re.search(r"(\d+) chars skipped", result)
        assert m is not None
        reported_skipped = int(m.group(1))
        # Verify the number is self-consistent: head + skipped + tail == total
        assert reported_skipped > 0
        # The marker reports exactly the chars between head and tail
        head_and_tail = len(output) - reported_skipped
        assert result.startswith(output[: head_and_tail // 2])

    def test_max_chars_zero_disables_truncation(self):
        output = "A" * 100000
        assert _truncate_bash_output(output, 0) == output

    def test_50_50_split(self):
        # head and tail should each be roughly max_chars // 2
        output = "H" * 20000 + "M" * 10000 + "T" * 20000
        result = _truncate_bash_output(output, 20000)
        assert result[:100] == "H" * 100
        assert result[-100:] == "T" * 100

    def test_small_max_chars_does_not_crash(self):
        output = "A" * 1000
        result = _truncate_bash_output(output, 10)
        # Limits below the marker-preserving floor (32) are raised so a
        # failing command's exit marker always fits; see
        # _BASH_OUTPUT_MIN_LIMIT_CHARS.
        assert len(result) <= 32

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

    def test_marker_reports_the_line_the_cut_lands_in(self):
        # Shape from #5475: a multi-line file cut mid-line, where the old
        # marker gave only a character count so the model could not compute
        # which line to resume from.
        output = "".join(f"def fn_{i}():\n    return {i}\n" for i in range(3000))
        result = _truncate_read_file_output(output, 50000)
        head, marker = _head_and_marker(result)
        cut_line = int(re.search(r"cut lands in line (\d+) of", marker).group(1))
        total_lines = output.count("\n")
        assert f"cut lands in line {cut_line} of {total_lines}" in marker
        assert f"start_line={cut_line}" in marker
        # The no-gap contract: the reported line is the one holding the first
        # hidden character (computed independently from line spans).
        assert _line_containing(output, len(head)) + 1 == cut_line

    def test_first_hidden_character_always_belongs_to_reported_line(self):
        # Whatever size the cut lands at — mid-line or exactly after a
        # newline — the reported line is the one holding the first hidden
        # character, so resuming at start_line=<reported> leaves no gap.
        lines = [f"line-{i}-with-padding\n" for i in range(1, 3001)]
        output = "".join(lines)
        for max_chars in [1000, 5000, 20000, 50000]:
            result = _truncate_read_file_output(output, max_chars)
            head, marker = _head_and_marker(result)
            cut_line = int(re.search(r"cut lands in line (\d+) of", marker).group(1))
            assert 1 <= cut_line <= len(lines)
            assert _line_containing(output, len(head)) + 1 == cut_line
            assert f"start_line={cut_line}" in marker
            assert len(result) <= max_chars

    def test_marker_reports_total_lines(self):
        lines = [f"line-{i}-with-padding\n" for i in range(1, 3001)]
        output = "".join(lines)
        result = _truncate_read_file_output(output, 50000)
        _, marker = _head_and_marker(result)
        assert f"of {output.count(chr(10))}" in marker

    def test_ranged_read_reports_absolute_lines(self):
        # Ranged reads hand a slice to the truncator; reported lines must be
        # absolute file lines or the resume hint loops back onto the slice's
        # own start (the repro from the #5478 review: start_line=831 kept
        # suggesting start_line=831 forever).
        slice_lines = [f"row-{i}-content\n" for i in range(1, 5171)]
        slice_output = "".join(slice_lines)
        offset = 830  # slice starts at absolute line 831
        result = _truncate_read_file_output(slice_output, 50000, line_offset=offset)
        head, marker = _head_and_marker(result)
        absolute_cut = offset + head.count("\n") + 1
        absolute_last = offset + len(slice_lines)
        assert f"cut lands in line {absolute_cut} of {absolute_last}" in marker
        assert f"start_line={absolute_cut}" in marker
        assert absolute_cut > offset + 1  # resume strictly advances

    def test_ranged_read_zero_offset_keeps_full_read_semantics(self):
        output = "".join(f"line-{i}-with-padding\n" for i in range(3000))
        assert _truncate_read_file_output(output, 50000) == _truncate_read_file_output(output, 50000, line_offset=0)

    def test_max_chars_zero_disables_truncation(self):
        output = "X" * 100000
        assert _truncate_read_file_output(output, 0) == output

    def test_cut_lands_on_a_line_boundary_and_names_the_next_line(self):
        lines = [f"line {i} " + "y" * (i % 50) for i in range(1, 3001)]
        output = "\n".join(lines) + "\n"
        result = _truncate_read_file_output(output, 50000)
        kept_text = result[: result.index("... [truncated:")]
        assert kept_text.endswith("\n")
        shown = kept_text.count("\n")
        assert kept_text == "\n".join(lines[:shown]) + "\n"
        assert f"showing first {shown} of 3000 lines" in result
        assert f"({len(kept_text)} of {len(output)} chars)" in result
        assert f"Continue with start_line={shown + 1}" in result
        assert "start_line/end_line" in result
        assert len(result) <= 50000

    def test_next_start_line_reads_the_rest_without_gap_or_overlap(self):
        lines = [f"line {i} " + "y" * (i % 50) for i in range(1, 3001)]
        output = "\n".join(lines) + "\n"
        result = _truncate_read_file_output(output, 50000)
        kept_text = result[: result.index("... [truncated:")]
        shown = kept_text.count("\n")
        # What read_file(start_line=shown + 1) returns is exactly the unread remainder.
        assert output[len(kept_text) :] == "\n".join(lines[shown:]) + "\n"

    def test_long_line_at_the_cut_falls_back_to_a_char_cut_that_names_the_line(self):
        output = "a\nb\n" + "X" * 60000
        result = _truncate_read_file_output(output, 50000)
        assert result.startswith("a\nb\nXXXX")
        assert result.count("X") > 49000  # the line boundary at char 4 is not used: it would drop the whole budget
        assert f"of {len(output)} chars" in result
        assert "cut inside line 3 of 3 lines" in result
        # Re-reading line 3 could only be truncated to the same head, so it is not offered as the continuation.
        assert "Continue with start_line" not in result
        assert "longer than a read can return" in result and "cut -c" in result
        assert "start_line/end_line" in result
        assert len(result) <= 50000

    def test_fallback_names_the_line_when_it_fits_a_fresh_read(self):
        lines = [f"line {i}" for i in range(1, 2001)]
        lines[1499] = "L" * 6000  # a long line at the cut, but one a fresh read can return whole
        output = "\n".join(lines) + "\n"
        # The cut lands about 5,000 chars into the long line: past the 4,096-char slack, so the
        # boundary is not used, while the whole 6,000-char line still fits a fresh read.
        max_chars = len("\n".join(lines[:1499])) + 1 + 5000 + 300
        result = _truncate_read_file_output(output, max_chars)
        assert "cut inside line 1500 of 2000 lines" in result
        assert "Continue with start_line=1500" in result
        assert len(result) <= max_chars

    def test_ranged_read_marker_uses_file_line_numbers(self):
        lines = [f"line {i} " + "y" * (i % 50) for i in range(1, 3001)]
        # A ranged read from line 744 returns the file's lines 744.., renumbered from 1 by the provider.
        output = "\n".join(lines[743:]) + "\n"
        result = _truncate_read_file_output(output, 50000, line_offset=743)
        kept_text = result[: result.index("... [truncated:")]
        shown = kept_text.count("\n")
        assert f"showing lines 744-{743 + shown} of 744-3000 lines" in result
        assert f"Continue with start_line={743 + shown + 1}" in result
        assert "showing first" not in result

    def test_ranged_read_fallback_names_the_file_line(self):
        output = "a\nb\n" + "X" * 60000
        result = _truncate_read_file_output(output, 50000, line_offset=10)
        assert "cut inside line 13 of 11-13 lines" in result

    def test_a_line_exactly_as_long_as_the_budget_is_kept_as_a_complete_line(self):
        # Sweep budgets around the marker size so that for some max_chars the
        # first line's newline sits exactly at the char budget. A named
        # continuation must always move past line 1; naming line 1 again would
        # send the model in a circle.
        output = "\n".join("x" * 40 for _ in range(100)) + "\n"
        seen_boundary_at_40 = False
        for max_chars in range(200, 420):
            result = _truncate_read_file_output(output, max_chars)
            if result == output:
                continue
            assert len(result) <= max_chars
            marker = result.find("... [truncated:")
            assert output.startswith(result[:marker].rstrip("\n"))
            match = re.search(r"Continue with start_line=(\d+)", result)
            if match and "Read that line whole" not in result:
                assert int(match.group(1)) >= 2, (max_chars, result[marker:])
            if result[:marker] == "x" * 40 + "\n":
                seen_boundary_at_40 = True
                assert "showing first 1 of 100 lines" in result
                assert "Continue with start_line=2" in result
        assert seen_boundary_at_40

    def test_a_ranged_read_never_names_its_own_first_line_as_the_continuation(self):
        output = "\n".join("x" * 40 for _ in range(100)) + "\n"  # the provider's slice for start_line=2
        for max_chars in range(200, 420):
            result = _truncate_read_file_output(output, max_chars, line_offset=1)
            if result == output:
                continue
            match = re.search(r"Continue with start_line=(\d+)", result)
            if match and "Read that line whole" not in result:
                assert int(match.group(1)) >= 3, (max_chars, result[result.find("... [truncated:") :])

    def test_fallback_offers_a_single_line_read_when_only_the_line_alone_fits(self):
        tail = "".join(f"tail {i}\n" for i in range(200))
        # Longer than what a read carrying a marker keeps, but not longer than max_chars:
        # read_file(start_line=2, end_line=2) returns it whole.
        output = "a\n" + "y" * 49900 + "\n" + tail
        result = _truncate_read_file_output(output, 50000)
        assert "cut inside line 2 of 202 lines" in result
        assert "Read that line whole with start_line=2, end_line=2, then continue with start_line=3" in result
        assert _truncate_read_file_output("y" * 49900, 50000) == "y" * 49900
        # Longer than max_chars: no read_file call can return it, so bash is the only honest pointer.
        output = "a\n" + "y" * 50001 + "\n" + tail
        result = _truncate_read_file_output(output, 50000)
        assert "Continue with start_line" not in result and "Read that line whole" not in result
        assert "longer than a read can return" in result and "cut -c" in result

    def test_a_budget_too_small_for_any_marker_still_says_the_output_was_cut(self):
        output = "".join(f"{i:04d} " + "x" * 55 + "\n" for i in range(1, 1001))
        for max_chars in (10, 60, 150, 238):
            result = _truncate_read_file_output(output, max_chars)
            assert len(result) <= max_chars
            assert result.startswith("... [truncated:"[:max_chars])
            assert not result.startswith("0001")

    def test_a_joined_slice_counts_an_empty_last_line(self):
        # Providers return a ranged read as lines joined with newlines, so a
        # trailing newline there is an empty last line, not a terminator.
        lines = [f"line {i} " + "y" * (i % 50) for i in range(1, 3000)] + [""]
        output = "\n".join(lines)  # 3000 lines ending with a blank one
        result = _truncate_read_file_output(output, 50000, line_offset=1, joined_lines=True)
        assert "of 2-3001 lines" in result
        result = _truncate_read_file_output(output + "\n", 50000)
        assert "of 3000 lines" in result  # a whole-file read: the trailing newline terminates the last line

    def test_single_line_read_form_names_no_continuation_after_the_last_line(self):
        result = _truncate_read_file_output("a\n" + "y" * 50000, 50000)
        assert "Read that line whole with start_line=2, end_line=2]" in result
        assert "then continue" not in result
        result = _truncate_read_file_output("a\n" + "y" * 50000 + "\nz\n", 50000)
        assert "Read that line whole with start_line=2, end_line=2, then continue with start_line=3]" in result

    def test_single_line_read_form_keeps_naming_the_next_line_for_a_bounded_slice(self):
        # A ranged read's slice may stop before the end of the file (an
        # end_line below its length), so the line after its last line can
        # still exist; naming it costs at most a harmless "exceeds file length".
        result = _truncate_read_file_output("a\n" + "y" * 50000, 50000, line_offset=1000, joined_lines=True, ends_at_eof=False)
        assert "Read that line whole with start_line=1002, end_line=1002, then continue with start_line=1003]" in result
        # A start_line-only read runs to the end of the file, so its last line is the file's last line.
        result = _truncate_read_file_output("a\n" + "y" * 50000, 50000, line_offset=1000, joined_lines=True, ends_at_eof=True)
        assert "Read that line whole with start_line=1002, end_line=1002]" in result

    def test_file_without_trailing_newline_counts_its_last_line(self):
        lines = [f"line {i} " + "y" * (i % 50) for i in range(1, 3001)]
        output = "\n".join(lines)
        result = _truncate_read_file_output(output, 50000)
        assert "of 3000 lines" in result

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


# ---------------------------------------------------------------------------
# _truncate_ls_output
# ---------------------------------------------------------------------------


class TestTruncateLsOutput:
    def test_short_output_returned_unchanged(self):
        output = "dir1\ndir2\nfile1.txt"
        assert _truncate_ls_output(output, 20000) == output

    def test_output_equal_to_limit_returned_unchanged(self):
        output = "X" * 20000
        assert _truncate_ls_output(output, 20000) == output

    def test_long_output_is_truncated(self):
        output = "\n".join(f"file_{i}.txt" for i in range(5000))
        result = _truncate_ls_output(output, 20000)
        assert len(result) < len(output)

    def test_result_never_exceeds_max_chars(self):
        output = "\n".join(f"subdir/file_{i}.txt" for i in range(5000))
        max_chars = 20000
        result = _truncate_ls_output(output, max_chars)
        assert len(result) <= max_chars

    def test_head_is_preserved(self):
        head = "first_dir\nsecond_dir\n"
        output = head + "\n".join(f"file_{i}" for i in range(5000))
        result = _truncate_ls_output(output, 20000)
        assert result.startswith(head)

    def test_truncation_marker_present(self):
        output = "\n".join(f"file_{i}.txt" for i in range(5000))
        result = _truncate_ls_output(output, 20000)
        assert "[truncated:" in result
        assert "showing first" in result

    def test_total_chars_reported_correctly(self):
        output = "X" * 30000
        result = _truncate_ls_output(output, 20000)
        assert "of 30000 chars" in result

    def test_hint_suggests_specific_path(self):
        output = "X" * 30000
        result = _truncate_ls_output(output, 20000)
        assert "Use a more specific path" in result

    def test_max_chars_zero_disables_truncation(self):
        output = "\n".join(f"file_{i}.txt" for i in range(10000))
        assert _truncate_ls_output(output, 0) == output

    def test_tail_is_not_preserved(self):
        output = "H" * 20000 + "TAIL_SHOULD_NOT_APPEAR"
        result = _truncate_ls_output(output, 20000)
        assert "TAIL_SHOULD_NOT_APPEAR" not in result

    def test_small_max_chars_does_not_crash(self):
        output = "\n".join(f"file_{i}.txt" for i in range(100))
        result = _truncate_ls_output(output, 10)
        assert len(result) <= 10

    def test_result_never_exceeds_max_chars_various_sizes(self):
        output = "\n".join(f"file_{i}.txt" for i in range(5000))
        for max_chars in [100, 1000, 5000, 20000, len(output) - 1]:
            result = _truncate_ls_output(output, max_chars)
            assert len(result) <= max_chars, f"failed for max_chars={max_chars}"
