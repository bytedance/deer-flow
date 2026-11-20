"""Unit tests for the Unbrowse community web fetch tool."""

import json
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the module-level warning flag before each test."""
    import deerflow.community.unbrowse.tools as unbrowse_mod

    unbrowse_mod._api_key_warned = set()
    yield
    unbrowse_mod._api_key_warned = set()


@pytest.fixture
def mock_config_with_key():
    with patch("deerflow.community.unbrowse.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {"api_key": "test-unbrowse-key"}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


@pytest.fixture
def mock_config_no_key():
    with patch("deerflow.community.unbrowse.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


def _make_response(payload: object) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _make_scrape_response(scrape: dict, *, structured: bool = False) -> MagicMock:
    """Build a JSON-RPC tools/call response the way Unbrowse's MCP endpoint returns it."""
    result: dict = {"content": [{"type": "text", "text": json.dumps(scrape)}], "isError": False}
    if structured:
        result["structuredContent"] = scrape
    return _make_response({"jsonrpc": "2.0", "id": 1, "result": result})


def _scrape(markdown: object = "# Example Domain\n\nBody", title: object = "Example Domain") -> dict:
    return {
        "url": "https://example.com",
        "finalUrl": "https://example.com/",
        "via": "http",
        "metadata": {"title": title, "sourceURL": "https://example.com/", "statusCode": 200},
        "markdown": markdown,
    }


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        with patch("deerflow.community.unbrowse.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "from-config"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.unbrowse.tools import _get_api_key

            assert _get_api_key("web_fetch") == "from-config"

    def test_falls_back_to_env_when_config_key_whitespace(self):
        with patch("deerflow.community.unbrowse.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "   "}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"UNBROWSE_API_KEY": "env-key"}):
                from deerflow.community.unbrowse.tools import _get_api_key

                assert _get_api_key("web_fetch") == "env-key"

    def test_uses_env_when_tool_is_not_configured(self):
        with patch("deerflow.community.unbrowse.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"UNBROWSE_API_KEY": "env-only"}):
                from deerflow.community.unbrowse.tools import _get_api_key

                assert _get_api_key("web_fetch") == "env-only"

    def test_returns_none_when_no_key_anywhere(self):
        with patch("deerflow.community.unbrowse.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.unbrowse.tools import _get_api_key

                assert _get_api_key("web_fetch") is None

    def test_returns_none_when_env_key_whitespace(self):
        with patch("deerflow.community.unbrowse.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"UNBROWSE_API_KEY": "  "}, clear=True):
                from deerflow.community.unbrowse.tools import _get_api_key

                assert _get_api_key("web_fetch") is None


class TestResolveRender:
    def test_defaults_to_auto(self):
        from deerflow.community.unbrowse.tools import _resolve_render

        assert _resolve_render(None) == "auto"

    def test_normalizes_supported_modes(self):
        from deerflow.community.unbrowse.tools import _resolve_render

        assert _resolve_render(" Never ") == "never"
        assert _resolve_render("always") == "always"

    def test_unsupported_mode_falls_back_with_warning(self, caplog):
        from deerflow.community.unbrowse.tools import _resolve_render

        with caplog.at_level(logging.WARNING, logger="deerflow.community.unbrowse.tools"):
            assert _resolve_render("headless") == "auto"

        assert "headless" in caplog.text


class TestMissingKeyMessage:
    def test_warns_once_per_tool_name(self, caplog):
        from deerflow.community.unbrowse.tools import _missing_key_message

        with caplog.at_level(logging.WARNING, logger="deerflow.community.unbrowse.tools"):
            assert _missing_key_message("web_fetch") == "UNBROWSE_API_KEY is not configured"
            assert _missing_key_message("web_fetch") == "UNBROWSE_API_KEY is not configured"

        assert sum("Unbrowse API key is not set" in r.message for r in caplog.records) == 1


class TestWebFetchTool:
    def test_returns_title_and_markdown(self, mock_config_with_key):
        with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = _make_scrape_response(_scrape())

            from deerflow.community.unbrowse.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Example Domain\n\n# Example Domain\n\nBody"

    def test_sends_one_json_rpc_tools_call(self, mock_config_with_key):
        with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = _make_scrape_response(_scrape())

            from deerflow.community.unbrowse.tools import web_fetch_tool

            web_fetch_tool.invoke({"url": "https://example.com"})

        assert mock_post.call_count == 1
        assert mock_post.call_args.args[0] == "https://unbrowse.ai/api/mcp"
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-unbrowse-key"
        assert mock_post.call_args.kwargs["json"] == {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "unbrowse.scrape",
                "arguments": {"url": "https://example.com", "formats": ["markdown"], "render": "auto"},
            },
        }

    def test_render_can_be_set_from_config(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {"api_key": "k", "render": "never"}

        with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = _make_scrape_response(_scrape())

            from deerflow.community.unbrowse.tools import web_fetch_tool

            web_fetch_tool.invoke({"url": "https://example.com"})

        assert mock_post.call_args.kwargs["json"]["params"]["arguments"]["render"] == "never"

    def test_prefers_structured_content(self, mock_config_with_key):
        response = _make_scrape_response(_scrape(markdown="from text"), structured=True)
        response.json.return_value["result"]["structuredContent"] = _scrape(markdown="from structured")

        with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = response

            from deerflow.community.unbrowse.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Example Domain\n\nfrom structured"

    def test_truncates_long_content(self, mock_config_with_key):
        with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_scrape_response(_scrape(markdown="x" * 9000, title="Long"))

            from deerflow.community.unbrowse.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert len(result) == len("# Long\n\n") + 4096

    def test_non_string_markdown_does_not_raise(self, mock_config_with_key):
        with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_scrape_response(_scrape(markdown=12345, title="Numeric"))

            from deerflow.community.unbrowse.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Numeric\n\n12345"

    def test_falls_back_to_untitled(self, mock_config_with_key):
        scrape = _scrape(markdown="Body")
        scrape["metadata"] = None

        with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_scrape_response(scrape)

            from deerflow.community.unbrowse.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Untitled\n\nBody"

    @pytest.mark.parametrize("markdown", ["", None])
    def test_empty_markdown_returns_error(self, mock_config_with_key, markdown):
        with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_scrape_response(_scrape(markdown=markdown))

            from deerflow.community.unbrowse.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: No content found"

    def test_json_rpc_error_returns_its_message(self, mock_config_with_key):
        payload = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "page.goto: net::ERR_NAME_NOT_RESOLVED", "data": None}}

        with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_response(payload)

            from deerflow.community.unbrowse.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://nope.invalid"})

        assert result == "Error: Unbrowse error: page.goto: net::ERR_NAME_NOT_RESOLVED"

    def test_tool_error_result_returns_its_text(self, mock_config_with_key):
        payload = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "render failed"}], "isError": True}}

        with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_response(payload)

            from deerflow.community.unbrowse.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: Unbrowse error: render failed"

    @pytest.mark.parametrize(
        "payload",
        [
            ["not", "a", "dict"],
            {"jsonrpc": "2.0", "id": 1, "result": "oops"},
            {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "not json"}]}},
            {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "[1, 2]"}]}},
        ],
        ids=["non-dict-body", "non-dict-result", "non-json-text", "non-object-json"],
    )
    def test_malformed_response_returns_error(self, mock_config_with_key, payload):
        with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_response(payload)

            from deerflow.community.unbrowse.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: Unbrowse returned an unexpected response format"

    def test_http_error_returns_error_string(self, mock_config_with_key):
        request = httpx.Request("POST", "https://unbrowse.ai/api/mcp")
        response = httpx.Response(401, text='{"error":"invalid_token"}', request=request)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=request, response=response)

        with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.unbrowse.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: Unbrowse API error: HTTP 401"

    def test_network_error_returns_error_string(self, mock_config_with_key):
        with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.side_effect = httpx.ConnectError("boom")

            from deerflow.community.unbrowse.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: boom"

    def test_missing_key_returns_error_string(self, mock_config_no_key):
        with patch.dict("os.environ", {}, clear=True):
            with patch("deerflow.community.unbrowse.tools.httpx.Client") as mock_client_cls:
                from deerflow.community.unbrowse.tools import web_fetch_tool

                result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: UNBROWSE_API_KEY is not configured"
        mock_client_cls.assert_not_called()
