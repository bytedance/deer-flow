"""Offline pacing and challenge regression tests."""

import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from ddgs.exceptions import DDGSException, RatelimitException

from deerflow.community.ddg_search import tools


@pytest.fixture
def clock(monkeypatch):
    state = SimpleNamespace(now=0.0, sleeps=[])

    def sleep(delay):
        state.sleeps.append(delay)
        state.now += delay

    monkeypatch.setattr(tools, "_last_call", None)
    monkeypatch.setattr(tools, "monotonic", lambda: state.now)
    monkeypatch.setattr(tools, "sleep", sleep)
    monkeypatch.setattr(tools, "uniform", lambda low, high: 0.25)
    return state


def fake_client(monkeypatch, operation):
    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=lambda **kw: SimpleNamespace(text=operation)))


def test_process_wide_pacing_across_threads(monkeypatch, clock):
    starts = []
    fake_client(monkeypatch, lambda *a, **kw: starts.append(clock.now) or [])
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(tools._search_text, ["one", "two", "three", "four"])) == [[], [], [], []]
    assert starts == [0, 4.25, 8.5, 12.75]


@pytest.mark.parametrize("error", [RatelimitException("limited"), DDGSException("HTTP 202"), DDGSException("anomaly detected"), DDGSException("CAPTCHA"), DDGSException("HTTP 429"), DDGSException("vqd extraction failed")])
def test_challenges_retry_then_raise(monkeypatch, clock, error):
    calls = []

    def blocked(*args, **kwargs):
        calls.append(clock.now)
        raise error

    fake_client(monkeypatch, blocked)
    with pytest.raises(tools.DDGSearchError, match="DuckDuckGo blocked/challenged this request"):
        tools._search_text("news", min_interval_seconds=0, max_retries=2)
    assert len(calls) == 3
    assert clock.sleeps == [1, 2]


def test_retry_can_recover(monkeypatch, clock):
    responses = [DDGSException("CAPTCHA"), [{"title": "ok"}]]

    def search(*args, **kwargs):
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    fake_client(monkeypatch, search)
    assert tools._search_text("news", min_interval_seconds=0) == [{"title": "ok"}]


@pytest.mark.parametrize("result", [[], DDGSException("No results found.")])
def test_genuine_empty_is_not_retried(monkeypatch, clock, result):
    calls = []

    def search(*args, **kwargs):
        calls.append(1)
        if isinstance(result, Exception):
            raise result
        return result

    fake_client(monkeypatch, search)
    assert tools._search_text("news") == []
    assert calls == [1]


def test_chained_challenge_is_not_an_empty_sentinel(monkeypatch, clock):
    def search(*args, **kwargs):
        try:
            raise RatelimitException("CAPTCHA")
        except RatelimitException as exc:
            raise DDGSException("No results found.") from exc

    fake_client(monkeypatch, search)
    with pytest.raises(tools.DDGSearchError, match="blocked/challenged"):
        tools._search_text("news", max_retries=0)


def test_tool_passes_pacing_config(monkeypatch):
    from unittest.mock import Mock

    config = SimpleNamespace(model_extra={"min_interval_seconds": 7, "max_retries": 1})
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: config))
    search = Mock(return_value=[])
    monkeypatch.setattr(tools, "_search_text", search)
    tools.web_search_tool.invoke({"query": "news"})
    assert search.call_args.kwargs["min_interval_seconds"] == 7
    assert search.call_args.kwargs["max_retries"] == 1


@pytest.mark.parametrize("options", [{"max_retries": -1}, {"max_retries": 6}, {"max_retries": True}, {"min_interval_seconds": float("nan")}, {"min_interval_seconds": -1}])
def test_invalid_pacing_config_fails_without_request(monkeypatch, clock, options):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid configuration must not reach DDGS")

    fake_client(monkeypatch, unexpected)
    with pytest.raises(tools.DDGSearchError):
        tools._search_text("news", **options)


def test_unrecognized_failure_is_not_retried(monkeypatch, clock):
    calls = []

    def search(*args, **kwargs):
        calls.append(1)
        raise DDGSException("connection lost")

    fake_client(monkeypatch, search)
    with pytest.raises(tools.DDGSearchError, match="connection lost"):
        tools._search_text("news")
    assert calls == [1]
    assert clock.sleeps == []


def test_elapsed_request_time_counts_toward_interval(monkeypatch, clock):
    def search(*args, **kwargs):
        clock.now += 10
        return []

    fake_client(monkeypatch, search)
    tools._search_text("first")
    tools._search_text("second")
    assert clock.sleeps == []
