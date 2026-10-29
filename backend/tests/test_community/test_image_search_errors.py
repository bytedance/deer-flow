"""Image search outages must not be reported as an empty result set."""

import json
import sys
import threading
from concurrent.futures import wait as wait_for_futures
from types import SimpleNamespace

import ddgs
import ddgs.ddgs as ddgs_dispatch
import pytest
from ddgs.ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from deerflow.community.image_search import tools

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def configured_search(monkeypatch):
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: None))


@pytest.mark.parametrize("failure", ["rate-limit", "timeout", "constructor", "missing-dependency", "iteration"])
async def test_image_search_reports_execution_failure(monkeypatch, failure):
    if failure == "missing-dependency":
        monkeypatch.setitem(sys.modules, "ddgs", None)
        expected = "not installed"
    elif failure == "constructor":

        def unavailable_client(**kwargs):
            raise RuntimeError("search client unavailable")

        monkeypatch.setattr(ddgs, "DDGS", unavailable_client)
        expected = "search client unavailable"
    else:
        error = RatelimitException("HTTP 429") if failure == "rate-limit" else TimeoutException("search timed out")

        def failing_search(self, query, **kwargs):
            if failure == "iteration":

                def incomplete_results():
                    yield {"title": "partial", "image": "https://example.com/image.jpg", "thumbnail": "https://example.com/thumb.jpg"}
                    raise error

                return incomplete_results()
            raise error

        monkeypatch.setattr(DDGS, "images", failing_search)
        expected = "429" if failure == "rate-limit" else "timed out"

    output = json.loads(await tools.image_search_tool.ainvoke({"query": "雪山"}))

    assert output["query"] == "雪山"
    assert expected in output["error"]
    assert output["error"] != "No images found"
    assert "results" not in output


async def test_image_search_reports_configuration_failure(monkeypatch):
    def invalid_config():
        raise ValueError("invalid image search configuration")

    monkeypatch.setattr(tools, "get_app_config", invalid_config)

    output = json.loads(await tools.image_search_tool.ainvoke({"query": "a cat"}))

    assert "invalid image search configuration" in output["error"]
    assert output["query"] == "a cat"


async def test_image_search_preserves_genuinely_empty_results(monkeypatch):
    def empty_search(self, query, **kwargs):
        return []

    monkeypatch.setattr(DDGS, "images", empty_search)

    output = json.loads(await tools.image_search_tool.ainvoke({"query": "a cat"}))

    assert output == {"error": "No images found", "query": "a cat"}


@pytest.mark.parametrize("backend_outcome", ["empty", "timeout", "late-timeout"])
async def test_image_search_does_not_mistake_sdk_dispatcher_failure_for_empty_results(monkeypatch, backend_outcome):
    engine_started = threading.Event()
    engine_outcome_observed = threading.Event()
    pending_at_deadline = threading.Event()
    deadline_expired = threading.Event()

    def search(query, **kwargs):
        engine_started.set()
        if backend_outcome == "late-timeout":
            assert deadline_expired.wait(timeout=5), "dispatcher must release the pending engine"
        engine_outcome_observed.set()
        if backend_outcome != "empty":
            raise TimeoutException("image backend timed out")
        return []

    def expire_wait(futures, **kwargs):
        try:
            assert engine_started.wait(timeout=5), "engine must run before the wait deadline"
            done, pending = wait_for_futures(futures, timeout=0.01, return_when=kwargs["return_when"])
            assert pending, "regression must leave the failed request pending at the SDK deadline"
            pending_at_deadline.set()
            return done, pending
        finally:
            deadline_expired.set()

    engine = SimpleNamespace(provider="offline", name="offline", search=search)
    monkeypatch.setattr(DDGS, "_get_network_client", lambda self: None)
    monkeypatch.setattr(DDGS, "_get_engines", lambda self, category, backend: [engine])
    if backend_outcome == "late-timeout":
        monkeypatch.setattr(ddgs_dispatch, "wait", expire_wait)

    output = json.loads(await tools.image_search_tool.ainvoke({"query": "snow mountains"}))

    assert engine_started.is_set()
    assert engine_outcome_observed.is_set(), "the engine must reach its intended result, not fail a watchdog"
    if backend_outcome == "late-timeout":
        assert pending_at_deadline.is_set(), "the SDK must observe an unfinished request at the deadline"
    assert output["query"] == "snow mountains"
    assert output["error"].startswith("DuckDuckGo image search failed:")
    assert output["error"] != "No images found"
    assert "results" not in output


async def test_image_search_does_not_confuse_embedded_empty_result_text_with_success(monkeypatch):
    def failed_search(self, query, **kwargs):
        raise DDGSException("No results found for query: HTTP 429")

    monkeypatch.setattr(DDGS, "images", failed_search)

    output = json.loads(await tools.image_search_tool.ainvoke({"query": "a cat"}))

    assert "429" in output["error"]
    assert output["error"] != "No images found"
