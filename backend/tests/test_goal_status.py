"""Tests for ``/goal`` reply text locale handling.

``goal_status.py`` hosts its own reply wording and, unlike the ``/connect``
handshake, used to index its ``_TEXT`` table directly with the caller's locale.
A locale outside ``NotificationLocale`` therefore raised ``KeyError`` instead of
falling back, which is the opposite of ``connect_reply_text``. These tests pin
the fallback behavior.
"""

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
