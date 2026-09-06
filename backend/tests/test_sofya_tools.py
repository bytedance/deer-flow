"""Unit tests for the Sofya community web search and fetch tools."""

import json
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the module-level warning flag before each test."""
    import deerflow.community.sofya.tools as sofya_mod

    sofya_mod._api_key_warned = set()
    yield
    sofya_mod._api_key_warned = set()


@pytest.fixture
def mock_config_with_key():
    with patch("deerflow.community.sofya.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {"api_key": "test-sofya-key", "max_results": 5}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


@pytest.fixture
def mock_config_no_key():
    with patch("deerflow.community.sofya.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


def _make_response(payload: object) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _make_search_response(results: list) -> MagicMock:
    return _make_response({"query": "test", "results": results})


def _make_fetch_response(results: list) -> MagicMock:
    return _make_response({"results": results})


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        with patch("deerflow.community.sofya.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "from-config"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.sofya.tools import _get_api_key

            assert _get_api_key("web_search") == "from-config"

    def test_falls_back_to_env_when_config_key_whitespace(self):
        with patch("deerflow.community.sofya.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "   "}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"SOFYA_API_KEY": "env-key"}):
                from deerflow.community.sofya.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"

    def test_uses_env_when_tool_is_not_configured(self):
        with patch("deerflow.community.sofya.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"SOFYA_API_KEY": "env-only"}):
                from deerflow.community.sofya.tools import _get_api_key

                assert _get_api_key("web_fetch") == "env-only"

    def test_returns_none_when_no_key_anywhere(self):
        with patch("deerflow.community.sofya.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.sofya.tools import _get_api_key

                assert _get_api_key("web_search") is None

    def test_returns_none_when_env_key_whitespace(self):
        with patch("deerflow.community.sofya.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"SOFYA_API_KEY": "   "}):
                from deerflow.community.sofya.tools import _get_api_key

                assert _get_api_key("web_search") is None

    def test_reads_config_for_requested_tool_name(self):
        with patch("deerflow.community.sofya.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "fetch-key"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.sofya.tools import _get_api_key

            assert _get_api_key("web_fetch") == "fetch-key"
            mock.return_value.get_tool_config.assert_called_with("web_fetch")


class TestCoerceMaxResults:
    def test_returns_value_when_valid_positive_int(self):
        from deerflow.community.sofya.tools import _coerce_max_results

        assert _coerce_max_results(3) == 3

    def test_returns_value_for_numeric_string(self):
        from deerflow.community.sofya.tools import _coerce_max_results

        assert _coerce_max_results("7") == 7

    def test_caps_value_at_default_maximum(self):
        from deerflow.community.sofya.tools import _coerce_max_results

        assert _coerce_max_results(999) == 20

    def test_returns_default_for_non_numeric_string(self):
        from deerflow.community.sofya.tools import _coerce_max_results

        assert _coerce_max_results("oops") == 5

    def test_returns_default_for_none(self):
        from deerflow.community.sofya.tools import _coerce_max_results

        assert _coerce_max_results(None) == 5

    def test_returns_default_for_zero_or_negative(self):
        from deerflow.community.sofya.tools import _coerce_max_results

        assert _coerce_max_results(0) == 5
        assert _coerce_max_results(-3) == 5


class TestMissingKeyMessage:
    def test_warns_once_per_tool_name(self, caplog):
        import deerflow.community.sofya.tools as sofya_mod

        with caplog.at_level(logging.WARNING):
            sofya_mod._missing_key_message("web_search")
            sofya_mod._missing_key_message("web_search")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "web_search" in warnings[0].getMessage()

    def test_warns_separately_for_each_tool(self, caplog):
        import deerflow.community.sofya.tools as sofya_mod

        with caplog.at_level(logging.WARNING):
            sofya_mod._missing_key_message("web_search")
            sofya_mod._missing_key_message("web_fetch")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 2


class TestWebSearchTool:
    def test_basic_search_returns_normalized_results(self, mock_config_with_key):
        results = [
            {"title": "Result 1", "url": "https://example.com/1", "content": "Page content 1", "description": "Snippet 1"},
            {"title": "Result 2", "url": "https://example.com/2", "content": "Page content 2", "description": "Snippet 2"},
        ]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "python tutorial"}))

        assert parsed["query"] == "python tutorial"
        assert parsed["total_results"] == 2
        assert parsed["results"][0] == {"title": "Result 1", "url": "https://example.com/1", "content": "Page content 1"}
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-sofya-key"
        assert mock_post.call_args.kwargs["json"]["query"] == "python tutorial"
        assert mock_post.call_args.kwargs["json"]["search_depth"] == "basic"
        assert "freshness" not in mock_post.call_args.kwargs["json"]

    def test_falls_back_to_description_when_content_is_empty(self, mock_config_with_key):
        results = [{"title": "Result", "url": "https://example.com", "content": "", "description": "Snippet"}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["results"][0]["content"] == "Snippet"

    def test_time_range_is_sent_as_freshness(self, mock_config_with_key):
        results = [{"title": "Result", "url": "https://example.com", "content": "Body"}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            web_search_tool.invoke({"query": "test", "time_range": "week"})

        assert mock_post.call_args.kwargs["json"]["freshness"] == "week"

    def test_search_depth_can_be_set_from_config(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "search_depth": "snippets",
        }
        results = [{"title": "Result", "url": "https://example.com", "description": "Snippet"}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            web_search_tool.invoke({"query": "test"})

        assert mock_post.call_args.kwargs["json"]["search_depth"] == "snippets"

    def test_non_string_content_does_not_raise(self, mock_config_with_key):
        results = [
            {"title": "Numeric", "url": "https://example.com/1", "content": 12345},
            {"title": "Listy", "url": "https://example.com/2", "content": None, "description": ["a", "b"]},
        ]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["results"][0]["content"] == "12345"
        assert parsed["results"][1]["content"] == "['a', 'b']"

    def test_result_content_is_capped_by_default(self, mock_config_with_key):
        results = [{"title": "Result", "url": "https://example.com", "content": "x" * 9000}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert len(parsed["results"][0]["content"]) == 2000

    def test_contents_max_characters_from_config(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "contents_max_characters": 100,
        }
        results = [{"title": "Result", "url": "https://example.com", "content": "x" * 9000}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert len(parsed["results"][0]["content"]) == 100

    def test_contents_max_characters_zero_disables_the_cap(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "contents_max_characters": 0,
        }
        results = [{"title": "Result", "url": "https://example.com", "content": "x" * 9000}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert len(parsed["results"][0]["content"]) == 9000

    def test_invalid_contents_max_characters_falls_back_to_default(self):
        from deerflow.community.sofya.tools import _coerce_content_limit

        assert _coerce_content_limit("oops") == 2000
        assert _coerce_content_limit(None) == 2000
        assert _coerce_content_limit(-5) == 2000
        assert _coerce_content_limit(0) == 0
        assert _coerce_content_limit("150") == 150

    def test_default_search_stays_under_the_externalize_threshold(self, mock_config_with_key):
        """Five capped results must stay inline rather than being persisted to disk."""
        results = [{"title": f"R{i}", "url": f"https://example.com/{i}", "content": "x" * 20000} for i in range(5)]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            output = web_search_tool.invoke({"query": "test"})

        assert len(output) < 12000

    def test_caller_max_results_wins_over_config(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "max_results": 5,
        }
        results = [{"title": f"R{i}", "url": f"https://x.com/{i}", "content": f"C{i}"} for i in range(10)]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test", "max_results": 8}))

        assert parsed["total_results"] == 8
        assert mock_post.call_args.kwargs["json"]["max_results"] == 8

    def test_unsupported_search_depth_falls_back_with_warning(self, mock_config_with_key, caplog):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "search_depth": "advanced",
        }
        results = [{"title": "Result", "url": "https://example.com", "content": "Body"}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            with caplog.at_level(logging.WARNING):
                web_search_tool.invoke({"query": "test"})

        assert mock_post.call_args.kwargs["json"]["search_depth"] == "basic"
        assert any("search_depth" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)

    def test_search_depth_is_normalized(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "search_depth": " Snippets ",
        }
        results = [{"title": "Result", "url": "https://example.com", "description": "Snippet"}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            web_search_tool.invoke({"query": "test"})

        assert mock_post.call_args.kwargs["json"]["search_depth"] == "snippets"

    def test_respects_max_results_from_config(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "max_results": 3,
        }
        results = [{"title": f"R{i}", "url": f"https://x.com/{i}", "content": f"C{i}"} for i in range(10)]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["total_results"] == 3
        assert mock_post.call_args.kwargs["json"]["max_results"] == 3

    def test_config_max_results_is_capped(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "max_results": 999,
        }
        results = [{"title": f"R{i}", "url": f"https://x.com/{i}", "content": f"C{i}"} for i in range(30)]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = _make_search_response(results)

            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["total_results"] == 20
        assert mock_post.call_args.kwargs["json"]["max_results"] == 20

    def test_max_results_parameter_accepted(self, mock_config_no_key):
        """Tool accepts max_results as a call parameter when config does not override it."""
        results = [{"title": f"R{i}", "url": f"https://x.com/{i}", "content": f"C{i}"} for i in range(10)]

        with patch.dict("os.environ", {"SOFYA_API_KEY": "env-key"}):
            with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
                mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_search_response(results)

                from deerflow.community.sofya.tools import web_search_tool

                parsed = json.loads(web_search_tool.invoke({"query": "test", "max_results": 2}))

        assert parsed["total_results"] == 2

    def test_empty_results_return_error_json(self, mock_config_with_key):
        """An empty result list returns a structured error, matching ddg_search convention."""
        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_search_response([])

            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "no results"}))

        assert parsed["error"] == "No results found"
        assert parsed["query"] == "no results"

    def test_unexpected_results_type_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_response({"results": "nope"})

            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["error"] == "Sofya returned an unexpected response format"

    def test_http_error_returns_error_json(self, mock_config_with_key):
        request = httpx.Request("POST", "https://sofya.co/v1/search")
        response = httpx.Response(402, text="Insufficient credits", request=request)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=request, response=response)

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["error"] == "Sofya API error: HTTP 402"

    def test_network_error_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.side_effect = httpx.ConnectError("boom")

            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["error"] == "boom"

    def test_missing_key_returns_error_json(self, mock_config_no_key):
        with patch.dict("os.environ", {}, clear=True):
            from deerflow.community.sofya.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert parsed["error"] == "SOFYA_API_KEY is not configured"
        assert parsed["query"] == "test"


class TestWebFetchTool:
    def test_returns_title_and_content(self, mock_config_with_key):
        results = [{"title": "Example Page", "url": "https://example.com", "content": "# Markdown body", "success": True}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = _make_fetch_response(results)

            from deerflow.community.sofya.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Example Page\n\n# Markdown body"
        assert mock_post.call_args.kwargs["json"] == {"urls": ["https://example.com"]}

    def test_truncates_long_content(self, mock_config_with_key):
        results = [{"title": "Long", "url": "https://example.com", "content": "x" * 9000, "success": True}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_fetch_response(results)

            from deerflow.community.sofya.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert len(result) == len("# Long\n\n") + 4096

    def test_non_string_content_does_not_raise(self, mock_config_with_key):
        results = [{"title": "Numeric", "url": "https://example.com", "content": 12345, "success": True}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_fetch_response(results)

            from deerflow.community.sofya.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Numeric\n\n12345"

    def test_missing_content_still_reports_no_content(self, mock_config_with_key):
        results = [{"title": "Empty", "url": "https://example.com", "content": None, "success": True}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_fetch_response(results)

            from deerflow.community.sofya.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: No content found"

    def test_falls_back_to_untitled(self, mock_config_with_key):
        results = [{"title": "", "url": "https://example.com", "content": "Body", "success": True}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_fetch_response(results)

            from deerflow.community.sofya.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Untitled\n\nBody"

    def test_failed_result_returns_its_error(self, mock_config_with_key):
        results = [{"url": "https://example.com", "success": False, "error": "404 Not Found"}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_fetch_response(results)

            from deerflow.community.sofya.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: 404 Not Found"

    def test_empty_content_returns_error(self, mock_config_with_key):
        results = [{"title": "Empty", "url": "https://example.com", "content": "", "success": True}]

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_fetch_response(results)

            from deerflow.community.sofya.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: No content found"

    def test_no_results_returns_error(self, mock_config_with_key):
        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = _make_fetch_response([])

            from deerflow.community.sofya.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: No results found"

    def test_http_error_returns_error_string(self, mock_config_with_key):
        request = httpx.Request("POST", "https://sofya.co/v1/fetch")
        response = httpx.Response(401, text="Invalid API key", request=request)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=request, response=response)

        with patch("deerflow.community.sofya.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.sofya.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: Sofya API error: HTTP 401"

    def test_missing_key_returns_error_string(self, mock_config_no_key):
        with patch.dict("os.environ", {}, clear=True):
            from deerflow.community.sofya.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: SOFYA_API_KEY is not configured"
