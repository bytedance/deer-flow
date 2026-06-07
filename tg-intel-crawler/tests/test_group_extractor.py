"""Tests for GroupExtractor — extract candidate group signals from messages."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tg_intel_crawler.collector.group_extractor import (
    CandidateSignal,
    GroupExtractor,
)


def _make_msg(
    text: str = "",
    msg_id: int = 1,
    group_name: str = "src_group",
    forward_from_username: str | None = None,
    entities: list | None = None,
) -> SimpleNamespace:
    """Build a MessageData-like object (the extractor only reads attributes,
    so a SimpleNamespace is enough — no Telethon dependency in tests)."""
    return SimpleNamespace(
        msg_id=msg_id,
        group_name=group_name,
        text=text,
        date=datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc),
        forward_from_username=forward_from_username,
        entities=entities or [],
    )


def test_extract_public_username_from_t_me_link():
    msg = _make_msg(text="出抖音老号 加 https://t.me/douyinhao88 详谈")
    signals = GroupExtractor().extract_from([msg])
    assert len(signals) == 1
    assert signals[0].username == "douyinhao88"
    assert signals[0].invite_hash is None
    assert signals[0].channel == "text"


def test_extract_invite_hash_from_t_me_plus_link():
    msg = _make_msg(text="入群链接 https://t.me/+abc123XYZ_-")
    signals = GroupExtractor().extract_from([msg])
    assert len(signals) == 1
    assert signals[0].username is None
    assert signals[0].invite_hash == "abc123XYZ_-"


def test_extract_legacy_joinchat_invite():
    msg = _make_msg(text="https://t.me/joinchat/AAAAAEhellohash")
    signals = GroupExtractor().extract_from([msg])
    assert len(signals) == 1
    assert signals[0].invite_hash == "AAAAAEhellohash"


def test_extract_at_mention():
    msg = _make_msg(text="联系 @sellerbot 不要 dm")
    signals = GroupExtractor().extract_from([msg])
    usernames = [s.username for s in signals]
    assert "sellerbot" in usernames


def test_at_mention_must_match_telegram_username_rules():
    # Telegram username: 5-32 chars, starts with letter, [A-Za-z0-9_]
    # @abc (too short), @1foo (starts with digit), @中文 (non-ascii) should NOT match.
    msg = _make_msg(text="@abc 不算 @1foo 不算 @中文你好 不算 @gooduser123 算")
    signals = GroupExtractor().extract_from([msg])
    usernames = [s.username for s in signals]
    assert usernames == ["gooduser123"]


def test_skip_special_telegram_usernames():
    # @username 紧跟在 / 后是 t.me 路径，不是真 mention（已经被 link 规则覆盖）。
    # 但 @c, @s 这种太短的、以及 @joinchat 已被 invite 处理；不应再当 username。
    msg = _make_msg(text="@joinchat 后面有内容，但本身不是用户名")
    signals = GroupExtractor().extract_from([msg])
    assert all(s.username != "joinchat" for s in signals)


def test_extract_forward_from_username():
    msg = _make_msg(text="转发内容", forward_from_username="origin_channel")
    signals = GroupExtractor().extract_from([msg])
    assert len(signals) == 1
    assert signals[0].username == "origin_channel"
    assert signals[0].channel == "forward"


def test_extract_dedupe_within_single_message():
    # Same username appearing in text and as @mention should produce ONE signal.
    msg = _make_msg(text="https://t.me/dupgroup 和 @dupgroup")
    signals = GroupExtractor().extract_from([msg])
    assert len(signals) == 1
    assert signals[0].username == "dupgroup"


def test_extract_does_not_pick_up_self_source_group():
    # If extracted username equals the source group, drop it (it'd just be noise).
    msg = _make_msg(text="本群 @selfgroup", group_name="selfgroup")
    signals = GroupExtractor().extract_from([msg])
    assert signals == []


def test_extract_multiple_messages_preserves_source_metadata():
    msgs = [
        _make_msg(text="@groupA", msg_id=10, group_name="src1"),
        _make_msg(text="https://t.me/groupB", msg_id=20, group_name="src2"),
    ]
    signals = GroupExtractor().extract_from(msgs)
    # usernames are normalized to lowercase
    by_username = {s.username: s for s in signals}
    assert by_username["groupa"].source_msg_id == 10
    assert by_username["groupa"].source_group == "src1"
    assert by_username["groupb"].source_msg_id == 20
    assert by_username["groupb"].source_group == "src2"


def test_extract_empty_text_no_signals():
    assert GroupExtractor().extract_from([_make_msg(text="")]) == []


def test_extract_no_telegram_links_no_signals():
    assert GroupExtractor().extract_from([_make_msg(text="今天天气不错")]) == []


def test_extract_normalizes_username_to_lowercase():
    # Telegram usernames are case-insensitive — normalize so dedupe works.
    msg = _make_msg(text="@FooBar 和 https://t.me/foobar")
    signals = GroupExtractor().extract_from([msg])
    assert len(signals) == 1
    assert signals[0].username == "foobar"


def test_t_me_path_with_message_id_yields_channel_username():
    # https://t.me/somechannel/12345 → username is "somechannel"
    msg = _make_msg(text="见 https://t.me/somechannel/12345")
    signals = GroupExtractor().extract_from([msg])
    assert len(signals) == 1
    assert signals[0].username == "somechannel"
