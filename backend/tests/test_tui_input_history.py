"""Tests for bounded composer input history (pure)."""

import pytest

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


@pytest.mark.parametrize("entries", [[], ["previous prompt"]])
def test_down_without_history_navigation_returns_no_change(entries):
    h = InputHistory(entries)
    assert h.down() is None


@pytest.mark.parametrize("draft", ["", "first line\nsecond line"])
def test_down_restores_draft_once_and_then_stops(draft):
    h = InputHistory(["previous prompt"])
    assert h.up(draft) == "previous prompt"
    assert h.down() == draft
    assert h.down() is None


@pytest.mark.parametrize("draft", ["", "keep", "first line\nsecond line"])
def test_up_with_empty_history_returns_no_change(draft):
    h = InputHistory()
    assert h.up(draft=draft) is None


def test_add_resets_navigation_cursor():
    h = InputHistory(["old"])
    h.up()
    h.add("new")
    # After adding, up() starts again from the newest entry.
    assert h.up() == "new"
