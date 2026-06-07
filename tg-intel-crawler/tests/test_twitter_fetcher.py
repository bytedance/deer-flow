"""Tests for the tikhub Twitter response parser."""

import json
from datetime import datetime, timezone

from tg_intel_crawler.collector.twitter_fetcher import (
    TweetData,
    _parse_twitter_date,
    extract_next_cursor,
    parse_tweet_results,
)


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------


def test_parse_twitter_date_rfc822():
    """Twitter uses RFC822 dates like 'Wed Oct 10 20:19:24 +0000 2018'."""
    dt = _parse_twitter_date("Wed Oct 10 20:19:24 +0000 2018")
    assert dt.year == 2018
    assert dt.month == 10
    assert dt.day == 10
    assert dt.tzinfo is not None


def test_parse_twitter_date_empty_returns_now():
    dt = _parse_twitter_date(None)
    assert dt.tzinfo is timezone.utc or dt.tzinfo is not None


def test_parse_twitter_date_iso():
    dt = _parse_twitter_date("2026-05-24T14:30:00Z")
    assert dt.year == 2026
    assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# Tweet parsing
# ---------------------------------------------------------------------------


def _sample_payload():
    """A minimal tikhub-style payload with one tweet + matching user."""
    return {
        "data": {
            "search_by_raw_query": {
                "search_timeline": {
                    "timeline": {
                        "instructions": [
                            {
                                "type": "TimelineAddEntries",
                                "entries": [
                                    {
                                        "entryId": "tweet-1808168603721650364",
                                        "content": {
                                            "itemContent": {
                                                "tweet_results": {
                                                    "result": {
                                                        "core": {
                                                            "user_results": {
                                                                "result": {
                                                                    "id_str": "111111",
                                                                    "legacy": {
                                                                        "id_str": "111111",
                                                                        "screen_name": "douyin_seller",
                                                                        "name": "Douyin Seller",
                                                                    },
                                                                }
                                                            }
                                                        },
                                                        "legacy": {
                                                            "id_str": "1808168603721650364",
                                                            "user_id_str": "111111",
                                                            "full_text": "抖音账号出售，刷粉服务，TG: @seller",
                                                            "created_at": "Wed Oct 10 20:19:24 +0000 2024",
                                                            "lang": "zh",
                                                            "reply_count": 5,
                                                            "retweet_count": 3,
                                                            "favorite_count": 12,
                                                            "quote_count": 1,
                                                            "entities": {
                                                                "media": [
                                                                    {
                                                                        "media_url_https": "https://pbs.twimg.com/media/abc.jpg"
                                                                    }
                                                                ]
                                                            },
                                                        },
                                                    }
                                                }
                                            }
                                        },
                                    },
                                    {
                                        "entryId": "cursor-bottom-xyz",
                                        "content": {
                                            "cursorType": "Bottom",
                                            "value": "DAABCgABF__cursor_token__",
                                            "entryType": "TimelineTimelineCursor",
                                        },
                                    },
                                ],
                            }
                        ]
                    }
                }
            }
        }
    }


def test_parse_tweet_results_extracts_tweet():
    tweets = parse_tweet_results(_sample_payload(), source_keyword="抖音 刷粉")
    assert len(tweets) == 1
    t = tweets[0]
    assert t.tweet_id == "1808168603721650364"
    assert t.user_id == "111111"
    assert t.screen_name == "douyin_seller"
    assert t.user_name == "Douyin Seller"
    assert "抖音账号出售" in t.text
    assert t.lang == "zh"
    assert t.reply_count == 5
    assert t.retweet_count == 3
    assert t.favorite_count == 12
    assert t.quote_count == 1
    assert t.source_keyword == "抖音 刷粉"
    assert t.url == "https://twitter.com/douyin_seller/status/1808168603721650364"
    assert t.media_urls == ["https://pbs.twimg.com/media/abc.jpg"]


def test_parse_tweet_results_dedupes_by_id():
    """A tweet that appears twice in the payload should be returned once."""
    payload = _sample_payload()
    # Duplicate the tweet under another nesting
    payload["dup"] = payload["data"]
    tweets = parse_tweet_results(payload, source_keyword="kw")
    assert len(tweets) == 1


def test_parse_tweet_results_empty_payload():
    assert parse_tweet_results({}) == []
    assert parse_tweet_results({"data": None}) == []


def test_extract_next_cursor_finds_bottom():
    cursor = extract_next_cursor(_sample_payload())
    assert cursor == "DAABCgABF__cursor_token__"


def test_extract_next_cursor_none_when_absent():
    payload = {"data": {"foo": "bar"}}
    assert extract_next_cursor(payload) is None


def test_extract_next_cursor_flat_next_cursor():
    payload = {"data": {"next_cursor": "abc123"}}
    assert extract_next_cursor(payload) == "abc123"


# ---------------------------------------------------------------------------
# TweetData serialization
# ---------------------------------------------------------------------------


def test_tweetdata_to_dict_roundtrip():
    t = TweetData(
        tweet_id="1",
        user_id="2",
        screen_name="x",
        user_name="X",
        text="hello",
        date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        lang="en",
    )
    d = t.to_dict()
    assert d["tweet_id"] == "1"
    assert d["date"] == "2026-01-01T00:00:00+00:00"
    # ensure JSON serializable
    json.dumps(d)
