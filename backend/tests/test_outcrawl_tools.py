"""Unit tests for the Outcrawl community web search and web fetch tools."""

import json
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.outcrawl import tools as outcrawl_tools

pytestmark = pytest.mark.anyio


def _patch_config(monkeypatch, extra: dict | None) -> None:
    def config():
        tool_config = None if extra is None else SimpleNamespace(model_extra=dict(extra))
        return SimpleNamespace(get_tool_config=lambda _name: tool_config)

    monkeypatch.setattr(outcrawl_tools, "get_app_config", config)


def _patch_transport(monkeypatch, respond) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return respond(request)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(outcrawl_tools.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))
    return requests


@pytest.fixture(autouse=True)
def _no_env_key(monkeypatch):
    monkeypatch.delenv("OUTCRAWL_API_KEY", raising=False)


async def test_web_search_posts_query_and_normalizes_hits(monkeypatch):
    _patch_config(monkeypatch, {"api_key": "test-key", "max_results": 2})
    payload = {
        "hits": [
            {"url": "https://example.com/a", "title": "A", "snippet": "first", "rank": 1},
            {"url": "https://example.com/b", "title": "B", "snippet": "second", "rank": 2},
            {"url": "https://example.com/c", "title": "C", "snippet": "third", "rank": 3},
        ],
        "usage": {"credits": "1.5"},
    }
    requests = _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json=payload))

    result = json.loads(await outcrawl_tools.web_search_tool.ainvoke({"query": "vector databases"}))

    assert str(requests[0].url) == "https://api.outcrawl.ai/v1/search"
    assert requests[0].headers["Authorization"] == "Bearer test-key"
    assert json.loads(requests[0].content) == {"query": "vector databases", "limit": 2}
    assert result == [
        {"title": "A", "url": "https://example.com/a", "snippet": "first"},
        {"title": "B", "url": "https://example.com/b", "snippet": "second"},
    ]


async def test_web_search_caller_max_results_wins_and_is_clamped(monkeypatch):
    _patch_config(monkeypatch, {"api_key": "test-key", "max_results": 3})
    requests = _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json={"hits": []}))

    result = json.loads(await outcrawl_tools.web_search_tool.ainvoke({"query": "q", "max_results": 500}))

    assert json.loads(requests[0].content)["limit"] == 20
    assert result == {"error": "No results found", "query": "q"}


async def test_web_search_uses_env_key_when_config_has_none(monkeypatch):
    monkeypatch.setenv("OUTCRAWL_API_KEY", "env-key")
    _patch_config(monkeypatch, None)
    requests = _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json={"hits": []}))

    await outcrawl_tools.web_search_tool.ainvoke({"query": "q"})

    assert requests[0].headers["Authorization"] == "Bearer env-key"
    assert json.loads(requests[0].content)["limit"] == 5


async def test_web_search_without_key_makes_no_request(monkeypatch):
    _patch_config(monkeypatch, {})
    requests = _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json={"hits": []}))

    result = json.loads(await outcrawl_tools.web_search_tool.ainvoke({"query": "q"}))

    assert result == {"error": "OUTCRAWL_API_KEY is not configured", "query": "q"}
    assert requests == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "Outcrawl API error: HTTP 401 (invalid or revoked OUTCRAWL_API_KEY)"),
        (500, "Outcrawl API error: HTTP 500"),
    ],
)
async def test_web_search_reports_http_errors(monkeypatch, status, expected):
    _patch_config(monkeypatch, {"api_key": "test-key"})
    _patch_transport(monkeypatch, lambda _request: httpx.Response(status, json={"code": "x", "message": "y"}))

    result = json.loads(await outcrawl_tools.web_search_tool.ainvoke({"query": "q"}))

    assert result == {"error": expected, "query": "q"}


async def test_web_search_rejects_malformed_hits(monkeypatch):
    _patch_config(monkeypatch, {"api_key": "test-key"})
    _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json={"hits": {"url": "x"}}))

    result = json.loads(await outcrawl_tools.web_search_tool.ainvoke({"query": "q"}))

    assert result == {"error": "Outcrawl returned an unexpected response format", "query": "q"}


async def test_web_fetch_returns_title_and_markdown(monkeypatch):
    _patch_config(monkeypatch, {"api_key": "test-key"})
    monkeypatch.setattr(outcrawl_tools, "validate_public_http_url", lambda _url: None)
    payload = {
        "url": "https://example.com/",
        "statusCode": 200,
        "markdown": "x" * 5000,
        "metadata": {"title": "Example Domain"},
        "usage": {"credits": "1"},
    }
    requests = _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json=payload))

    result = await outcrawl_tools.web_fetch_tool.ainvoke({"url": "https://example.com"})

    assert str(requests[0].url) == "https://api.outcrawl.ai/v1/scrape"
    assert json.loads(requests[0].content) == {"url": "https://example.com", "formats": ["markdown"]}
    assert result == "# Example Domain\n\n" + "x" * 4096


async def test_web_fetch_refuses_non_public_urls_before_any_request(monkeypatch):
    _patch_config(monkeypatch, {"api_key": "test-key"})
    requests = _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json={}))

    result = await outcrawl_tools.web_fetch_tool.ainvoke({"url": "http://127.0.0.1:8080/admin"})

    assert result.startswith("Error:")
    assert requests == []


async def test_web_fetch_reports_empty_content(monkeypatch):
    _patch_config(monkeypatch, {"api_key": "test-key"})
    monkeypatch.setattr(outcrawl_tools, "validate_public_http_url", lambda _url: None)
    _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json={"markdown": "", "metadata": {}}))

    result = await outcrawl_tools.web_fetch_tool.ainvoke({"url": "https://example.com"})

    assert result == "Error: No content found"


async def test_web_search_surfaces_outcrawl_warnings(monkeypatch):
    _patch_config(monkeypatch, {"api_key": "test-key"})
    payload = {
        "hits": [{"url": "https://example.com/a", "title": "A", "snippet": "first", "rank": 1}],
        "warnings": [
            {"code": "engines_refused", "message": "one search engine refused the query; results come from the others"},
            {"message": "no code, dropped"},
            "not an object, dropped",
        ],
        "usage": {"credits": "0.5"},
    }
    _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json=payload))

    result = json.loads(await outcrawl_tools.web_search_tool.ainvoke({"query": "q"}))

    assert result == {
        "query": "q",
        "results": [{"title": "A", "url": "https://example.com/a", "snippet": "first"}],
        "warnings": [{"code": "engines_refused", "message": "one search engine refused the query; results come from the others"}],
    }


async def test_web_search_reports_warnings_when_nothing_came_back(monkeypatch):
    _patch_config(monkeypatch, {"api_key": "test-key"})
    payload = {"hits": [], "warnings": [{"code": "engines_refused", "message": "every engine refused"}]}
    _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json=payload))

    result = json.loads(await outcrawl_tools.web_search_tool.ainvoke({"query": "q"}))

    assert result == {
        "error": "No results found",
        "query": "q",
        "warnings": [{"code": "engines_refused", "message": "every engine refused"}],
    }


async def test_web_fetch_puts_warnings_above_the_content(monkeypatch):
    _patch_config(monkeypatch, {"api_key": "test-key"})
    monkeypatch.setattr(outcrawl_tools, "validate_public_http_url", lambda _url: None)
    # Shape of a live /v1/scrape answer for a page that redirects to its sign-in page.
    payload = {
        "url": "https://github.com/login?return_to=https%3A%2F%2Fgithub.com%2Fsettings%2Fprofile",
        "statusCode": 200,
        "markdown": "Sign in to GitHub",
        "metadata": {"title": "Sign in to GitHub \u00b7 GitHub", "complete": False},
        "warnings": [
            {
                "code": "login_redirect",
                "message": "the site redirected this request to its sign-in page (github.com/login), so treat this as a failed fetch",
            }
        ],
    }
    _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json=payload))

    result = await outcrawl_tools.web_fetch_tool.ainvoke({"url": "https://github.com/settings/profile"})

    assert result == ("# Sign in to GitHub \u00b7 GitHub\n\n> Outcrawl warning (login_redirect): the site redirected this request to its sign-in page (github.com/login), so treat this as a failed fetch\n\nSign in to GitHub")


async def test_web_fetch_flags_a_target_http_error(monkeypatch):
    _patch_config(monkeypatch, {"api_key": "test-key"})
    monkeypatch.setattr(outcrawl_tools, "validate_public_http_url", lambda _url: None)
    payload = {"url": "https://example.com/missing", "statusCode": 404, "markdown": "Not found", "metadata": {"title": "404"}}
    _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json=payload))

    result = await outcrawl_tools.web_fetch_tool.ainvoke({"url": "https://example.com/missing"})

    assert result == "# 404\n\n> Outcrawl warning: the target page responded HTTP 404\n\nNot found"


async def test_web_fetch_reports_warnings_with_empty_content(monkeypatch):
    _patch_config(monkeypatch, {"api_key": "test-key"})
    monkeypatch.setattr(outcrawl_tools, "validate_public_http_url", lambda _url: None)
    payload = {"markdown": "", "metadata": {}, "warnings": [{"code": "empty_capture", "message": "the page rendered nothing"}]}
    _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json=payload))

    result = await outcrawl_tools.web_fetch_tool.ainvoke({"url": "https://example.com"})

    assert result == "Error: No content found\n> Outcrawl warning (empty_capture): the page rendered nothing"


@pytest.mark.parametrize(
    ("payload", "expected_title"),
    [
        ({"url": "https://example.com/post", "markdown": "intro\n\n## Release notes ##\n\nbody", "metadata": {}}, "Release notes"),
        ({"url": "https://example.com/post", "markdown": "no heading here", "metadata": {"title": "  "}}, "https://example.com/post"),
        ({"markdown": "no heading here"}, "https://example.com/requested"),
    ],
)
async def test_web_fetch_title_falls_back_to_heading_then_url(monkeypatch, payload, expected_title):
    _patch_config(monkeypatch, {"api_key": "test-key"})
    monkeypatch.setattr(outcrawl_tools, "validate_public_http_url", lambda _url: None)
    _patch_transport(monkeypatch, lambda _request: httpx.Response(200, json=payload))

    result = await outcrawl_tools.web_fetch_tool.ainvoke({"url": "https://example.com/requested"})

    assert result.startswith(f"# {expected_title}\n\n")
