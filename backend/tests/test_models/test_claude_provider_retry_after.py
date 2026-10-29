"""Offline regressions for provider-owned Retry-After backoff."""

import asyncio
import time
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from deerflow.models.claude_provider import ClaudeChatModel


@pytest.mark.parametrize("attempt", [1, 2])
@pytest.mark.parametrize("raw", ["1e999", "inf", "-inf", "nan", "1e15", "999999999999999999999999999999", pytest.param("9" * 1000, id="huge-integer"), "86401", "bad", None])
def test_unusable_claude_retry_after_uses_default_backoff(attempt: int, raw: str | None) -> None:
    error = Exception("rate limited")
    error.response = SimpleNamespace(headers={"Retry-After": raw})
    assert ClaudeChatModel._calc_backoff_ms(attempt, error) == 2400 * 2 ** (attempt - 1)


@pytest.mark.parametrize(("raw", "expected_ms"), [("-2", 0), ("0", 0), ("60", 60000), ("86400", 86400000)])
def test_usable_claude_retry_after_is_preserved(raw: str, expected_ms: int) -> None:
    error = Exception("rate limited")
    error.response = SimpleNamespace(headers={"Retry-After": raw})
    assert ClaudeChatModel._calc_backoff_ms(1, error) == expected_ms


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("error_type", [anthropic.RateLimitError, anthropic.InternalServerError])
@pytest.mark.parametrize("raw", ["999999999999999999999999999999", "86401", "1e999", "60"])
async def test_claude_retry_loops_use_safe_delay(monkeypatch: pytest.MonkeyPatch, mode: str, error_type: type[anthropic.APIStatusError], raw: str) -> None:
    # Avoid credential discovery/client construction; only the provider call is fake.
    monkeypatch.setattr(ClaudeChatModel, "model_post_init", lambda self, context: None)
    model = ClaudeChatModel(model="claude-sonnet-4-6", anthropic_api_key="sk-ant-fake", retry_max_attempts=2)
    model._is_oauth = False
    response = httpx.Response(429 if error_type is anthropic.RateLimitError else 500, headers={"Retry-After": raw}, request=httpx.Request("POST", "https://example.invalid/messages"))
    error = error_type("provider failure", response=response, body={})
    expected = ChatResult(generations=[ChatGeneration(message=AIMessage(content="recovered"))])
    attempts = 0
    waits: list[float] = []

    def provider_call(self, messages, **kwargs) -> ChatResult:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise error
        return expected

    async def async_provider_call(self, messages, **kwargs) -> ChatResult:
        return provider_call(self, messages, **kwargs)

    def fake_sleep(delay: float) -> None:
        assert delay == (60 if raw == "60" else 2.4)
        waits.append(delay)

    async def fake_async_sleep(delay: float) -> None:
        fake_sleep(delay)

    monkeypatch.setattr(ChatAnthropic, "_generate", provider_call)
    monkeypatch.setattr(ChatAnthropic, "_agenerate", async_provider_call)
    monkeypatch.setattr(time, "sleep", fake_sleep)
    monkeypatch.setattr(asyncio, "sleep", fake_async_sleep)
    if mode == "sync":
        result = model._generate([HumanMessage(content="hi")])
    else:
        result = await model._agenerate([HumanMessage(content="hi")])
    assert result is expected
    assert attempts == 2
    assert len(waits) == 1
