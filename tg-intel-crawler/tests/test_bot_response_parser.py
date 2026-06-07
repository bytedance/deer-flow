"""Tests for BotResponseParser — split a search-bot reply into BotPreview entries."""

from datetime import datetime, timezone

import pytest

from tg_intel_crawler.collector.bot_response_parser import (
    BotPreview,
    BotResponseParser,
)


# A realistic reply from @JISOU based on the user-supplied screenshot.
# Note the leading "广告:" line, multiple emoji-prefixed result lines,
# embedded t.me deeplinks, and tail noise.
SAMPLE_REPLY = """\
广告:南宫 集团🔥🔥问鼎 麻将胡了电子/真人/彩票加拿大🌈新人充值600送288包赢

🌄 木子洛抖音玩法三_关于抖加投流_一般别的也用不到，作品就是投个... https://t.me/somechannel/12345
🌄 X刀！香港1T_SSD大盘月付6.X元！_刚截获两份机密级套餐，手抖加剧... https://t.me/another_chan/9876
🎬 [00:09] 赏_好身材要不断雕刻_休闲穿搭女装_@抖加上热门dou+热点宝
🎬 [00:10] 天秤座_福清福清_抖加小助手_iFov5CXq_复制点击置顶消息查看
💬 你们把我当抖加
📂 版本_百分之一百不禁网_禁网剁吊_半火支持功能午后防抖加速范围聚点

热搜: 夏美 西安麻辣烫 夏美酱 牙套妹 在在吗 植物大战僵尸 唐山一拖三 魔女的侵袭
"""


def test_skips_ad_line_at_top():
    """Lines starting with '广告:' or '广告：' must NOT become previews."""
    previews = BotResponseParser().parse(SAMPLE_REPLY, query="抖加", bot="@JISOU")
    for p in previews:
        assert "广告" not in p.text or not p.text.startswith("广告")


def test_extracts_at_least_one_preview_with_deeplink():
    previews = BotResponseParser().parse(SAMPLE_REPLY, query="抖加", bot="@JISOU")
    with_link = [p for p in previews if p.deeplink]
    assert len(with_link) >= 2  # the two 🌄 entries
    assert any(p.channel_username == "somechannel" and p.msg_id == 12345 for p in with_link)
    assert any(p.channel_username == "another_chan" and p.msg_id == 9876 for p in with_link)


def test_emoji_starts_a_new_preview():
    """Each emoji-prefixed line should split into its own preview."""
    text = "🌄 line A\n🎬 line B\n📂 line C"
    previews = BotResponseParser().parse(text, query="x", bot="@JISOU")
    assert len(previews) == 3
    assert previews[0].text.endswith("line A")
    assert previews[1].text.endswith("line B")
    assert previews[2].text.endswith("line C")


def test_each_preview_records_query_and_bot():
    previews = BotResponseParser().parse(SAMPLE_REPLY, query="抖加", bot="@JISOU")
    assert all(p.query == "抖加" for p in previews)
    assert all(p.bot == "@JISOU" for p in previews)


def test_preview_keeps_raw_line_for_debug():
    text = "🌄 some content https://t.me/foo/1"
    previews = BotResponseParser().parse(text, query="x", bot="@JISOU")
    assert len(previews) == 1
    assert previews[0].raw_line.startswith("🌄")
    assert "https://t.me/foo/1" in previews[0].raw_line


def test_line_without_deeplink_still_returned():
    """Plain emoji-prefixed lines (no link) should still surface as previews —
    they're real bot results, just not directly visitable."""
    text = "💬 你们把我当抖加"
    previews = BotResponseParser().parse(text, query="抖加", bot="@JISOU")
    assert len(previews) == 1
    assert previews[0].deeplink is None
    assert previews[0].channel_username is None
    assert previews[0].msg_id is None


def test_empty_input_returns_empty():
    assert BotResponseParser().parse("", query="x", bot="@J") == []
    assert BotResponseParser().parse("   \n\n  ", query="x", bot="@J") == []


def test_pure_text_with_no_emoji_falls_through_as_single_preview():
    """If bot replies plain text without any emoji prefix, don't drop it on the
    floor — wrap the whole thing as one preview so we still capture the data."""
    text = "this is a plain reply that has no emoji prefix at all"
    previews = BotResponseParser().parse(text, query="x", bot="@JISOU")
    assert len(previews) == 1
    assert previews[0].text == text


def test_chinese_punctuation_ad_marker_also_skipped():
    """'广告：' (full-width colon) must also be filtered."""
    text = "广告：xxx 推广\n🌄 real result https://t.me/foochannel/1"
    previews = BotResponseParser().parse(text, query="x", bot="@JISOU")
    assert len(previews) == 1
    assert previews[0].channel_username == "foochannel"


def test_deeplink_with_invite_path_is_not_an_msg_link():
    """https://t.me/+abc is an invite, not a message deeplink — leave msg_id None."""
    text = "🌄 some private group invite https://t.me/+abcXYZ"
    previews = BotResponseParser().parse(text, query="x", bot="@JISOU")
    assert len(previews) == 1
    assert previews[0].channel_username is None
    assert previews[0].msg_id is None
    # but raw_line should preserve the URL, so downstream candidate-extraction
    # can still pick up the invite hash.
    assert "+abcXYZ" in previews[0].raw_line


def test_multiple_links_in_one_line_picks_the_message_deeplink():
    """If a line has both a t.me/+invite and a t.me/<channel>/<msg>, prefer the latter."""
    text = "🌄 mixed https://t.me/+abc https://t.me/realchan/4321"
    previews = BotResponseParser().parse(text, query="x", bot="@JISOU")
    assert len(previews) == 1
    assert previews[0].channel_username == "realchan"
    assert previews[0].msg_id == 4321


def test_seen_at_is_set_to_a_real_datetime():
    previews = BotResponseParser().parse("🌄 hi", query="x", bot="@J")
    assert isinstance(previews[0].seen_at, datetime)


def test_empty_emoji_line_skipped():
    """A line with only an emoji (no content) is just noise."""
    text = "🌄\n🌄 real https://t.me/realchan/1"
    previews = BotResponseParser().parse(text, query="x", bot="@J")
    # only the second one has actual content
    assert len(previews) == 1
    assert previews[0].channel_username == "realchan"


def test_parses_t_me_link_with_no_message_id_only_channel():
    """https://t.me/<channel> (no /msg_id) — channel_username set, msg_id None."""
    text = "🌄 see https://t.me/somegroup for details"
    previews = BotResponseParser().parse(text, query="x", bot="@J")
    assert len(previews) == 1
    assert previews[0].channel_username == "somegroup"
    assert previews[0].msg_id is None
    # deeplink is the channel-level URL, still a usable signal for candidate pool
    assert previews[0].deeplink == "https://t.me/somegroup"
