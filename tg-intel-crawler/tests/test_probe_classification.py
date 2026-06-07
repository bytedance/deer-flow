"""Tests for classify() — pure function mapping (reply, previews) → category."""

import pytest

from tg_intel_crawler.collector.bot_response_parser import BotPreview
from tg_intel_crawler.probe.runner import classify
from datetime import datetime, timezone


def _preview(channel_username: str | None = None) -> BotPreview:
    return BotPreview(
        bot="@JISOU",
        query="x",
        raw_line="🌄 ...",
        text="...",
        deeplink=None,
        channel_username=channel_username,
        msg_id=None,
        icon="🌄",
        seen_at=datetime.now(timezone.utc),
    )


def test_error_status_classifies_as_error():
    assert classify(
        candidate_key="x",
        reply_status="error",
        previews=[],
    ) == "error"


@pytest.mark.parametrize("reply_status", ["empty_reply"])
def test_empty_reply_classifies_as_empty_reply(reply_status):
    assert classify(
        candidate_key="x",
        reply_status=reply_status,
        previews=[],
    ) == "empty_reply"


def test_direct_hit_when_preview_channel_matches_key():
    previews = [_preview(channel_username="douyinhao88")]
    assert classify(
        candidate_key="douyinhao88",
        reply_status="ok",
        previews=previews,
    ) == "direct_hit"


def test_direct_hit_is_case_insensitive():
    previews = [_preview(channel_username="DouYinHao88")]
    assert classify(
        candidate_key="douyinhao88",
        reply_status="ok",
        previews=previews,
    ) == "direct_hit"


def test_indirect_hit_when_previews_exist_but_no_match():
    previews = [_preview(channel_username="other"), _preview(channel_username=None)]
    assert classify(
        candidate_key="douyinhao88",
        reply_status="ok",
        previews=previews,
    ) == "indirect_hit"


def test_no_results_when_reply_ok_but_no_previews():
    assert classify(
        candidate_key="x",
        reply_status="ok",
        previews=[],
    ) == "no_results"


def test_private_key_with_plus_never_direct_hits():
    """Private candidates have keys like '+abc'; no channel_username will
    ever equal that (channel usernames don't start with +)."""
    previews = [_preview(channel_username="abc")]
    assert classify(
        candidate_key="+abc",
        reply_status="ok",
        previews=previews,
    ) == "indirect_hit"


def test_error_short_circuits_even_with_previews():
    """Even if previews were parsed before the error, error wins."""
    previews = [_preview(channel_username="x")]
    assert classify(
        candidate_key="x",
        reply_status="error",
        previews=previews,
    ) == "error"
