"""Unit tests for the cloro community web search tool."""

import json
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the module-level warning flag before each test."""
    import deerflow.community.cloro.tools as cloro_mod

    cloro_mod._api_key_warned = set()
    yield
    cloro_mod._api_key_warned = set()


def _patch_config(extra: dict | None):
    """Patch get_app_config so web_search resolves to a tool config with ``extra``."""
    patcher = patch("deerflow.community.cloro.tools.get_app_config")
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
    patcher, mock = _patch_config({"api_key": "test-cloro-key", "max_results": 5})
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


def _organic_rows(n: int) -> list[dict]:
    """Rows in the shape that ``POST /v1/monitor/google`` returns."""
    return [
        {
            "position": i,
            "title": f"Result {i}",
            "link": f"https://example.com/{i}",
            "displayedLink": f"https://example.com > {i}",
            "snippet": f"Snippet {i}",
            "page": 1,
            "redirectLink": f"https://www.google.com/goto?url=CAES{i}",
        }
        for i in range(1, n + 1)
    ]


def _google_payload(rows: object, **extra: object) -> dict:
    return {"success": True, "result": {"organicResults": rows, **extra}}


def _run(query: str = "test query", max_results: int = 5) -> dict:
    from deerflow.community.cloro.tools import web_search_tool

    return json.loads(web_search_tool.invoke({"query": query, "max_results": max_results}))


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        patcher, _ = _patch_config({"api_key": "from-config"})
        try:
            from deerflow.community.cloro.tools import _get_api_key

            assert _get_api_key("web_search") == "from-config"
        finally:
            patcher.stop()

    def test_falls_back_to_env_when_config_key_blank(self):
        patcher, _ = _patch_config({"api_key": "   "})
        try:
            with patch.dict("os.environ", {"CLORO_API_KEY": "env-key"}):
                from deerflow.community.cloro.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"
        finally:
            patcher.stop()

    def test_returns_none_when_no_key_anywhere(self):
        patcher, _ = _patch_config(None)
        try:
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.cloro.tools import _get_api_key

                assert _get_api_key("web_search") is None
        finally:
            patcher.stop()


class TestCountForRequest:
    def test_returns_value_when_valid(self):
        from deerflow.community.cloro.tools import _count_for_request

        assert _count_for_request(3) == 3
        assert _count_for_request("7") == 7

    def test_caps_at_one_results_page(self):
        from deerflow.community.cloro.tools import _count_for_request

        assert _count_for_request(50) == 10

    def test_invalid_values_fall_back_to_default(self, caplog):
        from deerflow.community.cloro.tools import _count_for_request

        with caplog.at_level(logging.WARNING):
            assert _count_for_request("oops") == 5
            assert _count_for_request(True) == 5
            assert _count_for_request(float("inf")) == 5
        assert "Invalid cloro max_results" in caplog.text


class TestResolveCountry:
    def test_default_and_valid_codes(self):
        from deerflow.community.cloro.tools import _resolve_country

        assert _resolve_country(None) == "US"
        assert _resolve_country(" de ") == "DE"

    def test_invalid_code_falls_back_to_us(self, caplog):
        from deerflow.community.cloro.tools import _resolve_country

        with caplog.at_level(logging.WARNING):
            assert _resolve_country("Germany") == "US"
        assert "Invalid cloro country" in caplog.text


class TestWebSearchTool:
    def test_basic_search_returns_normalized_results(self, mock_config_with_key):
        with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = _make_response(_google_payload(_organic_rows(2)))
            result = _run("test query")

        assert result == {
            "query": "test query",
            "total_results": 2,
            "results": [
                {"title": "Result 1", "url": "https://example.com/1", "content": "Snippet 1"},
                {"title": "Result 2", "url": "https://example.com/2", "content": "Snippet 2"},
            ],
        }

    def test_sends_correct_headers_and_body(self, mock_config_with_key):
        with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = _make_response(_google_payload(_organic_rows(1)))
            _run("  padded query  ")

        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.cloro.dev/v1/monitor/google"
        assert kwargs["headers"]["Authorization"] == "Bearer test-cloro-key"
        assert kwargs["json"] == {"query": "padded query", "country": "US"}

    def test_country_and_ai_overview_from_config(self):
        patcher, _ = _patch_config({"api_key": "k", "country": "gb", "ai_overview": True})
        try:
            with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
                mock_post = mock_client.return_value.__enter__.return_value.post
                mock_post.return_value = _make_response(_google_payload(_organic_rows(1)))
                _run("q")
        finally:
            patcher.stop()

        assert mock_post.call_args.kwargs["json"] == {"query": "q", "country": "GB", "include": {"aioverview": True}}

    def test_ai_overview_is_returned_when_enabled(self):
        overview = {
            "text": "  An overview.  ",
            "sources": [
                {"label": "Source A", "url": "https://a.example.com/", "position": 1},
                {"label": "Redirect only", "url": "https://www.google.com/goto?url=X", "position": 2},
                "junk",
            ],
            "citationPills": [],
        }
        patcher, _ = _patch_config({"api_key": "k", "ai_overview": True})
        try:
            with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
                mock_client.return_value.__enter__.return_value.post.return_value = _make_response(_google_payload(_organic_rows(1), aioverview=overview))
                result = _run("q")
        finally:
            patcher.stop()

        assert result["ai_overview"] == {"text": "An overview.", "sources": [{"title": "Source A", "url": "https://a.example.com/"}]}

    def test_ai_overview_is_ignored_when_not_enabled(self, mock_config_with_key):
        with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = _make_response(_google_payload(_organic_rows(1), aioverview={"text": "x", "sources": []}))
            result = _run("q")

        assert "ai_overview" not in result

    def test_people_also_ask_questions_are_returned(self, mock_config_with_key):
        paa = [{"question": "What is X?", "type": "AIOVERVIEW"}, {"question": "  "}, "junk", {"question": "Why X?"}]
        with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = _make_response(_google_payload(_organic_rows(1), peopleAlsoAsk=paa))
            result = _run("q")

        assert result["people_also_ask"] == ["What is X?", "Why X?"]

    def test_empty_and_redirect_links_are_skipped_before_the_cap(self):
        rows = [
            {"title": "Empty link", "link": "", "snippet": "a"},
            {"title": "Redirect", "link": "https://www.google.com/goto?url=CAES", "snippet": "b"},
            {"title": "Private", "link": "http://127.0.0.1/admin", "snippet": "c"},
            *_organic_rows(3),
        ]
        patcher, _ = _patch_config({"api_key": "k", "max_results": 2})
        try:
            with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
                mock_client.return_value.__enter__.return_value.post.return_value = _make_response(_google_payload(rows))
                result = _run("q", max_results=5)
        finally:
            patcher.stop()

        assert [r["url"] for r in result["results"]] == ["https://example.com/1", "https://example.com/2"]

    def test_empty_results_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = _make_response(_google_payload([]))
            assert _run("nothing") == {"error": "No results found", "query": "nothing"}

        with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = _make_response({"success": True, "result": {}})
            assert _run("nothing") == {"error": "No results found", "query": "nothing"}

    @pytest.mark.parametrize(
        "payload",
        [
            ["not", "a", "dict"],
            {"success": True},
            {"success": True, "result": "text"},
            _google_payload("not-a-list"),
            _google_payload(["junk", 3]),
        ],
        ids=["list-payload", "no-result", "result-not-object", "rows-not-list", "rows-without-objects"],
    )
    def test_malformed_payload_returns_format_error(self, mock_config_with_key, payload):
        with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = _make_response(payload)
            assert _run("q") == {"error": "cloro returned an unexpected response format", "query": "q"}

    def test_missing_api_key_returns_error_json_and_warns_once(self, mock_config_no_key, caplog):
        with patch.dict("os.environ", {}, clear=True), caplog.at_level(logging.WARNING):
            first = _run("q")
            second = _run("q")

        assert first == {"error": "CLORO_API_KEY is not configured", "query": "q"}
        assert second == first
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "CLORO_API_KEY" in warnings[0].getMessage()

    @pytest.mark.parametrize("status", [401, 403, 429])
    def test_http_error_returns_structured_error(self, mock_config_with_key, status):
        mock_resp = MagicMock()
        mock_resp.status_code = status
        mock_resp.text = '{"success":false,"error":{"code":"X","message":"Y"}}'
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(str(status), request=MagicMock(), response=mock_resp)
        with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_resp
            result = _run("q")

        assert result == {"error": f"cloro API error: HTTP {status}", "query": "q"}

    def test_network_exception_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = httpx.ConnectError("boom")
            result = _run("q")

        assert result == {"error": "boom", "query": "q"}

    def test_long_query_is_truncated(self, mock_config_with_key):
        with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
            mock_post = mock_client.return_value.__enter__.return_value.post
            mock_post.return_value = _make_response(_google_payload(_organic_rows(1)))
            _run("x" * 600)

        assert len(mock_post.call_args.kwargs["json"]["query"]) == 500

    def test_uses_env_key_when_config_absent(self):
        patcher, _ = _patch_config(None)
        try:
            with patch.dict("os.environ", {"CLORO_API_KEY": "env-key"}):
                with patch("deerflow.community.cloro.tools.httpx.Client") as mock_client:
                    mock_post = mock_client.return_value.__enter__.return_value.post
                    mock_post.return_value = _make_response(_google_payload(_organic_rows(1)))
                    result = _run("q")
        finally:
            patcher.stop()

        assert result["total_results"] == 1
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer env-key"
