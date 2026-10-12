"""The stop condition is stored apart from the prompt and composed only at launch."""

import pytest

from deerflow.scheduler.stop_rule import MAX_STOP_CONDITION_CHARS, STOP_RULE_NO_TOOL_PREFIX, STOP_RULE_PREFIX, launch_prompt, normalize_stop_condition


def test_prefixes_are_pinned():
    # Model-facing text owned by the backend. Changing it is a deliberate,
    # reviewed edit; no stored row contains it, so no migration is needed.
    assert STOP_RULE_PREFIX == "Stop rule from the user: when this is true, report it and call stop_scheduled_task to pause this schedule: "
    assert STOP_RULE_NO_TOOL_PREFIX == "Stop rule from the user (this run cannot pause the schedule; if it is true, say so clearly so the user can pause it): "
    assert MAX_STOP_CONDITION_CHARS == 500


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("  \n\t ", None),
        ("every item\non the checklist\n\n  is checked ", "every item on the checklist is checked"),
        ("清单上的事项   都已勾选", "清单上的事项 都已勾选"),
    ],
)
def test_normalize_collapses_whitespace_and_treats_blank_as_none(raw, expected):
    assert normalize_stop_condition(raw) == expected


def test_normalize_length_limit():
    assert normalize_stop_condition("x" * 500) == "x" * 500
    assert normalize_stop_condition("  " + "x" * 500 + "\n") == "x" * 500
    with pytest.raises(ValueError):
        normalize_stop_condition("x" * 501)


def test_launch_prompt_without_condition_is_unchanged():
    prompt = "Check release-checklist.md and list the unchecked items.\n"
    assert launch_prompt(prompt, None, can_stop=True) == prompt
    assert launch_prompt(prompt, None, can_stop=False) == prompt


def test_launch_prompt_with_own_stop_names_the_tool():
    composed = launch_prompt("Check the checklist.\n\n", "every item is checked", can_stop=True)
    assert composed == "Check the checklist.\n\n" + STOP_RULE_PREFIX + "every item is checked"
    assert composed.endswith("\n\n" + STOP_RULE_PREFIX + "every item is checked")
    assert "stop_scheduled_task" in composed


def test_launch_prompt_without_own_stop_never_mentions_the_tool():
    composed = launch_prompt("Check the checklist.", "清单上的事项都已勾选", can_stop=False)
    assert composed == "Check the checklist.\n\n" + STOP_RULE_NO_TOOL_PREFIX + "清单上的事项都已勾选"
    assert "stop_scheduled_task" not in composed
