"""Tests for ``/goal`` reply text locale handling.

``goal_status.py`` hosts its own reply wording and, unlike the ``/connect``
handshake, used to index its ``_TEXT`` table directly with the caller's locale.
A locale outside ``NotificationLocale`` therefore raised ``KeyError`` instead of
falling back, which is the opposite of ``connect_reply_text``. These tests pin
the fallback behavior.
"""

import pytest

from app.channels.goal_status import goal_reply_text, goal_status_text


def test_goal_reply_text_unknown_locale_falls_back_to_default():
    """A locale outside NotificationLocale must fall back, not raise KeyError."""
    assert goal_reply_text("none", "ja-JP") == "No active goal."


def test_goal_reply_text_known_zh_locale():
    """A supported locale still selects its own wording."""
    assert goal_reply_text("none", "zh-CN") == "当前没有目标。"


def test_goal_status_text_unknown_locale_falls_back_to_default():
    """The status reply also falls back for an unsupported locale."""
    assert goal_status_text(None, None, running=False, locale="ja-JP") == "No active goal."


def _stood_down_goal(stand_down_reason: str) -> dict:
    """An active goal whose last evaluation stood auto-continue down."""
    return {
        "status": "active",
        "objective": "ship the release",
        "created_at": "2026-11-05T00:00:00+00:00",
        "continuation_count": 2,
        "max_continuations": 5,
        "last_evaluation": {"stand_down_reason": stand_down_reason, "satisfied": False},
    }


@pytest.mark.parametrize(
    "code",
    ["evaluator_failed", "blocked:evaluator_failed", "no_durable_end_of_turn", "blocked:thread_changed_after_evaluation"],
)
def test_a_failed_goal_check_is_not_reported_as_a_verdict(code):
    """The worker stores ``blocked:<code>``; a check failure is retried after the next message."""
    reply = goal_status_text(_stood_down_goal(code), None, running=False, locale="en-US")

    assert reply.endswith("It's checked again after your next message.")


def test_a_prefixed_failed_goal_check_reads_as_unchecked_in_chinese():
    reply = goal_status_text(_stood_down_goal("blocked:evaluator_failed"), None, running=False, locale="zh-CN")

    assert reply.endswith("下次发消息后会重新检查。")


def test_a_stand_down_verdict_still_reads_as_stopped():
    """Unwrapping the prefix must not turn a real verdict into a retry note."""
    reply = goal_status_text(_stood_down_goal("blocked:no_progress_detected"), None, running=False, locale="en-US")

    assert reply == "Goal: ship the release\nStopped: no progress was made between turns."
