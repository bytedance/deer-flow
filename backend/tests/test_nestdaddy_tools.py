"""Unit tests for the NestDaddy community web search tool."""

import json
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

_MODULE = "deerflow.community.nestdaddy.tools"


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the module-level warning flag before each test."""
    import deerflow.community.nestdaddy.tools as nestdaddy_mod

    nestdaddy_mod._api_key_warned = set()
    yield
    nestdaddy_mod._api_key_warned = set()


@pytest.fixture
def mock_config_with_key():
    with patch(f"{_MODULE}.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {"api_key": "test-nestdaddy-key", "max_results": 5}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


@pytest.fixture
def mock_config_no_key():
    with patch(f"{_MODULE}.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


def _make_response(body: object) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = body
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _result(n: int, **extra) -> dict:
    return {"title": f"Result {n}", "url": f"https://example.com/{n}", "snippet": f"Snippet {n}", "domain": "example.com", "type": "web", **extra}


def _body(results: object, **extra) -> dict:
    return {"success": True, "api": "search", "query": "q", "results": results, **extra}


def _patch_client(response=None, side_effect=None):
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    if side_effect is not None:
        client.get.side_effect = side_effect
    else:
        client.get.return_value = response
    return patch(f"{_MODULE}.httpx.Client", return_value=client), client


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        with patch(f"{_MODULE}.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "from-config"}
            mock.return_value.get_tool_config.return_value = tool_config
            from deerflow.community.nestdaddy.tools import _get_api_key

            assert _get_api_key("web_search") == "from-config"

    def test_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("NESTDADDY_API_KEY", "from-env")
        with patch(f"{_MODULE}.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            from deerflow.community.nestdaddy.tools import _get_api_key

            assert _get_api_key("web_search") == "from-env"

    def test_returns_none_without_any_key(self, monkeypatch):
        monkeypatch.delenv("NESTDADDY_API_KEY", raising=False)
        with patch(f"{_MODULE}.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            from deerflow.community.nestdaddy.tools import _get_api_key

            assert _get_api_key("web_search") is None


class TestWebSearchTool:
    def test_missing_key_returns_error_and_warns_once(self, mock_config_no_key, monkeypatch, caplog):
        monkeypatch.delenv("NESTDADDY_API_KEY", raising=False)
        from deerflow.community.nestdaddy.tools import web_search_tool

        with caplog.at_level(logging.WARNING):
            first = json.loads(web_search_tool.invoke({"query": "test"}))
            web_search_tool.invoke({"query": "test"})
        assert first["error"] == "NESTDADDY_API_KEY is not configured"
        assert sum("NestDaddy API key is not set" in r.message for r in caplog.records) == 1

    def test_sends_key_query_and_limit(self, mock_config_with_key):
        from deerflow.community.nestdaddy.tools import web_search_tool

        ctx, client = _patch_client(_make_response(_body([_result(1)])))
        with ctx:
            web_search_tool.invoke({"query": "  ai agents  ", "max_results": 3})
        args, kwargs = client.get.call_args
        assert args[0] == "https://nestdaddy.com/api/v1/search"
        assert kwargs["headers"] == {"X-API-Key": "test-nestdaddy-key"}
        assert kwargs["params"] == {"q": "ai agents", "limit": 3}

    def test_uses_configured_max_results_when_omitted(self, mock_config_with_key):
        from deerflow.community.nestdaddy.tools import web_search_tool

        ctx, client = _patch_client(_make_response(_body([_result(i) for i in range(8)])))
        with ctx:
            output = json.loads(web_search_tool.invoke({"query": "q"}))
        assert client.get.call_args.kwargs["params"]["limit"] == 5
        assert output["total_results"] == 5

    def test_clamps_max_results_to_api_cap(self, mock_config_with_key):
        from deerflow.community.nestdaddy.tools import web_search_tool

        ctx, client = _patch_client(_make_response(_body([_result(1)])))
        with ctx:
            web_search_tool.invoke({"query": "q", "max_results": 500})
        assert client.get.call_args.kwargs["params"]["limit"] <= 50

    def test_truncates_long_query(self, mock_config_with_key):
        from deerflow.community.nestdaddy.tools import web_search_tool

        ctx, client = _patch_client(_make_response(_body([_result(1)])))
        with ctx:
            web_search_tool.invoke({"query": "x" * 900})
        assert len(client.get.call_args.kwargs["params"]["q"]) == 500

    def test_normalizes_results(self, mock_config_with_key):
        from deerflow.community.nestdaddy.tools import web_search_tool

        news = {"title": "News", "url": "https://news.example.com/a", "description": "From description", "published_timestamp": "2026-11-26T13:00:00+08:00"}
        ctx, _ = _patch_client(_make_response(_body([_result(1, published_date=""), news])))
        with ctx:
            output = json.loads(web_search_tool.invoke({"query": "q"}))
        assert output["query"] == "q"
        assert output["total_results"] == 2
        assert output["results"][0] == {"title": "Result 1", "url": "https://example.com/1", "snippet": "Snippet 1"}
        assert output["results"][1]["snippet"] == "From description"
        assert output["results"][1]["published"] == "2026-11-26T13:00:00+08:00"

    def test_unsafe_result_url_is_dropped(self, mock_config_with_key):
        from deerflow.community.nestdaddy.tools import web_search_tool

        ctx, _ = _patch_client(_make_response(_body([_result(1, url="http://127.0.0.1/admin")])))
        with ctx:
            output = json.loads(web_search_tool.invoke({"query": "q"}))
        assert output["results"][0]["url"] != "http://127.0.0.1/admin"

    @pytest.mark.parametrize("results", [[], None])
    def test_empty_results_report_no_results(self, mock_config_with_key, results):
        from deerflow.community.nestdaddy.tools import web_search_tool

        ctx, _ = _patch_client(_make_response(_body(results)))
        with ctx:
            output = json.loads(web_search_tool.invoke({"query": "q"}))
        assert output["error"] == "No results found"

    @pytest.mark.parametrize("results", ["oops", {"a": 1}, ["x", 1]])
    def test_malformed_results_report_format_error(self, mock_config_with_key, results):
        from deerflow.community.nestdaddy.tools import web_search_tool

        ctx, _ = _patch_client(_make_response(_body(results)))
        with ctx:
            output = json.loads(web_search_tool.invoke({"query": "q"}))
        assert output["error"] == "NestDaddy returned an unexpected response format"

    def test_non_object_body_reports_format_error(self, mock_config_with_key):
        from deerflow.community.nestdaddy.tools import web_search_tool

        ctx, _ = _patch_client(_make_response(["not", "an", "object"]))
        with ctx:
            output = json.loads(web_search_tool.invoke({"query": "q"}))
        assert output["error"] == "NestDaddy returned an unexpected response format"

    def test_success_false_reports_stable_error_without_upstream_detail(self, mock_config_with_key, caplog):
        from deerflow.community.nestdaddy.tools import web_search_tool

        ctx, _ = _patch_client(_make_response({"success": False, "error": "secret-detail-from-upstream"}))
        with ctx, caplog.at_level(logging.ERROR):
            output = json.loads(web_search_tool.invoke({"query": "q"}))
        assert output["error"] == "NestDaddy API error: the request was not successful"
        assert "secret-detail-from-upstream" not in caplog.text

    def test_http_error_reports_status_and_keeps_body_out_of_logs(self, mock_config_with_key, caplog):
        from deerflow.community.nestdaddy.tools import web_search_tool

        request = httpx.Request("GET", "https://nestdaddy.com/api/v1/search")
        response = httpx.Response(503, request=request, text="upstream body with the query q=private")
        failing = MagicMock()
        failing.raise_for_status.side_effect = httpx.HTTPStatusError("503", request=request, response=response)
        ctx, _ = _patch_client(failing)
        with ctx, caplog.at_level(logging.ERROR):
            output = json.loads(web_search_tool.invoke({"query": "q"}))
        assert output["error"] == "NestDaddy API error: HTTP 503"
        assert "HTTP 503" in caplog.text
        assert "upstream body" not in caplog.text

    def test_network_error_returns_exception_class_only(self, mock_config_with_key, caplog):
        from deerflow.community.nestdaddy.tools import web_search_tool

        ctx, _ = _patch_client(side_effect=httpx.ConnectError("connect to 10.0.0.5 failed: private detail"))
        with ctx, caplog.at_level(logging.ERROR):
            output = json.loads(web_search_tool.invoke({"query": "q"}))
        assert output["error"] == "NestDaddy request failed: ConnectError"
        assert output["query"] == "q"
        assert "private detail" not in caplog.text
