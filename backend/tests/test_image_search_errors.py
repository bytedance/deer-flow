"""Image search outages must not be reported as an empty result set."""

import json
import sys
from types import SimpleNamespace

import ddgs
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


@pytest.mark.parametrize("sdk_sentinel", [False, True])
async def test_image_search_preserves_genuinely_empty_results(monkeypatch, sdk_sentinel):
    def empty_search(self, query, **kwargs):
        if sdk_sentinel:
            raise DDGSException("No results found.")
        return []

    monkeypatch.setattr(DDGS, "images", empty_search)

    output = json.loads(await tools.image_search_tool.ainvoke({"query": "a cat"}))

    assert output == {"error": "No images found", "query": "a cat"}


async def test_image_search_does_not_confuse_embedded_empty_result_text_with_success(monkeypatch):
    def failed_search(self, query, **kwargs):
        raise DDGSException("No results found for query: HTTP 429")

    monkeypatch.setattr(DDGS, "images", failed_search)

    output = json.loads(await tools.image_search_tool.ainvoke({"query": "a cat"}))

    assert "429" in output["error"]
    assert output["error"] != "No images found"
