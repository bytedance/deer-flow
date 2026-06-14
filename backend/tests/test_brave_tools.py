"""Unit tests for the Brave Search community web search tool."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the module-level warning flag before each test."""
    import deerflow.community.brave.tools as brave_mod

    brave_mod._api_key_warned = False
    yield
    brave_mod._api_key_warned = False


@pytest.fixture
def mock_config_with_key():
    with patch("deerflow.community.brave.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {"api_key": "test-brave-key", "max_results": 5}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


@pytest.fixture
def mock_config_no_key():
    with patch("deerflow.community.brave.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


def _make_brave_response(results: list) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"web": {"results": results}}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _count_aware_get(results: list):
    """Mimic Brave returning at most `count` results for the request."""

    def _get(url, **kwargs):
        count = kwargs["params"]["count"]
        return _make_brave_response(results[:count])

    return _get


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        with patch("deerflow.community.brave.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "from-config"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.brave.tools import _get_api_key

            assert _get_api_key() == "from-config"

    def test_falls_back_to_env_when_config_key_empty(self):
        with patch("deerflow.community.brave.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "   "}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "env-key"}, clear=True):
                from deerflow.community.brave.tools import _get_api_key

                assert _get_api_key() == "env-key"

    def test_falls_back_to_env_when_no_config(self):
        with patch("deerflow.community.brave.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "env-only"}, clear=True):
                from deerflow.community.brave.tools import _get_api_key

                assert _get_api_key() == "env-only"

    def test_ignores_legacy_brave_api_key(self):
        with patch("deerflow.community.brave.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"BRAVE_API_KEY": "legacy"}, clear=True):
                from deerflow.community.brave.tools import _get_api_key

                assert _get_api_key() is None

    def test_returns_none_when_no_key_anywhere(self):
        with patch("deerflow.community.brave.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.brave.tools import _get_api_key

                assert _get_api_key() is None

    def test_model_extra_none_does_not_crash(self):
        with patch("deerflow.community.brave.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = None
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "env-key"}, clear=True):
                from deerflow.community.brave.tools import _get_api_key

                assert _get_api_key() == "env-key"


class TestWebSearchTool:
    def test_basic_search_returns_normalized_results(self, mock_config_with_key):
        results = [
            {"title": "Result 1", "url": "https://example.com/1", "description": "Desc 1"},
            {"title": "Result 2", "url": "https://example.com/2", "description": "Desc 2"},
        ]
        mock_resp = _make_brave_response(results)

        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

            from deerflow.community.brave.tools import web_search_tool

            result = web_search_tool.invoke({"query": "python tutorial"})
            parsed = json.loads(result)

        assert parsed["query"] == "python tutorial"
        assert parsed["total_results"] == 2
        assert parsed["results"][0]["title"] == "Result 1"
        assert parsed["results"][0]["url"] == "https://example.com/1"
        assert parsed["results"][0]["content"] == "Desc 1"

    def test_respects_max_results_from_config(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "max_results": 3,
        }
        results = [{"title": f"R{i}", "url": f"https://x.com/{i}", "description": f"D{i}"} for i in range(10)]

        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.side_effect = _count_aware_get(results)

            from deerflow.community.brave.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["total_results"] == 3
        assert len(parsed["results"]) == 3

    def test_max_results_parameter_accepted(self, mock_config_no_key):
        """Tool accepts max_results as a call parameter when config does not override it."""
        results = [{"title": f"R{i}", "url": f"https://x.com/{i}", "description": f"D{i}"} for i in range(10)]

        with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "env-key"}, clear=True):
            with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
                mock_client_cls.return_value.__enter__.return_value.get.side_effect = _count_aware_get(results)

                from deerflow.community.brave.tools import web_search_tool

                result = web_search_tool.invoke({"query": "test", "max_results": 2})
                parsed = json.loads(result)

        assert parsed["total_results"] == 2

    def test_config_max_results_overrides_parameter(self):
        with patch("deerflow.community.brave.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "test-key", "max_results": 3}
            mock.return_value.get_tool_config.return_value = tool_config

            results = [{"title": f"R{i}", "url": f"https://x.com/{i}", "description": f"D{i}"} for i in range(10)]

            with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
                mock_client_cls.return_value.__enter__.return_value.get.side_effect = _count_aware_get(results)

                from deerflow.community.brave.tools import web_search_tool

                result = web_search_tool.invoke({"query": "test", "max_results": 8})
                parsed = json.loads(result)

        assert parsed["total_results"] == 3

    def test_max_results_string_from_env_is_coerced_and_clamped(self):
        """Env-sourced max_results is a string and must be coerced and clamped to 20."""
        with patch("deerflow.community.brave.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "test-key", "max_results": "50"}
            mock.return_value.get_tool_config.return_value = tool_config

            results = [{"title": f"R{i}", "url": f"https://x.com/{i}", "description": f"D{i}"} for i in range(30)]

            with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
                mock_get = mock_client_cls.return_value.__enter__.return_value.get
                mock_get.side_effect = _count_aware_get(results)

                from deerflow.community.brave.tools import web_search_tool

                result = web_search_tool.invoke({"query": "test"})
                parsed = json.loads(result)
                params = mock_get.call_args.kwargs["params"]

        assert params["count"] == 20
        assert parsed["total_results"] == 20

    def test_invalid_max_results_falls_back_to_default(self, caplog):
        with patch("deerflow.community.brave.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "test-key", "max_results": "abc"}
            mock.return_value.get_tool_config.return_value = tool_config

            results = [{"title": f"R{i}", "url": f"https://x.com/{i}", "description": f"D{i}"} for i in range(10)]

            with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
                mock_get = mock_client_cls.return_value.__enter__.return_value.get
                mock_get.side_effect = _count_aware_get(results)

                from deerflow.community.brave.tools import web_search_tool

                with caplog.at_level("WARNING", logger="deerflow.community.brave.tools"):
                    result = web_search_tool.invoke({"query": "test"})
                parsed = json.loads(result)
                params = mock_get.call_args.kwargs["params"]

        assert params["count"] == 5
        assert parsed["total_results"] == 5
        assert any("Invalid Brave Search max_results" in record.message for record in caplog.records)

    def test_empty_results_returns_error_json(self, mock_config_with_key):
        mock_resp = _make_brave_response([])

        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

            from deerflow.community.brave.tools import web_search_tool

            result = web_search_tool.invoke({"query": "no results"})
            parsed = json.loads(result)

        assert parsed["error"] == "No results found"
        assert parsed["query"] == "no results"

    def test_missing_web_key_returns_error_json(self, mock_config_with_key):
        """A response without a `web` block should be treated as no results."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()

        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

            from deerflow.community.brave.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["error"] == "No results found"

    def test_missing_api_key_returns_error_json(self, mock_config_no_key):
        with patch.dict("os.environ", {}, clear=True):
            from deerflow.community.brave.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed
        assert "BRAVE_SEARCH_API_KEY" in parsed["error"]

    def test_missing_api_key_logs_warning_once(self, mock_config_no_key, caplog):
        import logging

        with patch.dict("os.environ", {}, clear=True):
            from deerflow.community.brave.tools import web_search_tool

            with caplog.at_level(logging.WARNING, logger="deerflow.community.brave.tools"):
                web_search_tool.invoke({"query": "q1"})
                web_search_tool.invoke({"query": "q2"})

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

    def test_http_error_returns_structured_error(self, mock_config_with_key):
        mock_error_response = MagicMock()
        mock_error_response.status_code = 403
        mock_error_response.text = "Forbidden"

        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.side_effect = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_error_response)

            from deerflow.community.brave.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed
        assert "403" in parsed["error"]

    def test_network_exception_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.side_effect = Exception("timeout")

            from deerflow.community.brave.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed

    def test_sends_correct_headers_and_params(self, mock_config_with_key):
        results = [{"title": "T", "url": "https://x.com", "description": "D"}]
        mock_resp = _make_brave_response(results)

        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_get = mock_client_cls.return_value.__enter__.return_value.get
            mock_get.return_value = mock_resp

            from deerflow.community.brave.tools import web_search_tool

            web_search_tool.invoke({"query": "hello world"})

            call_kwargs = mock_get.call_args
            headers = call_kwargs.kwargs["headers"]
            params = call_kwargs.kwargs["params"]

        assert headers["X-Subscription-Token"] == "test-brave-key"
        assert params["q"] == "hello world"
        assert params["count"] == 5

    def test_uses_env_key_when_config_absent(self):
        with patch("deerflow.community.brave.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "env-only-key"}, clear=True):
                results = [{"title": "T", "url": "https://x.com", "description": "D"}]
                mock_resp = _make_brave_response(results)

                with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
                    mock_get = mock_client_cls.return_value.__enter__.return_value.get
                    mock_get.return_value = mock_resp

                    from deerflow.community.brave.tools import web_search_tool

                    web_search_tool.invoke({"query": "env key test"})
                    headers = mock_get.call_args.kwargs["headers"]

                assert headers["X-Subscription-Token"] == "env-only-key"

    def test_partial_fields_in_result(self, mock_config_with_key):
        """Missing title/url/description should default to empty string."""
        results = [{}]
        mock_resp = _make_brave_response(results)

        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

            from deerflow.community.brave.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["results"][0] == {"title": "", "url": "", "content": ""}
