"""Unit tests for the SpecStream community web search and fetch tools."""

import json
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

_MODULE = "deerflow.community.specstream.tools"


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the module-level warning flag before each test."""
    import deerflow.community.specstream.tools as specstream_mod

    specstream_mod._api_key_warned = set()
    yield
    specstream_mod._api_key_warned = set()


@pytest.fixture
def mock_config_with_key():
    with patch(f"{_MODULE}.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {"api_key": "test-specstream-key", "max_results": 5}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


@pytest.fixture
def mock_config_no_key():
    with patch(f"{_MODULE}.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


def _make_response(data: object) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": data}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _source(n: int, **extra) -> dict:
    return {"url": f"https://example.com/{n}", "title": f"Result {n}", "site": "example.com", "snippet": f"Snippet {n}", "cited": False, **extra}


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        with patch(f"{_MODULE}.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "from-config"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.specstream.tools import _get_api_key

            assert _get_api_key("web_search") == "from-config"

    def test_falls_back_to_env_when_config_key_whitespace(self):
        with patch(f"{_MODULE}.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "   "}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"SPECSTREAM_API_KEY": "env-key"}):
                from deerflow.community.specstream.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"

    def test_uses_env_when_tool_is_not_configured(self):
        with patch(f"{_MODULE}.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"SPECSTREAM_API_KEY": "env-only"}):
                from deerflow.community.specstream.tools import _get_api_key

                assert _get_api_key("web_fetch") == "env-only"

    def test_returns_none_when_no_key_anywhere(self):
        with patch(f"{_MODULE}.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.specstream.tools import _get_api_key

                assert _get_api_key("web_search") is None


class TestMissingKeyMessage:
    def test_warns_once_per_tool_name(self, caplog):
        from deerflow.community.specstream.tools import _missing_key_message

        with caplog.at_level(logging.WARNING, logger=_MODULE):
            assert _missing_key_message("web_search") == "SPECSTREAM_API_KEY is not configured"
            _missing_key_message("web_search")
        assert len([r for r in caplog.records if "SPECSTREAM_API_KEY" in r.getMessage()]) == 1


class TestWebSearchTool:
    def test_basic_search_returns_normalized_results(self, mock_config_with_key):
        data = {"sources": [_source(1), _source(2)], "answer": None}

        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_request = mock_client_cls.return_value.__enter__.return_value.request
            mock_request.return_value = _make_response(data)

            from deerflow.community.specstream.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "python tutorial"}))

        assert parsed["query"] == "python tutorial"
        assert parsed["total_results"] == 2
        assert parsed["results"][0] == {"title": "Result 1", "url": "https://example.com/1", "snippet": "Snippet 1"}
        assert "answer" not in parsed
        assert mock_request.call_args.args == ("GET", "https://api.specstream.ai/v1/web-search")
        assert mock_request.call_args.kwargs["headers"]["Authorization"] == "Bearer test-specstream-key"
        assert mock_request.call_args.kwargs["params"] == {"q": "python tutorial"}

    def test_direct_answer_is_returned_with_its_page(self, mock_config_with_key):
        data = {"sources": [_source(1)], "answer": {"value": "1889", "page": "https://example.com/1", "seen_at": "2026-11-01T00:00:00Z"}}

        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.request.return_value = _make_response(data)

            from deerflow.community.specstream.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "when was it built"}))

        assert parsed["answer"] == {"value": "1889", "url": "https://example.com/1"}

    def test_answer_page_is_screened(self, mock_config_with_key):
        data = {"sources": [_source(1)], "answer": {"value": "x", "page": "http://169.254.169.254/latest/meta-data/"}}

        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.request.return_value = _make_response(data)

            from deerflow.community.specstream.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "q"}))

        assert parsed["answer"]["url"] == ""

    def test_long_query_is_cut_to_the_api_limit(self, mock_config_with_key):
        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_request = mock_client_cls.return_value.__enter__.return_value.request
            mock_request.return_value = _make_response({"sources": [_source(1)]})

            from deerflow.community.specstream.tools import web_search_tool

            web_search_tool.invoke({"query": "a" * 2500})

        assert len(mock_request.call_args.kwargs["params"]["q"]) == 2000

    def test_respects_max_results_from_config(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra["max_results"] = 2

        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.request.return_value = _make_response({"sources": [_source(n) for n in range(5)]})

            from deerflow.community.specstream.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["total_results"] == 2

    def test_caller_max_results_wins_over_config(self, mock_config_with_key):
        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.request.return_value = _make_response({"sources": [_source(n) for n in range(8)]})

            from deerflow.community.specstream.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test", "max_results": 3}))

        assert parsed["total_results"] == 3

    def test_empty_sources_return_error_json(self, mock_config_with_key):
        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.request.return_value = _make_response({"sources": []})

            from deerflow.community.specstream.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["error"] == "No results found"

    @pytest.mark.parametrize("sources", [[], None])
    def test_answer_without_sources_is_still_returned(self, mock_config_with_key, sources):
        data = {"sources": sources, "answer": {"value": "1889", "page": "https://example.com/1"}}
        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.request.return_value = _make_response(data)

            from deerflow.community.specstream.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "when was it built"}))

        assert "error" not in parsed
        assert parsed["answer"] == {"value": "1889", "url": "https://example.com/1"}
        assert parsed["total_results"] == 0
        assert parsed["results"] == []

    @pytest.mark.parametrize("sources", ["oops", [1, "a"]])
    def test_malformed_sources_return_format_error(self, mock_config_with_key, sources, caplog):
        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.request.return_value = _make_response({"sources": sources})

            from deerflow.community.specstream.tools import web_search_tool

            with caplog.at_level(logging.ERROR, logger=_MODULE):
                parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["error"] == "SpecStream returned an unexpected response format"

    def test_reply_without_data_envelope_returns_format_error(self, mock_config_with_key):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"sources": []}

        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp

            from deerflow.community.specstream.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["error"] == "SpecStream returned an unexpected response format"

    def test_http_error_returns_error_json(self, mock_config_with_key):
        request = httpx.Request("GET", "https://api.specstream.ai/v1/web-search")
        response = httpx.Response(402, text="balance is empty", request=request)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=request, response=response)

        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp

            from deerflow.community.specstream.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["error"] == "SpecStream API error: HTTP 402"

    def test_network_error_returns_error_json(self, mock_config_with_key):
        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.request.side_effect = httpx.ConnectError("boom")

            from deerflow.community.specstream.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["error"] == "boom"

    def test_missing_key_returns_error_json(self, mock_config_no_key):
        with patch.dict("os.environ", {}, clear=True):
            from deerflow.community.specstream.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["error"] == "SPECSTREAM_API_KEY is not configured"
        assert parsed["query"] == "test"


class TestWebFetchTool:
    def _fetch(self, data):
        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_request = mock_client_cls.return_value.__enter__.return_value.request
            mock_request.return_value = _make_response(data)

            from deerflow.community.specstream.tools import web_fetch_tool

            return web_fetch_tool.invoke({"url": "https://example.com/post"}), mock_request

    def test_returns_title_and_content(self, mock_config_with_key):
        result, mock_request = self._fetch({"results": [{"url": "https://example.com/post", "status": "ok", "title": "Example", "text": "Hello world"}]})

        assert result == "# Example\n\nHello world"
        assert mock_request.call_args.args == ("POST", "https://api.specstream.ai/v1/extract")
        assert mock_request.call_args.kwargs["headers"]["Authorization"] == "Bearer test-specstream-key"
        assert mock_request.call_args.kwargs["json"] == {"urls": ["https://example.com/post"], "format": "markdown"}

    def test_truncates_long_content(self, mock_config_with_key):
        result, _ = self._fetch({"results": [{"status": "ok", "title": "T", "text": "x" * 10000}]})

        assert len(result) == len("# T\n\n") + 4096

    def test_falls_back_to_untitled(self, mock_config_with_key):
        result, _ = self._fetch({"results": [{"status": "ok", "text": "body"}]})

        assert result.startswith("# Untitled\n\n")

    @pytest.mark.parametrize("status", ["blocked", "not_found", "empty", "unsupported", "invalid_url", "failed"])
    def test_page_that_was_not_read_returns_its_status(self, mock_config_with_key, status):
        result, _ = self._fetch({"results": [{"status": status, "text": ""}]})

        assert result == f"Error: SpecStream could not read the page ({status})"

    def test_ok_page_without_text_returns_error(self, mock_config_with_key):
        result, _ = self._fetch({"results": [{"status": "ok", "text": None}]})

        assert result == "Error: No content found"

    def test_no_results_returns_error(self, mock_config_with_key):
        result, _ = self._fetch({"results": []})

        assert result == "Error: No results found"

    def test_results_without_any_objects_returns_format_error(self, mock_config_with_key):
        result, _ = self._fetch({"results": ["oops"]})

        assert result == "Error: SpecStream returned an unexpected response format"

    def test_http_error_returns_error_string(self, mock_config_with_key):
        request = httpx.Request("POST", "https://api.specstream.ai/v1/extract")
        response = httpx.Response(402, text="balance is empty", request=request)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=request, response=response)

        with patch(f"{_MODULE}.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp

            from deerflow.community.specstream.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: SpecStream API error: HTTP 402"

    def test_missing_key_returns_error_string(self, mock_config_no_key):
        with patch.dict("os.environ", {}, clear=True):
            from deerflow.community.specstream.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: SPECSTREAM_API_KEY is not configured"
