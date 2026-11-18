"""Unit tests for the SearchApi community web search tool."""

import json
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the module-level warning flag before each test."""
    import deerflow.community.searchapi.tools as searchapi_mod

    searchapi_mod._api_key_warned = set()
    yield
    searchapi_mod._api_key_warned = set()


def _patch_config(extra: dict | None):
    """Patch get_app_config so web_search resolves to a tool config with ``extra``."""
    patcher = patch("deerflow.community.searchapi.tools.get_app_config")
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
    patcher, mock = _patch_config({"api_key": "test-searchapi-key", "max_results": 5})
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
    return [{"position": i, "title": f"Result {i}", "link": f"https://example.com/{i}", "snippet": f"Snippet {i}"} for i in range(1, n + 1)]


def _run(query: str = "test query", max_results: int = 5, time_range: str | None = None) -> dict:
    from deerflow.community.searchapi.tools import web_search_tool

    args: dict = {"query": query, "max_results": max_results}
    if time_range is not None:
        args["time_range"] = time_range
    return json.loads(web_search_tool.invoke(args))


ENDPOINT = "https://www.searchapi.io/api/v1/search"


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        patcher, _ = _patch_config({"api_key": "from-config"})
        try:
            from deerflow.community.searchapi.tools import _get_api_key

            assert _get_api_key("web_search") == "from-config"
        finally:
            patcher.stop()

    def test_falls_back_to_env_when_config_key_blank(self):
        patcher, _ = _patch_config({"api_key": "   "})
        try:
            with patch.dict("os.environ", {"SEARCHAPI_API_KEY": "env-key"}):
                from deerflow.community.searchapi.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"
        finally:
            patcher.stop()

    def test_falls_back_to_env_when_no_config(self):
        patcher, _ = _patch_config(None)
        try:
            with patch.dict("os.environ", {"SEARCHAPI_API_KEY": "env-key"}):
                from deerflow.community.searchapi.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"
        finally:
            patcher.stop()

    def test_returns_none_when_no_key_anywhere(self):
        patcher, _ = _patch_config({})
        try:
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.searchapi.tools import _get_api_key

                assert _get_api_key("web_search") is None
        finally:
            patcher.stop()


class TestCountForRequest:
    def test_returns_value_when_valid(self):
        from deerflow.community.searchapi.tools import _count_for_request

        assert _count_for_request(7) == 7
        assert _count_for_request("3") == 3

    def test_caps_at_searchapi_maximum(self):
        from deerflow.community.searchapi.tools import _count_for_request

        assert _count_for_request(500) == 100

    def test_invalid_values_fall_back_to_default(self, caplog):
        from deerflow.community.searchapi.tools import _count_for_request

        with caplog.at_level(logging.WARNING):
            assert _count_for_request("abc") == 5
            assert _count_for_request(0) == 5
            assert _count_for_request(True) == 5
        assert "Invalid SearchApi max_results" in caplog.text


class TestCoerceVertical:
    def test_accepts_known_verticals(self):
        from deerflow.community.searchapi.tools import _coerce_vertical

        assert _coerce_vertical(None) == "search"
        assert _coerce_vertical(" News ") == "news"
        assert _coerce_vertical("scholar") == "scholar"

    def test_unknown_vertical_falls_back_to_search(self, caplog):
        from deerflow.community.searchapi.tools import _coerce_vertical

        with caplog.at_level(logging.WARNING):
            assert _coerce_vertical("images") == "search"
        assert "Invalid SearchApi vertical" in caplog.text


class TestWebSearchTool:
    def test_basic_search_returns_normalized_results(self, mock_config_with_key):
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
            mock_get = mock_client.return_value.__enter__.return_value.get
            mock_get.return_value = _make_response({"organic_results": _search_rows(3)})
            result = _run("python")

        assert result["query"] == "python"
        assert result["total_results"] == 3
        assert result["results"][0] == {"title": "Result 1", "url": "https://example.com/1", "content": "Snippet 1"}

    def test_sends_bearer_header_and_google_engine(self, mock_config_with_key):
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
            mock_get = mock_client.return_value.__enter__.return_value.get
            mock_get.return_value = _make_response({"organic_results": _search_rows(1)})
            _run("python", max_results=5)

        assert mock_get.call_args.args[0] == ENDPOINT
        headers = mock_get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer test-searchapi-key"
        assert headers["User-Agent"] == "deerflow"
        params = mock_get.call_args.kwargs["params"]
        assert params == {"engine": "google", "q": "python", "num": 5}

    def test_config_max_results_overrides_parameter(self):
        patcher, _ = _patch_config({"api_key": "k", "max_results": 2})
        try:
            with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
                mock_get = mock_client.return_value.__enter__.return_value.get
                mock_get.return_value = _make_response({"organic_results": _search_rows(5)})
                result = _run("q", max_results=5)
        finally:
            patcher.stop()

        assert mock_get.call_args.kwargs["params"]["num"] == 2
        assert result["total_results"] == 2

    def test_passes_through_locale_params_from_config(self):
        patcher, _ = _patch_config({"api_key": "k", "gl": "br", "hl": "pt"})
        try:
            with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
                mock_get = mock_client.return_value.__enter__.return_value.get
                mock_get.return_value = _make_response({"organic_results": _search_rows(1)})
                _run("q")
        finally:
            patcher.stop()

        params = mock_get.call_args.kwargs["params"]
        assert params["gl"] == "br"
        assert params["hl"] == "pt"

    def test_time_range_maps_to_time_period(self, mock_config_with_key):
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
            mock_get = mock_client.return_value.__enter__.return_value.get
            mock_get.return_value = _make_response({"organic_results": _search_rows(1)})
            _run("q", time_range="week")

        assert mock_get.call_args.kwargs["params"]["time_period"] == "last_week"

    def test_time_range_is_omitted_without_a_window(self, mock_config_with_key):
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
            mock_get = mock_client.return_value.__enter__.return_value.get
            mock_get.return_value = _make_response({"organic_results": _search_rows(1)})
            _run("q")

        assert "time_period" not in mock_get.call_args.kwargs["params"]

    def test_news_vertical_uses_news_engine_and_trims_client_side(self):
        rows = [
            {
                "position": i,
                "title": f"Story {i}",
                "link": f"https://news.example.com/{i}",
                "snippet": f"Summary {i}",
                "source": "Example Times",
                "date": "2 days ago",
                "iso_date": "2026-10-21T07:00:00Z",
            }
            for i in range(10)
        ]
        patcher, _ = _patch_config({"api_key": "k", "max_results": 3, "vertical": "news"})
        try:
            with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
                mock_get = mock_client.return_value.__enter__.return_value.get
                mock_get.return_value = _make_response({"organic_results": rows})
                result = _run("q", time_range="day")
        finally:
            patcher.stop()

        params = mock_get.call_args.kwargs["params"]
        assert params["engine"] == "google_news"
        assert params["time_period"] == "last_day"
        assert result["total_results"] == 3
        first = result["results"][0]
        assert first["content"] == "Summary 0"
        assert first["published"] == "2026-10-21T07:00:00Z"
        assert first["source"] == "Example Times"

    def test_scholar_vertical_maps_authors_and_citations(self):
        rows = [
            {
                "title": "Attention Is All You Need",
                "link": "https://arxiv.org/abs/1706.03762",
                "snippet": "The dominant sequence transduction models...",
                "publication": "A Vaswani, N Shazeer - NeurIPS, 2017 - proceedings.neurips.cc",
                "authors": [{"name": "A Vaswani", "id": "a1"}, {"name": "N Shazeer", "id": "a2"}],
                "inline_links": {"cited_by": {"total": 120000, "link": "https://scholar.google.com/scholar?cites=1"}},
                "resource": {"name": "[PDF]", "link": "https://arxiv.org/pdf/1706.03762"},
            },
            {"title": "No metadata", "link": "https://example.org/paper", "resource": {"name": "[PDF]", "link": "javascript:void(0)"}},
            {"title": "Glued stub", "link": "https://example.org/other", "resource": {"name": "[PDF]", "link": "https://scholar.google.comjavascript:void(0)"}},
        ]
        patcher, _ = _patch_config({"api_key": "k", "vertical": "scholar"})
        try:
            with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
                mock_get = mock_client.return_value.__enter__.return_value.get
                mock_get.return_value = _make_response({"organic_results": rows})
                result = _run("transformers", time_range="year")
        finally:
            patcher.stop()

        params = mock_get.call_args.kwargs["params"]
        assert params["engine"] == "google_scholar"
        assert "time_period" not in params
        assert result["results"][0]["authors"] == ["A Vaswani", "N Shazeer"]
        assert result["results"][0]["cited_by"] == 120000
        assert result["results"][0]["pdf_url"] == "https://arxiv.org/pdf/1706.03762"
        assert result["results"][0]["publication"].startswith("A Vaswani")
        assert result["results"][1] == {
            "title": "No metadata",
            "url": "https://example.org/paper",
            "content": "",
            "authors": [],
            "publication": "",
            "cited_by": 0,
            "pdf_url": "",
        }
        assert result["results"][2]["pdf_url"] == ""

    def test_empty_results_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"organic_results": []})
            result = _run("q")

        assert result == {"error": "No results found", "query": "q"}

    def test_missing_results_key_is_treated_as_no_results(self, mock_config_with_key):
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"search_metadata": {"status": "Success"}})
            result = _run("q")

        assert result == {"error": "No results found", "query": "q"}

    def test_unexpected_payload_shape_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response(["not", "a", "dict"])
            result = _run("q")

        assert result == {"error": "SearchApi returned an unexpected response format", "query": "q"}

    def test_rows_without_any_objects_return_format_error(self, mock_config_with_key, caplog):
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client, caplog.at_level(logging.ERROR):
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"organic_results": ["x", 1]})
            result = _run("q")

        assert result == {"error": "SearchApi returned an unexpected response format", "query": "q"}
        assert "no usable result objects" in caplog.text

    def test_mixed_rows_keep_the_object_entries(self, mock_config_with_key):
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"organic_results": ["junk", *_search_rows(2), None]})
            result = _run("q")

        assert [r["title"] for r in result["results"]] == ["Result 1", "Result 2"]

    def test_non_list_results_return_format_error(self, mock_config_with_key):
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"organic_results": {"title": "x"}})
            result = _run("q")

        assert result == {"error": "SearchApi returned an unexpected response format", "query": "q"}

    def test_unsafe_result_url_is_dropped(self, mock_config_with_key):
        rows = [{"title": "Local", "link": "http://127.0.0.1/admin", "snippet": "s"}]
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"organic_results": rows})
            result = _run("q")

        assert result["results"][0]["url"] == ""

    def test_missing_api_key_returns_error_json_and_warns_once(self, mock_config_no_key, caplog):
        with patch.dict("os.environ", {}, clear=True), caplog.at_level(logging.WARNING):
            first = _run("q")
            second = _run("q")

        assert first == {"error": "SEARCHAPI_API_KEY is not configured", "query": "q"}
        assert second == first
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "SEARCHAPI_API_KEY" in warnings[0].getMessage()

    def test_http_error_returns_structured_error(self, mock_config_with_key):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = '{"error": "Invalid API key."}'
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("401", request=MagicMock(), response=mock_resp)
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
            result = _run("q")

        assert result == {"error": "SearchApi error: HTTP 401", "query": "q"}

    def test_network_exception_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError("boom")
            result = _run("q")

        assert result == {"error": "boom", "query": "q"}

    def test_long_query_is_truncated(self, mock_config_with_key):
        with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
            mock_get = mock_client.return_value.__enter__.return_value.get
            mock_get.return_value = _make_response({"organic_results": _search_rows(1)})
            _run("x" * 600)

        assert len(mock_get.call_args.kwargs["params"]["q"]) == 500

    def test_uses_env_key_when_config_absent(self):
        patcher, _ = _patch_config(None)
        try:
            with patch.dict("os.environ", {"SEARCHAPI_API_KEY": "env-key"}):
                with patch("deerflow.community.searchapi.tools.httpx.Client") as mock_client:
                    mock_get = mock_client.return_value.__enter__.return_value.get
                    mock_get.return_value = _make_response({"organic_results": _search_rows(1)})
                    result = _run("q")
        finally:
            patcher.stop()

        assert result["total_results"] == 1
        assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer env-key"
