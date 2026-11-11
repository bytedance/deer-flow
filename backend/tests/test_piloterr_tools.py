"""Unit tests for the Piloterr community web fetch tool."""

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

_PAGE = "<!doctype html><html><head><title>Example Domain</title></head><body><article><h1>Example Domain</h1><p>This domain is for use in documentation examples without needing permission.</p></article></body></html>"
_URL = "https://example.com/page"


def _patch_config(extra: dict | None):
    patcher = patch("deerflow.community.piloterr.tools.get_app_config")
    mock = patcher.start()
    if extra is None:
        mock.return_value.get_tool_config.return_value = None
    else:
        tool_config = MagicMock()
        tool_config.model_extra = extra
        mock.return_value.get_tool_config.return_value = tool_config
    return patcher


@pytest.fixture(autouse=True)
def public_url():
    """Keep the tests offline: the URL screen would otherwise resolve the host."""
    with patch("deerflow.community.piloterr.tools.validate_public_http_url", return_value=None) as mock:
        yield mock


@pytest.fixture
def config_with_key():
    patcher = _patch_config({"api_key": "test-piloterr-key"})
    yield
    patcher.stop()


def _response(status: int = 200, json_body: object = _PAGE, text: str | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    if isinstance(json_body, Exception):
        resp.json.side_effect = json_body
    else:
        resp.json.return_value = json_body
    resp.text = text if text is not None else ""
    return resp


def _fetch(url: str = _URL) -> str:
    from deerflow.community.piloterr.tools import web_fetch_tool

    return web_fetch_tool.invoke({"url": url})


def _client(mock_client: MagicMock) -> MagicMock:
    return mock_client.return_value.__enter__.return_value


class TestGetApiKey:
    def test_config_key_wins_and_is_stripped(self):
        from deerflow.community.piloterr.tools import _get_api_key

        with patch.dict("os.environ", {"PILOTERR_API_KEY": "env-key"}):
            assert _get_api_key({"api_key": "from-file\n"}) == "from-file"

    def test_blank_config_key_falls_back_to_env(self):
        from deerflow.community.piloterr.tools import _get_api_key

        with patch.dict("os.environ", {"PILOTERR_API_KEY": " env-key "}):
            assert _get_api_key({"api_key": "   "}) == "env-key"

    def test_none_when_missing(self):
        from deerflow.community.piloterr.tools import _get_api_key

        with patch.dict("os.environ", {}, clear=True):
            assert _get_api_key({}) is None


class TestCoercion:
    def test_engines(self, caplog):
        from deerflow.community.piloterr.tools import _coerce_engine

        assert _coerce_engine(None) == "crawler"
        assert _coerce_engine(" Rendering ") == "rendering"
        assert _coerce_engine("webunlocker") == "webunlocker"
        with caplog.at_level(logging.WARNING):
            assert _coerce_engine("browser") == "crawler"
        assert "Invalid Piloterr engine" in caplog.text

    @pytest.mark.parametrize(("raw", "expected"), [(None, 60), (True, 60), ("x", 60), (2.5, 60), (0, 1), (999, 300), ("90", 90)])
    def test_timeout(self, raw, expected):
        from deerflow.community.piloterr.tools import _coerce_int

        assert _coerce_int(raw, default=60, minimum=1, maximum=300) == expected


class TestWebFetchTool:
    def test_fetches_through_the_crawler_and_returns_markdown(self, config_with_key):
        with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
            _client(mock_client).get.return_value = _response()
            result = _fetch()

        args, kwargs = _client(mock_client).get.call_args
        assert args[0] == "https://api.piloterr.com/v2/website/crawler"
        assert kwargs["params"] == {"query": _URL}
        assert kwargs["headers"]["x-api-key"] == "test-piloterr-key"
        assert mock_client.call_args.kwargs["timeout"] == 60
        assert result.startswith("# Example Domain")
        assert "documentation examples" in result

    def test_output_is_capped(self, config_with_key):
        long_page = "<html><head><title>Long</title></head><body><article>" + "<p>word " * 5000 + "</article></body></html>"
        with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
            _client(mock_client).get.return_value = _response(json_body=long_page)
            result = _fetch()

        assert len(result) <= 4096

    def test_rendering_engine_and_wait(self):
        patcher = _patch_config({"api_key": "k", "engine": "rendering", "wait_in_seconds": 99, "timeout": 120})
        try:
            with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
                _client(mock_client).get.return_value = _response()
                _fetch()
        finally:
            patcher.stop()

        args, kwargs = _client(mock_client).get.call_args
        assert args[0] == "https://api.piloterr.com/v2/website/rendering"
        assert kwargs["params"] == {"query": _URL, "wait_in_seconds": 30}
        assert mock_client.call_args.kwargs["timeout"] == 120

    def test_wait_is_ignored_outside_rendering(self):
        patcher = _patch_config({"api_key": "k", "engine": "webunlocker", "wait_in_seconds": 5})
        try:
            with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
                _client(mock_client).get.return_value = _response()
                _fetch()
        finally:
            patcher.stop()

        args, kwargs = _client(mock_client).get.call_args
        assert args[0] == "https://api.piloterr.com/v2/website/webunlocker"
        assert kwargs["params"] == {"query": _URL}

    def test_raw_html_body_is_accepted(self, config_with_key):
        with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
            _client(mock_client).get.return_value = _response(json_body=ValueError("not json"), text=_PAGE)
            result = _fetch()

        assert result.startswith("# Example Domain")

    @pytest.mark.parametrize("body", [{"html": "<p>x</p>"}, ["a"], 3, None])
    def test_non_string_payload_is_a_format_error(self, config_with_key, body):
        with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
            _client(mock_client).get.return_value = _response(json_body=body)
            assert _fetch() == "Error: Piloterr returned an unexpected response format"

    def test_empty_page_is_no_content(self, config_with_key):
        with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
            _client(mock_client).get.return_value = _response(json_body="   ")
            assert _fetch() == "Error: No content found"

    def test_page_with_no_readable_text_explains_itself(self, config_with_key):
        with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
            _client(mock_client).get.return_value = _response(json_body="<html><head><script>var a = 1;</script><style>p{}</style></head><body></body></html>")
            result = _fetch()

        assert result.strip()
        assert "No content could be extracted from this page" in result

    def test_rejected_url_never_reaches_the_api(self, config_with_key, public_url):
        public_url.return_value = "Error: URL resolves to a blocked address"
        with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
            assert _fetch("http://169.254.169.254/latest") == "Error: URL resolves to a blocked address"
        mock_client.assert_not_called()

    def test_missing_key(self, caplog):
        patcher = _patch_config({})
        try:
            with patch.dict("os.environ", {}, clear=True), patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client, caplog.at_level(logging.WARNING):
                assert _fetch() == "Error: PILOTERR_API_KEY is not configured"
        finally:
            patcher.stop()
        mock_client.assert_not_called()
        assert "PILOTERR_API_KEY" in caplog.text

    def test_env_key_when_config_absent(self):
        patcher = _patch_config(None)
        try:
            with patch.dict("os.environ", {"PILOTERR_API_KEY": "env-key"}), patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
                _client(mock_client).get.return_value = _response()
                _fetch()
        finally:
            patcher.stop()

        assert _client(mock_client).get.call_args.kwargs["headers"]["x-api-key"] == "env-key"

    def test_http_error_carries_the_api_message_without_the_key(self, config_with_key):
        with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
            _client(mock_client).get.return_value = _response(status=401, json_body={"error": "Invalid key test-piloterr-key"})
            result = _fetch()

        assert result == "Error: Piloterr API error: HTTP 401: Invalid key [REDACTED]"

    def test_http_error_with_nested_message(self, config_with_key):
        with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
            _client(mock_client).get.return_value = _response(status=422, json_body={"error": {"code": "bad", "message": "Invalid URL"}})
            assert _fetch() == "Error: Piloterr API error: HTTP 422: Invalid URL"

    def test_credits_exhausted_names_the_fix(self, config_with_key):
        with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
            _client(mock_client).get.return_value = _response(status=402, json_body=ValueError("empty"))
            assert _fetch() == "Error: Piloterr API error: HTTP 402: Piloterr credits exhausted, check the plan or top up at https://www.piloterr.com"

    def test_rate_limit_keeps_the_api_message_and_adds_the_hint(self, config_with_key):
        with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
            _client(mock_client).get.return_value = _response(status=429, json_body={"error": "Too many requests"})
            assert _fetch() == "Error: Piloterr API error: HTTP 429: Too many requests; Piloterr rate limit reached, retry later or lower the request rate"

    def test_http_error_without_body(self, config_with_key):
        with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
            _client(mock_client).get.return_value = _response(status=502, json_body=ValueError("html"))
            assert _fetch() == "Error: Piloterr API error: HTTP 502"

    def test_network_error_is_redacted(self, config_with_key):
        with patch("deerflow.community.piloterr.tools.httpx.Client") as mock_client:
            _client(mock_client).get.side_effect = httpx.ConnectError("boom test-piloterr-key")
            result = _fetch()

        assert result == "Error: boom [REDACTED]"
