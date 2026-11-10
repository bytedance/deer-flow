"""Unit tests for the Autom community web search tool."""

import json
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the module-level warning flag before each test."""
    import deerflow.community.autom.tools as autom_mod

    autom_mod._api_key_warned = set()
    yield
    autom_mod._api_key_warned = set()


def _patch_config(extra: dict | None):
    """Patch get_app_config so web_search resolves to a tool config with ``extra``."""
    patcher = patch("deerflow.community.autom.tools.get_app_config")
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
    patcher, mock = _patch_config({"api_key": "test-autom-key", "max_results": 5})
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


def _run(query: str = "test query", max_results: int = 5, **kwargs) -> dict:
    from deerflow.community.autom.tools import web_search_tool

    return json.loads(web_search_tool.invoke({"query": query, "max_results": max_results, **kwargs}))


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        patcher, _ = _patch_config({"api_key": "from-config"})
        try:
            from deerflow.community.autom.tools import _get_api_key

            assert _get_api_key("web_search") == "from-config"
        finally:
            patcher.stop()

    def test_falls_back_to_env_when_config_key_blank(self):
        patcher, _ = _patch_config({"api_key": "   "})
        try:
            with patch.dict("os.environ", {"AUTOM_API_KEY": "env-key"}):
                from deerflow.community.autom.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"
        finally:
            patcher.stop()

    def test_strips_trailing_newline_from_file_based_key(self):
        patcher, _ = _patch_config({"api_key": "from-file\n"})
        try:
            from deerflow.community.autom.tools import _get_api_key

            assert _get_api_key("web_search") == "from-file"
        finally:
            patcher.stop()

    def test_falls_back_to_env_when_no_config(self):
        patcher, _ = _patch_config(None)
        try:
            with patch.dict("os.environ", {"AUTOM_API_KEY": "env-only"}):
                from deerflow.community.autom.tools import _get_api_key

                assert _get_api_key("web_search") == "env-only"
        finally:
            patcher.stop()

    def test_returns_none_when_no_key_anywhere(self):
        patcher, _ = _patch_config(None)
        try:
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.autom.tools import _get_api_key

                assert _get_api_key("web_search") is None
        finally:
            patcher.stop()


class TestCountForRequest:
    def test_returns_value_when_valid(self):
        from deerflow.community.autom.tools import _count_for_request

        assert _count_for_request(3) == 3
        assert _count_for_request("7") == 7

    def test_caps_at_autom_page_size(self):
        from deerflow.community.autom.tools import _count_for_request

        assert _count_for_request(999) == 10

    @pytest.mark.parametrize(
        "raw",
        ["oops", None, 0, -3, True, False, 3.5, float("inf")],
        ids=["invalid-string", "none", "zero", "negative", "true", "false", "non-integral-float", "yaml-inf"],
    )
    def test_invalid_values_fall_back_to_default(self, raw):
        from deerflow.community.autom.tools import _count_for_request

        assert _count_for_request(raw) == 5


class TestCoerceVertical:
    def test_accepts_known_verticals(self):
        from deerflow.community.autom.tools import _coerce_vertical

        assert _coerce_vertical(None) == "search"
        assert _coerce_vertical(" News ") == "news"

    def test_unknown_vertical_falls_back_to_search(self, caplog):
        from deerflow.community.autom.tools import _coerce_vertical

        with caplog.at_level(logging.WARNING):
            assert _coerce_vertical("images") == "search"
        assert "Invalid Autom vertical" in caplog.text


class TestWebSearchTool:
    def test_basic_search_returns_normalized_results(self, mock_config_with_key):
        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"organic_results": _search_rows(2)})
            result = _run("test query")

        assert result["query"] == "test query"
        assert result["total_results"] == 2
        assert result["results"][0] == {"title": "Result 1", "url": "https://example.com/1", "content": "Snippet 1"}

    def test_sends_correct_headers_and_params(self, mock_config_with_key):
        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_get = mock_client.return_value.__enter__.return_value.get
            mock_get.return_value = _make_response({"organic_results": _search_rows(1)})
            _run("  padded query  ")

        args, kwargs = mock_get.call_args
        assert args[0] == "https://api.autom.dev/v1/google/search"
        assert kwargs["headers"]["x-api-key"] == "test-autom-key"
        assert kwargs["headers"]["Accept"] == "application/json"
        assert kwargs["params"] == {"query": "padded query"}

    def test_max_results_trims_client_side(self):
        patcher, _ = _patch_config({"api_key": "k", "max_results": 2})
        try:
            with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
                mock_get = mock_client.return_value.__enter__.return_value.get
                mock_get.return_value = _make_response({"organic_results": _search_rows(8)})
                result = _run("q", max_results=5)
        finally:
            patcher.stop()

        assert "num" not in mock_get.call_args.kwargs["params"]
        assert result["total_results"] == 2

    def test_passes_through_locale_params_from_config(self):
        patcher, _ = _patch_config({"api_key": "k", "gl": "fr", "hl": "fr", "tbs": "qdr:w", "ignored": "x"})
        try:
            with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
                mock_get = mock_client.return_value.__enter__.return_value.get
                mock_get.return_value = _make_response({"organic_results": _search_rows(1)})
                _run("q")
        finally:
            patcher.stop()

        params = mock_get.call_args.kwargs["params"]
        assert params["gl"] == "fr"
        assert params["hl"] == "fr"
        assert params["tbs"] == "qdr:w"
        assert "ignored" not in params

    @pytest.mark.parametrize(("time_range", "tbs"), [("day", "qdr:d"), ("week", "qdr:w"), ("month", "qdr:m"), ("year", "qdr:y")])
    def test_time_range_maps_to_tbs(self, mock_config_with_key, time_range, tbs):
        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_get = mock_client.return_value.__enter__.return_value.get
            mock_get.return_value = _make_response({"organic_results": _search_rows(1)})
            _run("q", time_range=time_range)

        assert mock_get.call_args.kwargs["params"]["tbs"] == tbs

    def test_time_range_wins_over_configured_tbs(self):
        patcher, _ = _patch_config({"api_key": "k", "tbs": "qdr:y"})
        try:
            with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
                mock_get = mock_client.return_value.__enter__.return_value.get
                mock_get.return_value = _make_response({"organic_results": _search_rows(1)})
                _run("q", time_range="day")
        finally:
            patcher.stop()

        assert mock_get.call_args.kwargs["params"]["tbs"] == "qdr:d"

    def test_news_vertical_uses_news_endpoint_and_maps_source(self):
        rows = [{"position": i, "title": f"Story {i}", "link": f"https://news.example.com/{i}", "source": "Example Times", "snippet": "Body", "date": "2 hours ago"} for i in range(1, 6)]
        patcher, _ = _patch_config({"api_key": "k", "max_results": 3, "vertical": "news"})
        try:
            with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
                mock_get = mock_client.return_value.__enter__.return_value.get
                mock_get.return_value = _make_response({"organic_results": rows})
                result = _run("q")
        finally:
            patcher.stop()

        assert mock_get.call_args.args[0] == "https://api.autom.dev/v1/google/news"
        assert result["total_results"] == 3
        assert result["results"][0] == {
            "title": "Story 1",
            "url": "https://news.example.com/1",
            "content": "Body",
            "source": "Example Times",
            "published": "2 hours ago",
        }

    def test_empty_results_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"organic_results": []})
            assert _run("nothing") == {"error": "No results found", "query": "nothing"}

    def test_missing_results_key_is_treated_as_no_results(self, mock_config_with_key):
        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"search_parameters": {"query": "nothing"}})
            assert _run("nothing")["error"] == "No results found"

    def test_unexpected_payload_shape_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"organic_results": "not-a-list"})
            assert "unexpected response format" in _run("q")["error"]

        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response(["not", "a", "dict"])
            assert "unexpected response format" in _run("q")["error"]

    @pytest.mark.parametrize("rows", [["junk", "more junk"], [None, None], [1, 2], [[]], [False]])
    def test_rows_without_any_objects_return_format_error(self, mock_config_with_key, rows, caplog):
        """A non-empty rows container holding no objects is malformed, not an empty search."""
        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"organic_results": rows})

            with caplog.at_level(logging.ERROR):
                result = _run("q")

        assert "unexpected response format" in result["error"]
        assert any("no usable result objects" in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)

    def test_mixed_rows_keep_the_object_entries(self, mock_config_with_key):
        rows = ["junk", {"title": "Kept", "link": "https://example.com/kept", "snippet": "Body"}, 7]

        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"organic_results": rows})
            result = _run("q")

        assert result["total_results"] == 1
        assert result["results"][0] == {"title": "Kept", "url": "https://example.com/kept", "content": "Body"}

    def test_non_string_snippet_becomes_empty_content(self, mock_config_with_key):
        rows = [{"title": "T", "link": "https://example.com/t", "snippet": {"html": "x"}}]

        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"organic_results": rows})
            result = _run("q")

        assert result["results"][0]["content"] == ""

    def test_missing_api_key_returns_error_json_and_warns_once(self, mock_config_no_key, caplog):
        with patch.dict("os.environ", {}, clear=True), caplog.at_level(logging.WARNING):
            first = _run("q")
            second = _run("q")

        assert first == {"error": "AUTOM_API_KEY is not configured", "query": "q"}
        assert second == first
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "AUTOM_API_KEY" in warnings[0].getMessage()

    def test_http_error_returns_structured_error(self, mock_config_with_key):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("401", request=MagicMock(), response=mock_resp)
        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
            result = _run("q")

        assert result == {"error": "Autom API error: HTTP 401", "query": "q"}

    def test_network_exception_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError("boom")
            result = _run("q")

        assert result == {"error": "boom", "query": "q"}

    def test_error_text_never_carries_the_key(self, mock_config_with_key):
        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError("bad header test-autom-key")
            result = _run("q")

        assert "test-autom-key" not in result["error"]
        assert "[REDACTED]" in result["error"]

    def test_long_query_is_truncated(self, mock_config_with_key):
        with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
            mock_get = mock_client.return_value.__enter__.return_value.get
            mock_get.return_value = _make_response({"organic_results": _search_rows(1)})
            _run("x" * 600)

        assert len(mock_get.call_args.kwargs["params"]["query"]) == 500

    def test_uses_env_key_when_config_absent(self):
        patcher, _ = _patch_config(None)
        try:
            with patch.dict("os.environ", {"AUTOM_API_KEY": "env-key"}):
                with patch("deerflow.community.autom.tools.httpx.Client") as mock_client:
                    mock_get = mock_client.return_value.__enter__.return_value.get
                    mock_get.return_value = _make_response({"organic_results": _search_rows(1)})
                    result = _run("q")
        finally:
            patcher.stop()

        assert result["total_results"] == 1
        assert mock_get.call_args.kwargs["headers"]["x-api-key"] == "env-key"
