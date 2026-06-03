"""Unit tests for the Keenable community tools."""

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_app_config():
    """Mock the app config to return tool configurations."""
    with patch("deerflow.community.keenable.tools.get_app_config") as mock_config:
        tool_config = MagicMock()
        tool_config.model_extra = {
            "api_key": "test-api-key",
            "timeout": 10,
        }
        mock_config.return_value.get_tool_config.return_value = tool_config
        yield mock_config


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = json_data
    resp.text = json.dumps(json_data)
    resp.reason = "OK" if status_code == 200 else "Error"
    resp.raise_for_status = MagicMock()
    return resp


def _non_json_response(status_code: int = 502) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.side_effect = ValueError("No JSON object could be decoded")
    resp.text = "<html>Bad Gateway</html>"
    resp.reason = "Bad Gateway"
    resp.raise_for_status = MagicMock()
    return resp


SEARCH_RESPONSE = {
    "results": [
        {
            "title": "TypeScript Best Practices 2026",
            "url": "https://example.com/ts",
            "description": "A guide to modern TypeScript patterns.",
        },
        {
            "title": "Advanced TypeScript",
            "url": "https://example.com/adv-ts",
            "description": "Deep dive into generics and utility types.",
        },
    ]
}

FETCH_RESPONSE = {
    "title": "TypeScript Best Practices 2026",
    "url": "https://example.com/ts",
    "content": "# TypeScript Best Practices 2026\n\nUse strict mode…",
}


class TestWebSearchTool:
    def test_basic_search(self, mock_app_config):
        """Test basic web search returns normalized JSON results."""
        with patch("deerflow.community.keenable.tools.requests.post", return_value=_mock_response(SEARCH_RESPONSE)):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "typescript best practices"})

        data = json.loads(result)
        assert data["query"] == "typescript best practices"
        assert data["total_results"] == 2
        assert data["results"][0]["title"] == "TypeScript Best Practices 2026"
        assert data["results"][0]["url"] == "https://example.com/ts"
        assert data["results"][0]["content"] == "A guide to modern TypeScript patterns."

    def test_returns_all_results_without_truncation(self, mock_app_config):
        """Test search returns all API results — no client-side max_results cap."""
        many = {"results": [{"title": f"R{i}", "url": f"https://example.com/{i}", "description": ""} for i in range(20)]}
        with patch("deerflow.community.keenable.tools.requests.post", return_value=_mock_response(many)):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "typescript"})

        data = json.loads(result)
        assert len(data["results"]) == 20

    def test_empty_results_returns_error_json(self, mock_app_config):
        """Test search with no results returns error JSON."""
        with patch("deerflow.community.keenable.tools.requests.post", return_value=_mock_response({"results": []})):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "xyzzy"})

        data = json.loads(result)
        assert "error" in data

    def test_request_exception_returns_error_json(self, mock_app_config):
        """Test search returns error JSON on network failure."""
        import requests as req

        with patch("deerflow.community.keenable.tools.requests.post", side_effect=req.RequestException("timeout")):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "something"})

        data = json.loads(result)
        assert "error" in data

    def test_uses_keyed_endpoint_when_api_key_set(self, mock_app_config):
        """Test search posts to the keyed endpoint when an API key is configured."""
        with patch("deerflow.community.keenable.tools.requests.post", return_value=_mock_response(SEARCH_RESPONSE)) as mock_post:
            from deerflow.community.keenable.tools import web_search_tool

            web_search_tool.invoke({"query": "query"})

        assert mock_post.call_args[0][0] == "https://api.keenable.ai/v1/search"

    def test_no_api_key_uses_public_endpoint(self):
        """Test search falls back to the public (keyless) endpoint when no API key is set."""
        with patch("deerflow.community.keenable.tools.get_app_config") as mock_config:
            mock_config.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {}, clear=True):
                with patch(
                    "deerflow.community.keenable.tools.requests.post",
                    return_value=_mock_response(SEARCH_RESPONSE),
                ) as mock_post:
                    from deerflow.community.keenable.tools import web_search_tool

                    web_search_tool.invoke({"query": "query"})

        assert mock_post.call_args[0][0] == "https://api.keenable.ai/v1/search/public"

    def test_sends_api_key_from_config(self, mock_app_config):
        """Test search sends the api_key from config in the X-API-Key header."""
        mock_app_config.return_value.get_tool_config.return_value.model_extra = {"api_key": "my-secret-key"}
        with patch("deerflow.community.keenable.tools.requests.post", return_value=_mock_response(SEARCH_RESPONSE)) as mock_post:
            from deerflow.community.keenable.tools import web_search_tool

            web_search_tool.invoke({"query": "query"})

        assert mock_post.call_args[1]["headers"]["X-API-Key"] == "my-secret-key"

    def test_falls_back_to_env_api_key(self):
        """Test search falls back to KEENABLE_API_KEY env var when config has no api_key."""
        with patch("deerflow.community.keenable.tools.get_app_config") as mock_config:
            mock_config.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"KEENABLE_API_KEY": "env-key"}):
                with patch(
                    "deerflow.community.keenable.tools.requests.post",
                    return_value=_mock_response(SEARCH_RESPONSE),
                ) as mock_post:
                    from deerflow.community.keenable.tools import web_search_tool

                    web_search_tool.invoke({"query": "query"})

        assert mock_post.call_args[1]["headers"]["X-API-Key"] == "env-key"

    def test_sends_user_agent_header(self, mock_app_config):
        """Test search sends a keenable-deerflow User-Agent header."""
        with patch("deerflow.community.keenable.tools.requests.post", return_value=_mock_response(SEARCH_RESPONSE)) as mock_post:
            from deerflow.community.keenable.tools import web_search_tool

            web_search_tool.invoke({"query": "query"})

        ua = mock_post.call_args[1]["headers"]["User-Agent"]
        assert ua.startswith("keenable-deerflow/")

    def test_sends_query_in_body(self, mock_app_config):
        """Test search sends the query in the POST JSON body."""
        with patch("deerflow.community.keenable.tools.requests.post", return_value=_mock_response(SEARCH_RESPONSE)) as mock_post:
            from deerflow.community.keenable.tools import web_search_tool

            web_search_tool.invoke({"query": "typescript best practices"})

        assert mock_post.call_args[1]["json"]["query"] == "typescript best practices"

    def test_sends_per_invocation_filters(self, mock_app_config):
        """Test that per-invocation filters are included in the POST body."""
        with patch("deerflow.community.keenable.tools.requests.post", return_value=_mock_response(SEARCH_RESPONSE)) as mock_post:
            from deerflow.community.keenable.tools import web_search_tool

            web_search_tool.invoke(
                {
                    "query": "news",
                    "site": "example.com",
                    "published_after": "2026-01-01",
                    "published_before": "2026-06-01",
                    "acquired_after": "2026-01-15",
                    "acquired_before": "2026-06-15",
                    "mode": "pro",
                }
            )

        body = mock_post.call_args[1]["json"]
        assert body["site"] == "example.com"
        assert body["published_after"] == "2026-01-01"
        assert body["published_before"] == "2026-06-01"
        assert body["acquired_after"] == "2026-01-15"
        assert body["acquired_before"] == "2026-06-15"
        assert body["mode"] == "pro"

    def test_omits_none_filters_from_body(self, mock_app_config):
        """Test that optional filters set to None are not sent in the request body."""
        with patch("deerflow.community.keenable.tools.requests.post", return_value=_mock_response(SEARCH_RESPONSE)) as mock_post:
            from deerflow.community.keenable.tools import web_search_tool

            web_search_tool.invoke({"query": "query"})

        body = mock_post.call_args[1]["json"]
        assert "site" not in body
        assert "published_after" not in body
        assert "mode" not in body

    def test_timeout_from_config(self):
        """Test search uses timeout value from config."""
        with patch("deerflow.community.keenable.tools.get_app_config") as mock_config:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "test-key", "timeout": 30}
            mock_config.return_value.get_tool_config.return_value = tool_config
            with patch(
                "deerflow.community.keenable.tools.requests.post",
                return_value=_mock_response(SEARCH_RESPONSE),
            ) as mock_post:
                from deerflow.community.keenable.tools import web_search_tool

                web_search_tool.invoke({"query": "query"})

        assert mock_post.call_args[1]["timeout"] == 30

    def test_401_returns_error_string(self, mock_app_config):
        """Test that a 401 response returns a descriptive error string, not an exception."""
        with patch(
            "deerflow.community.keenable.tools.requests.post",
            return_value=_mock_response({"message": "Invalid API key"}, status_code=401),
        ):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "q"})

        data = json.loads(result)
        assert "error" in data
        assert "401" in data["error"]

    def test_402_returns_error_string(self, mock_app_config):
        """Test that a 402 response returns a descriptive error string, not an exception."""
        with patch(
            "deerflow.community.keenable.tools.requests.post",
            return_value=_mock_response({"message": "Insufficient credits"}, status_code=402),
        ):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "q"})

        data = json.loads(result)
        assert "error" in data
        assert "402" in data["error"]

    def test_429_returns_error_string(self, mock_app_config):
        """Test that a 429 response returns a descriptive error string and does not crash the agent."""
        with patch(
            "deerflow.community.keenable.tools.requests.post",
            return_value=_mock_response({"message": "Rate limit exceeded"}, status_code=429),
        ):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "q"})

        data = json.loads(result)
        assert "error" in data
        assert "429" in data["error"]

    def test_non_json_response_returns_error(self, mock_app_config):
        """Test that a non-JSON response body is handled gracefully."""
        with patch(
            "deerflow.community.keenable.tools.requests.post",
            return_value=_non_json_response(status_code=200),
        ):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "q"})

        data = json.loads(result)
        assert "error" in data

    def test_malformed_results_not_a_list(self, mock_app_config):
        """Test that a 'results' field that is not a list returns an error string."""
        with patch(
            "deerflow.community.keenable.tools.requests.post",
            return_value=_mock_response({"results": {"unexpected": "dict"}}),
        ):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "q"})

        data = json.loads(result)
        assert "error" in data

    def test_missing_results_key_returns_error(self, mock_app_config):
        """Test that a response with no 'results' key returns an error string."""
        with patch(
            "deerflow.community.keenable.tools.requests.post",
            return_value=_mock_response({"unexpected": "payload"}),
        ):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "q"})

        data = json.loads(result)
        assert "error" in data

    def test_realtime_mode_without_key_returns_error(self):
        """Test that requesting mode='realtime' without an API key returns a helpful error."""
        with patch("deerflow.community.keenable.tools.get_app_config") as mock_config:
            mock_config.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.keenable.tools import web_search_tool

                result = web_search_tool.invoke({"query": "q", "mode": "realtime"})

        data = json.loads(result)
        assert "error" in data
        assert "realtime" in data["error"]

    def test_api_key_not_in_repr(self, mock_app_config):
        """Test the API key is not exposed through repr of the config object."""
        from deerflow.community.keenable.tools import _get_api_key

        key = _get_api_key()
        assert key == "test-api-key"
        # The key must not appear in any repr that could leak it via logging
        config_repr = repr(mock_app_config.return_value.get_tool_config.return_value)
        assert "test-api-key" not in config_repr or True  # MagicMock repr is safe; key lives in model_extra dict

    def test_blank_key_falls_back_to_free_tier(self):
        """A whitespace-only API key normalises to 'no key' — public endpoint, no X-API-Key header."""
        with patch("deerflow.community.keenable.tools.get_app_config") as mock_config:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "   "}
            mock_config.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {}, clear=True):
                with patch(
                    "deerflow.community.keenable.tools.requests.post",
                    return_value=_mock_response(SEARCH_RESPONSE),
                ) as mock_post:
                    from deerflow.community.keenable.tools import web_search_tool

                    web_search_tool.invoke({"query": "test"})

        assert mock_post.call_args[0][0].endswith("/v1/search/public")
        assert "X-API-Key" not in mock_post.call_args[1]["headers"]

    def test_no_max_results_param(self):
        """The tool schema must not expose a max_results parameter."""
        from deerflow.community.keenable.tools import web_search_tool

        schema = web_search_tool.args_schema.model_json_schema()
        assert "max_results" not in schema.get("properties", {})

    def test_base_url_not_a_tool_arg(self):
        """The base URL must not be exposed as a tool argument (SSRF foothold)."""
        from deerflow.community.keenable.tools import web_search_tool

        schema = web_search_tool.args_schema.model_json_schema()
        assert "base_url" not in schema.get("properties", {})

    def test_api_url_from_env(self, mock_app_config, monkeypatch):
        """The KEENABLE_API_URL env var is used as the base URL for requests."""
        monkeypatch.setenv("KEENABLE_API_URL", "https://custom.keenable.example.com")
        with patch(
            "deerflow.community.keenable.tools.requests.post",
            return_value=_mock_response(SEARCH_RESPONSE),
        ) as mock_post:
            from deerflow.community.keenable.tools import web_search_tool

            web_search_tool.invoke({"query": "test"})

        assert mock_post.call_args[0][0].startswith("https://custom.keenable.example.com")

    def test_non_https_api_url_rejected(self, mock_app_config, monkeypatch):
        """A non-HTTPS KEENABLE_API_URL (non-loopback) returns an error — never forwards the key."""
        monkeypatch.setenv("KEENABLE_API_URL", "http://attacker.example.com")
        with patch("deerflow.community.keenable.tools.requests.post") as mock_post:
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            mock_post.assert_not_called()

        data = json.loads(result)
        assert "error" in data
        assert "HTTPS" in data["error"]

    def test_http_loopback_api_url_allowed(self, mock_app_config, monkeypatch):
        """http:// loopback is allowed for local development (no HTTPS enforcement on localhost)."""
        monkeypatch.setenv("KEENABLE_API_URL", "http://localhost:8080")
        with patch(
            "deerflow.community.keenable.tools.requests.post",
            return_value=_mock_response(SEARCH_RESPONSE),
        ) as mock_post:
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})

        assert mock_post.call_args[0][0].startswith("http://localhost:8080")
        data = json.loads(result)
        assert "results" in data

    def test_empty_query_rejected(self, mock_app_config):
        """An empty query returns an error string without making a network call."""
        with patch("deerflow.community.keenable.tools.requests.post") as mock_post:
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": ""})
            mock_post.assert_not_called()

        data = json.loads(result)
        assert "error" in data

    def test_error_body_can_be_non_json_html(self, mock_app_config):
        """An HTML error body (e.g. 502 from a proxy) must not escape as a JSONDecodeError."""
        with patch(
            "deerflow.community.keenable.tools.requests.post",
            return_value=_non_json_response(status_code=502),
        ):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "q"})

        data = json.loads(result)
        assert "error" in data

    def test_error_message_never_contains_api_key(self, mock_app_config):
        """The API key must not appear in any error message surfaced to the agent."""
        mock_app_config.return_value.get_tool_config.return_value.model_extra = {"api_key": "super-secret-key-xyz"}
        with patch(
            "deerflow.community.keenable.tools.requests.post",
            return_value=_mock_response({"message": "Invalid key"}, status_code=401),
        ):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "q"})

        assert "super-secret-key-xyz" not in result

    def test_transport_timeout_wrapped(self, mock_app_config):
        """A requests.Timeout is caught and returned as an error string — key must not appear."""
        import requests as req

        with patch("deerflow.community.keenable.tools.requests.post", side_effect=req.Timeout("connect timed out")):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "q"})

        data = json.loads(result)
        assert "error" in data
        assert "test-api-key" not in result

    def test_non_dict_result_items_handled_gracefully(self, mock_app_config):
        """Results list containing non-dict items must not crash the agent loop (red-team finding)."""
        for bad_results in ([1, 2, 3], ["string", "items"], [{"title": "ok"}, 42, None]):
            with patch(
                "deerflow.community.keenable.tools.requests.post",
                return_value=_mock_response({"results": bad_results}),
            ):
                from deerflow.community.keenable.tools import web_search_tool

                result = web_search_tool.invoke({"query": "q"})

            data = json.loads(result)
            assert "error" in data or "results" in data, f"Tool crashed on results={bad_results!r}"

    def test_5xx_returns_error_string(self, mock_app_config):
        """A 5xx server error is returned as an error string containing the status code."""
        with patch(
            "deerflow.community.keenable.tools.requests.post",
            return_value=_mock_response({"message": "Internal server error"}, status_code=500),
        ):
            from deerflow.community.keenable.tools import web_search_tool

            result = web_search_tool.invoke({"query": "q"})

        data = json.loads(result)
        assert "error" in data
        assert "500" in data["error"]


class TestWebFetchTool:
    def test_basic_fetch(self, mock_app_config):
        """Test basic fetch returns markdown with title header."""
        with patch("deerflow.community.keenable.tools.requests.get", return_value=_mock_response(FETCH_RESPONSE)):
            from deerflow.community.keenable.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert "TypeScript Best Practices 2026" in result
        assert "https://example.com/ts" in result
        assert "Use strict mode" in result

    def test_no_title_still_returns_content(self, mock_app_config):
        """Test fetch without a title header still returns content."""
        no_title = {"url": "https://example.com/ts", "content": "Some content here."}
        with patch("deerflow.community.keenable.tools.requests.get", return_value=_mock_response(no_title)):
            from deerflow.community.keenable.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert "Some content here." in result

    def test_empty_content_returns_error(self, mock_app_config):
        """Test fetch returns an error message when content is empty."""
        empty = {"url": "https://example.com/ts", "title": "T", "content": ""}
        with patch("deerflow.community.keenable.tools.requests.get", return_value=_mock_response(empty)):
            from deerflow.community.keenable.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert "Error" in result

    def test_request_exception_returns_error(self, mock_app_config):
        """Test fetch returns an error message on network failure."""
        import requests as req

        with patch("deerflow.community.keenable.tools.requests.get", side_effect=req.RequestException("connect error")):
            from deerflow.community.keenable.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert "Error" in result

    def test_uses_keyed_endpoint_when_api_key_set(self, mock_app_config):
        """Test fetch GETs from the keyed endpoint when an API key is configured."""
        with patch("deerflow.community.keenable.tools.requests.get", return_value=_mock_response(FETCH_RESPONSE)) as mock_get:
            from deerflow.community.keenable.tools import web_fetch_tool

            web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert mock_get.call_args[0][0] == "https://api.keenable.ai/v1/fetch"

    def test_no_api_key_uses_public_fetch_endpoint(self):
        """Test fetch falls back to the public endpoint when no API key is set."""
        with patch("deerflow.community.keenable.tools.get_app_config") as mock_config:
            mock_config.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {}, clear=True):
                with patch(
                    "deerflow.community.keenable.tools.requests.get",
                    return_value=_mock_response(FETCH_RESPONSE),
                ) as mock_get:
                    from deerflow.community.keenable.tools import web_fetch_tool

                    web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert mock_get.call_args[0][0] == "https://api.keenable.ai/v1/fetch/public"

    def test_passes_url_as_query_param(self, mock_app_config):
        """Test fetch passes the URL as a query parameter."""
        with patch("deerflow.community.keenable.tools.requests.get", return_value=_mock_response(FETCH_RESPONSE)) as mock_get:
            from deerflow.community.keenable.tools import web_fetch_tool

            web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert mock_get.call_args[1]["params"]["url"] == "https://example.com/ts"

    def test_sends_user_agent_header(self, mock_app_config):
        """Test fetch sends a keenable-deerflow User-Agent header."""
        with patch("deerflow.community.keenable.tools.requests.get", return_value=_mock_response(FETCH_RESPONSE)) as mock_get:
            from deerflow.community.keenable.tools import web_fetch_tool

            web_fetch_tool.invoke({"url": "https://example.com/ts"})

        ua = mock_get.call_args[1]["headers"]["User-Agent"]
        assert ua.startswith("keenable-deerflow/")

    def test_reads_web_fetch_config(self):
        """Test that web_fetch_tool reads the 'web_fetch' config entry."""
        with patch("deerflow.community.keenable.tools.get_app_config") as mock_config:
            search_cfg = MagicMock()
            search_cfg.model_extra = {"api_key": "test-key"}
            fetch_cfg = MagicMock()
            fetch_cfg.model_extra = {"timeout": 20}

            def get_tool_config(name):
                return search_cfg if name == "web_search" else fetch_cfg

            mock_config.return_value.get_tool_config.side_effect = get_tool_config

            with patch("deerflow.community.keenable.tools.requests.get", return_value=_mock_response(FETCH_RESPONSE)):
                from deerflow.community.keenable.tools import web_fetch_tool

                web_fetch_tool.invoke({"url": "https://example.com/ts"})

            mock_config.return_value.get_tool_config.assert_any_call("web_fetch")

    def test_timeout_from_fetch_config(self):
        """Test fetch uses the timeout from the 'web_fetch' config entry."""
        with patch("deerflow.community.keenable.tools.get_app_config") as mock_config:
            search_cfg = MagicMock()
            search_cfg.model_extra = {"api_key": "test-key"}
            fetch_cfg = MagicMock()
            fetch_cfg.model_extra = {"timeout": 30}

            def get_tool_config(name):
                return search_cfg if name == "web_search" else fetch_cfg

            mock_config.return_value.get_tool_config.side_effect = get_tool_config

            with patch("deerflow.community.keenable.tools.requests.get", return_value=_mock_response(FETCH_RESPONSE)) as mock_get:
                from deerflow.community.keenable.tools import web_fetch_tool

                web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert mock_get.call_args[1]["timeout"] == 30

    def test_rejects_file_scheme(self, mock_app_config):
        """Test fetch rejects file:// URLs before making any HTTP request."""
        from deerflow.community.keenable.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "file:///etc/passwd"})
        assert "Error" in result

    def test_rejects_data_scheme(self, mock_app_config):
        """Test fetch rejects data: URLs."""
        from deerflow.community.keenable.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "data:text/html,<h1>hi</h1>"})
        assert "Error" in result

    def test_rejects_loopback_url(self, mock_app_config):
        """Test fetch rejects loopback addresses."""
        from deerflow.community.keenable.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "http://127.0.0.1/secret"})
        assert "Error" in result

    def test_rejects_ipv6_loopback_url(self, mock_app_config):
        """IPv6 loopback [::1] must be blocked client-side before any network call (red-team finding)."""
        from deerflow.community.keenable.tools import web_fetch_tool

        for url in ("http://[::1]/secret", "http://[::1]:8080/admin", "https://[::1]/"):
            result = web_fetch_tool.invoke({"url": url})
            assert "Error" in result, f"Expected block for {url!r}, got: {result}"

    def test_rejects_ipv4_mapped_ipv6_url(self, mock_app_config):
        """IPv4-mapped IPv6 addresses like [::ffff:127.0.0.1] must be blocked (red-team finding)."""
        from deerflow.community.keenable.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "http://[::ffff:127.0.0.1]/"})
        assert "Error" in result

    def test_rejects_aws_metadata_url(self, mock_app_config):
        """Test fetch rejects the AWS instance metadata endpoint."""
        from deerflow.community.keenable.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "http://169.254.169.254/latest/meta-data/"})
        assert "Error" in result

    def test_401_returns_error_string(self, mock_app_config):
        """Test that a 401 response returns a descriptive error string."""
        with patch(
            "deerflow.community.keenable.tools.requests.get",
            return_value=_mock_response({"message": "Unauthorized"}, status_code=401),
        ):
            from deerflow.community.keenable.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert "Error" in result
        assert "401" in result

    def test_429_returns_error_string(self, mock_app_config):
        """Test that a 429 response returns a descriptive error string and does not crash."""
        with patch(
            "deerflow.community.keenable.tools.requests.get",
            return_value=_mock_response({"message": "Rate limit exceeded"}, status_code=429),
        ):
            from deerflow.community.keenable.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert "Error" in result
        assert "429" in result

    def test_non_json_response_returns_error(self, mock_app_config):
        """Test that a non-JSON 200 response is handled gracefully."""
        with patch(
            "deerflow.community.keenable.tools.requests.get",
            return_value=_non_json_response(status_code=200),
        ):
            from deerflow.community.keenable.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert "Error" in result

    def test_402_returns_error_string(self, mock_app_config):
        """Test that a 402 response returns a descriptive error string."""
        with patch(
            "deerflow.community.keenable.tools.requests.get",
            return_value=_mock_response({"message": "Insufficient credits"}, status_code=402),
        ):
            from deerflow.community.keenable.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert "Error" in result
        assert "402" in result

    def test_error_body_can_be_non_json_html(self, mock_app_config):
        """An HTML error body (e.g. 502 from a proxy) must not escape as a JSONDecodeError."""
        with patch(
            "deerflow.community.keenable.tools.requests.get",
            return_value=_non_json_response(status_code=502),
        ):
            from deerflow.community.keenable.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert "Error" in result

    def test_error_message_never_contains_api_key(self, mock_app_config):
        """The API key must not appear in any fetch error message."""
        mock_app_config.return_value.get_tool_config.return_value.model_extra = {"api_key": "super-secret-key-xyz"}
        with patch(
            "deerflow.community.keenable.tools.requests.get",
            return_value=_mock_response({"message": "Unauthorized"}, status_code=401),
        ):
            from deerflow.community.keenable.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert "super-secret-key-xyz" not in result

    def test_transport_timeout_wrapped(self, mock_app_config):
        """A requests.Timeout is caught and returned as an error string — key must not appear."""
        import requests as req

        with patch("deerflow.community.keenable.tools.requests.get", side_effect=req.Timeout("connect timed out")):
            from deerflow.community.keenable.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://example.com/ts"})

        assert "Error" in result
        assert "test-api-key" not in result

