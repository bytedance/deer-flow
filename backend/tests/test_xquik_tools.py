"""Unit tests for the Xquik community X search tool."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warning():
    """Keep warning assertions independent between tests."""
    import deerflow.community.xquik.tools as xquik_tools

    xquik_tools._api_key_warned = False
    yield
    xquik_tools._api_key_warned = False


@pytest.fixture
def configured_tool():
    with patch("deerflow.community.xquik.tools.get_app_config") as get_app_config:
        tool_config = MagicMock()
        tool_config.model_extra = {"api_key": " test-xquik-key ", "max_results": 3}
        get_app_config.return_value.get_tool_config.return_value = tool_config
        yield get_app_config


def _response(payload: object, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("GET", "https://xquik.com/api/v1/x/tweets/search")
    return httpx.Response(status_code, request=request, json=payload)


class TestConfiguration:
    def test_config_key_takes_precedence_and_is_trimmed(self, monkeypatch):
        monkeypatch.setenv("XQUIK_API_KEY", "env-key")
        with patch("deerflow.community.xquik.tools.get_app_config") as get_app_config:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": " config-key "}
            get_app_config.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.xquik.tools import _get_api_key

            assert _get_api_key() == "config-key"

    def test_empty_config_key_falls_back_to_environment(self, monkeypatch):
        monkeypatch.setenv("XQUIK_API_KEY", " env-key ")
        with patch("deerflow.community.xquik.tools.get_app_config") as get_app_config:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "  "}
            get_app_config.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.xquik.tools import _get_api_key

            assert _get_api_key() == "env-key"

    def test_missing_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("XQUIK_API_KEY", raising=False)
        with patch("deerflow.community.xquik.tools.get_app_config") as get_app_config:
            get_app_config.return_value.get_tool_config.return_value = None

            from deerflow.community.xquik.tools import _get_api_key

            assert _get_api_key() is None

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(None, 5), ("bad", 5), (0, 5), (-2, 5), ("7", 7), (250, 100)],
    )
    def test_result_limit_is_bounded(self, value, expected):
        from deerflow.community.xquik.tools import _coerce_max_results

        assert _coerce_max_results(value) == expected


class TestXSearchTool:
    def test_returns_structured_posts_and_request_metadata(self, configured_tool):
        payload = {
            "tweets": [
                {
                    "id": "123",
                    "text": "DeerFlow release notes",
                    "url": "https://x.com/alice/status/123",
                    "createdAt": "2026-08-18T00:00:00Z",
                    "likeCount": 4,
                    "retweetCount": 3,
                    "replyCount": 2,
                    "quoteCount": 1,
                    "viewCount": 99,
                    "bookmarkCount": 5,
                    "author": {
                        "id": "7",
                        "username": "alice",
                        "name": "Alice",
                        "verified": True,
                    },
                }
            ],
            "has_next_page": True,
            "next_cursor": "cursor-2",
        }

        with patch("deerflow.community.xquik.tools.httpx.get", return_value=_response(payload)) as http_get:
            from deerflow.community.xquik.tools import x_search_tool

            result = json.loads(x_search_tool.invoke({"query": "DeerFlow", "query_type": "Top"}))

        assert result == {
            "posts": [
                {
                    "id": "123",
                    "text": "DeerFlow release notes",
                    "url": "https://x.com/alice/status/123",
                    "author": {"id": "7", "username": "alice", "name": "Alice", "verified": True},
                    "created_at": "2026-08-18T00:00:00Z",
                    "metrics": {"likes": 4, "reposts": 3, "replies": 2, "quotes": 1, "views": 99, "bookmarks": 5},
                }
            ],
            "count": 1,
            "has_next_page": True,
            "next_cursor": "cursor-2",
        }
        http_get.assert_called_once_with(
            "https://xquik.com/api/v1/x/tweets/search",
            params={"q": "DeerFlow", "queryType": "Top", "limit": 3},
            headers={"accept": "application/json", "x-api-key": "test-xquik-key"},
            timeout=30.0,
            follow_redirects=False,
        )

    def test_passes_a_trimmed_cursor_for_pagination(self, configured_tool):
        payload = {"tweets": [], "has_next_page": False, "next_cursor": ""}
        with patch("deerflow.community.xquik.tools.httpx.get", return_value=_response(payload)) as http_get:
            from deerflow.community.xquik.tools import x_search_tool

            result = json.loads(x_search_tool.invoke({"query": "updates", "cursor": "  page-2  "}))

        assert result["count"] == 0
        assert http_get.call_args.kwargs["params"]["cursor"] == "page-2"

    def test_omits_an_empty_cursor(self, configured_tool):
        payload = {"tweets": [], "has_next_page": False, "next_cursor": ""}
        with patch("deerflow.community.xquik.tools.httpx.get", return_value=_response(payload)) as http_get:
            from deerflow.community.xquik.tools import x_search_tool

            x_search_tool.invoke({"query": "updates", "cursor": "   "})

        assert "cursor" not in http_get.call_args.kwargs["params"]

    def test_rejects_an_empty_query_without_network_access(self, configured_tool):
        with patch("deerflow.community.xquik.tools.httpx.get") as http_get:
            from deerflow.community.xquik.tools import x_search_tool

            result = json.loads(x_search_tool.invoke({"query": "   "}))

        assert result == {"error": "query must not be empty"}
        http_get.assert_not_called()

    def test_missing_key_returns_actionable_error_and_warns_once(self, monkeypatch, caplog):
        monkeypatch.delenv("XQUIK_API_KEY", raising=False)
        with patch("deerflow.community.xquik.tools.get_app_config") as get_app_config:
            get_app_config.return_value.get_tool_config.return_value = None
            with patch("deerflow.community.xquik.tools.httpx.get") as http_get:
                from deerflow.community.xquik.tools import x_search_tool

                first = json.loads(x_search_tool.invoke({"query": "first"}))
                second = json.loads(x_search_tool.invoke({"query": "second"}))

        assert first == {"error": "XQUIK_API_KEY is not configured"}
        assert second == first
        assert sum("XQUIK_API_KEY" in record.getMessage() for record in caplog.records) == 1
        http_get.assert_not_called()

    def test_query_and_cursor_lengths_are_bounded(self, configured_tool):
        payload = {"tweets": [], "has_next_page": False, "next_cursor": ""}
        with patch("deerflow.community.xquik.tools.httpx.get", return_value=_response(payload)) as http_get:
            from deerflow.community.xquik.tools import x_search_tool

            x_search_tool.invoke({"query": f"  {'q' * 700}  ", "cursor": "c" * 5000})

        params = http_get.call_args.kwargs["params"]
        assert params["q"] == "q" * 500
        assert params["cursor"] == "c" * 4096

    def test_response_is_capped_even_if_provider_returns_extra_posts(self, configured_tool):
        configured_tool.return_value.get_tool_config.return_value.model_extra["max_results"] = 2
        payload = {
            "tweets": [{"id": str(index), "text": f"post {index}", "author": {"username": "alice"}} for index in range(3)],
            "has_next_page": False,
            "next_cursor": "",
        }
        with patch("deerflow.community.xquik.tools.httpx.get", return_value=_response(payload)):
            from deerflow.community.xquik.tools import x_search_tool

            result = json.loads(x_search_tool.invoke({"query": "updates"}))

        assert result["count"] == 2
        assert [post["id"] for post in result["posts"]] == ["0", "1"]

    def test_normalizes_snake_case_contract_fields(self, configured_tool):
        payload = {
            "tweets": [
                {
                    "id": "321",
                    "text": "snake case",
                    "created_at": 1787011200,
                    "like_count": 8,
                    "retweet_count": 7,
                    "reply_count": 6,
                    "quote_count": 5,
                    "view_count": 4,
                    "bookmark_count": 3,
                    "author": {"id": "9", "username": "bob", "name": "Bob", "is_verified": True},
                }
            ],
            "has_more": False,
            "next_cursor": "",
        }
        with patch("deerflow.community.xquik.tools.httpx.get", return_value=_response(payload)):
            from deerflow.community.xquik.tools import x_search_tool

            result = json.loads(x_search_tool.invoke({"query": "updates"}))

        post = result["posts"][0]
        assert post["created_at"] == 1787011200
        assert post["author"]["verified"] is True
        assert post["metrics"] == {"likes": 8, "reposts": 7, "replies": 6, "quotes": 5, "views": 4, "bookmarks": 3}
        assert result["has_next_page"] is False

    def test_discards_malformed_posts_and_untrusted_urls(self, configured_tool):
        payload = {
            "tweets": [
                None,
                {"id": "missing-text"},
                {"id": "1", "text": "safe fallback", "url": "http://127.0.0.1/private", "author": {"username": "alice"}},
                {"id": "2", "text": "no safe URL", "url": "javascript:alert(1)", "author": {}},
            ],
            "has_next_page": False,
            "next_cursor": "",
        }
        with patch("deerflow.community.xquik.tools.httpx.get", return_value=_response(payload)):
            from deerflow.community.xquik.tools import x_search_tool

            result = json.loads(x_search_tool.invoke({"query": "updates"}))

        assert [post["url"] for post in result["posts"]] == ["https://x.com/alice/status/1", ""]

    def test_bounds_untrusted_response_strings(self, configured_tool):
        payload = {
            "tweets": [
                {
                    "id": "1" * 100,
                    "text": "t" * 5000,
                    "url": f"https://x.com/{'u' * 3000}",
                    "createdAt": "c" * 200,
                    "author": {"id": "a" * 100, "username": "u" * 100, "name": "n" * 500},
                }
            ],
            "has_next_page": True,
            "next_cursor": "c" * 5000,
        }
        with patch("deerflow.community.xquik.tools.httpx.get", return_value=_response(payload)):
            from deerflow.community.xquik.tools import x_search_tool

            result = json.loads(x_search_tool.invoke({"query": "updates"}))

        post = result["posts"][0]
        assert len(post["id"]) == 64
        assert len(post["text"]) == 4096
        assert post["url"] == ""
        assert len(post["created_at"]) == 64
        assert len(post["author"]["id"]) == 64
        assert len(post["author"]["username"]) == 64
        assert len(post["author"]["name"]) == 256
        assert len(result["next_cursor"]) == 4096

    @pytest.mark.parametrize(
        ("failure", "expected"),
        [
            (_response({"private": "do-not-return"}, status_code=401), {"error": "Xquik request failed", "status_code": 401}),
            (httpx.ConnectError("network detail", request=httpx.Request("GET", "https://xquik.com")), {"error": "Xquik request failed"}),
        ],
    )
    def test_request_failures_are_sanitized(self, configured_tool, failure, expected):
        with patch("deerflow.community.xquik.tools.httpx.get") as http_get:
            if isinstance(failure, httpx.Response):
                http_get.return_value = failure
            else:
                http_get.side_effect = failure

            from deerflow.community.xquik.tools import x_search_tool

            result = json.loads(x_search_tool.invoke({"query": "updates"}))

        assert result == expected
        assert "do-not-return" not in json.dumps(result)
        assert "test-xquik-key" not in json.dumps(result)

    def test_invalid_json_is_sanitized(self, configured_tool):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("response body detail")
        with patch("deerflow.community.xquik.tools.httpx.get", return_value=response):
            from deerflow.community.xquik.tools import x_search_tool

            result = json.loads(x_search_tool.invoke({"query": "updates"}))

        assert result == {"error": "Xquik returned invalid JSON"}

    def test_unexpected_payload_is_rejected(self, configured_tool):
        with patch("deerflow.community.xquik.tools.httpx.get", return_value=_response({"tweets": "not-a-list"})):
            from deerflow.community.xquik.tools import x_search_tool

            result = json.loads(x_search_tool.invoke({"query": "updates"}))

        assert result == {"error": "Xquik returned an unexpected response format"}
