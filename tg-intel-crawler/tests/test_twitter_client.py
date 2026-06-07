"""Tests for the tikhub TwitterClient HTTP wrapper.

Uses ``httpx.MockTransport`` so no real network calls happen.
"""

import httpx
import pytest

from tg_intel_crawler.collector.twitter_client import (
    TikHubAPIError,
    TikHubAuthError,
    TwitterClient,
)


@pytest.fixture
def fake_payload():
    return {"data": {"search_by_raw_query": {"timeline": {"instructions": []}}}}


def _make_client_with_handler(handler) -> TwitterClient:
    """Build a TwitterClient whose internal httpx client uses MockTransport(handler)."""
    client = TwitterClient(api_key="test-key", max_retries=2)
    transport = httpx.MockTransport(handler)
    # Pre-populate the underlying httpx client so we don't need __aenter__'s real init.
    client._client = httpx.AsyncClient(
        base_url=client._base_url,
        headers=client._headers,
        timeout=client._timeout,
        transport=transport,
    )
    return client


@pytest.mark.asyncio
async def test_search_timeline_passes_keyword_and_auth(fake_payload):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=fake_payload)

    client = _make_client_with_handler(handler)
    try:
        result = await client.search_timeline(keyword="抖音 刷粉", search_type="Latest")
    finally:
        await client._client.aclose()

    assert result == fake_payload
    assert "fetch_search_timeline" in captured["url"]
    assert "keyword=" in captured["url"]
    assert captured["auth"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_user_post_tweet_with_cursor(fake_payload):
    seen_params: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.append(dict(request.url.params))
        return httpx.Response(200, json=fake_payload)

    client = _make_client_with_handler(handler)
    try:
        await client.user_post_tweet(screen_name="alice", cursor="cur_xyz")
    finally:
        await client._client.aclose()

    assert seen_params[0]["screen_name"] == "alice"
    assert seen_params[0]["cursor"] == "cur_xyz"


@pytest.mark.asyncio
async def test_auth_error_on_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "bad token"})

    client = _make_client_with_handler(handler)
    try:
        with pytest.raises(TikHubAuthError):
            await client.search_timeline(keyword="x")
    finally:
        await client._client.aclose()


@pytest.mark.asyncio
async def test_retry_then_success(fake_payload):
    """Transient 500 should retry and eventually succeed."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, json={"err": "boom"})
        return httpx.Response(200, json=fake_payload)

    client = _make_client_with_handler(handler)
    try:
        result = await client.search_timeline(keyword="x")
    finally:
        await client._client.aclose()

    assert result == fake_payload
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_drops_none_params(fake_payload):
    """cursor=None should not appear in the query string."""
    seen_params: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.append(dict(request.url.params))
        return httpx.Response(200, json=fake_payload)

    client = _make_client_with_handler(handler)
    try:
        await client.search_timeline(keyword="x", cursor=None)
    finally:
        await client._client.aclose()

    assert "cursor" not in seen_params[0]


@pytest.mark.asyncio
async def test_api_error_after_max_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"err": "always fails"})

    client = _make_client_with_handler(handler)
    try:
        with pytest.raises(TikHubAPIError):
            await client.search_timeline(keyword="x")
    finally:
        await client._client.aclose()


def test_init_requires_api_key():
    with pytest.raises(ValueError):
        TwitterClient(api_key="")
