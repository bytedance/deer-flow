"""Unit tests for the Tencent Cloud Web Search API community provider."""

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    import deerflow.community.tencent_wsa.tools as wsa

    wsa._api_key_warned = set()
    yield
    wsa._api_key_warned = set()


def _tool_config(extras: dict | None) -> MagicMock:
    config = MagicMock()
    config.model_extra = extras
    return config


def _response(pages: list[object] | None = None, **extra: object) -> dict:
    response: dict[str, object] = {"RequestId": "request-123"}
    if pages is not None:
        response["Pages"] = pages
    response.update(extra)
    return {"Response": response}


def _mock_http_client(response: MagicMock, *, asynchronous: bool = False):
    client = MagicMock()
    client.post = AsyncMock(return_value=response) if asynchronous else MagicMock(return_value=response)
    context_manager = MagicMock()
    context_manager.__enter__.return_value = client
    context_manager.__exit__.return_value = False
    context_manager.__aenter__ = AsyncMock(return_value=client)
    context_manager.__aexit__ = AsyncMock(return_value=False)
    return client, context_manager


class _Invocation:
    @pytest.fixture(params=["sync", "async"], autouse=True)
    def invocation(self, request):
        from deerflow.community.tencent_wsa.tools import web_search_tool

        self.asynchronous = request.param == "async"
        self.client_type = "deerflow.community.tencent_wsa.tools.httpx." + ("AsyncClient" if self.asynchronous else "Client")
        self.invoke = (lambda args: asyncio.run(web_search_tool.ainvoke(args))) if self.asynchronous else web_search_tool.invoke

    def mock_client(self, response):
        return _mock_http_client(response, asynchronous=self.asynchronous)


class TestTencentWsaApiKey(_Invocation):
    def test_config_key_takes_precedence_over_environment(self, monkeypatch):
        monkeypatch.setenv("TENCENTCLOUD_WSA_APIKEY", "environment-key")
        with patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config:
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "config-key"})

            from deerflow.community.tencent_wsa.tools import _get_api_key

            assert _get_api_key() == "config-key"

    def test_environment_key_is_used_as_fallback(self, monkeypatch):
        monkeypatch.setenv("TENCENTCLOUD_WSA_APIKEY", "environment-key")
        with patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config:
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": " "})

            from deerflow.community.tencent_wsa.tools import _get_api_key

            assert _get_api_key() == "environment-key"

    def test_missing_key_returns_a_structured_error(self, monkeypatch):
        monkeypatch.delenv("TENCENTCLOUD_WSA_APIKEY", raising=False)
        with patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config:
            get_config.return_value.get_tool_config.return_value = _tool_config({})

            result = json.loads(self.invoke({"query": "腾讯云"}))

        assert result == {
            "error": "TENCENTCLOUD_WSA_APIKEY is not configured",
            "query": "腾讯云",
        }


class TestTencentWsaSearch(_Invocation):
    def test_search_normalizes_documented_pages_and_honors_config(self):
        page_one = json.dumps(
            {
                "title": "第一条",
                "url": "https://example.com/one",
                "passage": "摘要一",
                "date": "2026-08-27",
                "site": "示例站点",
                "score": 0.9,
            }
        )
        page_two = json.dumps(
            {
                "title": "第二条",
                "url": "https://example.com/two",
                "content": "动态摘要二",
            }
        )
        http_response = MagicMock()
        http_response.json.return_value = _response([page_one, page_two])
        client, context_manager = self.mock_client(http_response)

        with (
            patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config,
            patch(self.client_type, return_value=context_manager),
        ):
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "test-key", "max_results": 1, "mode": 2})

            result = json.loads(self.invoke({"query": "  腾讯云搜索  ", "max_results": 99}))

        client.post.assert_called_once_with(
            "https://api.wsa.cloud.tencent.com/SearchPro",
            headers={
                "Authorization": "Bearer test-key",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={"Query": "腾讯云搜索", "Mode": 2},
        )
        assert get_config.call_count == 1
        assert result == {
            "query": "腾讯云搜索",
            "total_results": 1,
            "request_id": "request-123",
            "results": [
                {
                    "title": "第一条",
                    "url": "https://example.com/one",
                    "snippet": "摘要一",
                    "date": "2026-08-27",
                    "site": "示例站点",
                    "score": 0.9,
                }
            ],
        }

    def test_search_omits_mode_when_not_configured(self):
        http_response = MagicMock()
        http_response.json.return_value = _response([json.dumps({"title": "结果", "passage": "摘要"})])
        client, context_manager = self.mock_client(http_response)

        with (
            patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config,
            patch(self.client_type, return_value=context_manager),
        ):
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "test-key"})

            self.invoke({"query": "腾讯云"})

        assert client.post.call_args.kwargs["json"] == {"Query": "腾讯云"}

    def test_search_requests_supported_cnt_for_more_than_default_results(self):
        pages = [json.dumps({"title": f"结果 {index}", "passage": "摘要"}) for index in range(20)]
        http_response = MagicMock()
        http_response.json.return_value = _response(pages)
        client, context_manager = self.mock_client(http_response)

        with (
            patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config,
            patch(self.client_type, return_value=context_manager),
        ):
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "test-key"})

            result = json.loads(self.invoke({"query": "腾讯云", "max_results": 20}))

        assert client.post.call_args.kwargs["json"] == {"Query": "腾讯云", "Cnt": 20}
        assert result["total_results"] == 20

    def test_empty_query_does_not_call_paid_api(self):
        with (
            patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config,
            patch(self.client_type) as client,
        ):
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "test-key"})

            result = json.loads(self.invoke({"query": "  "}))

        assert result == {"error": "Search query must not be empty", "query": ""}
        client.assert_not_called()

    def test_search_skips_malformed_pages_without_losing_valid_results(self):
        http_response = MagicMock()
        http_response.json.return_value = _response(["not-json", 42, json.dumps({"title": "有效结果", "url": "https://example.com", "passage": "摘要"})])
        _, context_manager = self.mock_client(http_response)

        with (
            patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config,
            patch(self.client_type, return_value=context_manager),
        ):
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "test-key"})

            result = json.loads(self.invoke({"query": "腾讯云"}))

        assert result["total_results"] == 1
        assert result["results"][0]["title"] == "有效结果"

    def test_response_error_is_reported_even_with_http_200(self):
        http_response = MagicMock()
        http_response.json.return_value = _response(Error={"Code": "RequestLimitExceeded", "Message": "do not expose this"})
        _, context_manager = self.mock_client(http_response)

        with (
            patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config,
            patch(self.client_type, return_value=context_manager),
        ):
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "test-key"})

            result = json.loads(self.invoke({"query": "腾讯云"}))

        assert result == {
            "error": "Tencent Cloud WSA API error: RequestLimitExceeded",
            "query": "腾讯云",
            "request_id": "request-123",
        }

    def test_http_error_does_not_expose_upstream_body(self):
        response = MagicMock()
        response.status_code = 503
        response.text = "sensitive upstream diagnostic"
        http_response = MagicMock()
        http_response.raise_for_status.side_effect = httpx.HTTPStatusError("unavailable", request=MagicMock(), response=response)
        client, context_manager = self.mock_client(http_response)

        with (
            patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config,
            patch(self.client_type, return_value=context_manager),
        ):
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "test-key"})

            result = json.loads(self.invoke({"query": "腾讯云"}))

        assert result == {"error": "Tencent Cloud WSA API error: HTTP 503", "query": "腾讯云"}
        assert "sensitive" not in json.dumps(result)
        client.post.assert_called_once()

    @pytest.mark.parametrize(
        ("failure", "expected"),
        [
            (httpx.ReadTimeout("timed out"), "Tencent Cloud WSA request failed"),
            (httpx.ConnectError("connection failed"), "Tencent Cloud WSA request failed"),
            (ValueError("invalid JSON"), "Tencent Cloud WSA returned an invalid JSON response"),
            (["unexpected"], "Tencent Cloud WSA returned an unexpected response format"),
        ],
    )
    def test_transport_and_decode_errors_keep_structured_contract(self, failure, expected):
        response = MagicMock()
        client, context_manager = self.mock_client(response)
        if isinstance(failure, httpx.HTTPError):
            client.post.side_effect = failure
        elif isinstance(failure, ValueError):
            response.json.side_effect = failure
        else:
            response.json.return_value = failure
        with (
            patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config,
            patch(self.client_type, return_value=context_manager),
        ):
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "test-key"})
            assert json.loads(self.invoke({"query": "example"})) == {"error": expected, "query": "example"}

    def test_non_list_pages_returns_unexpected_format_error(self):
        http_response = MagicMock()
        http_response.json.return_value = _response("not-a-list")
        _, context_manager = self.mock_client(http_response)

        with (
            patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config,
            patch(self.client_type, return_value=context_manager),
        ):
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "test-key"})

            result = json.loads(self.invoke({"query": "腾讯云"}))

        assert result == {
            "error": "Tencent Cloud WSA returned an unexpected response format",
            "query": "腾讯云",
            "request_id": "request-123",
        }

    @pytest.mark.parametrize("pages", [["junk", 3, None], [12345], [[]], [False], ["not-json"]])
    def test_pages_without_any_usable_objects_return_format_error(self, pages, caplog):
        """A non-empty Pages container holding no usable page is malformed, not an empty search.

        Reporting "No results found" for it would tell the agent the query
        legitimately matched nothing, hiding a broken upstream payload.
        """
        http_response = MagicMock()
        http_response.json.return_value = _response(pages)
        _, context_manager = self.mock_client(http_response)

        with (
            patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config,
            patch(self.client_type, return_value=context_manager),
            caplog.at_level(logging.ERROR),
        ):
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "test-key"})

            result = json.loads(self.invoke({"query": "腾讯云"}))

        assert result["error"] == "Tencent Cloud WSA returned an unexpected response format"
        assert any("no usable page objects" in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)

    def test_pages_with_some_usable_objects_keep_them(self):
        """One usable page among malformed entries keeps the existing skip-and-keep behavior."""
        http_response = MagicMock()
        http_response.json.return_value = _response(["not-json", 42, {"title": "Kept", "url": "https://example.com", "content": "Body"}])
        _, context_manager = self.mock_client(http_response)

        with (
            patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config,
            patch(self.client_type, return_value=context_manager),
        ):
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "test-key"})

            result = json.loads(self.invoke({"query": "腾讯云"}))

        assert result["total_results"] == 1
        assert result["results"][0]["title"] == "Kept"

    def test_empty_and_missing_pages_keep_no_results(self):
        """A missing or empty Pages container stays a legitimate empty search."""
        for pages in ([], None):
            http_response = MagicMock()
            http_response.json.return_value = _response(pages)
            _, context_manager = self.mock_client(http_response)

            with (
                patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config,
                patch(self.client_type, return_value=context_manager),
            ):
                get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "test-key"})

                result = json.loads(self.invoke({"query": "腾讯云"}))

            assert result == {"error": "No results found", "query": "腾讯云", "request_id": "request-123"}


class TestTencentWsaConfiguration(_Invocation):
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (3, 3),
            ("7", 7),
            (True, 5),
            (2.9, 5),
            (0, 5),
            (-1, 5),
            (500, 50),
            ("bad", 5),
            # str.isdigit() is true for these, but int() raises ValueError (#6921).
            ("²", 5),
            ("1²", 5),
            # Valid non-ASCII decimal digits must still parse.
            ("٣", 3),
        ],
    )
    def test_coerce_max_results(self, value, expected):
        from deerflow.community.tencent_wsa.tools import _coerce_max_results

        assert _coerce_max_results(value) == expected

    def test_configured_unparseable_digit_max_results_falls_back(self):
        """Config max_results that passes isdigit but fails int must not crash invoke."""
        page = json.dumps(
            {
                "title": "ok",
                "url": "https://example.com",
                "content": "snippet",
            },
            ensure_ascii=False,
        )
        http_response = MagicMock()
        http_response.json.return_value = _response([page])
        _client, context_manager = self.mock_client(http_response)

        with (
            patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config,
            patch(self.client_type, return_value=context_manager),
        ):
            get_config.return_value.get_tool_config.return_value = _tool_config({"api_key": "test-key", "max_results": "²"})

            result = json.loads(self.invoke({"query": "腾讯云"}))

        assert "error" not in result
        assert result["query"] == "腾讯云"
        assert result["total_results"] == 1
        assert result["results"][0]["title"] == "ok"

    @pytest.mark.parametrize("value", (None, "2", True, 2.0, "bad", -1, 3))
    def test_invalid_mode_is_omitted(self, value):
        with patch("deerflow.community.tencent_wsa.tools.get_app_config") as get_config:
            extras = {} if value is None else {"mode": value}
            get_config.return_value.get_tool_config.return_value = _tool_config(extras)

            from deerflow.community.tencent_wsa.tools import _get_mode

            assert _get_mode() is None
