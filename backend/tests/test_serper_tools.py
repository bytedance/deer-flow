"""Unit tests for the Serper community web search tool."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the module-level warning flag before each test."""
    import deerflow.community.serper.tools as serper_mod

    serper_mod._api_key_warned = set()
    yield
    serper_mod._api_key_warned = set()


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


def _make_serper_images_response(images: list) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"images": images}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "from-config"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.serper.tools import _get_api_key

            assert _get_api_key("web_search") == "from-config"

    def test_falls_back_to_env_when_config_key_empty(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": ""}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"SERPER_API_KEY": "env-key"}):
                from deerflow.community.serper.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"

    def test_falls_back_to_env_when_config_key_whitespace(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "   "}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"SERPER_API_KEY": "env-key"}):
                from deerflow.community.serper.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"

    def test_falls_back_to_env_when_config_key_null(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": None}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"SERPER_API_KEY": "env-key"}):
                from deerflow.community.serper.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"

    def test_falls_back_to_env_when_no_config(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"SERPER_API_KEY": "env-only"}):
                from deerflow.community.serper.tools import _get_api_key

                assert _get_api_key("web_search") == "env-only"

    def test_returns_none_when_no_key_anywhere(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {}, clear=True):
                import os

                os.environ.pop("SERPER_API_KEY", None)
                from deerflow.community.serper.tools import _get_api_key

                assert _get_api_key("web_search") is None

    def test_returns_none_when_env_key_whitespace(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"SERPER_API_KEY": "   "}):
                from deerflow.community.serper.tools import _get_api_key

                assert _get_api_key("web_search") is None

    def test_reads_config_for_requested_tool_name(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "image-key"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.serper.tools import _get_api_key

            assert _get_api_key("image_search") == "image-key"
            mock.return_value.get_tool_config.assert_called_with("image_search")


class TestCoerceMaxResults:
    def test_returns_value_when_valid_positive_int(self):
        from deerflow.community.serper.tools import _coerce_max_results

        assert _coerce_max_results(3) == 3

    def test_returns_value_for_numeric_string(self):
        from deerflow.community.serper.tools import _coerce_max_results

        assert _coerce_max_results("7") == 7

    def test_caps_value_at_default_maximum(self):
        from deerflow.community.serper.tools import _coerce_max_results

        assert _coerce_max_results(999) == 10

    def test_respects_custom_maximum(self):
        from deerflow.community.serper.tools import _coerce_max_results

        assert _coerce_max_results(999, max_allowed=3) == 3

    def test_returns_default_for_non_numeric_string(self):
        from deerflow.community.serper.tools import _coerce_max_results

        assert _coerce_max_results("oops") == 5

    def test_returns_default_for_none(self):
        from deerflow.community.serper.tools import _coerce_max_results

        assert _coerce_max_results(None) == 5

    def test_returns_default_for_non_coercible_object(self):
        from deerflow.community.serper.tools import _coerce_max_results

        assert _coerce_max_results(object()) == 5

    def test_returns_default_for_zero(self):
        from deerflow.community.serper.tools import _coerce_max_results

        assert _coerce_max_results(0) == 5

    def test_returns_default_for_negative(self):
        from deerflow.community.serper.tools import _coerce_max_results

        assert _coerce_max_results(-3) == 5

    def test_respects_custom_default(self):
        from deerflow.community.serper.tools import _coerce_max_results

        assert _coerce_max_results("bad", default=2) == 2


class TestMissingKeyError:
    def test_warns_once_per_tool_name(self, caplog):
        import logging

        import deerflow.community.serper.tools as serper_mod

        with caplog.at_level(logging.WARNING):
            serper_mod._missing_key_error("q1", "web_search")
            serper_mod._missing_key_error("q2", "web_search")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "web_search" in warnings[0].getMessage()

    def test_warns_separately_for_each_tool(self, caplog):
        import logging

        import deerflow.community.serper.tools as serper_mod

        with caplog.at_level(logging.WARNING):
            serper_mod._missing_key_error("q1", "web_search")
            serper_mod._missing_key_error("q2", "image_search")

        warned_tools = {r.getMessage() for r in caplog.records if r.levelno == logging.WARNING}
        assert any("web_search" in m for m in warned_tools)
        assert any("image_search" in m for m in warned_tools)

    def test_returns_structured_error_json(self):
        import deerflow.community.serper.tools as serper_mod

        parsed = json.loads(serper_mod._missing_key_error("hello", "web_search"))
        assert parsed["error"] == "SERPER_API_KEY is not configured"
        assert parsed["query"] == "hello"


class TestSafePublicUrl:
    def test_https_public_hostname_passes(self):
        from deerflow.community.serper.tools import _safe_public_url

        assert _safe_public_url("https://example.com/i.jpg") == "https://example.com/i.jpg"

    def test_public_ip_literal_passes(self):
        from deerflow.community.serper.tools import _safe_public_url

        assert _safe_public_url("https://8.8.8.8/i.jpg") == "https://8.8.8.8/i.jpg"

    def test_localhost_is_filtered(self):
        from deerflow.community.serper.tools import _safe_public_url

        assert _safe_public_url("http://localhost/x.jpg") == ""

    def test_localhost_subdomain_is_filtered(self):
        from deerflow.community.serper.tools import _safe_public_url

        assert _safe_public_url("http://foo.localhost/x.jpg") == ""

    def test_trailing_dot_localhost_is_filtered(self):
        from deerflow.community.serper.tools import _safe_public_url

        # FQDN root label: localhost. still resolves to loopback.
        assert _safe_public_url("http://localhost./x.jpg") == ""

    def test_trailing_dot_loopback_ip_is_filtered(self):
        from deerflow.community.serper.tools import _safe_public_url

        assert _safe_public_url("http://127.0.0.1./x.jpg") == ""

    def test_trailing_dot_private_ip_is_filtered(self):
        from deerflow.community.serper.tools import _safe_public_url

        assert _safe_public_url("http://10.0.0.1./x.jpg") == ""

    def test_trailing_dot_public_host_passes(self):
        from deerflow.community.serper.tools import _safe_public_url

        # A trailing dot on a public host is harmless and must not be rejected.
        assert _safe_public_url("https://example.com./i.jpg") == "https://example.com./i.jpg"

    def test_private_ip_is_filtered(self):
        from deerflow.community.serper.tools import _safe_public_url

        assert _safe_public_url("http://10.0.0.1/x.jpg") == ""

    def test_ipv4_mapped_ipv6_loopback_is_filtered(self):
        from deerflow.community.serper.tools import _safe_public_url

        assert _safe_public_url("http://[::ffff:127.0.0.1]/x.jpg") == ""

    def test_non_http_scheme_is_filtered(self):
        from deerflow.community.serper.tools import _safe_public_url

        assert _safe_public_url("file:///etc/passwd") == ""

    def test_non_string_is_filtered(self):
        from deerflow.community.serper.tools import _safe_public_url

        assert _safe_public_url(None) == ""

    def test_decimal_encoded_loopback_is_filtered(self):
        from deerflow.community.serper.tools import _safe_public_url

        # 2130706433 == 127.0.0.1
        assert _safe_public_url("http://2130706433/x.jpg") == ""

    def test_hex_encoded_loopback_is_filtered(self):
        from deerflow.community.serper.tools import _safe_public_url

        # 0x7f000001 == 127.0.0.1
        assert _safe_public_url("http://0x7f000001/x.jpg") == ""

    def test_octal_encoded_loopback_is_filtered(self):
        from deerflow.community.serper.tools import _safe_public_url

        # 0177.0.0.1 == 127.0.0.1
        assert _safe_public_url("http://0177.0.0.1/x.jpg") == ""

    def test_decimal_encoded_private_ip_is_filtered(self):
        from deerflow.community.serper.tools import _safe_public_url

        # 167772161 == 10.0.0.1
        assert _safe_public_url("http://167772161/x.jpg") == ""

    def test_decimal_encoded_public_ip_passes(self):
        from deerflow.community.serper.tools import _safe_public_url

        # 134744072 == 8.8.8.8
        assert _safe_public_url("http://134744072/i.jpg") == "http://134744072/i.jpg"

    def test_domain_with_hex_chars_is_not_treated_as_ip(self):
        from deerflow.community.serper.tools import _safe_public_url

        assert _safe_public_url("https://cafe.com/i.jpg") == "https://cafe.com/i.jpg"

    def test_out_of_range_octet_is_not_treated_as_ip(self):
        from deerflow.community.serper.tools import _safe_public_url

        # 999.1.1.1 is not a valid IPv4 literal; treat as a hostname, not blocked.
        assert _safe_public_url("https://999.1.1.1/i.jpg") == "https://999.1.1.1/i.jpg"

    def test_too_many_octets_is_not_treated_as_ip(self):
        from deerflow.community.serper.tools import _safe_public_url

        # More than 4 dotted parts cannot be an IPv4 literal; treat as hostname.
        assert _safe_public_url("https://1.2.3.4.5/i.jpg") == "https://1.2.3.4.5/i.jpg"

    def test_empty_octet_is_not_treated_as_ip(self):
        from deerflow.community.serper.tools import _safe_public_url

        # Empty dotted part (e.g. trailing/leading dot) cannot decode to an IP.
        assert _safe_public_url("https://1.2..3/i.jpg") == "https://1.2..3/i.jpg"

    def test_trailing_octet_out_of_range_is_not_treated_as_ip(self):
        from deerflow.community.serper.tools import _safe_public_url

        # Leading octets are valid but the trailing block exceeds its range.
        assert _safe_public_url("https://1.2.3.999/i.jpg") == "https://1.2.3.999/i.jpg"


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

    def test_invalid_config_max_results_falls_back_to_default(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "max_results": "oops",
        }
        organic = [{"title": f"R{i}", "link": f"https://x.com/{i}", "snippet": f"S{i}"} for i in range(10)]
        mock_resp = _make_serper_response(organic)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["total_results"] == 5
        assert mock_post.call_args.kwargs["json"]["num"] == 5

    def test_config_max_results_is_capped(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "max_results": 999,
        }
        organic = [{"title": f"R{i}", "link": f"https://x.com/{i}", "snippet": f"S{i}"} for i in range(20)]
        mock_resp = _make_serper_response(organic)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["total_results"] == 10
        assert len(parsed["results"]) == 10
        assert mock_post.call_args.kwargs["json"]["num"] == 10

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

    def test_http_status_error_from_response_returns_structured_error(self, mock_config_with_key):
        mock_error_response = MagicMock()
        mock_error_response.status_code = 403
        mock_error_response.text = "Forbidden"
        mock_error_response.raise_for_status.side_effect = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_error_response)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_error_response

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed
        assert "403" in parsed["error"]

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

    def test_malformed_json_response_returns_error(self, mock_config_with_key):
        mock_resp = MagicMock()
        mock_resp.json.side_effect = json.JSONDecodeError(" Expecting value", "doc", 0)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed

    def test_non_dict_json_response_returns_error(self, mock_config_with_key):
        """A valid but non-dict payload (e.g. a list) must not crash the tool."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = ["unexpected", "list"]
        mock_resp.raise_for_status = MagicMock()

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed
        assert parsed["query"] == "test"

    def test_non_list_organic_returns_error(self, mock_config_with_key):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"organic": {"unexpected": "dict"}}
        mock_resp.raise_for_status = MagicMock()

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["error"] == "Serper returned an unexpected response format"

    def test_null_organic_field_is_treated_as_no_results(self, mock_config_with_key):
        """A null-typed field (some APIs use it for "no results") is not a format error."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"organic": None}
        mock_resp.raise_for_status = MagicMock()

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["error"] == "No results found"

    def test_non_dict_organic_items_are_ignored(self, mock_config_with_key):
        mock_resp = _make_serper_response(["bad", {"title": "T", "link": "https://x.com", "snippet": "S"}])

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["total_results"] == 1
        assert parsed["results"][0]["title"] == "T"

    def test_timeout_returns_error(self, mock_config_with_key):
        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.side_effect = httpx.TimeoutException("Read timed out")

            from deerflow.community.serper.tools import web_search_tool

            result = web_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed
        assert "timed out" in parsed["error"].lower()

    def test_long_query_is_truncated(self, mock_config_with_key):
        organic = [{"title": "T", "link": "https://x.com", "snippet": "S"}]
        mock_resp = _make_serper_response(organic)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            long_query = "a" * 1000
            web_search_tool.invoke({"query": long_query})
            payload = mock_post.call_args.kwargs["json"]

        assert payload["q"] == "a" * 500

    def test_query_is_stripped(self, mock_config_with_key):
        organic = [{"title": "T", "link": "https://x.com", "snippet": "S"}]
        mock_resp = _make_serper_response(organic)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = mock_resp

            from deerflow.community.serper.tools import web_search_tool

            web_search_tool.invoke({"query": "  hello world  "})
            payload = mock_post.call_args.kwargs["json"]

        assert payload["q"] == "hello world"


class TestImageSearchTool:
    def test_basic_search_returns_normalized_results(self, mock_config_with_key):
        images = [
            {
                "title": "Cat 1",
                "imageUrl": "https://example.com/cat1.jpg",
                "thumbnailUrl": "https://example.com/cat1_thumb.jpg",
            },
            {
                "title": "Cat 2",
                "imageUrl": "https://example.com/cat2.jpg",
                "thumbnailUrl": "https://example.com/cat2_thumb.jpg",
            },
        ]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "cat photo"})
            parsed = json.loads(result)

        assert parsed["query"] == "cat photo"
        assert parsed["total_results"] == 2
        assert parsed["results"][0]["title"] == "Cat 1"
        assert parsed["results"][0]["image_url"] == "https://example.com/cat1.jpg"
        assert parsed["results"][0]["thumbnail_url"] == "https://example.com/cat1_thumb.jpg"
        assert parsed["usage_hint"] == "Use the 'image_url' values as reference images in image generation. Download them first if needed."

    def test_sends_correct_headers_and_payload_to_images_endpoint(self, mock_config_with_key):
        images = [{"title": "T", "imageUrl": "https://x.com/i.jpg", "thumbnailUrl": "https://x.com/t.jpg"}]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            image_search_tool.invoke({"query": "hello world"})

            call_args = mock_post.call_args
            endpoint = call_args.args[0]
            headers = call_args.kwargs["headers"]
            payload = call_args.kwargs["json"]

        assert endpoint == "https://google.serper.dev/images"
        assert headers["X-API-KEY"] == "test-serper-key"
        assert payload["q"] == "hello world"
        assert payload["num"] == 5

    def test_image_url_falls_back_to_thumbnail(self, mock_config_with_key):
        images = [{"title": "Only thumb", "thumbnailUrl": "https://x.com/thumb.jpg"}]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["results"][0]["image_url"] == "https://x.com/thumb.jpg"
        assert parsed["results"][0]["thumbnail_url"] == "https://x.com/thumb.jpg"

    def test_thumbnail_url_falls_back_to_image(self, mock_config_with_key):
        images = [{"title": "Only image", "imageUrl": "https://x.com/full.jpg"}]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["results"][0]["image_url"] == "https://x.com/full.jpg"
        assert parsed["results"][0]["thumbnail_url"] == "https://x.com/full.jpg"

    def test_filtered_image_url_does_not_collapse_onto_thumbnail(self, mock_config_with_key):
        """A present-but-unsafe imageUrl must not be replaced by the safe thumbnail."""
        images = [{"title": "T", "imageUrl": "http://10.0.0.1/full.jpg", "thumbnailUrl": "https://example.com/t.jpg"}]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        # The high-res field stays empty rather than masquerading as the preview.
        assert parsed["results"][0]["image_url"] == ""
        assert parsed["results"][0]["thumbnail_url"] == "https://example.com/t.jpg"

    def test_filtered_thumbnail_does_not_collapse_onto_image(self, mock_config_with_key):
        """A present-but-unsafe thumbnailUrl must not be replaced by the safe image."""
        images = [{"title": "T", "imageUrl": "https://example.com/full.jpg", "thumbnailUrl": "http://127.0.0.1/t.jpg"}]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["results"][0]["image_url"] == "https://example.com/full.jpg"
        assert parsed["results"][0]["thumbnail_url"] == ""

    def test_respects_max_results_from_config(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "max_results": 3,
        }
        images = [{"title": f"I{i}", "imageUrl": f"https://x.com/{i}.jpg"} for i in range(10)]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["total_results"] == 3
        assert len(parsed["results"]) == 3

    def test_config_max_results_is_capped(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "max_results": 999,
        }
        images = [{"title": f"I{i}", "imageUrl": f"https://x.com/{i}.jpg"} for i in range(20)]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["total_results"] == 10
        assert len(parsed["results"]) == 10
        assert mock_post.call_args.kwargs["json"]["num"] == 10

    def test_empty_images_returns_error_json(self, mock_config_with_key):
        mock_resp = _make_serper_images_response([])

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "no results"})
            parsed = json.loads(result)

        assert "error" in parsed
        assert parsed["error"] == "No images found"
        assert parsed["query"] == "no results"

    def test_missing_api_key_returns_error_json(self, mock_config_no_key):
        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("SERPER_API_KEY", None)

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed
        assert "SERPER_API_KEY" in parsed["error"]

    def test_http_error_returns_structured_error(self, mock_config_with_key):
        mock_error_response = MagicMock()
        mock_error_response.status_code = 403
        mock_error_response.text = "Forbidden"

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.side_effect = httpx.HTTPStatusError("403", request=MagicMock(), response=mock_error_response)

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed
        assert "403" in parsed["error"]

    def test_network_exception_returns_error_json(self, mock_config_with_key):
        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.side_effect = Exception("timeout")

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed

    def test_uses_env_key_when_config_absent(self):
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {"SERPER_API_KEY": "env-only-key"}):
                images = [{"title": "T", "imageUrl": "https://x.com/i.jpg"}]
                mock_resp = _make_serper_images_response(images)

                with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
                    mock_post = mock_client_cls.return_value.__enter__.return_value.post
                    mock_post.return_value = mock_resp

                    from deerflow.community.serper.tools import image_search_tool

                    image_search_tool.invoke({"query": "env key test"})
                    headers = mock_post.call_args.kwargs["headers"]

                assert headers["X-API-KEY"] == "env-only-key"

    def test_max_results_parameter_accepted(self, mock_config_no_key):
        """Tool accepts max_results as a call parameter when config does not override it."""
        images = [{"title": f"I{i}", "imageUrl": f"https://x.com/{i}.jpg"} for i in range(10)]
        mock_resp = _make_serper_images_response(images)

        with patch.dict("os.environ", {"SERPER_API_KEY": "env-key"}):
            with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
                mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

                from deerflow.community.serper.tools import image_search_tool

                result = image_search_tool.invoke({"query": "test", "max_results": 2})
                parsed = json.loads(result)

        assert parsed["total_results"] == 2

    def test_config_max_results_overrides_parameter(self):
        """Config max_results overrides the parameter passed at call time."""
        with patch("deerflow.community.serper.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "test-key", "max_results": 3}
            mock.return_value.get_tool_config.return_value = tool_config

            images = [{"title": f"I{i}", "imageUrl": f"https://x.com/{i}.jpg"} for i in range(10)]
            mock_resp = _make_serper_images_response(images)

            with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
                mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

                from deerflow.community.serper.tools import image_search_tool

                result = image_search_tool.invoke({"query": "test", "max_results": 8})
                parsed = json.loads(result)

        assert parsed["total_results"] == 3

    def test_missing_api_key_logs_warning_once(self, mock_config_no_key, caplog):
        import logging

        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("SERPER_API_KEY", None)

            from deerflow.community.serper.tools import image_search_tool

            with caplog.at_level(logging.WARNING, logger="deerflow.community.serper.tools"):
                image_search_tool.invoke({"query": "q1"})
                image_search_tool.invoke({"query": "q2"})

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

    def test_malformed_json_response_returns_error(self, mock_config_with_key):
        mock_resp = MagicMock()
        mock_resp.json.side_effect = json.JSONDecodeError(" Expecting value", "doc", 0)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed

    def test_non_dict_json_response_returns_error(self, mock_config_with_key):
        """A valid but non-dict payload (e.g. a list) must not crash the tool."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = ["unexpected", "list"]
        mock_resp.raise_for_status = MagicMock()

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed
        assert parsed["query"] == "test"

    def test_non_list_images_returns_error(self, mock_config_with_key):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"images": {"unexpected": "dict"}}
        mock_resp.raise_for_status = MagicMock()

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["error"] == "Serper returned an unexpected response format"

    def test_null_images_field_is_treated_as_no_results(self, mock_config_with_key):
        """A null-typed images field is "no images", not a malformed payload."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"images": None}
        mock_resp.raise_for_status = MagicMock()

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["error"] == "No images found"

    def test_non_dict_image_items_are_ignored(self, mock_config_with_key):
        images = ["bad", {"title": "T", "imageUrl": "https://x.com/i.jpg"}]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["total_results"] == 1
        assert parsed["results"][0]["image_url"] == "https://x.com/i.jpg"

    def test_timeout_returns_error(self, mock_config_with_key):
        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.side_effect = httpx.TimeoutException("Read timed out")

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert "error" in parsed
        assert "timed out" in parsed["error"].lower()

    def test_long_query_is_truncated(self, mock_config_with_key):
        images = [{"title": "T", "imageUrl": "https://x.com/i.jpg"}]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            long_query = "a" * 1000
            image_search_tool.invoke({"query": long_query})
            payload = mock_post.call_args.kwargs["json"]

        assert payload["q"] == "a" * 500

    def test_query_is_stripped(self, mock_config_with_key):
        images = [{"title": "T", "imageUrl": "https://x.com/i.jpg"}]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_post = mock_client_cls.return_value.__enter__.return_value.post
            mock_post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            image_search_tool.invoke({"query": "  cat photo  "})
            payload = mock_post.call_args.kwargs["json"]

        assert payload["q"] == "cat photo"

    def test_partial_fields_in_image_result_returns_error(self, mock_config_with_key):
        """Missing image URLs should not be reported as usable results."""
        images = [{}]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["error"] == "No safe image URLs found"
        assert parsed["query"] == "test"

    def test_unsafe_image_urls_are_filtered(self, mock_config_with_key):
        images = [
            {"title": "Local", "imageUrl": "file:///etc/passwd", "thumbnailUrl": "http://127.0.0.1/thumb.jpg"},
            {"title": "Data", "imageUrl": "data:image/png;base64,abc", "thumbnailUrl": "http://10.0.0.1/thumb.jpg"},
            {"title": "Safe", "imageUrl": "https://example.com/i.jpg", "thumbnailUrl": "http://example.com/t.jpg"},
        ]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["total_results"] == 1
        assert parsed["results"][0]["title"] == "Safe"
        assert parsed["results"][0]["image_url"] == "https://example.com/i.jpg"
        assert parsed["results"][0]["thumbnail_url"] == "http://example.com/t.jpg"

    def test_all_unsafe_image_urls_return_error(self, mock_config_with_key):
        images = [
            {"title": "Local", "imageUrl": "file:///etc/passwd", "thumbnailUrl": "http://127.0.0.1/thumb.jpg"},
            {"title": "Private", "imageUrl": "http://10.0.0.1/image.jpg", "thumbnailUrl": "data:image/png;base64,abc"},
        ]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["error"] == "No safe image URLs found"
        assert parsed["query"] == "test"

    def test_unsafe_image_urls_do_not_consume_result_limit(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {
            "api_key": "test-key",
            "max_results": 1,
        }
        images = [
            {"title": "Unsafe", "imageUrl": "file:///etc/passwd", "thumbnailUrl": "http://127.0.0.1/thumb.jpg"},
            {"title": "Safe", "imageUrl": "https://example.com/i.jpg", "thumbnailUrl": "https://example.com/t.jpg"},
        ]
        mock_resp = _make_serper_images_response(images)

        with patch("deerflow.community.serper.tools.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

            from deerflow.community.serper.tools import image_search_tool

            result = image_search_tool.invoke({"query": "test"})
            parsed = json.loads(result)

        assert parsed["total_results"] == 1
        assert parsed["results"][0]["title"] == "Safe"


def test_package_exports_image_search_tool():
    from deerflow.community.serper import image_search_tool
    from deerflow.community.serper.tools import image_search_tool as direct_image_search_tool

    assert image_search_tool is direct_image_search_tool
