"""Tests for bounded composer input history (pure)."""

from deerflow.tui.input_history import InputHistory


def test_add_ignores_empty_and_whitespace():
    h = InputHistory()
    h.add("")
    h.add("   \n")
    assert h.entries() == []


def test_add_ignores_consecutive_duplicate():
    h = InputHistory()
    h.add("same")
    h.add("same")
    assert h.entries() == ["same"]


def test_add_keeps_non_consecutive_duplicates():
    h = InputHistory()
    h.add("a")
    h.add("b")
    h.add("a")
    assert h.entries() == ["a", "b", "a"]


def test_add_bounds_to_limit_dropping_oldest():
    h = InputHistory(limit=3)
    for text in ["1", "2", "3", "4"]:
        h.add(text)
    assert h.entries() == ["2", "3", "4"]


def test_up_walks_back_and_stops_at_oldest():
    h = InputHistory(["first", "second", "third"])
    assert h.up() == "third"
    assert h.up() == "second"
    assert h.up() == "first"
    assert h.up() == "first"  # clamped at oldest


def test_down_walks_forward_then_restores_draft():
    h = InputHistory(["first", "second"])
    assert h.up(draft="my draft") == "second"
    assert h.up() == "first"
    assert h.down() == "second"
    assert h.down() == "my draft"  # past newest -> stashed draft


def test_up_with_empty_history_returns_draft():
    h = InputHistory()
    assert h.up(draft="keep") == "keep"


def test_add_resets_navigation_cursor():
    h = InputHistory(["old"])
    h.up()
    h.add("new")
    # After adding, up() starts again from the newest entry.
    assert h.up() == "new"
