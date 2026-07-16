"""Unit tests for the Brave Search community web search tool."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the module-level warning flag before each test."""
    import deerflow.community.brave.tools as brave_mod

    brave_mod._api_key_warned = set()
    yield
    brave_mod._api_key_warned = set()


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


def _make_brave_images_response(results: list | object) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": results}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _count_aware_get(results: list):
    """Mimic Brave returning at most `count` results for the request."""

    def _get(url, **kwargs):
        count = kwargs["params"]["count"]
        return _make_brave_response(results[:count])

    return _get


def _image_count_aware_get(results: list):
    """Mimic Brave Image Search returning at most `count` results for the request."""

    def _get(url, **kwargs):
        count = kwargs["params"]["count"]
        return _make_brave_images_response(results[:count])

    return _get


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        with patch("deerflow.community.brave.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "from-config"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.brave.tools import _get_api_key

            assert _get_api_key() == "from-config"

    def test_reads_config_for_requested_tool_name(self):
        with patch("deerflow.community.brave.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "image-key"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.brave.tools import _get_api_key

            assert _get_api_key("image_search") == "image-key"
            mock.return_value.get_tool_config.assert_called_with("image_search")

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

    def test_long_query_is_truncated_to_brave_limit(self, mock_config_with_key):
        results = [{"title": "T", "url": "https://x.com", "description": "D"}]
        mock_resp = _make_brave_response(results)

        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_get = mock_client_cls.return_value.__enter__.return_value.get
            mock_get.return_value = mock_resp

            from deerflow.community.brave.tools import web_search_tool

            result = web_search_tool.invoke({"query": "a" * 500})
            parsed = json.loads(result)
            params = mock_get.call_args.kwargs["params"]

        assert len(params["q"]) == 400
        assert parsed["query"] == "a" * 400

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


class TestSafePublicUrl:
    def test_https_public_hostname_passes(self):
        from deerflow.community.brave.tools import _safe_public_url

        assert _safe_public_url("https://example.com/i.jpg") == "https://example.com/i.jpg"

    def test_non_http_scheme_is_filtered(self):
        from deerflow.community.brave.tools import _safe_public_url

        assert _safe_public_url("file:///etc/passwd") == ""

    def test_localhost_is_filtered(self):
        from deerflow.community.brave.tools import _safe_public_url

        assert _safe_public_url("http://localhost/i.jpg") == ""

    def test_private_ip_is_filtered(self):
        from deerflow.community.brave.tools import _safe_public_url

        assert _safe_public_url("http://10.0.0.1/i.jpg") == ""

    def test_obfuscated_loopback_ip_is_filtered(self):
        from deerflow.community.brave.tools import _safe_public_url

        assert _safe_public_url("http://2130706433/i.jpg") == ""

    def test_malformed_ipv6_url_does_not_raise(self):
        from deerflow.community.brave.tools import _safe_public_url

        assert _safe_public_url("http://[::1/i.jpg") == ""

    def test_nat64_embedded_loopback_is_filtered(self):
        from deerflow.community.brave.tools import _safe_public_url

        assert _safe_public_url("http://[64:ff9b::127.0.0.1]/i.jpg") == ""

    def test_ipv4_compatible_embedded_private_is_filtered(self):
        from deerflow.community.brave.tools import _safe_public_url

        assert _safe_public_url("http://[::10.0.0.1]/i.jpg") == ""

    def test_ipv4_mapped_loopback_is_filtered(self):
        from deerflow.community.brave.tools import _safe_public_url

        assert _safe_public_url("http://[::ffff:127.0.0.1]/i.jpg") == ""

    def test_sixtofour_loopback_is_filtered(self):
        from deerflow.community.brave.tools import _safe_public_url

        assert _safe_public_url("http://[2002:7f00:1::]/i.jpg") == ""

    def test_global_ipv6_passes(self):
        from deerflow.community.brave.tools import _safe_public_url

        assert _safe_public_url("http://[2001:4860:4860::8888]/i.jpg") == "http://[2001:4860:4860::8888]/i.jpg"


class TestImageSearchTool:
    def test_basic_image_search_returns_normalized_results(self, mock_config_with_key):
        results = [
            {
                "title": "Mountain",
                "url": "https://example.com/mountain-page",
                "source": "example.com",
                "thumbnail": {"src": "https://imgs.search.brave.com/thumb.jpg", "width": 500, "height": 320},
                "properties": {"url": "https://cdn.example.com/mountain.jpg", "width": 1920, "height": 1080},
            },
            {
                "title": "Forest",
                "url": "https://example.org/forest-page",
                "thumbnail": {"src": "https://imgs.search.brave.com/forest.jpg"},
                "properties": {"url": "https://cdn.example.org/forest.jpg"},
            },
        ]
        mock_resp = _make_brave_images_response(results)

        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

            from deerflow.community.brave.tools import image_search_tool

            result = image_search_tool.invoke({"query": "mountain landscape"})
            parsed = json.loads(result)

        assert parsed["query"] == "mountain landscape"
        assert parsed["total_results"] == 2
        assert parsed["results"][0] == {
            "title": "Mountain",
            "image_url": "https://cdn.example.com/mountain.jpg",
            "thumbnail_url": "https://imgs.search.brave.com/thumb.jpg",
            "source_url": "https://example.com/mountain-page",
            "source": "example.com",
            "width": 1920,
            "height": 1080,
        }
        assert "usage_hint" in parsed

    def test_image_search_sends_brave_image_params_from_config(self):
        with patch("deerflow.community.brave.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {
                "api_key": "test-key",
                "max_results": "250",
                "country": "JP",
                "search_lang": "ja",
                "safesearch": "off",
                "spellcheck": False,
            }
            mock.return_value.get_tool_config.return_value = tool_config

            results = [
                {
                    "title": f"R{i}",
                    "url": f"https://example.com/{i}",
                    "thumbnail": {"src": f"https://imgs.search.brave.com/{i}.jpg"},
                    "properties": {"url": f"https://cdn.example.com/{i}.jpg"},
                }
                for i in range(250)
            ]

            with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
                mock_get = mock_client_cls.return_value.__enter__.return_value.get
                mock_get.side_effect = _image_count_aware_get(results)

                from deerflow.community.brave.tools import image_search_tool

                result = image_search_tool.invoke({"query": "sakura", "max_results": 5})
                parsed = json.loads(result)
                call = mock_get.call_args
                params = call.kwargs["params"]

        assert call.args[0] == "https://api.search.brave.com/res/v1/images/search"
        assert params["q"] == "sakura"
        assert params["count"] == 200
        assert params["country"] == "JP"
        assert params["search_lang"] == "ja"
        assert params["safesearch"] == "off"
        assert params["spellcheck"] is False
        assert mock_get.call_count == 1
        assert parsed["total_results"] == 200

    def test_image_search_filters_unsafe_image_urls_but_keeps_safe_thumbnail(self, mock_config_with_key):
        results = [
            {
                "title": "Unsafe original",
                "url": "http://localhost/page",
                "thumbnail": {"src": "https://imgs.search.brave.com/thumb.jpg"},
                "properties": {"url": "http://127.0.0.1/image.jpg"},
            },
            {
                "title": "Fully unsafe",
                "url": "http://10.0.0.1/page",
                "thumbnail": {"src": "http://0177.0.0.1/thumb.jpg"},
                "properties": {"url": "http://2130706433/image.jpg"},
            },
        ]

        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = _make_brave_images_response(results)

            from deerflow.community.brave.tools import image_search_tool

            result = image_search_tool.invoke({"query": "unsafe"})
            parsed = json.loads(result)

        assert parsed["total_results"] == 1
        assert parsed["results"][0]["title"] == "Unsafe original"
        assert parsed["results"][0]["image_url"] == ""
        assert parsed["results"][0]["thumbnail_url"] == "https://imgs.search.brave.com/thumb.jpg"
        assert parsed["results"][0]["source_url"] == ""

    def test_image_search_falls_back_when_only_one_image_url_is_present(self, mock_config_with_key):
        results = [
            {
                "title": "Only thumbnail",
                "thumbnail": {"src": "https://imgs.search.brave.com/only-thumb.jpg"},
                "properties": {},
            },
            {
                "title": "Only original",
                "thumbnail": {},
                "properties": {"url": "https://cdn.example.com/original.jpg"},
            },
        ]

        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = _make_brave_images_response(results)

            from deerflow.community.brave.tools import image_search_tool

            result = image_search_tool.invoke({"query": "fallback"})
            parsed = json.loads(result)

        assert parsed["total_results"] == 2
        assert parsed["results"][0]["image_url"] == "https://imgs.search.brave.com/only-thumb.jpg"
        assert parsed["results"][0]["thumbnail_url"] == "https://imgs.search.brave.com/only-thumb.jpg"
        assert parsed["results"][1]["image_url"] == "https://cdn.example.com/original.jpg"
        assert parsed["results"][1]["thumbnail_url"] == "https://cdn.example.com/original.jpg"

    def test_image_search_reports_thumbnail_dimensions_when_original_dropped(self, mock_config_with_key):
        """When only the thumbnail URL survives, width/height must describe it, not the dropped original."""
        results = [
            {
                "title": "Unsafe original with dims",
                "url": "https://example.com/page",
                "thumbnail": {"src": "https://imgs.search.brave.com/thumb.jpg", "width": 300, "height": 200},
                "properties": {"url": "http://127.0.0.1/image.jpg", "width": 1920, "height": 1080},
            },
        ]

        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = _make_brave_images_response(results)

            from deerflow.community.brave.tools import image_search_tool

            result = image_search_tool.invoke({"query": "dims"})
            parsed = json.loads(result)

        assert parsed["total_results"] == 1
        entry = parsed["results"][0]
        assert entry["image_url"] == ""
        assert entry["thumbnail_url"] == "https://imgs.search.brave.com/thumb.jpg"
        assert entry["width"] == 300
        assert entry["height"] == 200

    def test_image_search_missing_api_key_returns_error_json(self, mock_config_no_key):
        with patch.dict("os.environ", {}, clear=True):
            from deerflow.community.brave.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["error"] == "BRAVE_SEARCH_API_KEY is not configured"
        assert parsed["query"] == "test"

    def test_image_search_missing_api_key_logs_warning_once_per_tool(self, mock_config_no_key, caplog):
        import logging

        with patch.dict("os.environ", {}, clear=True):
            from deerflow.community.brave.tools import image_search_tool, web_search_tool

            with caplog.at_level(logging.WARNING, logger="deerflow.community.brave.tools"):
                web_search_tool.invoke({"query": "q1"})
                image_search_tool.invoke({"query": "q2"})
                image_search_tool.invoke({"query": "q3"})

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 2
        assert any("web_search" in r.message for r in warnings)
        assert any("image_search" in r.message for r in warnings)

    def test_image_search_http_error_returns_structured_error(self, mock_config_with_key):
        mock_error_response = MagicMock()
        mock_error_response.status_code = 403
        mock_error_response.text = "Forbidden"

        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.side_effect = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_error_response)

            from deerflow.community.brave.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["error"] == "Brave Image Search API error: HTTP 403"
        assert parsed["query"] == "test"

    def test_image_search_unexpected_results_format_returns_error(self, mock_config_with_key):
        with patch("deerflow.community.brave.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = _make_brave_images_response({"not": "a list"})

            from deerflow.community.brave.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["error"] == "Brave Image Search returned an unexpected response format"
        assert parsed["query"] == "test"


def test_package_exports_image_search_tool():
    from deerflow.community.brave import image_search_tool
    from deerflow.community.brave.tools import image_search_tool as direct_image_search_tool

    assert image_search_tool is direct_image_search_tool
