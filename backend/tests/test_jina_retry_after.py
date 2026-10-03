"""Deterministic, offline provider-directed retry regressions."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from deerflow.community.jina_ai import jina_client, tools

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def rig(monkeypatch):
    loop = asyncio.get_running_loop()
    now = [1000.0]  # Exact origin keeps simulated budget arithmetic reproducible.
    waits = []
    post = AsyncMock()
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post = post
    options = []

    def factory(**kwargs):
        options.append(kwargs)
        return client

    async def sleep(delay):
        waits.append(delay)
        now[0] += delay

    monkeypatch.setattr(loop, "time", lambda: now[0])
    monkeypatch.setattr(time, "time", lambda: 784111777.0)  # Sun, 06 Nov 1994 08:49:37 GMT
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(jina_client.random, "uniform", lambda low, high: 1.0)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    monkeypatch.setenv("JINA_API_KEY", "offline-test")
    return SimpleNamespace(post=post, client=client, waits=waits, now=now, options=options)


def response(status, hint=None):
    return httpx.Response(status, text="provider result", headers={} if hint is None else {"Retry-After": hint})


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("hint,wait", [("7", 7), ("0007", 7), (" 7\t", 7), ("0", 0.5), ("Sun, 06 Nov 1994 08:49:44 GMT", 7), ("Sunday, 06-Nov-94 08:49:44 GMT", 7), ("Sun Nov  6 08:49:44 1994", 7), ("Sun, 06 Nov 1994 08:49:30 GMT", 0.5)])
async def test_recovery(rig, status, hint, wait):
    rig.post.side_effect = [response(status, hint), response(200)]
    assert await jina_client.JinaClient().crawl("https://example.com", max_retries=1) == "provider result"
    assert rig.waits == [wait]
    assert rig.post.await_count == 2


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("hint", [None, "", "-1", "+1", "1.5", "NaN", "inf", "1e2", "tomorrow", "06 Nov 1994 08:49:44 GMT", "Sun, 06 Nov 1994 08:49:44 +0000", "Sun, 06 Nov 1994 08:49:44 GMT junk", "Sun, 31 Feb 1994 08:49:44 GMT"])
async def test_missing_or_malformed(rig, status, hint):
    rig.post.side_effect = [response(status, hint), response(200)]
    result = await jina_client.JinaClient().crawl("https://example.com", max_retries=1)
    assert rig.post.await_count == (1 if status == 429 else 2)
    assert result == ("Error: Jina API returned status 429: provider result" if status == 429 else "provider result")
    assert rig.waits == ([] if status == 429 else [0.5])


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("hint", ["10", "11", "9" * 5000])
async def test_cannot_fit_budget(rig, status, hint):
    rig.post.return_value = response(status, hint)
    result = await jina_client.JinaClient().crawl("https://example.com", max_retries=2, retry_budget_seconds=10)
    assert result == f"Error: Jina API returned status {status}: provider result"
    assert rig.post.await_count == 1
    assert rig.waits == []


@pytest.mark.parametrize("elapsed", [3, 10])
async def test_request_time_consumes_budget(rig, elapsed):
    async def post(*args, **kwargs):
        rig.now[0] += elapsed
        return response(503, "7")

    rig.post.side_effect = post
    assert "status 503" in await jina_client.JinaClient().crawl("https://example.com", max_retries=2, retry_budget_seconds=10)
    assert rig.post.await_count == 1
    assert not rig.waits


@pytest.mark.parametrize("status", [429, 503])
async def test_exhaustion_and_defaults(rig, status):
    rig.post.return_value = response(status, "7")
    assert "Error:" in await jina_client.JinaClient().crawl("https://example.com")
    assert rig.post.await_count == 1
    assert not rig.waits
    rig.post.reset_mock()
    assert f"status {status}" in await jina_client.JinaClient().crawl("https://example.com", max_retries=2)
    assert rig.post.await_count == 3
    assert rig.waits == [7, 7]


@pytest.mark.parametrize("status", [401, 402, 403, 409, 500, 418])
async def test_other_statuses_terminal(rig, status):
    rig.post.return_value = response(status, "1")
    assert f"status {status}" in await jina_client.JinaClient().crawl("https://example.com", max_retries=2)
    assert rig.post.await_count == 1
    assert not rig.waits


async def test_changing_hints_and_connection_failure(rig):
    rig.post.side_effect = [response(503, "7"), httpx.ConnectError("offline"), response(429, "3"), response(503), response(200)]
    assert await jina_client.JinaClient().crawl("https://example.com", max_retries=4, retry_budget_seconds=20) == "provider result"
    assert rig.waits == [7, 1, 3, 4]
    assert [call.kwargs["timeout"] for call in rig.post.await_args_list] == [10, 10, 10, 9, 5]


@pytest.mark.parametrize("during_sleep", [True, False])
async def test_cancellation(rig, monkeypatch, during_sleep):
    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError

    if during_sleep:
        rig.post.return_value = response(429, "7")
        monkeypatch.setattr(asyncio, "sleep", cancel)
    else:
        rig.post.side_effect = cancel
    with pytest.raises(asyncio.CancelledError):
        await jina_client.JinaClient().crawl("https://example.com", max_retries=2)
    assert rig.post.await_count == 1


async def test_web_fetch_integration(rig, monkeypatch):
    config = SimpleNamespace(model_extra={"max_retries": 1, "retry_budget_seconds": 8, "proxy": "http://proxy:8080", "trust_env": False, "timeout": 6})
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: config))
    rig.post.side_effect = [response(429, "7"), response(402, "1")]
    assert await tools.web_fetch_tool.ainvoke({"url": "https://example.com"}) == "Error: Jina API returned status 402: provider result"
    assert rig.waits == [7]
    assert rig.options == [{"proxy": "http://proxy:8080", "trust_env": False}]
    assert [call.kwargs["timeout"] for call in rig.post.await_args_list] == [6, 1]
    assert set(tools.web_fetch_tool.args) == {"url"}


@pytest.mark.parametrize("value", ["١", "１", "²", "\n7", "7\n"])
async def test_non_ascii_or_non_http_whitespace(value):
    assert jina_client._retry_after(value) is None


async def test_obsolete_year_window(rig):
    # At the fixture's 1994 wall time, 00 means 2000, not 1900.
    assert jina_client._retry_after("Saturday, 01-Jan-00 00:00:00 GMT") > 0
    assert jina_client._retry_after("Sunday, 06-Nov-94 08:49:44 GMT") == 7
    assert jina_client._retry_after("Monday, 01-Jan-45 00:00:00 GMT") == 0


async def test_local_pacing_cannot_fit_hinted_budget(rig):
    rig.post.return_value = response(503, "0")
    assert "status 503" in await jina_client.JinaClient().crawl("https://example.com", max_retries=1, retry_budget_seconds=0.25)
    assert not rig.waits
    assert rig.post.await_count == 1


async def test_later_429_without_hint_is_terminal(rig):
    rig.post.side_effect = [response(503, "7"), response(429)]
    assert "status 429" in await jina_client.JinaClient().crawl("https://example.com", max_retries=3)
    assert rig.waits == [7]
    assert rig.post.await_count == 2


async def test_future_date_cannot_fit_budget(rig):
    rig.post.return_value = response(503, "Sun, 06 Nov 1994 08:49:47 GMT")
    assert "status 503" in await jina_client.JinaClient().crawl("https://example.com", max_retries=1, retry_budget_seconds=10)
    assert rig.post.await_count == 1
    assert not rig.waits


async def test_oversleep_does_not_send_after_deadline(rig, monkeypatch):
    async def oversleep(delay):
        rig.now[0] += 10

    monkeypatch.setattr(asyncio, "sleep", oversleep)
    rig.post.return_value = response(429, "7")
    assert "budget exhausted" in await jina_client.JinaClient().crawl("https://example.com", max_retries=2, retry_budget_seconds=10)
    assert rig.post.await_count == 1


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("jitter", [0.5, 0.75])
async def test_jitter_never_shortens_server_floor(rig, monkeypatch, status, jitter):
    monkeypatch.setattr(jina_client.random, "uniform", lambda low, high: jitter)
    rig.post.side_effect = [response(status, "7"), response(200)]
    assert await jina_client.JinaClient().crawl("https://example.com", max_retries=1) == "provider result"
    assert rig.waits == [7]
    assert rig.post.await_count == 2


async def test_client_setup_consumes_shared_budget(rig):
    async def enter():
        rig.now[0] += 10
        return rig.client

    rig.client.__aenter__.side_effect = enter
    result = await jina_client.JinaClient().crawl("https://example.com", max_retries=1, retry_budget_seconds=10)
    assert "budget exhausted" in result
    rig.post.assert_not_awaited()
    assert not rig.waits
