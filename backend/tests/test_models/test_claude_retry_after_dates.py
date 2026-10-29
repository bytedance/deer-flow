"""HTTP-date retry hints through the public Claude model and real SDK."""

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from deerflow.models import claude_provider as provider


@pytest.fixture
def fixed_clock(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(provider, "time", SimpleNamespace(time=lambda: now.timestamp()))
    return now


@pytest.mark.parametrize("seconds, expected", [(-60, 0), (0, 0), (60, 60000), (86400, 86400000), (86401, 2400)])
def test_date_delay_bounds(fixed_clock, seconds, expected):
    raw = format_datetime(fixed_clock + timedelta(seconds=seconds), usegmt=True)
    error = SimpleNamespace(response=httpx.Response(429, headers={"Retry-After": raw}))
    assert provider.ClaudeChatModel._calc_backoff_ms(1, error) == expected


@pytest.mark.parametrize("raw", ["Thu, 99 Jan 2026 00:10:00 GMT", "Fri, 31 Dec 9999 23:59:59 GMT", "not a date"])
def test_unusable_dates_keep_local_backoff(fixed_clock, raw):
    error = SimpleNamespace(response=httpx.Response(503, headers={"Retry-After": raw}))
    assert provider.ClaudeChatModel._calc_backoff_ms(2, error) == 4800


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("raw", ["Thu, 01 Jan 2026 00:01:00 GMT", "Thursday, 01-Jan-26 00:01:00 GMT", "Thu Jan  1 00:01:00 2026"])
async def test_public_call_waits_for_http_date(monkeypatch, fixed_clock, mode, status, raw):
    requests = []
    waits = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(status, headers={"Retry-After": raw}, json={"type": "error", "error": {"type": "rate_limit_error" if status == 429 else "api_error", "message": "Try later"}})
        return httpx.Response(
            200, json={"id": "msg-test", "type": "message", "role": "assistant", "model": "claude-sonnet-4-6", "content": [{"type": "text", "text": "recovered"}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}
        )

    async def sleep(delay):
        waits.append(delay)

    provider.time.sleep = waits.append
    monkeypatch.setattr(asyncio, "sleep", sleep)
    model = provider.ClaudeChatModel(model="claude-sonnet-4-6", anthropic_api_key="sk-ant-fake", max_tokens=1024, max_retries=0, retry_max_attempts=2)
    transport = httpx.MockTransport(respond)
    if mode == "sync":
        with anthropic.Anthropic(api_key="sk-ant-fake", max_retries=0, http_client=httpx.Client(transport=transport)) as client:
            model._client = client
            result = model.invoke("hi")
    else:
        async with anthropic.AsyncAnthropic(api_key="sk-ant-fake", max_retries=0, http_client=httpx.AsyncClient(transport=transport)) as client:
            model._async_client = client
            result = await model.ainvoke("hi")
    assert result.content == "recovered"
    assert len(requests) == 2
    assert waits == [60.0]
