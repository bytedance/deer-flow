"""Unit tests for the Serply community web search tool."""

import json
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the module-level warning flag before each test."""
    import deerflow.community.serply.tools as serply_mod

    serply_mod._api_key_warned = set()
    yield
    serply_mod._api_key_warned = set()


def _patch_config(extra: dict | None):
    """Patch get_app_config so web_search resolves to a tool config with ``extra``."""
    patcher = patch("deerflow.community.serply.tools.get_app_config")
    mock = patcher.start()
    if extra is None:
        mock.return_value.get_tool_config.return_value = None
    else:
        tool_config = MagicMock()
        tool_config.model_extra = extra
        mock.return_value.get_tool_config.return_value = tool_config
    return patcher, mock


@pytest.fixture
def mock_config_with_key():
    patcher, mock = _patch_config({"api_key": "test-serply-key", "max_results": 5})
    yield mock
    patcher.stop()


@pytest.fixture
def mock_config_no_key():
    patcher, mock = _patch_config({})
    yield mock
    patcher.stop()


def _make_response(payload: object) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _search_rows(n: int) -> list[dict]:
    return [{"title": f"Result {i}", "link": f"https://example.com/{i}", "description": f"Snippet {i}", "position": i} for i in range(1, n + 1)]


def _run(query: str = "test query", max_results: int = 5) -> dict:
    from deerflow.community.serply.tools import web_search_tool

    return json.loads(web_search_tool.invoke({"query": query, "max_results": max_results}))


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        patcher, _ = _patch_config({"api_key": "from-config"})
        try:
            from deerflow.community.serply.tools import _get_api_key

            assert _get_api_key("web_search") == "from-config"
        finally:
            patcher.stop()

    def test_falls_back_to_env_when_config_key_blank(self):
        patcher, _ = _patch_config({"api_key": "   "})
        try:
            with patch.dict("os.environ", {"SERPLY_API_KEY": "env-key"}):
                from deerflow.community.serply.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"
        finally:
            patcher.stop()

    def test_falls_back_to_env_when_no_config(self):
        patcher, _ = _patch_config(None)
        try:
            with patch.dict("os.environ", {"SERPLY_API_KEY": "env-only"}):
                from deerflow.community.serply.tools import _get_api_key

                assert _get_api_key("web_search") == "env-only"
        finally:
            patcher.stop()

    def test_returns_none_when_no_key_anywhere(self):
        patcher, _ = _patch_config(None)
        try:
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.serply.tools import _get_api_key

                assert _get_api_key("web_search") is None
        finally:
            patcher.stop()


class TestCoerceMaxResults:
    def test_returns_value_when_valid(self):
        from deerflow.community.serply.tools import _coerce_max_results

        assert _coerce_max_results(3) == 3
        assert _coerce_max_results("7") == 7

    def test_caps_at_serply_maximum(self):
        from deerflow.community.serply.tools import _coerce_max_results

        assert _coerce_max_results(999) == 100

    def test_invalid_values_fall_back_to_default(self):
        from deerflow.community.serply.tools import _coerce_max_results

        assert _coerce_max_results("oops") == 5
        assert _coerce_max_results(None) == 5
        assert _coerce_max_results(0) == 5
        assert _coerce_max_results(-3) == 5


class TestCoerceVertical:
    def test_accepts_known_verticals(self):
        from deerflow.community.serply.tools import _coerce_vertical

        assert _coerce_vertical(None) == "search"
        assert _coerce_vertical("news") == "news"
        assert _coerce_vertical(" Scholar ") == "scholar"

    def test_unknown_vertical_falls_back_to_search(self, caplog):
        from deerflow.community.serply.tools import _coerce_vertical

        with caplog.at_level(logging.WARNING):
            assert _coerce_vertical("images") == "search"
        assert "Invalid Serply vertical" in caplog.text


class TestWebSearchTool:
    def test_basic_search_returns_normalized_results(self, mock_config_with_key):
        with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"results": _search_rows(2)})
            result = _run("test query")

        assert result["query"] == "test query"
        assert result["total_results"] == 2
        assert result["results"][0] == {"title": "Result 1", "url": "https://example.com/1", "content": "Snippet 1"}

    def test_sends_correct_headers_and_params(self, mock_config_with_key):
        with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
            mock_get = mock_client.return_value.__enter__.return_value.get
            mock_get.return_value = _make_response({"results": _search_rows(1)})
            _run("  padded query  ")

        args, kwargs = mock_get.call_args
        assert args[0] == "https://api.serply.io/v1/search/"
        assert kwargs["headers"]["X-Api-Key"] == "test-serply-key"
        assert kwargs["headers"]["Accept"] == "application/json"
        assert kwargs["params"] == {"q": "padded query", "num": 5}

    def test_config_max_results_overrides_parameter(self):
        patcher, _ = _patch_config({"api_key": "k", "max_results": 2})
        try:
            with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
                mock_get = mock_client.return_value.__enter__.return_value.get
                mock_get.return_value = _make_response({"results": _search_rows(5)})
                result = _run("q", max_results=5)
        finally:
            patcher.stop()

        assert mock_get.call_args.kwargs["params"]["num"] == 2
        assert result["total_results"] == 2

    def test_passes_through_locale_params_from_config(self):
        patcher, _ = _patch_config({"api_key": "k", "gl": "fr", "hl": "fr", "ignored": "x"})
        try:
            with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
                mock_get = mock_client.return_value.__enter__.return_value.get
                mock_get.return_value = _make_response({"results": _search_rows(1)})
                _run("q")
        finally:
            patcher.stop()

        params = mock_get.call_args.kwargs["params"]
        assert params["gl"] == "fr"
        assert params["hl"] == "fr"
        assert "ignored" not in params

    def test_news_vertical_uses_news_endpoint_and_trims_client_side(self):
        entries = [
            {
                "title": f"Story {i}",
                "link": f"https://news.example.com/{i}",
                "summary": "<a href='x'>Genuine&nbsp;attention</a> &amp; chatbots",
                "published": "Mon, 01 Jun 2026 08:00:00 GMT",
                "source": {"title": "Example Times"},
            }
            for i in range(10)
        ]
        patcher, _ = _patch_config({"api_key": "k", "max_results": 3, "vertical": "news"})
        try:
            with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
                mock_get = mock_client.return_value.__enter__.return_value.get
                mock_get.return_value = _make_response({"entries": entries})
                result = _run("q")
        finally:
            patcher.stop()

        assert mock_get.call_args.args[0] == "https://api.serply.io/v1/news/"
        assert result["total_results"] == 3
        first = result["results"][0]
        assert first["content"] == "Genuine\xa0attention & chatbots"
        assert first["published"] == "Mon, 01 Jun 2026 08:00:00 GMT"
        assert first["source"] == "Example Times"

    def test_scholar_vertical_maps_authors_and_citations(self):
        articles = [
            {
                "title": "Attention Is All You Need",
                "link": "https://arxiv.org/abs/1706.03762",
                "description": "The dominant sequence transduction models...",
                "author": {
                    "names": "A Vaswani, N Shazeer - NeurIPS, 2017",
                    "authors": [{"name": "A Vaswani", "link": "https://openalex.org/A1"}, {"name": "N Shazeer", "link": "https://openalex.org/A2"}],
                },
                "extras": {"citations": {"count": 120000}},
                "doc": {"link": "https://arxiv.org/pdf/1706.03762", "type": "PDF"},
            },
            {"title": "No metadata", "link": "https://example.org/paper"},
        ]
        patcher, _ = _patch_config({"api_key": "k", "vertical": "scholar"})
        try:
            with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
                mock_get = mock_client.return_value.__enter__.return_value.get
                mock_get.return_value = _make_response({"articles": articles})
                result = _run("transformers")
        finally:
            patcher.stop()

        assert mock_get.call_args.args[0] == "https://api.serply.io/v1/scholar/"
        assert result["results"][0]["authors"] == ["A Vaswani", "N Shazeer"]
        assert result["results"][0]["cited_by"] == 120000
        assert result["results"][0]["pdf_url"] == "https://arxiv.org/pdf/1706.03762"
        assert result["results"][1] == {"title": "No metadata", "url": "https://example.org/paper", "content": "", "authors": [], "cited_by": 0, "pdf_url": ""}

    def test_empty_results_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"results": []})
            assert _run("nothing") == {"error": "No results found", "query": "nothing"}

    def test_missing_results_key_is_treated_as_no_results(self, mock_config_with_key):
        with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"results": None})
            assert _run("nothing")["error"] == "No results found"

    def test_unexpected_payload_shape_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"results": "not-a-list"})
            assert "unexpected response format" in _run("q")["error"]

        with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response(["not", "a", "dict"])
            assert "unexpected response format" in _run("q")["error"]

    def test_missing_api_key_returns_error_json_and_warns_once(self, mock_config_no_key, caplog):
        with patch.dict("os.environ", {}, clear=True), caplog.at_level(logging.WARNING):
            first = _run("q")
            second = _run("q")

        assert first == {"error": "SERPLY_API_KEY is not configured", "query": "q"}
        assert second == first
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "SERPLY_API_KEY" in warnings[0].getMessage()

    def test_http_error_returns_structured_error(self, mock_config_with_key):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_resp)
        with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
            result = _run("q")

        assert result == {"error": "Serply API error: HTTP 403", "query": "q"}

    def test_network_exception_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError("boom")
            result = _run("q")

        assert result == {"error": "boom", "query": "q"}

    def test_long_query_is_truncated(self, mock_config_with_key):
        with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
            mock_get = mock_client.return_value.__enter__.return_value.get
            mock_get.return_value = _make_response({"results": _search_rows(1)})
            _run("x" * 600)

        assert len(mock_get.call_args.kwargs["params"]["q"]) == 500

    def test_uses_env_key_when_config_absent(self):
        patcher, _ = _patch_config(None)
        try:
            with patch.dict("os.environ", {"SERPLY_API_KEY": "env-key"}):
                with patch("deerflow.community.serply.tools.httpx.Client") as mock_client:
                    mock_get = mock_client.return_value.__enter__.return_value.get
                    mock_get.return_value = _make_response({"results": _search_rows(1)})
                    result = _run("q")
        finally:
            patcher.stop()

        assert result["total_results"] == 1
        assert mock_get.call_args.kwargs["headers"]["X-Api-Key"] == "env-key"
