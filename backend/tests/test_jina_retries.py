"""Offline coverage of Jina's opt-in retry policy."""

import asyncio
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from deerflow.community.jina_ai.jina_client import JinaClient

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def requests(monkeypatch):
    post = AsyncMock()
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post = post
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setenv("JINA_API_KEY", "test-key")
    return post


async def test_default_single_attempt(requests, monkeypatch):
    jitter = Mock()
    monkeypatch.setattr(random, "uniform", jitter)
    requests.return_value = httpx.Response(503, text="unavailable")
    assert "503" in await JinaClient().crawl("https://example.com")
    assert requests.await_count == 1
    jitter.assert_not_called()


@pytest.mark.parametrize("failure", [httpx.Response(502), httpx.Response(503), httpx.Response(504), httpx.ConnectError("offline"), httpx.ConnectTimeout("offline")])
async def test_transient_recovers(requests, monkeypatch, failure):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    requests.side_effect = [failure, httpx.Response(200, text="success")]
    assert await JinaClient().crawl("https://example.com", max_retries=1) == "success"
    assert requests.await_count == 2


@pytest.mark.parametrize("failure", [httpx.Response(code) for code in (400, 401, 403, 404, 429, 500)] + [httpx.Response(200, text="  "), httpx.ReadTimeout("slow"), httpx.WriteError("write"), RuntimeError("unexpected")])
async def test_permanent_failure(requests, failure):
    requests.side_effect = [failure, httpx.Response(200, text="unexpected")]
    assert (await JinaClient().crawl("https://example.com", max_retries=2)).startswith("Error:")
    assert requests.await_count == 1


@pytest.mark.parametrize(
    ("jitter_factor", "expected_waits"),
    [(0.5, [0.25, 0.5, 1, 2, 2, 2]), (0.75, [0.375, 0.75, 1.5, 3, 3, 3]), (1.0, [0.5, 1, 2, 4, 4, 4])],
)
async def test_exhaustion_and_capped_backoff(requests, monkeypatch, jitter_factor, expected_waits):
    sleep = AsyncMock()
    jitter = Mock(return_value=jitter_factor)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(random, "uniform", jitter)
    requests.return_value = httpx.Response(503, text="unavailable")
    assert "503" in await JinaClient().crawl("https://example.com", max_retries=6)
    assert requests.await_count == 7
    assert [call.args[0] for call in sleep.await_args_list] == expected_waits
    assert jitter.call_count == 6
    assert all(call.args == (0.5, 1.0) for call in jitter.call_args_list)


async def test_each_retry_samples_new_jitter(requests, monkeypatch):
    sleep = AsyncMock()
    jitter = Mock(side_effect=[0.5, 1.0, 0.75])
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(random, "uniform", jitter)
    requests.return_value = httpx.Response(503, text="unavailable")

    assert "503" in await JinaClient().crawl("https://example.com", max_retries=3)

    assert requests.await_count == 4
    assert [call.args[0] for call in sleep.await_args_list] == [0.25, 1, 1.5]
    assert jitter.call_count == 3


async def test_backoff_jitter_is_capped_by_remaining_budget(requests, monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(random, "uniform", lambda low, high: 0.5)
    requests.side_effect = [httpx.Response(503), httpx.Response(200, text="success")]

    assert await JinaClient().crawl("https://example.com", max_retries=1, retry_budget_seconds=0.1) == "success"

    assert requests.await_count == 2
    sleep.assert_awaited_once()
    assert 0 < sleep.await_args.args[0] <= 0.05


@pytest.mark.parametrize("during_backoff", [False, True])
async def test_shared_deadline(requests, monkeypatch, during_backoff):
    monkeypatch.setattr(random, "uniform", lambda low, high: 1.0)

    async def post(*args, **kwargs):
        assert 0 < kwargs["timeout"] <= 0.05
        if not during_backoff:
            await asyncio.Event().wait()
        return httpx.Response(503)

    requests.side_effect = post
    result = await asyncio.wait_for(JinaClient().crawl("https://example.com", max_retries=2, retry_budget_seconds=0.05), timeout=1)
    assert result.startswith("Error:")
    assert "budget" in result
    assert requests.await_count == 1


async def test_budget_is_shared_across_attempts(requests, monkeypatch):
    timeouts = []
    real_sleep = asyncio.sleep

    async def post(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        if len(timeouts) == 1:
            await real_sleep(0.02)
            return httpx.Response(503)
        await asyncio.Event().wait()

    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    requests.side_effect = post
    result = await asyncio.wait_for(JinaClient().crawl("https://example.com", max_retries=2, retry_budget_seconds=0.1), 1)
    assert "budget" in result
    assert len(timeouts) == 2
    assert timeouts[1] < timeouts[0]


@pytest.mark.parametrize("during_backoff", [False, True])
async def test_cancellation(requests, monkeypatch, during_backoff):
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def block(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    if during_backoff:
        requests.return_value = httpx.Response(503)
        monkeypatch.setattr(asyncio, "sleep", block)
    else:
        requests.side_effect = block
    task = asyncio.create_task(JinaClient().crawl("https://example.com", max_retries=2))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert cancelled.is_set()
        assert requests.await_count == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("options", [{"max_retries": value} for value in (-1, True, 1.5, "2", None)] + [{"retry_budget_seconds": value} for value in (0, -1, True, float("nan"), float("inf"), "10", None)])
async def test_invalid_settings_do_not_send(requests, options):
    assert (await JinaClient().crawl("https://example.com", **options)).startswith("Error:")
    requests.assert_not_awaited()


async def test_tool_forwards_settings(monkeypatch):
    from deerflow.community.jina_ai import tools

    crawl = AsyncMock(return_value="Error: test")
    config = SimpleNamespace(model_extra={"max_retries": 2, "retry_budget_seconds": 12.5})
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: config))
    monkeypatch.setattr(JinaClient, "crawl", crawl)
    assert await tools.web_fetch_tool.ainvoke("https://example.com") == "Error: test"
    assert crawl.call_args.kwargs["max_retries"] == 2
    assert crawl.call_args.kwargs["retry_budget_seconds"] == 12.5
