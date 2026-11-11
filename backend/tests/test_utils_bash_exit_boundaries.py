"""Boundary coverage for ``deerflow.utils.bash_exit``.

``backend/tests/test_tool_result_meta.py`` already drives the same markers
through ``normalize_tool_message``. This file pins the direct return contract
of ``bash_exit_status`` -- the exact ``(status, marker)`` tuple -- for the
inputs where string handling, sign, or unbounded length matters. The few cases
that overlap the existing suite are kept as the baseline for those assertions.
"""

from __future__ import annotations

import sys

from deerflow.utils.bash_exit import bash_exit_status


def test_exit_code_tail_is_recognised_only_at_the_end() -> None:
    assert bash_exit_status("output\nExit Code: 0") == ("success", "Exit Code: 0")
    assert bash_exit_status("output\nExit Code: 1") == ("error", "Exit Code: 1")


def test_embedded_phrase_in_ordinary_output_is_not_a_marker() -> None:
    assert bash_exit_status("he said Exit Code: 0 then left") is None


def test_signed_zero_is_success() -> None:
    assert bash_exit_status("Command exited with code -0") == (
        "success",
        "Command exited with code -0",
    )


def test_negative_and_timeout_codes_are_errors() -> None:
    for code in ("-1", "124", "137"):
        assert bash_exit_status(f"Exit Code: {code}") == ("error", f"Exit Code: {code}")


def test_unbounded_digits_are_compared_as_strings() -> None:
    # CPython >= 3.11 refuses int() on digit strings longer than
    # sys.get_int_max_str_digits() (4300 by default). Exceeding that cap makes
    # an implementation regressed to int(match.group(2)) raise ValueError here
    # instead of silently returning the same ("error", marker) tuple.
    # A disabled cap (0) falls back to the default so the test still uses a
    # length far beyond the standard conversion limit.
    limit = sys.get_int_max_str_digits() or 4300
    huge = "9" * (limit + 1)
    assert bash_exit_status(f"Exit Code: {huge}") == ("error", f"Exit Code: {huge}")


def test_trailing_whitespace_after_tail_is_allowed() -> None:
    assert bash_exit_status("done\nExit Code: 0  \n") == ("success", "Exit Code: 0")
