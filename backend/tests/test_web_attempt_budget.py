"""Offline coverage for the optional first-party Web attempt cap."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from deerflow.community.jina_ai import tools as jina_tools
from deerflow.community.jina_ai.jina_client import JinaClient
from deerflow.community.serper import tools as serper
from deerflow.community.web_attempt_budget import (
    WebAttemptBudgetExceeded,
    counter_for_config,
    register_run,
    unregister_run,
)
from deerflow.config.web_attempt_budget_config import WebAttemptBudgetConfig


def test_config_is_off_by_default_and_rejects_invalid_limits():
    assert WebAttemptBudgetConfig().max_attempts is None
    for value in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            WebAttemptBudgetConfig(max_attempts=value)


def test_atomic_reservations_across_threads_and_run_isolation():
    register_run("budget-test-a", 4)
    register_run("budget-test-b", 1)
    try:
        a = counter_for_config({"context": {"run_id": "budget-test-a"}})
        b = counter_for_config({"context": {"run_id": "budget-test-b"}})

        def reserve():
            try:
                a.reserve()
                return True
            except WebAttemptBudgetExceeded:
                return False

        with ThreadPoolExecutor(max_workers=12) as pool:
            assert sum(pool.map(lambda _: reserve(), range(30))) == 4
        b.reserve()
        with pytest.raises(WebAttemptBudgetExceeded):
            b.reserve()
    finally:
        unregister_run("budget-test-a")
        unregister_run("budget-test-b")
    assert counter_for_config({"context": {"run_id": "budget-test-a"}}) is None


def test_unavailable_cross_process_counter_fails_closed():
    policy = SimpleNamespace(web_attempt_budget=WebAttemptBudgetConfig(max_attempts=2))
    counter = counter_for_config({"context": {"run_id": "parent-on-another-worker", "app_config": policy}})
    with pytest.raises(WebAttemptBudgetExceeded):
        counter.reserve()
    child_config = {
        "configurable": {
            "__pregel_runtime": SimpleNamespace(context={"run_id": "parent-on-another-worker"}),
            "context": {"run_id": "parent-on-another-worker", "app_config": policy},
        }
    }
    with pytest.raises(WebAttemptBudgetExceeded):
        counter_for_config(child_config).reserve()


@pytest.mark.anyio
async def test_serper_and_jina_share_one_counter_including_redirect(monkeypatch):
    original_sync = httpx.Client
    original_async = httpx.AsyncClient
    sent = []

    def respond(request):
        sent.append(str(request.url))
        if request.url.host == "r.jina.ai" and request.url.path == "/":
            return httpx.Response(307, headers={"Location": "https://r.jina.ai/final"})
        if request.url.host == "r.jina.ai":
            return httpx.Response(200, text="article")
        return httpx.Response(200, json={"organic": []})

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_sync(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_async(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setenv("JINA_API_KEY", "test-key")
    register_run("budget-test-shared", 2)
    try:
        counter = counter_for_config({"context": {"run_id": "budget-test-shared"}})
        data, error = serper._serper_post("https://google.serper.dev/search", "test", "q", 1, attempt_budget=counter)
        assert data == {"organic": []} and error is None
        assert (await JinaClient().crawl("https://example.com", trust_env=False, attempt_budget=counter)).endswith("web_attempt_budget_exhausted)")
        assert len(sent) == 2  # Serper request and Jina's first hop; redirect rejected.
        _, error = serper._serper_post("https://google.serper.dev/images", "test", "q", 1, attempt_budget=counter)
        assert json.loads(error)["code"] == "web_attempt_budget_exhausted"
        assert len(sent) == 2
    finally:
        unregister_run("budget-test-shared")


@pytest.mark.anyio
async def test_jina_retry_consumes_each_attempt(monkeypatch):
    original_async = httpx.AsyncClient
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(503, text="unavailable")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_async(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(asyncio, "sleep", lambda _: _noop())
    monkeypatch.setenv("JINA_API_KEY", "test-key")
    register_run("budget-test-retry", 1)
    try:
        counter = counter_for_config({"context": {"run_id": "budget-test-retry"}})
        assert "web_attempt_budget_exhausted" in await JinaClient().crawl("https://example.com", trust_env=False, max_retries=1, attempt_budget=counter)
        assert len(sent) == 1
    finally:
        unregister_run("budget-test-retry")


async def _noop():
    return None


@pytest.mark.anyio
async def test_tool_runtime_config_passes_shared_counter_without_model_argument(monkeypatch):
    monkeypatch.setattr(serper, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: None))
    monkeypatch.setattr(serper, "_get_api_key", lambda *args, **kwargs: "test")
    seen = []

    def post(*args, **kwargs):
        seen.append(kwargs["attempt_budget"])
        return {"organic": []}, None

    monkeypatch.setattr(serper, "_serper_post", post)
    original_lookup = serper.counter_for_config
    captured_configs = []

    def lookup(value):
        captured_configs.append(value)
        return original_lookup(value)

    monkeypatch.setattr(serper, "counter_for_config", lookup)
    crawl = AsyncMock(return_value="Error: done")
    monkeypatch.setattr(jina_tools.JinaClient, "crawl", crawl)
    monkeypatch.setattr(jina_tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: None))
    register_run("budget-test-tool", 2)
    try:
        config = {"context": {"run_id": "budget-test-tool"}}
        serper.web_search_tool.invoke({"query": "sample"}, config=config)
        await jina_tools.web_fetch_tool.ainvoke({"url": "https://example.com"}, config=config)
        assert seen == [counter_for_config(config)], captured_configs
        assert crawl.await_args.kwargs["attempt_budget"] is seen[0]
        assert "runnable_config" not in serper.web_search_tool.args_schema.model_json_schema()["properties"]
    finally:
        unregister_run("budget-test-tool")
