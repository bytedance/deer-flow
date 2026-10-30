"""Unit tests for the Desearch community web search tool."""

import json
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the module-level warning flag before each test."""
    import deerflow.community.desearch.tools as desearch_mod

    desearch_mod._api_key_warned = set()
    yield
    desearch_mod._api_key_warned = set()


def _patch_config(extra: dict | None):
    """Patch get_app_config so web_search resolves to a tool config with ``extra``."""
    patcher = patch("deerflow.community.desearch.tools.get_app_config")
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
    patcher, mock = _patch_config({"api_key": "test-desearch-key", "max_results": 5})
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
    return [{"title": f"Result {i}", "link": f"https://example.com/{i}", "snippet": f"Snippet {i}", "highlights": None, "text": None} for i in range(1, n + 1)]


def _run(query: str = "test query", max_results: int = 5) -> dict:
    from deerflow.community.desearch.tools import web_search_tool

    return json.loads(web_search_tool.invoke({"query": query, "max_results": max_results}))


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        patcher, _ = _patch_config({"api_key": "from-config"})
        try:
            from deerflow.community.desearch.tools import _get_api_key

            with patch.dict("os.environ", {"DESEARCH_API_KEY": "from-env"}):
                assert _get_api_key("web_search") == "from-config"
        finally:
            patcher.stop()

    def test_falls_back_to_env_when_config_key_blank(self):
        patcher, _ = _patch_config({"api_key": "   "})
        try:
            with patch.dict("os.environ", {"DESEARCH_API_KEY": "env-key"}):
                from deerflow.community.desearch.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"
        finally:
            patcher.stop()

    def test_falls_back_to_env_when_no_config(self):
        patcher, _ = _patch_config(None)
        try:
            with patch.dict("os.environ", {"DESEARCH_API_KEY": "env-only"}):
                from deerflow.community.desearch.tools import _get_api_key

                assert _get_api_key("web_search") == "env-only"
        finally:
            patcher.stop()

    def test_returns_none_when_no_key_anywhere(self):
        patcher, _ = _patch_config(None)
        try:
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.desearch.tools import _get_api_key

                assert _get_api_key("web_search") is None
        finally:
            patcher.stop()


@pytest.mark.parametrize(
    "value, expected",
    [(3, 3), ("7", 7), (4.0, 4), (True, 5), (False, 5), (3.5, 5), ("oops", 5), (None, 5), (0, 5), (-3, 5), (float("inf"), 5), (float("-inf"), 5), (float("nan"), 5), (999, 10)],
)
def test_configured_result_count_uses_shared_coercion(value, expected, mock_config_with_key, caplog):
    mock_config_with_key.return_value.get_tool_config.return_value.model_extra["max_results"] = value
    with patch("deerflow.community.desearch.tools.httpx.Client") as client, caplog.at_level(logging.WARNING):
        client.return_value.__enter__.return_value.get.return_value = _make_response({"data": _search_rows(25)})
        assert _run()["total_results"] == expected
    if expected == 5:
        assert len(caplog.records) == 1
        assert caplog.records[0].name == "deerflow.community.desearch.tools"
        assert "Invalid Desearch max_results=" in caplog.text


class TestWebSearchTool:
    def test_basic_search_returns_normalized_results(self, mock_config_with_key):
        with patch("deerflow.community.desearch.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"data": _search_rows(2)})
            result = _run("test query")

        assert result["query"] == "test query"
        assert result["total_results"] == 2
        assert result["results"][0] == {"title": "Result 1", "url": "https://example.com/1", "content": "Snippet 1"}

    def test_sends_correct_headers_and_params(self, mock_config_with_key):
        with patch("deerflow.community.desearch.tools.httpx.Client") as mock_client:
            mock_get = mock_client.return_value.__enter__.return_value.get
            mock_get.return_value = _make_response({"data": _search_rows(1)})
            _run("  padded query  ")

        args, kwargs = mock_get.call_args
        assert args[0] == "https://api.desearch.ai/web"
        assert kwargs["headers"]["Authorization"] == "test-desearch-key"
        assert kwargs["headers"]["Accept"] == "application/json"
        assert kwargs["params"] == {"query": "padded query"}

    def test_config_max_results_overrides_parameter(self):
        patcher, _ = _patch_config({"api_key": "k", "max_results": 2})
        try:
            with patch("deerflow.community.desearch.tools.httpx.Client") as mock_client:
                mock_get = mock_client.return_value.__enter__.return_value.get
                mock_get.return_value = _make_response({"data": _search_rows(5)})
                result = _run("q", max_results=5)
        finally:
            patcher.stop()

        assert mock_get.call_args.kwargs["params"] == {"query": "q"}
        assert result["total_results"] == 2

    def test_empty_results_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.desearch.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"data": []})
            assert _run("nothing") == {"error": "No results found", "query": "nothing"}

    def test_missing_results_key_is_treated_as_no_results(self, mock_config_with_key):
        with patch("deerflow.community.desearch.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"data": None})
            assert _run("nothing")["error"] == "No results found"

    def test_unexpected_payload_shape_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.desearch.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"data": "not-a-list"})
            assert "unexpected response format" in _run("q")["error"]

        with patch("deerflow.community.desearch.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response(["not", "a", "dict"])
            assert "unexpected response format" in _run("q")["error"]

    @pytest.mark.parametrize("rows", [["junk", "more junk"], [None, None], [1, 2], [[]], [False]])
    def test_rows_without_any_objects_return_format_error(self, mock_config_with_key, rows, caplog):
        """A non-empty rows container holding no objects is malformed, not an empty search.

        Reporting "No results found" for it would tell the agent the query
        legitimately matched nothing, hiding a broken upstream payload.
        """
        with patch("deerflow.community.desearch.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"data": rows})

            with caplog.at_level(logging.ERROR):
                result = _run("q")

        assert "unexpected response format" in result["error"]
        assert any("no usable result objects" in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)

    def test_mixed_rows_keep_the_object_entries(self, mock_config_with_key):
        rows = ["junk", {"title": "Kept", "link": "https://example.com/kept", "snippet": "Body"}, 7]

        with patch("deerflow.community.desearch.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = _make_response({"data": rows})
            result = _run("q")

        assert result["total_results"] == 1
        assert result["results"][0] == {"title": "Kept", "url": "https://example.com/kept", "content": "Body"}

    def test_missing_api_key_returns_error_json_and_warns_once(self, mock_config_no_key, caplog):
        with patch.dict("os.environ", {}, clear=True), caplog.at_level(logging.WARNING):
            first = _run("q")
            second = _run("q")

        assert first == {"error": "DESEARCH_API_KEY is not configured", "query": "q"}
        assert second == first
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "DESEARCH_API_KEY" in warnings[0].getMessage()

    def test_http_error_returns_structured_error(self, mock_config_with_key):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_resp)
        with patch("deerflow.community.desearch.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
            result = _run("q")

        assert result == {"error": "Desearch API error: HTTP 403", "query": "q"}

    def test_network_exception_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.desearch.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError("boom")
            result = _run("q")

        assert result == {"error": "boom", "query": "q"}

    def test_long_query_is_truncated(self, mock_config_with_key):
        with patch("deerflow.community.desearch.tools.httpx.Client") as mock_client:
            mock_get = mock_client.return_value.__enter__.return_value.get
            mock_get.return_value = _make_response({"data": _search_rows(1)})
            _run("x" * 600)

        assert len(mock_get.call_args.kwargs["params"]["query"]) == 500

    def test_uses_env_key_when_config_absent(self):
        patcher, _ = _patch_config(None)
        try:
            with patch.dict("os.environ", {"DESEARCH_API_KEY": "env-key"}):
                with patch("deerflow.community.desearch.tools.httpx.Client") as mock_client:
                    mock_get = mock_client.return_value.__enter__.return_value.get
                    mock_get.return_value = _make_response({"data": _search_rows(1)})
                    result = _run("q")
        finally:
            patcher.stop()

        assert result["total_results"] == 1
        assert mock_get.call_args.kwargs["headers"]["Authorization"] == "env-key"


@pytest.mark.parametrize(
    "payload, code, message",
    [
        ({"error_code": "upstream_empty"}, "upstream_empty", None),
        ({"error_code": "upstream_failed", "detail": "Unavailable"}, "upstream_failed", "Unavailable"),
        ({"error_code": "upstream_timeout", "detail": "Timed out"}, "upstream_timeout", "Timed out"),
        ({"error_code": "something_new"}, "something_new", None),
        ({"detail": "Unavailable"}, None, "Unavailable"),
        ({"error_code": 123}, None, None),
        ({"detail": {"error_code": "upstream_timeout", "message": "Nested timeout"}}, "upstream_timeout", "Nested timeout"),
        ({"error_code": "upstream_failed", "detail": {"error_code": "upstream_empty", "message": "Top wins"}}, "upstream_failed", "Top wins"),
        ({"detail": {"message": 123}}, None, None),
        ([], None, None),
        ({"detail": "x" * 600}, None, "x" * 500),
    ],
)
def test_503_error_details(mock_config_with_key, payload, code, message, caplog):
    response = httpx.Response(503, json=payload, request=httpx.Request("GET", "https://api.desearch.ai/web"))
    with patch("deerflow.community.desearch.tools.httpx.Client") as client, caplog.at_level(logging.ERROR):
        client.return_value.__enter__.return_value.get.return_value = response
        result = _run("nothing")
    if code == "upstream_empty":
        assert result == {"error": "No results found", "query": "nothing"}
    else:
        assert result == {"error": "Desearch API error: HTTP 503", "error_code": code, "message": message, "query": "nothing"}
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.ERROR
        assert caplog.records[0].args == (503, code, message)


@pytest.mark.parametrize("body", [b"", b"not JSON"])
def test_503_non_json_body(mock_config_with_key, body):
    response = httpx.Response(503, content=body, request=httpx.Request("GET", "https://api.desearch.ai/web"))
    with patch("deerflow.community.desearch.tools.httpx.Client") as client:
        client.return_value.__enter__.return_value.get.return_value = response
        assert _run("q") == {"error": "Desearch API error: HTTP 503", "error_code": None, "message": None, "query": "q"}


@pytest.mark.parametrize("nested", [False, True])
def test_503_redacts_api_key(mock_config_with_key, caplog, nested):
    message = "x" * 490 + "test-desearch-key echoed"
    detail = {"message": message} if nested else message
    response = httpx.Response(503, json={"error_code": "upstream_failed", "detail": detail}, request=httpx.Request("GET", "https://api.desearch.ai/web"))
    with patch("deerflow.community.desearch.tools.httpx.Client") as client, caplog.at_level(logging.ERROR):
        client.return_value.__enter__.return_value.get.return_value = response
        result = _run("q")
    assert result["message"] == ("x" * 490 + "[redacted] echoed")[:500]
    assert "test-desearch-key" not in json.dumps(result)
    assert "test-desearch-key" not in caplog.text
    assert result["message"] in caplog.text


@pytest.mark.parametrize("count, expected", [(0, 5), (-9, 5), (1, 1), (10, 10), (20, 10), (50, 10)])
def test_result_count_is_clamped_locally(mock_config_no_key, count, expected):
    with patch.dict("os.environ", {"DESEARCH_API_KEY": "key"}), patch("deerflow.community.desearch.tools.httpx.Client") as client:
        get = client.return_value.__enter__.return_value.get
        get.return_value = _make_response({"data": _search_rows(25)})
        result = _run("q", count)
        assert result["total_results"] == expected
        get.assert_called_once()
        assert get.call_args.kwargs["params"] == {"query": "q"}


def test_blank_query_does_not_send_request(mock_config_with_key):
    with patch("deerflow.community.desearch.tools.httpx.Client") as client:
        assert _run("   ") == {"error": "Query must not be blank", "query": ""}
        client.assert_not_called()


def test_only_supported_parameters_are_sent(mock_config_with_key):
    mock_config_with_key.return_value.get_tool_config.return_value.model_extra.update({"time_range": "day", "domains": ["example.com"], "count": 1})
    with patch("deerflow.community.desearch.tools.httpx.Client") as client:
        get = client.return_value.__enter__.return_value.get
        get.return_value = _make_response({"data": _search_rows(1)})
        _run()
        assert get.call_args.kwargs["params"] == {"query": "test query"}
        client.assert_called_once_with(timeout=30)


def test_invalid_json_returns_structured_error(mock_config_with_key):
    with patch("deerflow.community.desearch.tools.httpx.Client") as client:
        response = _make_response(None)
        response.json.side_effect = ValueError("Invalid JSON")
        client.return_value.__enter__.return_value.get.return_value = response
        assert _run("q") == {"error": "Invalid JSON", "query": "q"}


@pytest.mark.parametrize("url", ["http://127.0.0.1/private", "http://localhost/a", "javascript:alert(1)", "file:///etc/passwd"])
def test_unsafe_result_url_is_screened(mock_config_with_key, url):
    with patch("deerflow.community.desearch.tools.httpx.Client") as client:
        client.return_value.__enter__.return_value.get.return_value = _make_response({"data": [{"title": "t", "link": url, "snippet": "s"}]})
        assert _run()["results"][0] == {"title": "t", "url": "", "content": "s"}


def test_default_count_and_package_export(mock_config_no_key):
    from deerflow.community.desearch import web_search_tool

    with patch.dict("os.environ", {"DESEARCH_API_KEY": "key"}), patch("deerflow.community.desearch.tools.httpx.Client") as client:
        client.return_value.__enter__.return_value.get.return_value = _make_response({"data": _search_rows(20)})
        result = json.loads(web_search_tool.invoke({"query": "q"}))
        assert result["total_results"] == 5
