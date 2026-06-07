"""High-level Twitter fetcher that turns tikhub.io API responses into TweetData.

This module is intentionally defensive when parsing the upstream payload — the
tikhub Twitter Web API mirrors the X/Twitter GraphQL schema, which is deeply
nested and changes occasionally. We walk the response tree and collect any
``tweet`` / ``tweet_results`` / ``legacy`` blobs we can find.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable, Optional

from tg_intel_crawler.collector.twitter_client import (
    TikHubAPIError,
    TikHubAuthError,
    TwitterClient,
)
from tg_intel_crawler.utils.rate_limiter import RateLimiter

logger = logging.getLogger("tg_crawler")


@dataclass
class TweetData:
    """Unified tweet structure (analogous to MessageData for Telegram)."""

    tweet_id: str = ""
    user_id: str = ""
    screen_name: str = ""        # @handle, e.g. "elonmusk"
    user_name: str = ""          # display name
    text: str = ""
    date: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lang: str = ""
    reply_count: int = 0
    retweet_count: int = 0
    favorite_count: int = 0
    quote_count: int = 0
    view_count: int = 0
    is_retweet: bool = False
    in_reply_to: str = ""
    source_keyword: str = ""     # the search query that surfaced this tweet
    url: str = ""
    media_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tweet_id": self.tweet_id,
            "user_id": self.user_id,
            "screen_name": self.screen_name,
            "user_name": self.user_name,
            "text": self.text,
            "date": self.date.isoformat(),
            "lang": self.lang,
            "reply_count": self.reply_count,
            "retweet_count": self.retweet_count,
            "favorite_count": self.favorite_count,
            "quote_count": self.quote_count,
            "view_count": self.view_count,
            "is_retweet": self.is_retweet,
            "in_reply_to": self.in_reply_to,
            "source_keyword": self.source_keyword,
            "url": self.url,
            "media_urls": self.media_urls,
        }


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------


def _parse_twitter_date(s: Optional[str]) -> datetime:
    """Parse a Twitter ``created_at`` string. Returns aware UTC datetime."""
    if not s:
        return datetime.now(timezone.utc)
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)


def _walk(obj: Any) -> Iterable[dict]:
    """Yield every dict found anywhere inside a nested structure."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _looks_like_tweet_legacy(d: dict) -> bool:
    """Heuristic: a tweet 'legacy' object has these signature fields."""
    return (
        isinstance(d, dict)
        and "full_text" in d
        and ("created_at" in d or "user_id_str" in d)
    )


def _find_user_legacy(root: dict, user_id_str: str) -> dict:
    """Try to find the user 'legacy' block matching a user_id_str."""
    for d in _walk(root):
        if (
            d.get("id_str") == user_id_str
            and ("screen_name" in d or "name" in d)
        ):
            return d
    return {}


def _extract_media_urls(legacy: dict) -> list[str]:
    urls: list[str] = []
    media = (legacy.get("entities") or {}).get("media") or []
    for m in media:
        u = m.get("media_url_https") or m.get("media_url") or m.get("expanded_url")
        if u:
            urls.append(u)
    return urls


def parse_tweet_results(payload: dict, source_keyword: str = "") -> list[TweetData]:
    """Turn a tikhub response payload into TweetData objects.

    Walks the entire JSON tree and pulls out anything that quacks like a
    tweet ``legacy`` object. Survives upstream schema drift better than a
    rigid path-based parser.
    """
    seen_ids: set[str] = set()
    out: list[TweetData] = []

    for node in _walk(payload):
        if not _looks_like_tweet_legacy(node):
            continue
        tid = node.get("id_str") or str(node.get("id") or "")
        if not tid or tid in seen_ids:
            continue
        seen_ids.add(tid)

        user_id = node.get("user_id_str") or str(node.get("user_id") or "")
        user_legacy = _find_user_legacy(payload, user_id) if user_id else {}

        td = TweetData(
            tweet_id=tid,
            user_id=user_id,
            screen_name=user_legacy.get("screen_name", ""),
            user_name=user_legacy.get("name", ""),
            text=node.get("full_text") or node.get("text") or "",
            date=_parse_twitter_date(node.get("created_at")),
            lang=node.get("lang", "") or "",
            reply_count=int(node.get("reply_count") or 0),
            retweet_count=int(node.get("retweet_count") or 0),
            favorite_count=int(node.get("favorite_count") or 0),
            quote_count=int(node.get("quote_count") or 0),
            view_count=int(node.get("views_count") or node.get("view_count") or 0),
            is_retweet=bool(node.get("retweeted_status_id_str") or node.get("retweeted")),
            in_reply_to=node.get("in_reply_to_status_id_str") or "",
            source_keyword=source_keyword,
            media_urls=_extract_media_urls(node),
        )
        if td.screen_name:
            td.url = f"https://twitter.com/{td.screen_name}/status/{tid}"
        out.append(td)
    return out


def extract_next_cursor(payload: dict) -> Optional[str]:
    """Find the 'bottom' cursor used for paginating older tweets."""
    for node in _walk(payload):
        if not isinstance(node, dict):
            continue
        # GraphQL-style cursor entry: {"entryType":"...Cursor", "value":"..."}
        if node.get("cursorType") == "Bottom" and node.get("value"):
            return node["value"]
        if node.get("entryType", "").endswith("Cursor") and node.get("cursorType") == "Bottom":
            return node.get("value")
        # Some tikhub wrappers expose a flat 'next_cursor'
        if "next_cursor" in node and isinstance(node["next_cursor"], str) and node["next_cursor"]:
            return node["next_cursor"]
    return None


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


class TwitterFetcher:
    """Fetch tweets via tikhub.io with pagination, rate limiting and date cutoff."""

    def __init__(self, client: TwitterClient, rate_limiter: RateLimiter):
        self._client = client
        self._rate_limiter = rate_limiter

    async def search(
        self,
        keyword: str,
        search_type: str = "Latest",
        max_pages: int = 5,
        days: Optional[int] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> list[TweetData]:
        """Page through the search timeline for ``keyword``.

        Args:
            keyword: search query.
            search_type: ``Latest`` (default) or ``Top``.
            max_pages: hard cap on pagination — keeps API spend bounded.
            days: only keep tweets newer than this many days. ``None`` = no filter.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
            if days is not None
            else None
        )
        results: list[TweetData] = []
        cursor: Optional[str] = None
        logger.info(f"🔎 Searching Twitter: '{keyword}' (type={search_type}, max_pages={max_pages})")

        for page in range(max_pages):
            try:
                payload = await self._client.search_timeline(
                    keyword=keyword, search_type=search_type, cursor=cursor
                )
            except TikHubAuthError:
                raise
            except TikHubAPIError as e:
                logger.error(f"Search '{keyword}' page {page+1} failed, stopping: {e}")
                break

            tweets = parse_tweet_results(payload, source_keyword=keyword)
            if not tweets:
                logger.info(f"  page {page+1}: no tweets parsed, stopping")
                break

            kept = 0
            stop = False
            for t in tweets:
                if cutoff and t.date < cutoff:
                    stop = True
                    continue
                results.append(t)
                kept += 1

            logger.info(f"  page {page+1}: parsed {len(tweets)}, kept {kept}")
            if on_progress:
                on_progress(len(results))

            if stop:
                logger.info(f"  hit cutoff date, stopping pagination")
                break

            cursor = extract_next_cursor(payload)
            if not cursor:
                logger.info(f"  no further cursor, stopping")
                break

            await self._rate_limiter.wait()

        logger.info(f"✅ Search '{keyword}': {len(results)} tweets total")
        return results

    async def user_tweets(
        self,
        screen_name: str,
        max_pages: int = 3,
        days: Optional[int] = None,
    ) -> list[TweetData]:
        """Fetch recent tweets posted by a single user."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
            if days is not None
            else None
        )
        results: list[TweetData] = []
        cursor: Optional[str] = None
        logger.info(f"👤 Fetching @{screen_name} tweets (max_pages={max_pages})")

        for page in range(max_pages):
            try:
                payload = await self._client.user_post_tweet(
                    screen_name=screen_name, cursor=cursor
                )
            except TikHubAuthError:
                raise
            except TikHubAPIError as e:
                logger.error(f"user_post_tweet @{screen_name} page {page+1} failed: {e}")
                break

            tweets = parse_tweet_results(payload, source_keyword=f"@{screen_name}")
            # Make sure source_keyword is the user handle, not empty
            for t in tweets:
                if not t.source_keyword:
                    t.source_keyword = f"@{screen_name}"

            if not tweets:
                break

            stop = False
            kept = 0
            for t in tweets:
                if cutoff and t.date < cutoff:
                    stop = True
                    continue
                results.append(t)
                kept += 1
            logger.info(f"  page {page+1}: parsed {len(tweets)}, kept {kept}")

            if stop:
                break
            cursor = extract_next_cursor(payload)
            if not cursor:
                break
            await self._rate_limiter.wait()

        logger.info(f"✅ @{screen_name}: {len(results)} tweets")
        return results
