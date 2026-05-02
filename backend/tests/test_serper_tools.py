"""Unit tests for the Serper community web search tool."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the module-level warning flag before each test."""
    import deerflow.community.serper.tools as serper_mod

    serper_mod._api_key_warned = False
    yield
    serper_mod._api_key_warned = False


@pytest.fixture
def mock_config_with_key():
    with patch("deerflow.community.serper.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {"api_key": "test-serper-key", "max_results": 5}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


@pytest.fixture
def mock_config_no_key():
    with patch("deerflow.community.serper.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


def _make_serper_response(organic: list) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"organic": organic}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "from-config"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.serper.tools import _get_api_key

            assert _get_api_key() == "from-config"

    def test_falls_back_to_env_when_config_key_empty(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": ""}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"SERPER_API_KEY": "env-key"}):
                from deerflow.community.serper.tools import _get_api_key

                assert _get_api_key() == "env-key"

    def test_falls_back_to_env_when_config_key_whitespace(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "   "}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"SERPER_API_KEY": "env-key"}):
                from deerflow.community.serper.tools import _get_api_key

                assert _get_api_key() == "env-key"

    def test_falls_back_to_env_when_config_key_null(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": None}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"SERPER_API_KEY": "env-key"}):
                from deerflow.community.serper.tools import _get_api_key

                assert _get_api_key() == "env-key"

    def test_falls_back_to_env_when_no_config(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"SERPER_API_KEY": "env-only"}):
                from deerflow.community.serper.tools import _get_api_key

                assert _get_api_key() == "env-only"

    def test_returns_none_when_no_key_anywhere(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {}, clear=True):
                import os

                os.environ.pop("SERPER_API_KEY", None)
                from deerflow.community.serper.tools import _get_api_key

                assert _get_api_key() is None


class TestWebSearchTool:
    def test_basic_search_returns_normalized_results(self, mock_config_with_key):
        organic = [
            {"title": "Result 1", "link": "https://example.com/1", "snippet": "Snippet 1"},
            {"title": "Result 2", "link": "https://example.com/2", "snippet": "Snippet 2"},
        ]
        mock_resp = _make_serper_response(organic)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "python tutorial"})
            parsed = json.loads(result)

        assert parsed["query"] == "python tutorial"
        assert parsed["total_results"] == 2
        assert parsed["results"][0]["title"] == "Result 1"
        assert parsed["results"][0]["url"] == "https://example.com/1"
        assert parsed["results"][0]["content"] == "Snippet 1"

    def test_respects_max_results_from_config(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "max_results": 3,
        }
        organic = [{"title": f"R{i}", "link": f"https://x.com/{i}", "snippet": f"S{i}"} for i in range(10)]
        mock_resp = _make_serper_response(organic)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["total_results"] == 3
        assert len(parsed["results"]) == 3

    def test_max_results_parameter_accepted(self, mock_config_no_key):
        """Tool accepts max_results as a call parameter when config does not override it."""
        organic = [{"title": f"R{i}", "link": f"https://x.com/{i}", "snippet": f"S{i}"} for i in range(10)]
        mock_resp = _make_serper_response(organic)

        with patch.dict("os.environ", {"SERPER_API_KEY": "env-key"}):
            with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
                mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

                from deerflow.community.serper.tools import web_search_tool

                result = web_search_tool.invoke({"query": "test", "max_results": 2})
                parsed = json.loads(result)

        assert parsed["total_results"] == 2

    def test_config_max_results_overrides_parameter(self):
        """Config max_results overrides the parameter passed at call time, matching ddg_search behaviour."""
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "test-key", "max_results": 3}
            mock.return_value.get_tool_config.return_value = tool_config

            organic = [{"title": f"R{i}", "link": f"https://x.com/{i}", "snippet": f"S{i}"} for i in range(10)]
            mock_resp = _make_serper_response(organic)

            with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
                mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

                from deerflow.community.serper.tools import web_search_tool

                result = web_search_tool.invoke({"query": "test", "max_results": 8})
                parsed = json.loads(result)

        assert parsed["total_results"] == 3

    def test_empty_organic_returns_error_json(self, mock_config_with_key):
        """Empty organic list returns structured error, matching ddg_search convention."""
        mock_resp = _make_serper_response([])

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "no results"})
            parsed = json.loads(result)

        assert "error" in parsed
        assert parsed["error"] == "No results found"
        assert parsed["query"] == "no results"

    def test_missing_api_key_returns_error_json(self, mock_config_no_key):
        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("SERPER_API_KEY", None)

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed
        assert "SERPER_API_KEY" in parsed["error"]

    def test_missing_api_key_logs_warning_once(self, mock_config_no_key, caplog):
        import logging

        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("SERPER_API_KEY", None)

            from deerflow.community.serper.tools import web_search_tool

            with caplog.at_level(logging.WARNING, logger="deerflow.community.serper.tools"):
                web_search_tool.invoke({"query": "q1"})
                web_search_tool.invoke({"query": "q2"})

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

    def test_http_error_returns_structured_error(self, mock_config_with_key):
        mock_error_response = MagicMock()
        mock_error_response.status_code = 403
        mock_error_response.text = "Forbidden"

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.side_effect = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_error_response)

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed
        assert "403" in parsed["error"]

    def test_network_exception_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.side_effect = Exception("timeout")

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed

    def test_sends_correct_headers_and_payload(self, mock_config_with_key):
        organic = [{"title": "T", "link": "https://x.com", "snippet": "S"}]
        mock_resp = _make_serper_response(organic)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            web_search_tool.invoke({"query": "hello world"})

            call_kwargs = mock_post.call_args
            headers = call_kwargs.kwargs["headers"]
            payload = call_kwargs.kwargs["json"]

        assert headers["X-API-KEY"] == "test-serper-key"
        assert payload["q"] == "hello world"
        assert payload["num"] == 5

    def test_uses_env_key_when_config_absent(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"SERPER_API_KEY": "env-only-key"}):
                organic = [{"title": "T", "link": "https://x.com", "snippet": "S"}]
                mock_resp = _make_serper_response(organic)

                with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
                    mock_post = mock_client_cls.return_value.__enter__.return_value.post
                    mock_post.return_value = mock_resp

                    from deerflow.community.serper.tools import web_search_tool

                    web_search_tool.invoke({"query": "env key test"})
                    headers = mock_post.call_args.kwargs["headers"]

                assert headers["X-API-KEY"] == "env-only-key"

    def test_partial_fields_in_organic_result(self, mock_config_with_key):
        """Missing title/link/snippet should default to empty string."""
        organic = [{}]
        mock_resp = _make_serper_response(organic)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["results"][0] == {"title": "", "url": "", "content": ""}
